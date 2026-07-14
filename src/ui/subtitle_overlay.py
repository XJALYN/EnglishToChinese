"""视频区域下方的实时双语字幕条 — Corporate Clean.

必须作为 mpv embed 容器的兄弟控件，不能做其子控件。
macOS 上若将 QWidget 子控件挂到 mpv wid 容器，NSView 会被遮挡 → 永久黑屏。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SubtitleOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("subtitleStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumHeight(88)
        self.setMaximumHeight(130)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(4)

        self._label = QLabel("字幕将显示在这里")
        self._label.setObjectName("subtitleZh")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._english_label = QLabel("")
        self._english_label.setObjectName("subtitleEn")
        self._english_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._english_label.setWordWrap(True)
        layout.addWidget(self._english_label)

    def set_partial(self, text: str) -> None:
        self._label.setText(text or "…")

    def set_final(self, english: str, chinese: str) -> None:
        self._label.setText(chinese)
        self._english_label.setText(english)

    def clear(self) -> None:
        self._label.setText("字幕将显示在这里")
        self._english_label.setText("")
