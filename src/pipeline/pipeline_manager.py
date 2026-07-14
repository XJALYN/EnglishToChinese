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
from src.utils.cpu_throttle import lower_current_thread_priority


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
    ):
        self.page_url = page_url
        self.stream_url = stream_url
        self.referer = referer
        self.on_subtitle_partial = on_subtitle_partial
        self.on_subtitle_final = on_subtitle_final
        self.on_status = on_status
        self.on_log = on_log
        self.start_offset = start_offset

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
        self._tts = TtsWorker(on_log=self._log)
        self._partial_buf = ""

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
        self._extractor = AudioExtractor(
            self.page_url,
            on_chunk=self._enqueue_audio,
            on_log=self._log,
            start_offset=self.start_offset,
            stream_url=self.stream_url,
            referer=self.referer,
            startup_delay=4.0,
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
        self._running.clear()
        if self._extractor:
            self._extractor.stop()
        self._audio_q.put(None)
        self._text_q.put(None)
        self._tts.stop()
        self._log("INFO 管线已停止")

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

    def _translate_loop(self) -> None:
        self._log("INFO 翻译处理循环已就绪")
        while self._running.is_set():
            item = self._text_q.get()
            if item is None:
                break
            english, ts = item
            self._partial_buf = ""
            self.on_subtitle_partial("")

            tts_session = self._tts.begin_session()

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
                    self._tts.end_session(tts_session)
                except Exception as exc:
                    self._log(f"ERROR TTS 结束会话错误: {exc}")

    def _accumulate_partial(self, token: str) -> str:
        self._partial_buf += token
        return self._partial_buf
