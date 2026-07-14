"""AI 一键总结."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from src.config import settings_manager
from src.services.llm_client import chat_complete
from src.store.transcript_store import SessionTranscript

SUMMARY_SYSTEM = """你是专业的视频内容分析师。根据提供的视频字幕/转录文本，生成结构清晰的中文总结。

输出格式要求（Markdown）：
# 视频总结

## 核心主题
（1-2 句话）

## 关键要点
- 要点1
- 要点2
...

## 精彩引用
> 引用原文及其中文含义

## 总结
（2-3 句话收尾）

只输出 Markdown，不要额外解释。"""


def fetch_bilibili_subtitles(page_url: str) -> str:
    """尝试从 B 站拉取已有字幕作为补充."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "sub"
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang",
            "en.*,zh.*",
            "--skip-download",
            "-o",
            str(out),
            page_url,
        ]
        subprocess.run(cmd, capture_output=True, text=True)
        texts: list[str] = []
        for f in sorted(Path(td).glob("*")):
            if f.suffix in {".vtt", ".srt", ".ass"}:
                texts.append(f.read_text(errors="ignore"))
        return "\n".join(texts)


def build_source_text(session: SessionTranscript, page_url: str = "") -> str:
    parts = [f"视频标题：{session.title}"]
    if session.chinese_text:
        parts.append("\n## 同声传译累积字幕（中文）\n" + session.chinese_text)
    if session.english_text:
        parts.append("\n## 同声传译累积字幕（英文）\n" + session.english_text)
    if page_url:
        try:
            subs = fetch_bilibili_subtitles(page_url)
            if subs.strip():
                parts.append("\n## B站原始字幕\n" + subs[:12000])
        except Exception:
            pass
    text = "\n".join(parts)
    if len(text.strip()) < 50:
        raise ValueError("暂无足够字幕内容，请先播放视频积累转录，或确认视频有字幕")
    return text[:20000]


def generate_summary(
    session: SessionTranscript,
    page_url: str = "",
    *,
    on_token=None,
) -> str:
    cfg = settings_manager.data
    source = build_source_text(session, page_url)
    user = f"请总结以下视频内容：\n\n{source}"
    return chat_complete(
        cfg.summary_model,
        SUMMARY_SYSTEM,
        user,
        stream=on_token is not None,
        on_token=on_token,
    )
