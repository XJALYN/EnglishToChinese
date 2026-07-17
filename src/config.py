"""可持久化、可视化的应用配置."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config.json"

load_dotenv(ENV_PATH)

WHISPER_MODELS = ["tiny", "base", "small", "medium"]
from src.tts_voices import TTS_VOICES, TTS_VOICE_OPTIONS, tts_voice_catalog

# 向后兼容
QWEN_MODELS = ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"]

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "dashscope": {
        "label": "阿里云百炼 / DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"],
        "env_key": "DASHSCOPE_API_KEY",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
        "env_key": "OPENAI_API_KEY",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "env_key": "DEEPSEEK_API_KEY",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容",
        "base_url": "",
        "models": [],
        "env_key": "LLM_API_KEY",
    },
}

DEFAULT_LLM_PROVIDER = "dashscope"


def _resolve_api_key(env_name: str = "DASHSCOPE_API_KEY") -> str:
    key = os.getenv(env_name, "")
    if key:
        return key
    if env_name == "DASHSCOPE_API_KEY":
        bl_config = Path.home() / ".bailian" / "config.json"
        if bl_config.exists():
            try:
                data = json.loads(bl_config.read_text())
                return data.get("api_key") or data.get("apiKey") or ""
            except (json.JSONDecodeError, OSError):
                pass
    return ""


def provider_base_url(provider: str, custom_url: str = "") -> str:
    if provider == "custom":
        return custom_url.strip()
    return LLM_PROVIDERS.get(provider, LLM_PROVIDERS[DEFAULT_LLM_PROVIDER])["base_url"]


def provider_models(provider: str) -> list[str]:
    return list(LLM_PROVIDERS.get(provider, LLM_PROVIDERS[DEFAULT_LLM_PROVIDER])["models"])


def _float_setting(cfg: dict, env: dict, key: str, env_key: str, default: float) -> float:
    raw = cfg.get(key) if cfg.get(key) is not None else env.get(env_key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass
class AppSettings:
    llm_provider: str = DEFAULT_LLM_PROVIDER
    llm_api_key: str = ""
    llm_base_url: str = ""
    provider_credentials: dict[str, dict[str, str]] = field(default_factory=dict)

    # 向后兼容字段（DashScope 专用，与 llm_* 同步）
    dashscope_api_key: str = ""
    dashscope_base_url: str = LLM_PROVIDERS["dashscope"]["base_url"]

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
    # 同声传译固定听视间隔（秒）：配音相对画面内容的计划播放延迟
    interpretation_delay: float = 3.0
    # 视频开播后等待缓冲再启动音频提取（秒）
    startup_delay: float = 4.0

    def active_api_key(self) -> str:
        return self.llm_api_key.strip()

    def active_base_url(self) -> str:
        url = self.llm_base_url.strip()
        if url:
            return url
        return provider_base_url(self.llm_provider)


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

        provider = (
            cfg.get("llm_provider") or env.get("LLM_PROVIDER") or DEFAULT_LLM_PROVIDER
        )
        if provider not in LLM_PROVIDERS:
            provider = DEFAULT_LLM_PROVIDER

        credentials = cfg.get("provider_credentials") or {}
        if not isinstance(credentials, dict):
            credentials = {}

        # 向后兼容：旧版仅 dashscope_api_key
        legacy_key = (
            cfg.get("dashscope_api_key")
            or env.get("DASHSCOPE_API_KEY")
            or _resolve_api_key()
            or ""
        )
        if legacy_key and "dashscope" not in credentials:
            credentials["dashscope"] = {
                "api_key": legacy_key,
                "base_url": LLM_PROVIDERS["dashscope"]["base_url"],
            }

        # 从各厂商环境变量补全凭证
        for pid, meta in LLM_PROVIDERS.items():
            env_key = meta["env_key"]
            env_val = env.get(env_key, "")
            if env_val and pid not in credentials:
                credentials[pid] = {
                    "api_key": env_val,
                    "base_url": meta["base_url"],
                }

        cred = credentials.get(provider, {})
        llm_api_key = cfg.get("llm_api_key") or cred.get("api_key") or ""
        llm_base_url = (
            cfg.get("llm_base_url")
            or cred.get("base_url")
            or provider_base_url(provider)
        )

        if not llm_api_key and provider == "dashscope":
            llm_api_key = legacy_key

        dash_key = credentials.get("dashscope", {}).get("api_key") or legacy_key

        self._data = AppSettings(
            llm_provider=provider,
            llm_api_key=llm_api_key,
            llm_base_url=llm_base_url,
            provider_credentials=credentials,
            dashscope_api_key=dash_key,
            dashscope_base_url=LLM_PROVIDERS["dashscope"]["base_url"],
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
            interpretation_delay=_float_setting(
                cfg, env, "interpretation_delay", "INTERPRETATION_DELAY", 3.0
            ),
            startup_delay=_float_setting(cfg, env, "startup_delay", "STARTUP_DELAY", 4.0),
            chunk_seconds=_float_setting(cfg, env, "chunk_seconds", "CHUNK_SECONDS", 3.0),
            chunk_overlap=_float_setting(
                cfg, env, "chunk_overlap", "CHUNK_OVERLAP", 0.5
            ),
        )

    def save(self, updates: dict | None = None) -> None:
        if updates:
            for k, v in updates.items():
                if hasattr(self._data, k):
                    setattr(self._data, k, v)

        # 同步当前厂商凭证缓存
        creds = dict(self._data.provider_credentials)
        creds[self._data.llm_provider] = {
            "api_key": self._data.llm_api_key,
            "base_url": self._data.llm_base_url or provider_base_url(self._data.llm_provider),
        }
        self._data.provider_credentials = creds

        if self._data.llm_provider == "dashscope":
            self._data.dashscope_api_key = self._data.llm_api_key

        persist = {
            "llm_provider": self._data.llm_provider,
            "llm_api_key": self._data.llm_api_key,
            "llm_base_url": self._data.llm_base_url,
            "provider_credentials": creds,
            "dashscope_api_key": self._data.dashscope_api_key,
            "translate_model": self._data.translate_model,
            "summary_model": self._data.summary_model,
            "mindmap_model": self._data.mindmap_model,
            "whisper_model": self._data.whisper_model,
            "tts_voice": self._data.tts_voice,
            "hf_endpoint": self._data.hf_endpoint,
            "interpretation_delay": self._data.interpretation_delay,
            "startup_delay": self._data.startup_delay,
            "chunk_seconds": self._data.chunk_seconds,
            "chunk_overlap": self._data.chunk_overlap,
        }
        CONFIG_PATH.write_text(json.dumps(persist, indent=2, ensure_ascii=False))
        self._sync_env(persist)

    def _sync_env(self, persist: dict) -> None:
        provider = persist["llm_provider"]
        meta = LLM_PROVIDERS.get(provider, LLM_PROVIDERS[DEFAULT_LLM_PROVIDER])

        lines = {
            "LLM_PROVIDER": provider,
            "LLM_API_KEY": persist["llm_api_key"],
            "LLM_BASE_URL": persist["llm_base_url"],
            "TRANSLATE_MODEL": persist["translate_model"],
            "SUMMARY_MODEL": persist["summary_model"],
            "MINDMAP_MODEL": persist["mindmap_model"],
            "WHISPER_MODEL": persist["whisper_model"],
            "TTS_VOICE": persist["tts_voice"],
            "HF_ENDPOINT": persist["hf_endpoint"],
            "INTERPRETATION_DELAY": str(persist["interpretation_delay"]),
            "STARTUP_DELAY": str(persist["startup_delay"]),
            "CHUNK_SECONDS": str(persist["chunk_seconds"]),
            "CHUNK_OVERLAP": str(persist["chunk_overlap"]),
        }

        # 向后兼容 DashScope
        dash_key = persist.get("provider_credentials", {}).get("dashscope", {}).get(
            "api_key"
        ) or persist.get("dashscope_api_key", "")
        lines["DASHSCOPE_API_KEY"] = dash_key

        # 同步各厂商 API Key 到 .env
        for pid, pinfo in LLM_PROVIDERS.items():
            pk = persist.get("provider_credentials", {}).get(pid, {}).get("api_key", "")
            if pk:
                lines[pinfo["env_key"]] = pk

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
            os.environ[k] = v


settings_manager = SettingsManager()
# 向后兼容
settings = settings_manager.data
