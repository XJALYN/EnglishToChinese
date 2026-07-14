"""FastAPI 后端 — 供 Electron 前端调用."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.config import settings_manager
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
    dashscope_api_key: str | None = None
    translate_model: str | None = None
    summary_model: str | None = None
    mindmap_model: str | None = None
    whisper_model: str | None = None
    tts_voice: str | None = None
    hf_endpoint: str | None = None


class SummaryRequest(BaseModel):
    page_url: str = ""


class MindmapRequest(BaseModel):
    summary: str = ""


@app.get("/api/settings")
def get_settings():
    cfg = settings_manager.data
    return {
        "dashscope_api_key": cfg.dashscope_api_key[:8] + "..." if cfg.dashscope_api_key else "",
        "translate_model": cfg.translate_model,
        "summary_model": cfg.summary_model,
        "mindmap_model": cfg.mindmap_model,
        "whisper_model": cfg.whisper_model,
        "tts_voice": cfg.tts_voice,
        "hf_endpoint": cfg.hf_endpoint,
        "qwen_models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-long"],
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
