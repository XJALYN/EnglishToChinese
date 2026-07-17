"""主窗口: 视频播放 + 同声传译 + AI 总结/思维导图 — Corporate Clean 布局."""

from __future__ import annotations

import threading
from datetime import datetime

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config import settings_manager
from src.pipeline.pipeline_manager import InterpretationPipeline
from src.player.bilibili import resolve_video_url
from src.player.mpv_player import WINDOW_TITLE, MpvPlayer
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
    stop_complete = pyqtSignal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("本地同声传译播放器")
        self.resize(1440, 880)

        self._pipeline: InterpretationPipeline | None = None
        self._player: MpvPlayer | None = None
        self._video_info = None
        self._page_url = ""
        self._pending_pipeline_info = None
        self._log_expanded = True
        self._stopping = False
        self._stop_done = threading.Event()
        self._stop_done.set()

        self._signals = _BridgeSignals()
        self._signals.subtitle_partial.connect(self._on_subtitle_partial)
        self._signals.subtitle_final.connect(self._on_subtitle_final)
        self._signals.status.connect(self._on_status)
        self._signals.log.connect(self._append_log)
        self._signals.playback_ready.connect(self._start_playback)
        self._signals.reset_controls.connect(self._reset_play_controls)
        self._signals.stop_complete.connect(self._on_stop_complete)

        self._build_ui()
        self._refresh_model_label()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_top_bar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 14, 16, 12)
        body_layout.setSpacing(12)

        # 主区域：舞台 | AI
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)

        splitter.addWidget(self._build_stage())
        self._ai_panel = AiPanel()
        self._ai_panel.setMinimumWidth(360)
        self._ai_panel.setObjectName("aiPanel")
        splitter.addWidget(self._ai_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([860, 480])
        body_layout.addWidget(splitter, stretch=1)

        body_layout.addWidget(self._build_log_strip())
        root.addWidget(body, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")

        if not MpvPlayer.is_available():
            self.statusBar().showMessage("警告: 未安装 mpv，请运行 brew install mpv")

    def _build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topBar")
        bar.setFixedHeight(64)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 10, 16, 10)
        layout.setSpacing(12)

        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        brand_col.setContentsMargins(0, 0, 8, 0)
        brand = QLabel("本地同声传译")
        brand.setObjectName("brandTitle")
        brand_sub = QLabel("播放器")
        brand_sub.setObjectName("brandSub")
        brand_col.addWidget(brand)
        brand_col.addWidget(brand_sub)
        layout.addLayout(brand_col)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet("color: #e5e7eb; max-width: 1px;")
        layout.addWidget(divider)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("粘贴视频链接（Bilibili / YouTube）…")
        self._url_input.setMinimumWidth(280)
        layout.addWidget(self._url_input, stretch=1)

        self._play_btn = QPushButton("开始同传")
        self._play_btn.setObjectName("primaryBtn")
        self._play_btn.clicked.connect(self._on_play)
        layout.addWidget(self._play_btn)

        self._stop_btn = QPushButton("停止")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)
        layout.addWidget(self._stop_btn)

        self._settings_btn = QPushButton("设置")
        self._settings_btn.clicked.connect(self._open_settings)
        layout.addWidget(self._settings_btn)

        return bar

    def _build_stage(self) -> QWidget:
        stage = QWidget()
        stage.setObjectName("stageCard")
        layout = QVBoxLayout(stage)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        # 标题行：长标题截断，避免把窗口撑宽
        info = QHBoxLayout()
        info.setSpacing(10)
        self._title_full = "等待输入链接"
        self._title_suffix = ""
        self._title_label = QLabel("等待输入链接")
        self._title_label.setObjectName("videoTitle")
        self._title_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self._title_label.setMinimumWidth(0)
        self._title_label.setWordWrap(False)
        info.addWidget(self._title_label, stretch=1)
        self._model_label = QLabel()
        self._model_label.setObjectName("modelMeta")
        self._model_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._model_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        self._model_label.setMinimumWidth(0)
        self._model_label.setWordWrap(False)
        info.addWidget(self._model_label, stretch=0)
        layout.addLayout(info)

        # 视频舞台（mpv 独立窗口时显示提示；内嵌时仍需空容器）
        video_wrap = QWidget()
        video_wrap.setObjectName("videoStage")
        # 重叠布局：容器始终参与布局（保证 winId），提示层按需显隐
        grid = QGridLayout(video_wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)

        # mpv embed 容器必须始终为空：任何子控件在 macOS 上都会导致黑屏
        self._video_container = QWidget()
        self._video_container.setMinimumSize(640, 320)
        self._video_container.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._video_container.setAttribute(
            Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True
        )
        self._video_container.setStyleSheet("background: transparent;")
        grid.addWidget(self._video_container, 0, 0)

        self._stage_hint_wrap = QWidget()
        self._stage_hint_wrap.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self._stage_hint_wrap.setStyleSheet("background: transparent;")
        hint_layout = QVBoxLayout(self._stage_hint_wrap)
        hint_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_layout.setContentsMargins(24, 24, 24, 24)
        hint_layout.setSpacing(6)
        self._stage_hint = QLabel("视频画面")
        self._stage_hint.setObjectName("stageHint")
        self._stage_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage_hint_sub = QLabel(
            "开始同传后，画面在独立 mpv 窗口播放\n"
            f"窗口标题：「{WINDOW_TITLE}」"
        )
        self._stage_hint_sub.setObjectName("stageHintSmall")
        self._stage_hint_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stage_hint_sub.setWordWrap(True)
        hint_layout.addWidget(self._stage_hint)
        hint_layout.addWidget(self._stage_hint_sub)
        grid.addWidget(self._stage_hint_wrap, 0, 0)

        layout.addWidget(video_wrap, stretch=1)

        focus_row = QHBoxLayout()
        focus_row.setSpacing(8)
        self._video_alert = QLabel("")
        self._video_alert.setObjectName("videoAlert")
        self._video_alert.setWordWrap(True)
        self._video_alert.setVisible(False)
        focus_row.addWidget(self._video_alert, stretch=1)
        self._focus_video_btn = QPushButton("前置视频窗口")
        self._focus_video_btn.setObjectName("ghostBtn")
        self._focus_video_btn.setVisible(False)
        self._focus_video_btn.clicked.connect(self._on_focus_video)
        focus_row.addWidget(self._focus_video_btn)
        layout.addLayout(focus_row)

        # 字幕条（兄弟控件，绝不挂到 embed 容器）
        self._subtitle = SubtitleOverlay()
        layout.addWidget(self._subtitle)

        return stage

    def _build_log_strip(self) -> QWidget:
        strip = QWidget()
        strip.setObjectName("logStrip")
        layout = QVBoxLayout(strip)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._log_heading = QLabel("运行日志")
        self._log_heading.setObjectName("logHeading")
        header.addWidget(self._log_heading)
        header.addStretch()

        self._clear_log_btn = QPushButton("清空")
        self._clear_log_btn.setObjectName("ghostBtn")
        self._clear_log_btn.clicked.connect(self._clear_log)
        header.addWidget(self._clear_log_btn)

        self._toggle_log_btn = QPushButton("收起")
        self._toggle_log_btn.setObjectName("ghostBtn")
        self._toggle_log_btn.clicked.connect(self._toggle_log)
        header.addWidget(self._toggle_log_btn)
        layout.addLayout(header)

        self._log_panel = QTextEdit()
        self._log_panel.setObjectName("logPanel")
        self._log_panel.setReadOnly(True)
        self._log_panel.setMinimumHeight(100)
        self._log_panel.setMaximumHeight(160)
        self._log_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._log_panel)

        self._append_log("应用已启动，等待输入视频链接…")
        return strip

    def _toggle_log(self) -> None:
        self._log_expanded = not self._log_expanded
        self._log_panel.setVisible(self._log_expanded)
        self._toggle_log_btn.setText("收起" if self._log_expanded else "展开")

    def _set_stage_hint_visible(self, visible: bool) -> None:
        self._stage_hint_wrap.setVisible(visible)

    def _set_video_title(self, title: str, *, suffix: str = "") -> None:
        self._title_full = title or ""
        self._title_suffix = suffix or ""
        tip = (
            f"{self._title_full}  ·  {self._title_suffix}"
            if self._title_suffix
            else self._title_full
        )
        self._title_label.setToolTip(tip)
        self._elide_video_title()

    def _elide_video_title(self) -> None:
        full = self._title_full
        if self._title_suffix:
            full = f"{self._title_full}  ·  {self._title_suffix}"
        width = max(self._title_label.width() - 8, 80)
        elided = self._title_label.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, width
        )
        self._title_label.setText(elided)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._elide_model_label()
        self._elide_video_title()

    def _refresh_model_label(self) -> None:
        from src.config import LLM_PROVIDERS

        cfg = settings_manager.data
        provider_label = LLM_PROVIDERS.get(cfg.llm_provider, {}).get(
            "label", cfg.llm_provider
        )
        self._model_label.setText(
            f"{provider_label}  ·  翻译 {cfg.translate_model}  ·  "
            f"总结 {cfg.summary_model}  ·  导图 {cfg.mindmap_model}  ·  "
            f"ASR {cfg.whisper_model}"
        )
        self._model_label.setToolTip(self._model_label.text())
        # 模型元信息过长时也截断，避免撑开窗口
        QTimer.singleShot(0, self._elide_model_label)

    def _elide_model_label(self) -> None:
        full = self._model_label.toolTip() or self._model_label.text()
        if not full:
            return
        # 最多约占舞台宽度 40%，且不超过 420px
        stage_w = max(self._title_label.parentWidget().width() if self._title_label.parentWidget() else 800, 400)
        max_w = min(420, int(stage_w * 0.4))
        elided = self._model_label.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideRight, max_w
        )
        self._model_label.setText(elided)
        self._model_label.setMaximumWidth(max_w)
        self._elide_video_title()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.saved.connect(self._refresh_model_label)
        dlg.exec()

    def _on_play(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请输入视频链接（Bilibili / YouTube）")
            return
        settings_manager.reload()
        if not settings_manager.data.active_api_key():
            QMessageBox.warning(self, "缺少 API Key", "请点击「设置」配置 API Key")
            return

        self._page_url = url
        self._ai_panel.set_page_url(url)
        self._play_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._subtitle.clear()
        self._clear_log()
        self._append_log(f"开始处理: {url}")
        self._stage_hint.setText("正在解析…")
        self._stage_hint_sub.setText("请稍候")
        self._set_stage_hint_visible(True)
        self.statusBar().showMessage("正在解析视频…")

        threading.Thread(target=self._load_and_start, args=(url,), daemon=True).start()

    def _load_and_start(self, page_url: str) -> None:
        try:
            self._emit_log("正在解析视频链接…")
            info = resolve_video_url(page_url)
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
        self._set_video_title(info.title)

        if self._player:
            self._emit_log("正在销毁旧播放器…")
            self._player.destroy()

        self._pending_play_info = info
        self._emit_log("正在初始化 mpv 播放器…")
        QTimer.singleShot(0, self._attach_and_play)

    def _attach_and_play(self) -> None:
        info = getattr(self, "_pending_play_info", None)
        if not info:
            return
        self._pending_play_info = None

        try:
            self._player = MpvPlayer(self._video_container, on_log=self._emit_log)
            self._player.window_opened.connect(self._on_video_window_opened)
            self._player.window_failed.connect(self._on_video_window_failed)
            self._emit_log("正在启动 mpv（macOS 默认系统独立窗口）…")
            self._player.attach()
            self._emit_log(
                f"正在播放视频流: vcodec={getattr(info, 'vcodec', None)} "
                f"h={getattr(info, 'height', None)} "
                f"url={info.url[:80]}…"
            )
            page = info.webpage_url or self._page_url
            self._player.play(info.url, referer=info.webpage_url, page_url=page)
            mode = getattr(self._player, "playback_mode", None) or (
                "embedded" if self._player.is_embedded else "external"
            )
            mode_cn = {
                "embedded": "主界面内嵌",
                "external": "python-mpv 独立窗口",
                "subprocess": "系统 mpv 独立窗口",
            }.get(mode, mode)
            src = getattr(self._player, "source_mode", "") or ""
            self._emit_log(f"视频播放器已启动 ({mode_cn} / {mode} / source={src})")
            if not self._player.is_embedded:
                self._signals.status.emit(f"视频窗口已打开（标题: {WINDOW_TITLE}），请查看独立窗口")
                self._set_video_title(info.title, suffix="画面在独立 mpv 窗口")
                self._stage_hint.setText("视频窗口已打开")
                self._stage_hint_sub.setText(
                    f"标题：「{WINDOW_TITLE}」\n"
                    "勿关闭该窗口；此处显示实时字幕"
                )
                self._set_stage_hint_visible(True)
                self._show_video_alert(
                    f"视频窗口已打开（标题: {WINDOW_TITLE}），请查看独立窗口"
                )
                self._focus_video_btn.setVisible(True)
                self._emit_log(
                    f"INFO 画面在独立系统 mpv 窗口，标题「{WINDOW_TITLE}」，"
                    "会短暂置顶；可点「前置视频窗口」。"
                )
            else:
                self._set_stage_hint_visible(False)
                self._focus_video_btn.setVisible(False)
                self._video_alert.setVisible(False)
        except Exception as exc:
            self._emit_log(f"ERROR 视频播放失败: {exc}")
            self._signals.status.emit(f"视频播放失败: {exc}")
            self._stage_hint.setText("播放失败")
            self._stage_hint_sub.setText(str(exc))
            self._set_stage_hint_visible(True)
            self._show_video_alert(f"播放失败: {exc}")
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
        start_offset = 0.0
        if self._player:
            try:
                start_offset = float(self._player.get_position() or 0.0)
            except Exception:
                start_offset = 0.0

        self._pipeline = InterpretationPipeline(
            self._page_url,
            stream_url=info.url,
            referer=info.webpage_url,
            start_offset=start_offset,
            get_media_position=lambda: (
                self._player.get_position() if self._player else 0.0
            ),
            on_tts_active=self._on_tts_active,
            on_subtitle_partial=lambda t: self._signals.subtitle_partial.emit(t),
            on_subtitle_final=lambda e, c, ts: self._signals.subtitle_final.emit(e, c, ts),
            on_status=lambda s: self._signals.status.emit(s),
            on_log=lambda s: self._signals.log.emit(s),
        )
        self._emit_log("正在启动管线 (音频提取 / ASR / 翻译)…")
        self._pipeline.start()
        if self._player:
            self._player.set_volume(40, mute=False)
        self._emit_log(
            f"INFO 音频策略: 原声40%保底; 配音延迟 "
            f"{settings_manager.data.interpretation_delay:.0f}s; "
            f"起点≈{start_offset:.1f}s"
        )
        self.statusBar().showMessage("播放中 · 同声传译已启动（原声已开启作保底）")

    def _on_stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._stop_done.clear()
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("正在停止…")
        self._play_btn.setEnabled(False)
        self._emit_log("INFO 开始停止播放与同声传译…")
        self.statusBar().showMessage("正在停止…")

        # Stop video immediately so playback feels responsive.
        if self._player:
            self._player.stop()

        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self) -> None:
        try:
            pipeline = self._pipeline
            self._pipeline = None
            if pipeline:
                pipeline.stop()
        except Exception as exc:
            self._signals.log.emit(f"ERROR 停止管线失败: {exc}")
        finally:
            self._signals.stop_complete.emit()

    def _on_stop_complete(self) -> None:
        self._stopping = False
        self._stop_done.set()
        self._stop_btn.setText("停止")
        self._reset_play_controls()
        self._subtitle.clear()
        self._stage_hint.setText("视频画面")
        self._stage_hint_sub.setText(
            "开始同传后，画面在独立 mpv 窗口播放\n"
            f"窗口标题：「{WINDOW_TITLE}」"
        )
        self._set_stage_hint_visible(True)
        self._focus_video_btn.setVisible(False)
        self._video_alert.setVisible(False)
        self._emit_log("INFO 停止完成")
        self.statusBar().showMessage("已停止")

    def _show_video_alert(self, text: str) -> None:
        self._video_alert.setText(text)
        self._video_alert.setVisible(True)

    def _on_video_window_opened(self, title: str) -> None:
        msg = f"视频窗口已打开（标题: {title}），请查看独立窗口"
        self._show_video_alert(msg)
        self._focus_video_btn.setVisible(True)
        self._stage_hint.setText("视频窗口已打开")
        self._stage_hint_sub.setText(f"标题：「{title}」\n可点右侧按钮前置窗口")
        self._signals.status.emit(msg)
        self._emit_log(f"INFO {msg}")

    def _on_video_window_failed(self, reason: str) -> None:
        msg = f"视频窗口未能出画: {reason}"
        self._show_video_alert(msg)
        self._stage_hint.setText("未检测到画面")
        self._stage_hint_sub.setText(reason)
        self._signals.status.emit(msg)
        self._emit_log(f"ERROR {msg}")
        QMessageBox.warning(self, "视频画面", msg)

    def _on_focus_video(self) -> None:
        if self._player:
            self._player.focus_window()
            self._emit_log(f"INFO 再次前置「{WINDOW_TITLE}」")
            self.statusBar().showMessage(f"已尝试前置「{WINDOW_TITLE}」")

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

    def _on_tts_active(self, active: bool) -> None:
        """TTS 播出时压低原声，避免盖过中文配音；结束或失败则恢复保底音量."""
        if not self._player:
            return
        try:
            if active:
                self._player.set_volume(8, mute=False)
            else:
                self._player.set_volume(40, mute=False)
        except Exception:
            pass

    def closeEvent(self, event):
        if self._stopping:
            self._stop_done.wait(timeout=2.0)
        elif self._pipeline or self._player:
            self._on_stop()
            self._stop_done.wait(timeout=2.0)
        if self._player:
            self._player.destroy()
            self._player = None
        super().closeEvent(event)
