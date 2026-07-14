"""视频区域下方的实时双语字幕条 (不得挂在 mpv embed 容器上)."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SubtitleOverlay(QWidget):
    """字幕条 — 必须作为 mpv 容器的兄弟控件，不能做其子控件。

    macOS 上若将 QWidget 子控件挂到 mpv wid 容器，NSView 会被遮挡 → 永久黑屏。
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setMinimumHeight(96)
        self.setMaximumHeight(140)
        self.setStyleSheet("background: #111; border-top: 1px solid #2a2a2a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 12)
        layout.setSpacing(4)

        self._label = QLabel("")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            """
            QLabel {
                color: #ffffff;
                font-size: 20px;
                font-weight: 600;
                padding: 6px 12px;
                background-color: rgba(0, 0, 0, 0.55);
                border-radius: 8px;
            }
            """
        )
        layout.addWidget(self._label)

        self._english_label = QLabel("")
        self._english_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._english_label.setWordWrap(True)
        self._english_label.setStyleSheet(
            """
            QLabel {
                color: rgba(255, 255, 255, 0.75);
                font-size: 13px;
                padding: 2px 10px;
                background: transparent;
            }
            """
        )
        layout.addWidget(self._english_label)

    def set_partial(self, text: str) -> None:
        self._label.setText(text)

    def set_final(self, english: str, chinese: str) -> None:
        self._label.setText(chinese)
        self._english_label.setText(english)

    def clear(self) -> None:
        self._label.setText("")
        self._english_label.setText("")
