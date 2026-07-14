"""百炼 CosyVoice 流式 TTS — 边收译文边播放 (无缝 PCM 流)."""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable

import numpy as np
import sounddevice as sd

from src.config import settings_manager

_log = logging.getLogger(__name__)


class _AudioPlayer:
    """持续 OutputStream + 缓冲队列，避免每个小 chunk 单独 sd.play 造成卡顿."""

    def __init__(self):
        self._chunks: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._sample_rate = settings_manager.data.tts_sample_rate
        # Wait for ~250ms before starting stream to absorb tiny websocket frames
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

    def set_log(self, on_log: Callable[[str], None] | None) -> None:
        self._on_log = on_log

    def _emit(self, msg: str) -> None:
        _log.info(msg)
        if self._on_log:
            self._on_log(msg)

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
            # Session may end with less than prebuffer still waiting — flush it
            if self._bytes_queued > 0 and not self._stream_started:
                self._ensure_stream_locked()
        self._pending_done.wait(timeout=120)

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
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception as exc:
                _log.warning("TTS stream close: %s", exc)
        # Allow reuse after stop (new pipeline run)
        with self._cv:
            self._closing = False
            self._device_error_logged = False

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
        except Exception as exc:
            self._stream = None
            self._stream_started = False
            msg = f"ERROR TTS 音频设备打开失败 (PortAudio): {exc}"
            if not self._device_error_logged:
                self._device_error_logged = True
                self._emit(msg)
            # Fallback: concatenation play reduces open/close churn vs per-chunk
            self._fallback_play_locked()

    def _fallback_play_locked(self) -> None:
        if not self._chunks:
            return
        buf = np.concatenate(list(self._chunks))
        self._chunks.clear()
        self._bytes_queued = 0
        self._pending_done.set()
        try:
            # Concatenate reduces open/close churn vs per-chunk sd.play
            threading.Thread(
                target=lambda: sd.play(buf, self._sample_rate, blocking=True),
                daemon=True,
            ).start()
        except Exception as exc:
            self._emit(f"ERROR TTS fallback play failed: {exc}")

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
            if filled < need:
                # underrun — leave zeros (brief silence better than abort)
                pass
            if not self._chunks and self._bytes_queued <= 0:
                self._pending_done.set()
        outdata[:, 0] = out


_player = _AudioPlayer()


class StreamingTtsSession:
    """单次翻译的流式 TTS 会话."""

    def __init__(self, on_log: Callable[[str], None] | None = None):
        self._on_log = on_log
        import dashscope
        from dashscope.audio.tts_v2 import AudioFormat, ResultCallback, SpeechSynthesizer

        dashscope.api_key = settings_manager.data.dashscope_api_key
        self._done = threading.Event()
        self._error: str | None = None
        self._got_audio = False

        class _Cb(ResultCallback):
            def __init__(self, outer: "StreamingTtsSession"):
                self._outer = outer

            def on_data(self, data: bytes) -> None:
                if data:
                    self._outer._got_audio = True
                _player.push(data)

            def on_complete(self) -> None:
                self._outer._done.set()

            def on_error(self, message) -> None:
                self._outer._error = str(message)
                if self._outer._on_log:
                    self._outer._on_log(f"ERROR TTS: {message}")
                self._outer._done.set()

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
        with self._lock:
            self._synth.streaming_call(text)
            self._started = True

    def finish(self) -> None:
        with self._lock:
            if self._started:
                self._synth.streaming_complete()
                self._done.wait(timeout=60)
        _player.drain()
        if self._on_log and self._started and not self._got_audio and not self._error:
            self._on_log("WARN TTS 会话结束但未收到音频数据")


class TtsWorker:
    def __init__(self, on_log: Callable[[str], None] | None = None):
        self._on_log = on_log

    def begin_session(self) -> StreamingTtsSession:
        _player.set_log(self._on_log)
        if self._on_log:
            self._on_log("INFO TTS 会话开始 (连续音频流模式)")
        return StreamingTtsSession(on_log=self._on_log)

    def end_session(self, session: StreamingTtsSession) -> None:
        session.finish()

    def stop(self) -> None:
        if self._on_log:
            self._on_log("INFO 正在停止 TTS 音频输出…")
        _player.stop()
