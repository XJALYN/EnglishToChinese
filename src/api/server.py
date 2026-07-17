"""FastAPI 后端 — 供 Electron 前端调用."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.config import LLM_PROVIDERS, provider_models, settings_manager
from src.tts_voices import tts_voice_catalog
from src.services.exporter import export_mindmap, export_summary
from src.services.mindmap import generate_mindmap
from src.services.summarizer import generate_summary
from src.store.transcript_store import transcript_store

app = FastAPI(title="EnglishToChinese API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SettingsUpdate(BaseModel):
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    provider_credentials: dict | None = None
    dashscope_api_key: str | None = None
    translate_model: str | None = None
    summary_model: str | None = None
    mindmap_model: str | None = None
    whisper_model: str | None = None
    tts_voice: str | None = None
    hf_endpoint: str | None = None
    interpretation_delay: float | None = None
    startup_delay: float | None = None
    chunk_seconds: float | None = None
    chunk_overlap: float | None = None


class SummaryRequest(BaseModel):
    page_url: str = ""


class MindmapRequest(BaseModel):
    summary: str = ""


@app.get("/api/settings")
def get_settings():
    cfg = settings_manager.data
    providers = {
        pid: {
            "label": meta["label"],
            "base_url": meta["base_url"],
            "models": meta["models"],
        }
        for pid, meta in LLM_PROVIDERS.items()
    }
    return {
        "llm_provider": cfg.llm_provider,
        "llm_api_key": cfg.llm_api_key[:8] + "..." if cfg.llm_api_key else "",
        "llm_base_url": cfg.active_base_url(),
        "translate_model": cfg.translate_model,
        "summary_model": cfg.summary_model,
        "mindmap_model": cfg.mindmap_model,
        "whisper_model": cfg.whisper_model,
        "tts_voice": cfg.tts_voice,
        "tts_voices": tts_voice_catalog(),
        "hf_endpoint": cfg.hf_endpoint,
        "interpretation_delay": cfg.interpretation_delay,
        "startup_delay": cfg.startup_delay,
        "chunk_seconds": cfg.chunk_seconds,
        "chunk_overlap": cfg.chunk_overlap,
        "providers": providers,
        "current_models": provider_models(cfg.llm_provider),
        # 向后兼容
        "dashscope_api_key": cfg.dashscope_api_key[:8] + "..." if cfg.dashscope_api_key else "",
        "qwen_models": provider_models("dashscope"),
    }


@app.put("/api/settings")
def update_settings(body: SettingsUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    settings_manager.save(updates)
    return {"ok": True}


@app.get("/api/transcript")
def get_transcript():
    s = transcript_store.session
    return {
        "title": s.title,
        "url": s.url,
        "segment_count": len(s.segments),
        "chinese_text": s.chinese_text,
    }


@app.post("/api/summary")
def create_summary(body: SummaryRequest):
    try:
        text = generate_summary(transcript_store.session, body.page_url)
        return {"summary": text}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/mindmap")
def create_mindmap(body: MindmapRequest):
    try:
        mermaid = generate_mindmap(transcript_store.session, body.summary)
        return {"mermaid": mermaid}
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port)
