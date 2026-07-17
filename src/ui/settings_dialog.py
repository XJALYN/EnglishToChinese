"""可视化大模型配置对话框 — Corporate Clean."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.config import (
    LLM_PROVIDERS,
    TTS_VOICE_OPTIONS,
    WHISPER_MODELS,
    provider_base_url,
    provider_models,
    settings_manager,
)


class SettingsDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(580)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        title = QLabel("大模型与 ASR")
        title.setObjectName("panelHeading")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setHorizontalSpacing(16)

        self._provider = QComboBox()
        for pid, meta in LLM_PROVIDERS.items():
            self._provider.addItem(meta["label"], pid)
        self._provider.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("大模型厂商", self._provider)

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-…")

        show_btn = QPushButton("显示")
        show_btn.setFixedWidth(56)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self._toggle_key_visibility)
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(self._api_key)
        key_row.addWidget(show_btn)
        self._api_key_label = QLabel("API Key")
        form.addRow(self._api_key_label, key_row)

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("https://…")
        form.addRow("Base URL", self._base_url)

        self._translate_model = QComboBox()
        self._translate_model.setEditable(True)
        form.addRow("同声传译模型", self._translate_model)

        self._summary_model = QComboBox()
        self._summary_model.setEditable(True)
        form.addRow("总结模型", self._summary_model)

        self._mindmap_model = QComboBox()
        self._mindmap_model.setEditable(True)
        form.addRow("思维导图模型", self._mindmap_model)

        self._whisper_model = QComboBox()
        self._whisper_model.addItems(WHISPER_MODELS)
        form.addRow("本地 ASR 模型", self._whisper_model)

        self._tts_voice = QComboBox()
        self._tts_voice.setEditable(True)
        self._populate_tts_voices()
        form.addRow("TTS 音色", self._tts_voice)

        self._hf_endpoint = QLineEdit()
        form.addRow("HF 镜像", self._hf_endpoint)

        layout.addLayout(form)

        latency_title = QLabel("同声传译延时")
        latency_title.setObjectName("panelHeading")
        layout.addWidget(latency_title)

        latency_form = QFormLayout()
        latency_form.setSpacing(12)
        latency_form.setHorizontalSpacing(16)

        self._interpretation_delay = QDoubleSpinBox()
        self._interpretation_delay.setRange(0.5, 10.0)
        self._interpretation_delay.setSingleStep(0.5)
        self._interpretation_delay.setSuffix(" 秒")
        self._interpretation_delay.setToolTip(
            "配音相对画面内容的计划延迟。越小响应越快，但过小易与画面对不上。"
        )
        latency_form.addRow("配音延迟", self._interpretation_delay)

        self._startup_delay = QDoubleSpinBox()
        self._startup_delay.setRange(0.0, 15.0)
        self._startup_delay.setSingleStep(0.5)
        self._startup_delay.setSuffix(" 秒")
        self._startup_delay.setToolTip("视频开播后等待缓冲再启动音频提取。可设为 0 立即开始。")
        latency_form.addRow("启动等待", self._startup_delay)

        self._chunk_seconds = QDoubleSpinBox()
        self._chunk_seconds.setRange(1.0, 8.0)
        self._chunk_seconds.setSingleStep(0.5)
        self._chunk_seconds.setSuffix(" 秒")
        self._chunk_seconds.setToolTip("每块送入 ASR 的音频长度。越小延迟越低，CPU 占用略增。")
        latency_form.addRow("音频分块", self._chunk_seconds)

        self._chunk_overlap = QDoubleSpinBox()
        self._chunk_overlap.setRange(0.0, 3.0)
        self._chunk_overlap.setSingleStep(0.1)
        self._chunk_overlap.setSuffix(" 秒")
        self._chunk_overlap.setToolTip("相邻音频块重叠时长，避免切词。通常 0.2~0.5 秒。")
        latency_form.addRow("块间重叠", self._chunk_overlap)

        layout.addLayout(latency_form)

        latency_hint = QLabel(
            "低延时推荐：配音延迟 1.5s、启动等待 1s、音频分块 2s、块间重叠 0.3s；"
            "翻译模型选 qwen-turbo，ASR 选 tiny。修改后需重启同传。"
        )
        latency_hint.setObjectName("settingsHint")
        latency_hint.setWordWrap(True)
        layout.addWidget(latency_hint)

        hint = QLabel(
            "支持百炼、OpenAI、DeepSeek 及自定义 OpenAI 兼容接口。\n"
            "配置保存至 config.json 并同步 .env；切换厂商会保留各自 API Key。"
        )
        hint.setObjectName("settingsHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setObjectName("primaryBtn")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._pending_credentials: dict[str, dict[str, str]] = {}

    def _current_provider_id(self) -> str:
        return self._provider.currentData() or "dashscope"

    def _stash_current_credentials(self) -> None:
        pid = self._current_provider_id()
        self._pending_credentials[pid] = {
            "api_key": self._api_key.text().strip(),
            "base_url": self._base_url.text().strip(),
        }

    def _on_provider_changed(self, _index: int) -> None:
        self._stash_current_credentials()
        pid = self._current_provider_id()
        meta = LLM_PROVIDERS[pid]

        cred = self._pending_credentials.get(pid, {})
        self._api_key.setText(cred.get("api_key", ""))
        base = cred.get("base_url") or provider_base_url(pid)
        self._base_url.setText(base)
        self._base_url.setReadOnly(pid != "custom")
        if pid != "custom":
            self._base_url.setStyleSheet("color: palette(mid);")
        else:
            self._base_url.setStyleSheet("")

        self._api_key_label.setText(f"{meta['label']} API Key")
        self._populate_model_combos(pid)

    def _populate_model_combos(self, provider: str) -> None:
        models = provider_models(provider)
        for combo in (self._translate_model, self._summary_model, self._mindmap_model):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            if models:
                combo.addItems(models)
                combo.setEditable(False)
            else:
                combo.setEditable(True)
                le = combo.lineEdit()
                if le:
                    le.setPlaceholderText("输入模型名称")
            if current:
                self._set_combo(combo, current)
            elif models:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self._api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        sender = self.sender()
        if isinstance(sender, QPushButton):
            sender.setText("隐藏" if visible else "显示")

    def _load(self) -> None:
        cfg = settings_manager.data
        self._pending_credentials = dict(cfg.provider_credentials)

        self._provider.blockSignals(True)
        idx = self._provider.findData(cfg.llm_provider)
        if idx >= 0:
            self._provider.setCurrentIndex(idx)
        self._provider.blockSignals(False)

        pid = cfg.llm_provider
        meta = LLM_PROVIDERS[pid]
        cred = self._pending_credentials.get(pid, {})
        self._api_key.setText(cred.get("api_key") or cfg.llm_api_key)
        self._base_url.setText(
            cred.get("base_url") or cfg.llm_base_url or provider_base_url(pid)
        )
        self._base_url.setReadOnly(pid != "custom")
        if pid != "custom":
            self._base_url.setStyleSheet("color: palette(mid);")
        else:
            self._base_url.setStyleSheet("")

        self._api_key_label.setText(f"{meta['label']} API Key")
        self._populate_model_combos(pid)
        self._set_combo(self._translate_model, cfg.translate_model)
        self._set_combo(self._summary_model, cfg.summary_model)
        self._set_combo(self._mindmap_model, cfg.mindmap_model)
        self._set_combo(self._whisper_model, cfg.whisper_model)
        self._set_tts_voice(cfg.tts_voice)
        self._hf_endpoint.setText(cfg.hf_endpoint)
        self._interpretation_delay.setValue(cfg.interpretation_delay)
        self._startup_delay.setValue(cfg.startup_delay)
        self._chunk_seconds.setValue(cfg.chunk_seconds)
        self._chunk_overlap.setValue(cfg.chunk_overlap)

    def _populate_tts_voices(self) -> None:
        self._tts_voice.clear()
        last_cat: str | None = None
        for opt in TTS_VOICE_OPTIONS:
            if opt.category != last_cat:
                if last_cat is not None:
                    self._tts_voice.insertSeparator(self._tts_voice.count())
                last_cat = opt.category
            self._tts_voice.addItem(f"{opt.label}  ({opt.voice_id})", opt.voice_id)

    def _set_tts_voice(self, voice_id: str) -> None:
        idx = self._tts_voice.findData(voice_id)
        if idx >= 0:
            self._tts_voice.setCurrentIndex(idx)
        else:
            self._tts_voice.addItem(voice_id, voice_id)
            self._tts_voice.setCurrentIndex(self._tts_voice.count() - 1)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(value)

    def _save(self) -> None:
        self._stash_current_credentials()
        pid = self._current_provider_id()
        key = self._api_key.text().strip()
        base_url = self._base_url.text().strip()

        if not key:
            QMessageBox.warning(self, "提示", "请填写 API Key")
            return
        if pid == "custom" and not base_url:
            QMessageBox.warning(self, "提示", "自定义厂商请填写 Base URL")
            return

        chunk_seconds = self._chunk_seconds.value()
        chunk_overlap = self._chunk_overlap.value()
        if chunk_overlap >= chunk_seconds * 0.8:
            QMessageBox.warning(
                self,
                "提示",
                "块间重叠过大，应小于音频分块的 80%。",
            )
            return

        settings_manager.save(
            {
                "llm_provider": pid,
                "llm_api_key": key,
                "llm_base_url": base_url,
                "provider_credentials": self._pending_credentials,
                "translate_model": self._translate_model.currentText().strip(),
                "summary_model": self._summary_model.currentText().strip(),
                "mindmap_model": self._mindmap_model.currentText().strip(),
                "whisper_model": self._whisper_model.currentText(),
                "tts_voice": (
                    self._tts_voice.currentData()
                    or self._tts_voice.currentText().strip()
                ),
                "hf_endpoint": self._hf_endpoint.text().strip(),
                "interpretation_delay": self._interpretation_delay.value(),
                "startup_delay": self._startup_delay.value(),
                "chunk_seconds": chunk_seconds,
                "chunk_overlap": chunk_overlap,
            }
        )
        settings_manager.reload()
        self.saved.emit()
        self.accept()
