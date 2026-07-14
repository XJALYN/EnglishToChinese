"""可持久化、可视化的应用配置."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.json"

load_dotenv(ENV_PATH)

WHISPER_MODELS = ["tiny", "base", "small", "medium"]
QWEN_MODELS = ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"]
TTS_VOICES = [
    "longxiaochun_v3",
    "longanyang",
    "longanhuan",
    "longcheng_v3",
    "longze_v3",
    "longtian_v3",
]


def _resolve_api_key() -> str:
    key = os.getenv("DASHSCOPE_API_KEY", "")
    if key:
        return key
    bl_config = Path.home() / ".bailian" / "config.json"
    if bl_config.exists():
        try:
            data = json.loads(bl_config.read_text())
            return data.get("api_key") or data.get("apiKey") or ""
        except (json.JSONDecodeError, OSError):
            pass
    return ""


@dataclass
class AppSettings:
    dashscope_api_key: str = ""
    translate_model: str = "qwen-plus"
    summary_model: str = "qwen-plus"
    mindmap_model: str = "qwen-plus"
    whisper_model: str = "base"
    tts_voice: str = "longxiaochun_v3"
    hf_endpoint: str = "https://hf-mirror.com"

    sample_rate: int = 16000
    chunk_seconds: float = 3.0
    chunk_overlap: float = 0.5
    tts_sample_rate: int = 24000
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"


class SettingsManager:
    """单例配置管理，支持 GUI 读写与 .env / config.json 同步."""

    _instance: SettingsManager | None = None

    def __new__(cls) -> SettingsManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self) -> None:
        if self._loaded:
            return
        self._data = AppSettings()
        self.reload()
        self._loaded = True

    @property
    def data(self) -> AppSettings:
        return self._data

    def reload(self) -> None:
        env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
        cfg: dict = {}
        if CONFIG_PATH.exists():
            try:
                cfg = json.loads(CONFIG_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                cfg = {}

        self._data = AppSettings(
            dashscope_api_key=cfg.get("dashscope_api_key")
            or env.get("DASHSCOPE_API_KEY")
            or _resolve_api_key()
            or "",
            translate_model=cfg.get("translate_model")
            or env.get("TRANSLATE_MODEL")
            or "qwen-plus",
            summary_model=cfg.get("summary_model")
            or env.get("SUMMARY_MODEL")
            or env.get("TRANSLATE_MODEL")
            or "qwen-plus",
            mindmap_model=cfg.get("mindmap_model")
            or env.get("MINDMAP_MODEL")
            or env.get("TRANSLATE_MODEL")
            or "qwen-plus",
            whisper_model=cfg.get("whisper_model")
            or env.get("WHISPER_MODEL")
            or "base",
            tts_voice=cfg.get("tts_voice") or env.get("TTS_VOICE") or "longxiaochun_v3",
            hf_endpoint=cfg.get("hf_endpoint")
            or env.get("HF_ENDPOINT")
            or "https://hf-mirror.com",
        )

    def save(self, updates: dict | None = None) -> None:
        if updates:
            for k, v in updates.items():
                if hasattr(self._data, k):
                    setattr(self._data, k, v)

        persist = {
            "dashscope_api_key": self._data.dashscope_api_key,
            "translate_model": self._data.translate_model,
            "summary_model": self._data.summary_model,
            "mindmap_model": self._data.mindmap_model,
            "whisper_model": self._data.whisper_model,
            "tts_voice": self._data.tts_voice,
            "hf_endpoint": self._data.hf_endpoint,
        }
        CONFIG_PATH.write_text(json.dumps(persist, indent=2, ensure_ascii=False))
        self._sync_env(persist)

    def _sync_env(self, persist: dict) -> None:
        lines = {
            "DASHSCOPE_API_KEY": persist["dashscope_api_key"],
            "TRANSLATE_MODEL": persist["translate_model"],
            "SUMMARY_MODEL": persist["summary_model"],
            "MINDMAP_MODEL": persist["mindmap_model"],
            "WHISPER_MODEL": persist["whisper_model"],
            "TTS_VOICE": persist["tts_voice"],
            "HF_ENDPOINT": persist["hf_endpoint"],
        }
        existing: dict[str, str] = {}
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

        existing.update(lines)
        content = "\n".join(f"{k}={v}" for k, v in existing.items()) + "\n"
        ENV_PATH.write_text(content)

        for k, v in lines.items():
            os.environ[k if k != "DASHSCOPE_API_KEY" else k] = v
        os.environ["DASHSCOPE_API_KEY"] = persist["dashscope_api_key"]


settings_manager = SettingsManager()
# 向后兼容
settings = settings_manager.data
