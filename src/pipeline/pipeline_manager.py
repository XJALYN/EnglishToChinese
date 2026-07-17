"""同声传译流式处理管线编排."""

from __future__ import annotations

import queue
import threading
import traceback
from typing import Callable

import numpy as np

from src.pipeline.asr_worker import AsrWorker
from src.pipeline.audio_extractor import AudioExtractor
from src.pipeline.translate_worker import TranslateWorker
from src.pipeline.tts_worker import TtsWorker
from src.config import settings_manager
from src.utils.cpu_throttle import lower_current_thread_priority

# 文本队列积压阈值（秒，相对计划播出时刻）
_MAX_QUEUE_LAG_SECONDS = 12.0


class InterpretationPipeline:
    """
    音频 chunk → ASR → 翻译(流式) → TTS(流式) → 扬声器
    字幕通过回调实时更新。
    """

    def __init__(
        self,
        page_url: str,
        *,
        on_subtitle_partial: Callable[[str], None],
        on_subtitle_final: Callable[[str, str, float], None],
        on_status: Callable[[str], None],
        on_log: Callable[[str], None] | None = None,
        start_offset: float = 0.0,
        stream_url: str | None = None,
        referer: str | None = None,
        get_media_position: Callable[[], float] | None = None,
        on_tts_active: Callable[[bool], None] | None = None,
    ):
        self.page_url = page_url
        self.stream_url = stream_url
        self.referer = referer
        self.on_subtitle_partial = on_subtitle_partial
        self.on_subtitle_final = on_subtitle_final
        self.on_status = on_status
        self.on_log = on_log
        self.start_offset = start_offset
        self.get_media_position = get_media_position
        self.on_tts_active = on_tts_active

        self._audio_q: queue.Queue[tuple[np.ndarray, float] | None] = queue.Queue(
            maxsize=8
        )
        self._text_q: queue.Queue[tuple[str, float] | None] = queue.Queue(maxsize=16)
        self._running = threading.Event()
        self._threads: list[threading.Thread] = []

        self._extractor: AudioExtractor | None = None
        self._asr = AsrWorker(
            on_segment=self._enqueue_text,
            on_log=self._log,
        )
        self._tts = TtsWorker(
            on_log=self._log,
            on_tts_active=on_tts_active,
            get_media_position=get_media_position,
        )
        self._partial_buf = ""
        self._stop_lock = threading.Lock()
        self._stopped = False

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def start(self) -> None:
        self._running.set()
        self._log("INFO 管线启动中…")
        self.on_status("管线启动中…")

        self._log(
            f"INFO 创建音频提取器 (page={self.page_url[:60]}…, "
            f"stream={'有' if self.stream_url else '无'})"
        )
        # 预填起点（延迟结束后还会再校准）；勿用过严 seek 导致抽不到音频
        offset = self.start_offset
        if self.get_media_position:
            try:
                offset = max(offset, float(self.get_media_position() or 0.0))
            except Exception:
                pass
        self.start_offset = offset

        self._extractor = AudioExtractor(
            self.page_url,
            on_chunk=self._enqueue_audio,
            on_log=self._log,
            start_offset=self.start_offset,
            stream_url=self.stream_url,
            referer=self.referer,
            startup_delay=settings_manager.data.startup_delay,
            get_media_position=self.get_media_position,
        )
        self._log("INFO 启动音频提取线程…")
        self._extractor.start()

        self._log("INFO 启动 ASR / 翻译工作线程…")
        for target in (self._audio_loop, self._translate_loop):
            t = threading.Thread(target=self._safe_thread, args=(target,), daemon=True)
            t.start()
            self._threads.append(t)

        self._log("INFO 管线线程已启动，等待音频输入…")
        self.on_status("正在聆听并翻译…")

    def stop(self) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True

        self._log("INFO 开始停止管线…")
        self._running.clear()

        if self._extractor:
            self._extractor.stop()
            self._extractor = None

        self._put_stop_sentinel(self._audio_q)
        self._put_stop_sentinel(self._text_q)
        self._tts.stop()
        self._log("INFO 管线停止完成")

    @staticmethod
    def _put_stop_sentinel(q: queue.Queue) -> None:
        """Wake worker threads without blocking when the queue is full."""
        try:
            q.put_nowait(None)
        except queue.Full:
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(None)
            except queue.Full:
                pass

    def _safe_thread(self, target: Callable[[], None]) -> None:
        try:
            target()
        except Exception:
            self._log(f"ERROR 管线线程异常:\n{traceback.format_exc()}")
            self.on_status("管线异常，请查看运行日志")

    def _enqueue_audio(self, pcm: np.ndarray, ts: float) -> None:
        if self._running.is_set():
            try:
                self._audio_q.put((pcm, ts), timeout=2)
            except queue.Full:
                self._log("WARN 音频队列已满，丢弃片段")
            else:
                if self._audio_q.qsize() == 1:
                    self._log("INFO 收到首个音频片段，即将开始 ASR")

    def _enqueue_text(self, text: str, ts: float) -> None:
        if self._running.is_set():
            self._log(f"INFO ASR 识别: {text[:80]}{'…' if len(text) > 80 else ''}")
            try:
                self._text_q.put((text, ts), timeout=2)
            except queue.Full:
                self._log("WARN 文本队列已满，丢弃片段")

    def _audio_loop(self) -> None:
        lower_current_thread_priority()
        self._log("INFO ASR 线程已降优先级，减少对视频解码的 CPU 争抢")
        self._log("INFO ASR 音频处理循环已就绪")
        while self._running.is_set():
            item = self._audio_q.get()
            if item is None:
                break
            pcm, ts = item
            try:
                self._asr.transcribe(pcm, ts)
            except Exception as exc:
                self._log(f"ERROR ASR 错误: {exc}")

    def _media_position(self) -> float:
        if not self.get_media_position:
            return 0.0
        try:
            return float(self.get_media_position() or 0.0)
        except Exception:
            return 0.0

    def _interpretation_delay(self) -> float:
        return settings_manager.data.interpretation_delay

    def _scheduled_at(self, segment_ts: float) -> float:
        return segment_ts + self._interpretation_delay()

    def _trim_text_backlog(self, english: str, ts: float) -> tuple[str, float]:
        """
        队列积压且待播内容相对计划播出时刻严重过时时，跳到最新一条。
        当前句始终保留并配音。
        """
        if self._text_q.qsize() <= 0:
            return english, ts

        pos = self._media_position()
        play_at = self._scheduled_at(ts)
        if pos <= 0 or (pos - play_at) <= _MAX_QUEUE_LAG_SECONDS:
            return english, ts

        latest = (english, ts)
        dropped = 0
        while self._running.is_set():
            try:
                nxt = self._text_q.get_nowait()
            except queue.Empty:
                break
            if nxt is None:
                self._put_stop_sentinel(self._text_q)
                break
            latest = nxt
            dropped += 1

        if dropped:
            self._tts.flush()
            self._log(
                f"WARN 文本队列积压，丢弃 {dropped} 条旧片段，"
                f"从最新 @ {latest[1]:.1f}s 继续 "
                f"(计划播出 {self._scheduled_at(latest[1]):.1f}s, 画面 {pos:.1f}s)"
            )
        return latest

    def _translate_loop(self) -> None:
        self._log("INFO 翻译处理循环已就绪")
        while self._running.is_set():
            item = self._text_q.get()
            if item is None:
                break
            english, ts = item
            english, ts = self._trim_text_backlog(english, ts)

            self._partial_buf = ""
            self.on_subtitle_partial("")

            tts_session = self._tts.begin_session(ts)

            def feed_tts(token: str) -> None:
                tts_session.feed(token)

            translator = TranslateWorker(
                on_token=lambda tok: self.on_subtitle_partial(
                    self._accumulate_partial(tok)
                ),
                on_complete=lambda _zh: None,
                on_tts_feed=feed_tts,
            )
            self._partial_buf = ""

            try:
                self._log(f"INFO 开始翻译: {english[:80]}{'…' if len(english) > 80 else ''}")
                chinese = translator.translate(english)
                self._log(
                    f"INFO 翻译完成: {chinese[:80]}{'…' if len(chinese) > 80 else ''}"
                )
                self.on_subtitle_final(english, chinese, ts)
            except Exception as exc:
                self._log(f"ERROR 翻译错误: {exc}")
                self.on_status(f"翻译错误: {exc}")
            finally:
                try:
                    # 始终播完当前句配音，保证有声音
                    self._tts.end_session(tts_session, drain=True)
                except Exception as exc:
                    self._log(f"ERROR TTS 结束会话错误: {exc}")

    def _accumulate_partial(self, token: str) -> str:
        self._partial_buf += token
        return self._partial_buf
