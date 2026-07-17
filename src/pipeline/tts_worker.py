"""百炼 CosyVoice TTS — 优先流式；失败则整句合成 / 本机 say 降级；按主时钟调度播放."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd

from src.config import settings_manager

_log = logging.getLogger(__name__)

# 计划播放时间已过太久则跳过，避免播「过时」内容
_MAX_STALE_SECONDS = 8.0


class _AudioPlayer:
    """持续 OutputStream + 缓冲队列，避免每个小 chunk 单独 sd.play 造成卡顿."""

    def __init__(self):
        self._chunks: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._sample_rate = settings_manager.data.tts_sample_rate
        self._prebuffer_samples = int(self._sample_rate * 0.25)
        self._stream: sd.OutputStream | None = None
        self._stream_started = False
        self._closing = False
        self._device_error_logged = False
        self._pending_done = threading.Event()
        self._pending_done.set()
        self._bytes_queued = 0
        self._underruns = 0
        self._on_log: Callable[[str], None] | None = None
        self._on_active: Callable[[bool], None] | None = None
        self._active_notified = False

    def set_log(self, on_log: Callable[[str], None] | None) -> None:
        self._on_log = on_log

    def set_on_active(self, on_active: Callable[[bool], None] | None) -> None:
        self._on_active = on_active

    def _emit(self, msg: str) -> None:
        _log.info(msg)
        if self._on_log:
            self._on_log(msg)

    def _notify_active(self, active: bool) -> None:
        if active and self._active_notified:
            return
        if not active and not self._active_notified:
            return
        self._active_notified = active
        if self._on_active:
            try:
                self._on_active(active)
            except Exception:
                pass

    def push(self, data: bytes) -> None:
        if not data or self._closing:
            return
        audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return
        with self._cv:
            self._chunks.append(audio)
            self._bytes_queued += audio.size
            self._pending_done.clear()
            need = self._prebuffer_samples if not self._stream_started else 1
            if self._bytes_queued >= need:
                self._ensure_stream_locked()
            self._cv.notify_all()

    def drain(self) -> None:
        """Block until currently queued audio finishes playing."""
        with self._cv:
            if self._closing:
                return
            if self._bytes_queued > 0 and not self._stream_started:
                self._ensure_stream_locked()
        self._pending_done.wait(timeout=120)
        self._notify_active(False)

    def flush(self) -> None:
        """丢弃已排队未播完的 PCM."""
        with self._cv:
            dropped = self._bytes_queued
            self._chunks.clear()
            self._bytes_queued = 0
            self._pending_done.set()
            self._cv.notify_all()
        self._notify_active(False)
        if dropped > 0:
            self._emit(f"INFO TTS 已清空积压音频 ({dropped} samples)")

    def stop(self) -> None:
        with self._cv:
            self._closing = True
            self._chunks.clear()
            self._bytes_queued = 0
            self._pending_done.set()
            stream = self._stream
            self._stream = None
            self._stream_started = False
            self._cv.notify_all()
        self._notify_active(False)
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception as exc:
                _log.warning("TTS stream close: %s", exc)
        with self._cv:
            self._closing = False
            self._device_error_logged = False
            self._active_notified = False

    def _ensure_stream_locked(self) -> None:
        if self._stream_started or self._closing:
            return
        sr = settings_manager.data.tts_sample_rate
        self._sample_rate = sr
        try:
            out_dev = None
            try:
                pair = sd.default.device
                out_dev = pair[1]
            except Exception:
                out_dev = None
            kwargs = dict(
                samplerate=sr,
                channels=1,
                dtype="float32",
                callback=self._callback,
                blocksize=2048,
                latency="high",
            )
            if out_dev is not None:
                kwargs["device"] = out_dev
            self._stream = sd.OutputStream(**kwargs)
            self._stream.start()
            self._stream_started = True
            self._emit(f"INFO TTS OutputStream 已启动 (sr={sr}, device={out_dev})")
            # notify outside lock
        except Exception as exc:
            self._stream = None
            self._stream_started = False
            msg = f"ERROR TTS 音频设备打开失败 (PortAudio): {exc}"
            if not self._device_error_logged:
                self._device_error_logged = True
                self._emit(msg)
            self._fallback_play_locked()
            return
        # release path: notify duck after stream starts
        threading.Thread(
            target=lambda: self._notify_active(True), daemon=True
        ).start()

    def _fallback_play_locked(self) -> None:
        if not self._chunks:
            return
        buf = np.concatenate(list(self._chunks))
        self._chunks.clear()
        self._bytes_queued = 0
        self._pending_done.set()
        try:
            self._notify_active(True)

            def _play() -> None:
                try:
                    sd.play(buf, self._sample_rate, blocking=True)
                finally:
                    self._notify_active(False)

            threading.Thread(target=_play, daemon=True).start()
        except Exception as exc:
            self._emit(f"ERROR TTS fallback play failed: {exc}")
            self._notify_active(False)

    def _callback(self, outdata, frames, _time, status) -> None:
        if status:
            self._underruns += 1
            if self._underruns <= 3 or self._underruns % 50 == 0:
                self._emit(f"WARN TTS 音频回调状态: {status}")

        need = frames
        out = np.zeros(need, dtype=np.float32)
        filled = 0
        with self._lock:
            while filled < need and self._chunks:
                chunk = self._chunks[0]
                take = min(need - filled, chunk.size)
                out[filled : filled + take] = chunk[:take]
                if take < chunk.size:
                    self._chunks[0] = chunk[take:]
                else:
                    self._chunks.popleft()
                filled += take
                self._bytes_queued -= take
            if not self._chunks and self._bytes_queued <= 0:
                self._pending_done.set()
        outdata[:, 0] = out


class _PlayoutScheduler:
    """
    以 mpv 播放位置为主时钟，在 segment_ts + interpretation_delay 时再播出 PCM。
    合成阶段只缓冲，避免「TTS 就绪即播」与画面脱节。
    """

    def __init__(
        self,
        get_media_position: Callable[[], float],
        *,
        on_log: Callable[[str], None] | None = None,
        on_active: Callable[[bool], None] | None = None,
    ):
        self._get_pos = get_media_position
        self._delay = settings_manager.data.interpretation_delay
        self._on_log = on_log
        self._on_active = on_active
        self._cancel = threading.Event()

    def _emit(self, msg: str) -> None:
        _log.info(msg)
        if self._on_log:
            self._on_log(msg)

    def cancel(self) -> None:
        self._cancel.set()

    def _wait_until_play_at(self, play_at: float) -> bool:
        """阻塞至计划播放时刻；若内容已严重过时则返回 False."""
        stall_at_zero = 0
        while not self._cancel.is_set():
            pos = self._get_pos()
            if pos >= play_at - 0.08:
                return True
            if pos > play_at + _MAX_STALE_SECONDS:
                self._emit(
                    f"WARN 跳过过时配音 (内容 @{play_at - self._delay:.1f}s, "
                    f"计划 {play_at:.1f}s, 当前画面 {pos:.1f}s)"
                )
                return False
            if pos <= 0:
                stall_at_zero += 1
                if stall_at_zero > 40:
                    self._emit("WARN 无法读取播放进度，降级为立即配音")
                    return True
            else:
                stall_at_zero = 0
            wait = min(0.12, max(0.03, play_at - pos if pos > 0 else 0.08))
            time.sleep(wait)
        return False

    def play_pcm(self, segment_ts: float, chunks: list[bytes], *, drain: bool = True) -> bool:
        if not chunks:
            return False
        play_at = segment_ts + self._delay
        if not self._wait_until_play_at(play_at):
            return False
        pos = self._get_pos()
        if abs(pos - play_at) > 0.5:
            self._emit(
                f"INFO 配音播出 @ 画面 {pos:.1f}s "
                f"(内容 {segment_ts:.1f}s, 计划延迟 {self._delay:.1f}s)"
            )
        for data in chunks:
            if self._cancel.is_set():
                return False
            _player.push(data)
        if drain:
            _player.drain()
        return True

    def play_local_say(self, segment_ts: float, text: str, *, drain: bool = True) -> bool:
        play_at = segment_ts + self._delay
        if not self._wait_until_play_at(play_at):
            return False
        if self._on_active:
            try:
                self._on_active(True)
            except Exception:
                pass
        ok = _local_say(text, self._on_log)
        if self._on_active:
            try:
                self._on_active(False)
            except Exception:
                pass
        return ok


_player = _AudioPlayer()


def _pick_say_voices() -> list[str]:
    """解析 `say -v ?`，优先中文音色."""
    try:
        r = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = (r.stdout or "").splitlines()
    except Exception:
        return []
    zh: list[str] = []
    other: list[str] = []
    for line in lines:
        name = line.split("#", 1)[0].strip()
        if not name:
            continue
        parts = name.rsplit(None, 1)
        voice = parts[0].strip() if parts else name
        low = line.lower()
        if "zh_" in low or "chinese" in low or "中文" in line:
            zh.append(voice)
        else:
            other.append(voice)
    seen: set[str] = set()
    ordered: list[str] = []
    for v in zh + other[:3]:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _local_say(text: str, on_log: Callable[[str], None] | None = None) -> bool:
    """macOS 本机语音降级（不依赖 CosyVoice 网络）."""
    if not text.strip() or sys.platform != "darwin":
        return False
    if not shutil.which("say"):
        return False
    if on_log:
        on_log("WARN CosyVoice 无音频，降级为本机 say 配音")
    voices = _pick_say_voices() or [
        "Tingting",
        "Meijia",
        "Ting-Ting",
        "Mei-Jia",
    ]
    for voice in voices[:6]:
        try:
            r = subprocess.run(
                ["say", "-v", voice, text],
                capture_output=True,
                timeout=120,
            )
            if r.returncode == 0:
                if on_log:
                    on_log(f"INFO 本机 say 配音完成 (voice={voice})")
                return True
        except Exception:
            continue
    try:
        subprocess.run(["say", text], capture_output=True, timeout=120, check=False)
        if on_log:
            on_log("INFO 本机 say 配音完成 (默认音色)")
        return True
    except Exception as exc:
        if on_log:
            on_log(f"ERROR 本机 say 失败: {exc}")
        return False


class StreamingTtsSession:
    """单次翻译的 TTS 会话：流式优先，失败则整句 / 本机降级；音频先缓冲再调度播出."""

    def __init__(
        self,
        segment_ts: float,
        scheduler: _PlayoutScheduler,
        on_log: Callable[[str], None] | None = None,
    ):
        self._segment_ts = segment_ts
        self._scheduler = scheduler
        self._on_log = on_log
        self._audio_buffer: list[bytes] = []
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

        key = (
            settings_manager.data.dashscope_api_key
            or settings_manager.data.active_api_key()
        )
        dashscope.api_key = key
        self._done = threading.Event()
        self._error: str | None = None
        self._got_audio = False
        self._text_parts: list[str] = []
        self._AudioFormat = AudioFormat
        self._SpeechSynthesizer = SpeechSynthesizer
        self._ResultCallback = ResultCallback

        class _Cb(ResultCallback):
            def __init__(self, outer: "StreamingTtsSession"):
                self._outer = outer

            def on_data(self, data: bytes) -> None:
                if data:
                    self._outer._got_audio = True
                    self._outer._audio_buffer.append(data)

            def on_complete(self) -> None:
                self._outer._done.set()

            def on_error(self, message) -> None:
                self._outer._error = str(message)
                if self._outer._on_log:
                    self._outer._on_log(f"ERROR TTS: {message}")
                self._outer._done.set()

        self._Cb = _Cb
        self._synth = SpeechSynthesizer(
            model="cosyvoice-v3-flash",
            voice=settings_manager.data.tts_voice,
            format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            callback=_Cb(self),
        )
        self._started = False
        self._lock = threading.Lock()

    def feed(self, text: str) -> None:
        if not text:
            return
        self._text_parts.append(text)
        with self._lock:
            try:
                self._synth.streaming_call(text)
                self._started = True
            except Exception as exc:
                if self._on_log:
                    self._on_log(f"WARN TTS streaming_call 失败: {exc}")

    def _full_text(self) -> str:
        return "".join(self._text_parts).strip()

    def _batch_synthesize(self, text: str) -> None:
        """整句非流式合成（websocket 抖动能再试一次）."""
        if not text:
            return
        if self._on_log:
            self._on_log("INFO 尝试 CosyVoice 整句合成降级…")
        self._done.clear()
        self._error = None

        class _Cb(self._ResultCallback):
            def __init__(self, outer: "StreamingTtsSession"):
                self._outer = outer

            def on_data(self, data: bytes) -> None:
                if data:
                    self._outer._got_audio = True
                    self._outer._audio_buffer.append(data)

            def on_complete(self) -> None:
                self._outer._done.set()

            def on_error(self, message) -> None:
                self._outer._error = str(message)
                if self._outer._on_log:
                    self._outer._on_log(f"ERROR TTS 整句合成: {message}")
                self._outer._done.set()

        try:
            synth = self._SpeechSynthesizer(
                model="cosyvoice-v3-flash",
                voice=settings_manager.data.tts_voice,
                format=self._AudioFormat.PCM_24000HZ_MONO_16BIT,
                callback=_Cb(self),
            )
            synth.call(text)
            self._done.wait(timeout=60)
        except Exception as exc:
            if self._on_log:
                self._on_log(f"ERROR TTS 整句合成异常: {exc}")

    def finish(self, *, drain: bool = True) -> None:
        with self._lock:
            if self._started:
                try:
                    self._synth.streaming_complete()
                except Exception as exc:
                    if self._on_log:
                        self._on_log(f"WARN TTS streaming_complete: {exc}")
                self._done.wait(timeout=30)

        full = self._full_text()
        if self._started and not self._got_audio and full:
            # 典型：websocket timed out → 无 PCM
            if self._on_log:
                self._on_log(
                    "WARN TTS 流式未收到音频"
                    + (f" ({self._error})" if self._error else "")
                    + "，尝试降级"
                )
            self._batch_synthesize(full)

        if not self._got_audio and full:
            ok = self._scheduler.play_local_say(self._segment_ts, full, drain=drain)
            if not ok and self._on_log:
                self._on_log(
                    "ERROR 所有 TTS 路径失败；请检查网络 / DashScope Key，"
                    "并确认已听到视频原声（已降低音量保留）"
                )
            return

        if self._audio_buffer:
            self._scheduler.play_pcm(
                self._segment_ts, self._audio_buffer, drain=drain
            )
        elif self._on_log and self._started and not self._got_audio and not self._error:
            self._on_log("WARN TTS 会话结束但未收到音频数据")


class TtsWorker:
    def __init__(
        self,
        on_log: Callable[[str], None] | None = None,
        on_tts_active: Callable[[bool], None] | None = None,
        get_media_position: Callable[[], float] | None = None,
    ):
        self._on_log = on_log
        self._on_tts_active = on_tts_active
        self._get_pos = get_media_position or (lambda: 0.0)
        self._scheduler = _PlayoutScheduler(
            self._get_pos,
            on_log=on_log,
            on_active=on_tts_active,
        )

    def begin_session(self, segment_ts: float) -> StreamingTtsSession:
        _player.set_log(self._on_log)
        _player.set_on_active(self._on_tts_active)
        delay = settings_manager.data.interpretation_delay
        if self._on_log:
            self._on_log(
                f"INFO TTS 会话开始 (内容 @{segment_ts:.1f}s, "
                f"计划延迟 {delay:.1f}s 后播出)"
            )
        return StreamingTtsSession(
            segment_ts=segment_ts,
            scheduler=self._scheduler,
            on_log=self._on_log,
        )

    def end_session(self, session: StreamingTtsSession, *, drain: bool = True) -> None:
        session.finish(drain=drain)

    def flush(self) -> None:
        self._scheduler.cancel()
        self._scheduler = _PlayoutScheduler(
            self._get_pos,
            on_log=self._on_log,
            on_active=self._on_tts_active,
        )
        _player.flush()

    def stop(self) -> None:
        if self._on_log:
            self._on_log("INFO 正在停止 TTS 音频输出…")
        self._scheduler.cancel()
        _player.stop()
