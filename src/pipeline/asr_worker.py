"""faster-whisper 流式语音识别."""

from __future__ import annotations

import threading
from typing import Callable

import numpy as np

from src.config import settings_manager


class AsrWorker:
    def __init__(
        self,
        on_segment: Callable[[str, float], None],
        on_log: Callable[[str], None] | None = None,
    ):
        self.on_segment = on_segment
        self.on_log = on_log
        self._model = None
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def _ensure_model(self):
        if self._model is None:
            import os

            from faster_whisper import WhisperModel

            model_name = settings_manager.data.whisper_model
            self._log(
                f"INFO 正在加载 Whisper 模型「{model_name}」(首次可能需下载)…"
            )
            os.environ.setdefault("HF_ENDPOINT", settings_manager.data.hf_endpoint)
            self._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
            )
            self._log(f"INFO Whisper 模型「{model_name}」加载完成")
        return self._model

    def transcribe(self, pcm: np.ndarray, timestamp: float) -> None:
        model = self._ensure_model()
        audio = pcm.astype(np.float32) / 32768.0

        segments, _ = model.transcribe(
            audio,
            language="en",
            vad_filter=True,
            beam_size=1,
        )

        parts: list[str] = []
        seg_ts = timestamp
        for seg in segments:
            text = seg.text.strip()
            if not text or len(text) < 2:
                continue
            parts.append(text)
            seg_ts = min(seg_ts, timestamp + float(seg.start))

        if not parts:
            return

        merged = " ".join(parts)
        key = f"{seg_ts:.1f}:{merged}"
        with self._lock:
            if key in self._seen:
                return
            self._seen.add(key)
        self.on_segment(merged, seg_ts)
