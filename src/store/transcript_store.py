"""播放过程中累积字幕，供 AI 总结 / 思维导图使用."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TranscriptSegment:
    timestamp: float
    english: str
    chinese: str


@dataclass
class SessionTranscript:
    title: str = ""
    url: str = ""
    segments: list[TranscriptSegment] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add(self, english: str, chinese: str, timestamp: float = 0.0) -> None:
        self.segments.append(
            TranscriptSegment(timestamp=timestamp, english=english, chinese=chinese)
        )

    @property
    def english_text(self) -> str:
        return " ".join(s.english for s in self.segments)

    @property
    def chinese_text(self) -> str:
        return " ".join(s.chinese for s in self.segments)

    @property
    def bilingual_text(self) -> str:
        lines = []
        for s in self.segments:
            lines.append(f"[EN] {s.english}")
            lines.append(f"[ZH] {s.chinese}")
        return "\n".join(lines)

    def clear(self) -> None:
        self.segments.clear()
        self.title = ""
        self.url = ""


class TranscriptStore:
    _instance: TranscriptStore | None = None

    def __new__(cls) -> TranscriptStore:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.session = SessionTranscript()
        return cls._instance

    def start_session(self, title: str, url: str) -> None:
        self.session = SessionTranscript(title=title, url=url)

    def add_segment(self, english: str, chinese: str, timestamp: float = 0.0) -> None:
        self.session.add(english, chinese, timestamp)


transcript_store = TranscriptStore()
