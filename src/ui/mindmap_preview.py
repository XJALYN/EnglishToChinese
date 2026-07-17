"""思维导图全屏预览对话框 — Corporate Clean."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from src.services.mindmap import mindmap_to_html

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


class MindmapPreviewDialog(QDialog):
    """独立最大化窗口，用于舒适阅读思维导图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mindmapPreviewDialog")
        self.setWindowTitle("思维导图预览")
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1200, 800)
        self._build()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self._title = QLabel("思维导图")
        self._title.setObjectName("panelHeading")
        bar.addWidget(self._title, stretch=1)

        self._zoom_out_btn = QPushButton("缩小")
        self._zoom_out_btn.setToolTip("缩小（Ctrl+滚轮）")
        self._zoom_out_btn.clicked.connect(self._zoom_out)
        bar.addWidget(self._zoom_out_btn)

        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("panelStatus")
        self._zoom_label.setMinimumWidth(44)
        self._zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.addWidget(self._zoom_label)

        self._zoom_in_btn = QPushButton("放大")
        self._zoom_in_btn.setToolTip("放大（Ctrl+滚轮）")
        self._zoom_in_btn.clicked.connect(self._zoom_in)
        bar.addWidget(self._zoom_in_btn)

        self._zoom_reset_btn = QPushButton("重置")
        self._zoom_reset_btn.clicked.connect(self._zoom_reset)
        bar.addWidget(self._zoom_reset_btn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("primaryBtn")
        close_btn.setToolTip("Esc 关闭")
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        root.addLayout(bar)

        hint = QLabel("拖拽平移 · Ctrl+滚轮缩放 · Esc 关闭")
        hint.setObjectName("panelStatus")
        root.addWidget(hint)

        if HAS_WEBENGINE:
            self._view = QWebEngineView()
            self._fallback = None
        else:
            self._view = None
            self._fallback = QTextEdit()
            self._fallback.setReadOnly(True)
        root.addWidget(self._view or self._fallback, stretch=1)

        has_web = HAS_WEBENGINE
        for btn in (
            self._zoom_out_btn,
            self._zoom_in_btn,
            self._zoom_reset_btn,
        ):
            btn.setEnabled(has_web)
        self._zoom_label.setEnabled(has_web)

    def show_mindmap(self, mermaid: str, title: str) -> None:
        self._title.setText(title or "思维导图")
        self.setWindowTitle(f"{title or '思维导图'} — 全屏预览")
        if HAS_WEBENGINE and self._view is not None:
            html = mindmap_to_html(mermaid, title or "思维导图", preview=True)
            self._view.setHtml(html)
            self._zoom_label.setText("100%")
        elif self._fallback is not None:
            self._fallback.setPlainText(f"```mermaid\n{mermaid}\n```")
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _run_js(self, script: str) -> None:
        if HAS_WEBENGINE and self._view is not None:
            self._view.page().runJavaScript(script)

    def _zoom_in(self) -> None:
        self._run_js(
            "if (typeof mindmapZoomIn === 'function') mindmapZoomIn();"
        )
        self._sync_zoom_label()

    def _zoom_out(self) -> None:
        self._run_js(
            "if (typeof mindmapZoomOut === 'function') mindmapZoomOut();"
        )
        self._sync_zoom_label()

    def _zoom_reset(self) -> None:
        self._run_js(
            "if (typeof mindmapZoomReset === 'function') mindmapZoomReset();"
        )
        self._zoom_label.setText("100%")

    def _sync_zoom_label(self) -> None:
        if not HAS_WEBENGINE or self._view is None:
            return

        def _apply(text: str | None) -> None:
            if text:
                self._zoom_label.setText(str(text).strip())

        self._view.page().runJavaScript(
            "document.getElementById('zoom-pct')?.textContent || '100%'",
            _apply,
        )
