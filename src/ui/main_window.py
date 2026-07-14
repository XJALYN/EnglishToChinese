"""主窗口: B站播放 + 同声传译 + AI 总结/思维导图."""

from __future__ import annotations

import threading
from datetime import datetime

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config import settings_manager
from src.pipeline.pipeline_manager import InterpretationPipeline
from src.player.bilibili import resolve_bilibili_url
from src.player.mpv_player import MpvPlayer
from src.store.transcript_store import transcript_store
from src.ui.ai_panel import AiPanel
from src.ui.settings_dialog import SettingsDialog
from src.ui.subtitle_overlay import SubtitleOverlay


class _BridgeSignals(QObject):
    subtitle_partial = pyqtSignal(str)
    subtitle_final = pyqtSignal(str, str, float)
    status = pyqtSignal(str)
    log = pyqtSignal(str)
    playback_ready = pyqtSignal(object)
    reset_controls = pyqtSignal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("本地同声传译播放器")
        self.resize(1400, 820)

        self._pipeline: InterpretationPipeline | None = None
        self._player: MpvPlayer | None = None
        self._video_info = None
        self._page_url = ""
        self._pending_pipeline_info = None

        self._signals = _BridgeSignals()
        self._signals.subtitle_partial.connect(self._on_subtitle_partial)
        self._signals.subtitle_final.connect(self._on_subtitle_final)
        self._signals.status.connect(self._on_status)
        self._signals.log.connect(self._append_log)
        self._signals.playback_ready.connect(self._start_playback)
        self._signals.reset_controls.connect(self._reset_play_controls)

        self._build_ui()
        self._refresh_model_label()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)

        # 顶部工具栏
        bar = QHBoxLayout()
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("粘贴 B 站视频链接…")
        bar.addWidget(self._url_input, stretch=1)

        self._play_btn = QPushButton("开始同传")
        self._play_btn.clicked.connect(self._on_play)
        bar.addWidget(self._play_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        bar.addWidget(self._stop_btn)

        self._settings_btn = QPushButton("⚙ 大模型配置")
        self._settings_btn.clicked.connect(self._open_settings)
        bar.addWidget(self._settings_btn)

        root.addLayout(bar)

        # 主区域：视频 | AI 面板
        splitter = QSplitter(Qt.Orientation.Horizontal)

        video_wrap = QWidget()
        v_layout = QVBoxLayout(video_wrap)
        v_layout.setContentsMargins(0, 0, 0, 0)
        v_layout.setSpacing(0)
        # mpv embed 容器必须始终为空：任何子控件在 macOS 上都会导致黑屏
        self._video_container = QWidget()
        self._video_container.setMinimumSize(640, 360)
        self._video_container.setStyleSheet("background: #111;")
        self._video_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._video_container.setAttribute(
            Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True
        )
        v_layout.addWidget(self._video_container, stretch=1)
        # 字幕作为兄弟控件，绝不挂到 embed 容器上
        self._subtitle = SubtitleOverlay()
        v_layout.addWidget(self._subtitle)
        splitter.addWidget(video_wrap)

        self._ai_panel = AiPanel()
        self._ai_panel.setMinimumWidth(380)
        splitter.addWidget(self._ai_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, stretch=1)

        # 信息行
        info = QHBoxLayout()
        self._title_label = QLabel("等待输入链接")
        self._title_label.setStyleSheet("color: #666;")
        info.addWidget(self._title_label)
        info.addStretch()
        self._model_label = QLabel()
        self._model_label.setStyleSheet("color: #888; font-size: 12px;")
        info.addWidget(self._model_label)
        root.addLayout(info)

        # 运行日志面板
        log_bar = QHBoxLayout()
        log_title = QLabel("运行日志")
        log_title.setStyleSheet("font-weight: 600; color: #444;")
        log_bar.addWidget(log_title)
        log_bar.addStretch()
        self._clear_log_btn = QPushButton("清空日志")
        self._clear_log_btn.clicked.connect(self._clear_log)
        log_bar.addWidget(self._clear_log_btn)
        root.addLayout(log_bar)

        self._log_panel = QTextEdit()
        self._log_panel.setReadOnly(True)
        self._log_panel.setMinimumHeight(140)
        self._log_panel.setMaximumHeight(220)
        self._log_panel.setStyleSheet(
            """
            QTextEdit {
                font-family: Menlo, Monaco, Consolas, monospace;
                font-size: 12px;
                background: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 6px;
            }
            """
        )
        root.addWidget(self._log_panel)
        self._append_log("应用已启动，等待输入 B 站链接…")

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪 · PyQt6 主壳 + 可选 Electron 前端")

        if not MpvPlayer.is_available():
            self.statusBar().showMessage("警告: 未安装 mpv，请运行 brew install mpv")

    def _refresh_model_label(self) -> None:
        cfg = settings_manager.data
        self._model_label.setText(
            f"翻译:{cfg.translate_model} | 总结:{cfg.summary_model} | "
            f"导图:{cfg.mindmap_model} | ASR:{cfg.whisper_model}"
        )

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.saved.connect(self._refresh_model_label)
        dlg.exec()

    def _on_play(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入 B 站视频链接")
            return
        settings_manager.reload()
        if not settings_manager.data.dashscope_api_key:
            QMessageBox.warning(self, "缺少 API Key", "请点击「大模型配置」设置 API Key")
            return

        self._page_url = url
        self._ai_panel.set_page_url(url)
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._subtitle.clear()
        self._clear_log()
        self._append_log(f"开始处理: {url}")
        self.statusBar().showMessage("正在解析视频…")

        threading.Thread(target=self._load_and_start, args=(url,), daemon=True).start()

    def _load_and_start(self, page_url: str) -> None:
        try:
            self._emit_log("正在解析 B 站链接…")
            info = resolve_bilibili_url(page_url)
            self._video_info = info
            transcript_store.start_session(info.title, page_url)
            self._emit_log(f"解析成功: {info.title}")
            self._emit_log(
                f"INFO 视频流: vcodec={getattr(info, 'vcodec', None)} "
                f"height={getattr(info, 'height', None)} "
                f"format_id={getattr(info, 'format_id', None)}"
            )
            self._signals.status.emit(f"已解析: {info.title}")
            self._emit_log("正在切换到主线程启动播放与管线…")
            self._signals.playback_ready.emit(info)
        except Exception as exc:
            self._emit_log(f"ERROR 解析失败: {exc}")
            self._signals.status.emit(f"解析失败: {exc}")
            self._signals.reset_controls.emit()

    def _start_playback(self, info) -> None:
        self._emit_log("主线程: 开始启动播放与同声传译管线")
        self._title_label.setText(info.title)

        if self._player:
            self._emit_log("正在销毁旧播放器…")
            self._player.destroy()

        self._pending_play_info = info
        self._emit_log("正在初始化 mpv 播放器…")
        # 延迟到事件循环下一拍，确保视频容器已 show 且有有效 winId
        QTimer.singleShot(0, self._attach_and_play)

    def _attach_and_play(self) -> None:
        info = getattr(self, "_pending_play_info", None)
        if not info:
            return
        self._pending_play_info = None

        try:
            self._player = MpvPlayer(self._video_container, on_log=self._emit_log)
            self._emit_log("正在启动 mpv（嵌入优先，失败则独立窗口）…")
            self._player.attach()
            self._emit_log(f"正在播放视频流: {info.url[:80]}…")
            self._player.play(info.url, referer=info.webpage_url)
            mode = "嵌入" if self._player.is_embedded else "独立窗口"
            self._emit_log(f"视频播放器已启动 ({mode})")
            if not self._player.is_embedded:
                self._signals.status.emit("视频在独立 mpv 窗口中播放")
                self._title_label.setText(
                    f"{info.title}  ·  画面在独立 mpv 窗口（勿关）"
                )
                self._emit_log(
                    "INFO macOS 默认独立 mpv 窗口以避免嵌入黑屏；"
                    "若需尝试嵌入请设置环境变量 ETC_MPV_EMBED=1"
                )
        except Exception as exc:
            self._emit_log(f"ERROR 视频播放失败: {exc}")
            self._signals.status.emit(f"视频播放失败: {exc}")
            return

        if self._pipeline:
            self._emit_log("正在停止旧管线…")
            self._pipeline.stop()

        self._pending_pipeline_info = info
        self._emit_log("视频已启动，1s 后启动同声传译管线…")
        QTimer.singleShot(1000, self._start_pipeline)

    def _start_pipeline(self) -> None:
        info = self._pending_pipeline_info
        self._pending_pipeline_info = None
        if not info:
            return

        self._emit_log("正在创建同声传译管线…")
        self._pipeline = InterpretationPipeline(
            self._page_url,
            stream_url=info.url,
            referer=info.webpage_url,
            on_subtitle_partial=lambda t: self._signals.subtitle_partial.emit(t),
            on_subtitle_final=lambda e, c, ts: self._signals.subtitle_final.emit(e, c, ts),
            on_status=lambda s: self._signals.status.emit(s),
            on_log=lambda s: self._signals.log.emit(s),
        )
        self._emit_log("正在启动管线 (音频提取 / ASR / 翻译)…")
        self._pipeline.start()
        self._emit_log(
            "INFO 已启用播放优化: mpv 60s 缓存, 音频提取延迟 4s, "
            "yt-dlp 限速 2M/s"
        )
        self.statusBar().showMessage("播放中 · 同声传译已启动")

    def _on_stop(self) -> None:
        if self._pipeline:
            self._pipeline.stop()
            self._pipeline = None
        if self._player:
            self._player.stop()
        self._reset_play_controls()
        self._subtitle.clear()
        self._emit_log("已停止")
        self.statusBar().showMessage("已停止")

    def _reset_play_controls(self) -> None:
        self._play_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)

    def _emit_log(self, msg: str) -> None:
        self._signals.log.emit(msg)

    def _append_log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self._log_panel.append(line)
        sb = self._log_panel.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_log(self) -> None:
        self._log_panel.clear()

    def _on_subtitle_partial(self, text: str) -> None:
        self._subtitle.set_partial(text)

    def _on_subtitle_final(self, english: str, chinese: str, timestamp: float) -> None:
        self._subtitle.set_final(english, chinese)
        transcript_store.add_segment(english, chinese, timestamp)

    def _on_status(self, msg: str) -> None:
        self.statusBar().showMessage(msg)

    def closeEvent(self, event):
        self._on_stop()
        if self._player:
            self._player.destroy()
        super().closeEvent(event)
