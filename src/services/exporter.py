"""导出 AI 总结与思维导图."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.services.markdown_render import summary_export_html
from src.services.mindmap import mindmap_to_html
from src.store.transcript_store import SessionTranscript


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def export_summary(
    summary: str,
    session: SessionTranscript,
    path: Path,
    fmt: str,
) -> Path:
    path = Path(path)
    title = session.title or "视频总结"
    if fmt == "md":
        content = f"# {title}\n\n> 导出时间：{datetime.now().isoformat()}\n\n{summary}"
        path.write_text(content, encoding="utf-8")
    elif fmt == "txt":
        path.write_text(f"{title}\n{'='*40}\n\n{summary}", encoding="utf-8")
    elif fmt == "html":
        html = summary_export_html(
            summary, title, datetime.now().isoformat()
        )
        path.write_text(html, encoding="utf-8")
    elif fmt == "json":
        path.write_text(
            json.dumps(
                {
                    "title": title,
                    "url": session.url,
                    "summary": summary,
                    "exported_at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        raise ValueError(f"不支持的格式: {fmt}")
    return path


def export_mindmap(
    mermaid: str,
    session: SessionTranscript,
    path: Path,
    fmt: str,
) -> Path:
    path = Path(path)
    title = session.title or "思维导图"
    if fmt == "md":
        content = f"# {title}\n\n```mermaid\n{mermaid}\n```"
        path.write_text(content, encoding="utf-8")
    elif fmt == "html":
        path.write_text(mindmap_to_html(mermaid, title), encoding="utf-8")
    elif fmt == "json":
        path.write_text(
            json.dumps(
                {
                    "title": title,
                    "url": session.url,
                    "mermaid": mermaid,
                    "exported_at": datetime.now().isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        raise ValueError(f"不支持的格式: {fmt}")
    return path


def export_all(
    summary: str,
    mermaid: str,
    session: SessionTranscript,
    folder: Path,
) -> list[Path]:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in session.title[:30])
    base = folder / f"{safe}_{stamp}"
    files = [
        export_summary(summary, session, Path(f"{base}_summary.md"), "md"),
        export_summary(summary, session, Path(f"{base}_summary.html"), "html"),
        export_mindmap(mermaid, session, Path(f"{base}_mindmap.md"), "md"),
        export_mindmap(mermaid, session, Path(f"{base}_mindmap.html"), "html"),
    ]
    return files
