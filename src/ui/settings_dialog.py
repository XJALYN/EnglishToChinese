"""可视化大模型配置对话框."""

from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from src.config import QWEN_MODELS, TTS_VOICES, WHISPER_MODELS, settings_manager


class SettingsDialog(QDialog):
    saved = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("大模型配置")
        self.setMinimumWidth(480)
        self._build()
        self._load()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-...")
        form.addRow("百炼 API Key", self._api_key)

        show_btn = QPushButton("显示")
        show_btn.setFixedWidth(48)
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self._toggle_key_visibility)
        key_row = QHBoxLayout()
        key_row.addWidget(self._api_key)
        key_row.addWidget(show_btn)
        form.addRow("", key_row)

        self._translate_model = QComboBox()
        self._translate_model.addItems(QWEN_MODELS)
        form.addRow("同声传译模型", self._translate_model)

        self._summary_model = QComboBox()
        self._summary_model.addItems(QWEN_MODELS)
        form.addRow("AI 总结模型", self._summary_model)

        self._mindmap_model = QComboBox()
        self._mindmap_model.addItems(QWEN_MODELS)
        form.addRow("思维导图模型", self._mindmap_model)

        self._whisper_model = QComboBox()
        self._whisper_model.addItems(WHISPER_MODELS)
        form.addRow("本地 ASR 模型", self._whisper_model)

        self._tts_voice = QComboBox()
        self._tts_voice.setEditable(True)
        self._tts_voice.addItems(TTS_VOICES)
        form.addRow("TTS 音色", self._tts_voice)

        self._hf_endpoint = QLineEdit()
        form.addRow("HF 镜像", self._hf_endpoint)

        layout.addLayout(form)

        hint = QLabel(
            "配置保存至 config.json 并同步 .env。\n"
            "也可使用 Electron 前端（npm run electron）连接同一套 Python 后端。"
        )
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_key_visibility(self, visible: bool) -> None:
        self._api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )

    def _load(self) -> None:
        cfg = settings_manager.data
        self._api_key.setText(cfg.dashscope_api_key)
        self._set_combo(self._translate_model, cfg.translate_model)
        self._set_combo(self._summary_model, cfg.summary_model)
        self._set_combo(self._mindmap_model, cfg.mindmap_model)
        self._set_combo(self._whisper_model, cfg.whisper_model)
        self._set_combo(self._tts_voice, cfg.tts_voice)
        self._hf_endpoint.setText(cfg.hf_endpoint)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setEditText(value)

    def _save(self) -> None:
        key = self._api_key.text().strip()
        if not key:
            QMessageBox.warning(self, "提示", "请填写 API Key")
            return
        settings_manager.save(
            {
                "dashscope_api_key": key,
                "translate_model": self._translate_model.currentText(),
                "summary_model": self._summary_model.currentText(),
                "mindmap_model": self._mindmap_model.currentText(),
                "whisper_model": self._whisper_model.currentText(),
                "tts_voice": self._tts_voice.currentText(),
                "hf_endpoint": self._hf_endpoint.text().strip(),
            }
        )
        settings_manager.reload()
        self.saved.emit()
        self.accept()
