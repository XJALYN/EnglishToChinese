"""AI 总结 + 思维导图面板 — Corporate Clean."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.services.exporter import export_all, export_mindmap, export_summary
from src.services.mindmap import generate_mindmap, mindmap_to_html
from src.services.summarizer import generate_summary
from src.store.transcript_store import transcript_store

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False


class _AiSignals(QObject):
    summary_chunk = pyqtSignal(str)
    summary_done = pyqtSignal(str)
    mindmap_done = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)


class AiPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("aiPanel")
        self._page_url = ""
        self._summary_text = ""
        self._mindmap_text = ""
        self._signals = _AiSignals()
        self._signals.summary_chunk.connect(self._append_summary)
        self._signals.summary_done.connect(self._on_summary_done)
        self._signals.mindmap_done.connect(self._on_mindmap_done)
        self._signals.error.connect(self._on_error)
        self._signals.status.connect(self._on_status)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        heading = QLabel("学习辅助")
        heading.setObjectName("panelHeading")
        root.addWidget(heading)

        self._tabs = QTabWidget()

        # --- 总结 Tab ---
        summary_tab = QWidget()
        s_layout = QVBoxLayout(summary_tab)
        s_layout.setContentsMargins(8, 10, 8, 8)
        s_layout.setSpacing(8)
        s_bar = QHBoxLayout()
        s_bar.setSpacing(8)
        self._summary_btn = QPushButton("生成总结")
        self._summary_btn.setObjectName("primaryBtn")
        self._summary_btn.clicked.connect(self._run_summary)
        s_bar.addWidget(self._summary_btn)
        self._export_summary_btn = QPushButton("导出")
        self._export_summary_btn.clicked.connect(self._export_summary)
        s_bar.addWidget(self._export_summary_btn)
        s_bar.addStretch()
        s_layout.addLayout(s_bar)
        self._summary_view = QTextEdit()
        self._summary_view.setReadOnly(True)
        self._summary_view.setPlaceholderText(
            "同传结束后，点击「生成总结」整理视频要点…"
        )
        s_layout.addWidget(self._summary_view)
        self._tabs.addTab(summary_tab, "总结")

        # --- 思维导图 Tab ---
        mindmap_tab = QWidget()
        m_layout = QVBoxLayout(mindmap_tab)
        m_layout.setContentsMargins(8, 10, 8, 8)
        m_layout.setSpacing(8)
        m_bar = QHBoxLayout()
        m_bar.setSpacing(8)
        self._mindmap_btn = QPushButton("生成导图")
        self._mindmap_btn.setObjectName("primaryBtn")
        self._mindmap_btn.clicked.connect(self._run_mindmap)
        m_bar.addWidget(self._mindmap_btn)
        self._export_mindmap_btn = QPushButton("导出")
        self._export_mindmap_btn.clicked.connect(self._export_mindmap)
        m_bar.addWidget(self._export_mindmap_btn)
        self._export_all_btn = QPushButton("全部导出")
        self._export_all_btn.clicked.connect(self._export_all)
        m_bar.addWidget(self._export_all_btn)
        m_bar.addStretch()
        m_layout.addLayout(m_bar)

        if HAS_WEBENGINE:
            self._mindmap_view = QWebEngineView()
            self._mindmap_view.setHtml(self._empty_mindmap_html())
        else:
            self._mindmap_view = QTextEdit()
            self._mindmap_view.setReadOnly(True)
            self._mindmap_view.setPlaceholderText(
                "安装 PyQt6-WebEngine 可预览可视化思维导图\n"
                "pip install PyQt6-WebEngine"
            )
        m_layout.addWidget(self._mindmap_view)
        self._tabs.addTab(mindmap_tab, "思维导图")

        root.addWidget(self._tabs, stretch=1)

        self._status = QLabel("")
        self._status.setObjectName("panelStatus")
        root.addWidget(self._status)

    def set_page_url(self, url: str) -> None:
        self._page_url = url

    def _empty_mindmap_html(self) -> str:
        return mindmap_to_html(
            "mindmap\n  root((等待生成))", "思维导图"
        )

    def _run_summary(self) -> None:
        self._summary_btn.setEnabled(False)
        self._summary_view.clear()
        self._summary_text = ""
        self._signals.status.emit("正在生成总结…")
        threading.Thread(target=self._summary_worker, daemon=True).start()

    def _summary_worker(self) -> None:
        try:
            session = transcript_store.session

            def on_token(t: str) -> None:
                self._signals.summary_chunk.emit(t)

            result = generate_summary(session, self._page_url, on_token=on_token)
            self._signals.summary_done.emit(result)
        except Exception as exc:
            self._signals.error.emit(str(exc))

    def _run_mindmap(self) -> None:
        self._mindmap_btn.setEnabled(False)
        self._signals.status.emit("正在生成思维导图…")
        threading.Thread(target=self._mindmap_worker, daemon=True).start()

    def _mindmap_worker(self) -> None:
        try:
            session = transcript_store.session
            result = generate_mindmap(session, self._summary_text)
            self._signals.mindmap_done.emit(result)
        except Exception as exc:
            self._signals.error.emit(str(exc))

    def _append_summary(self, text: str) -> None:
        self._summary_view.insertPlainText(text)

    def _on_summary_done(self, text: str) -> None:
        self._summary_text = text
        self._summary_view.setPlainText(text)
        self._summary_btn.setEnabled(True)
        self._signals.status.emit("总结完成")
        self._tabs.setCurrentIndex(0)

    def _on_mindmap_done(self, mermaid: str) -> None:
        self._mindmap_text = mermaid
        title = transcript_store.session.title or "思维导图"
        html = mindmap_to_html(mermaid, title)
        if HAS_WEBENGINE:
            self._mindmap_view.setHtml(html)
        else:
            self._mindmap_view.setPlainText(f"```mermaid\n{mermaid}\n```")
        self._mindmap_btn.setEnabled(True)
        self._signals.status.emit("思维导图完成")
        self._tabs.setCurrentIndex(1)

    def _on_error(self, msg: str) -> None:
        self._summary_btn.setEnabled(True)
        self._mindmap_btn.setEnabled(True)
        QMessageBox.warning(self, "AI 错误", msg)
        self._status.setText(msg)

    def _on_status(self, msg: str) -> None:
        self._status.setText(msg)

    def _export_summary(self) -> None:
        if not self._summary_text:
            QMessageBox.information(self, "提示", "请先生成总结")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出总结", "summary.md", "Markdown (*.md);;HTML (*.html);;JSON (*.json)"
        )
        if not path:
            return
        fmt = Path(path).suffix.lstrip(".") or "md"
        export_summary(self._summary_text, transcript_store.session, Path(path), fmt)
        self._status.setText(f"已导出: {path}")

    def _export_mindmap(self) -> None:
        if not self._mindmap_text:
            QMessageBox.information(self, "提示", "请先生成思维导图")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出思维导图", "mindmap.html", "HTML (*.html);;Markdown (*.md);;JSON (*.json)"
        )
        if not path:
            return
        fmt = Path(path).suffix.lstrip(".") or "html"
        export_mindmap(self._mindmap_text, transcript_store.session, Path(path), fmt)
        self._status.setText(f"已导出: {path}")

    def _export_all(self) -> None:
        if not self._summary_text or not self._mindmap_text:
            QMessageBox.information(self, "提示", "请先生成总结和思维导图")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not folder:
            return
        files = export_all(
            self._summary_text,
            self._mindmap_text,
            transcript_store.session,
            Path(folder),
        )
        self._status.setText(f"已导出 {len(files)} 个文件到 {folder}")
