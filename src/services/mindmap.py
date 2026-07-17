"""AI 思维导图生成 (Mermaid mindmap)."""

from __future__ import annotations

import html as html_lib
import re

from src.config import settings_manager
from src.services.llm_client import chat_complete
from src.store.transcript_store import SessionTranscript

MINDMAP_SYSTEM = """你是思维导图专家。根据视频内容生成 Mermaid mindmap 语法。

严格要求：
1. 只输出一个 ```mermaid 代码块
2. 使用 mindmap 语法，根节点为视频主题
3. 2-4 层分支，每层 3-6 个节点
4. 节点文字简洁（不超过 15 字）
5. 使用中文

示例：
```mermaid
mindmap
  root((核心主题))
    分支一
      细节A
      细节B
    分支二
      细节C
```"""


def extract_mermaid(text: str) -> str:
    match = re.search(r"```(?:mermaid)?\s*(mindmap[\s\S]*?)```", text, re.I)
    if match:
        return match.group(1).strip()
    if text.strip().startswith("mindmap"):
        return text.strip()
    return text.strip()


def generate_mindmap(
    session: SessionTranscript,
    summary: str = "",
    *,
    on_token=None,
) -> str:
    cfg = settings_manager.data
    content = session.chinese_text or session.english_text
    if summary:
        content = f"AI总结：\n{summary}\n\n字幕：\n{content}"
    if len(content.strip()) < 30:
        raise ValueError("内容不足，请先播放视频或生成 AI 总结")

    user = f"视频标题：{session.title}\n\n内容：\n{content[:15000]}"
    raw = chat_complete(
        cfg.mindmap_model,
        MINDMAP_SYSTEM,
        user,
        stream=on_token is not None,
        on_token=on_token,
    )
    return extract_mermaid(raw)


def mindmap_to_html(
    mermaid_code: str,
    title: str = "思维导图",
    *,
    preview: bool = False,
) -> str:
    safe_title = html_lib.escape(title)
    # Mermaid 在 <pre> 内解析源码；转义避免破坏 HTML 结构
    safe_code = (
        mermaid_code.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    body_class = "preview" if preview else "panel"
    hide_page_chrome = "true" if preview else "false"
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>{safe_title}</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    html, body {{
      height: 100%;
    }}
    body {{
      font-family: "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      margin: 0;
      padding: 0;
      overflow: hidden;
    }}
    body.panel {{
      padding: 12px 16px 16px;
    }}
    body.preview {{
      padding: 0;
    }}
    h1 {{
      text-align: center;
      font-size: 1.1rem;
      font-weight: 600;
      margin: 0 0 10px;
      color: #f8fafc;
    }}
    body.preview h1,
    body.preview .zoom-toolbar {{
      display: none;
    }}
    .zoom-toolbar {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }}
    .zoom-toolbar button {{
      min-width: 36px;
      padding: 6px 12px;
      border: 1px solid #475569;
      border-radius: 8px;
      background: #1e293b;
      color: #e2e8f0;
      cursor: pointer;
      font-size: 0.9rem;
    }}
    .zoom-toolbar button:hover {{ background: #334155; }}
    #zoom-pct {{
      min-width: 48px;
      text-align: center;
      font-size: 0.85rem;
      color: #94a3b8;
    }}
    #mindmap-wrap {{
      overflow: auto;
      background: #1e293b;
      border-radius: 12px;
      cursor: grab;
      box-sizing: border-box;
    }}
    body.panel #mindmap-wrap {{
      max-height: calc(100vh - 100px);
      min-height: 280px;
      padding: 16px;
    }}
    body.preview #mindmap-wrap {{
      height: 100vh;
      max-height: none;
      border-radius: 0;
      padding: 24px 32px 40px;
    }}
    #mindmap-wrap.is-panning {{ cursor: grabbing; }}
    #mindmap-scale {{
      transform-origin: center top;
      transition: transform 0.12s ease-out;
      display: flex;
      justify-content: center;
      min-width: max-content;
      min-height: max-content;
    }}
    .mermaid {{ display: flex; justify-content: center; margin: 0; }}
  </style>
</head>
<body class="{body_class}">
  <h1>{safe_title}</h1>
  <div class="zoom-toolbar">
    <button type="button" id="zoom-out" title="缩小">−</button>
    <span id="zoom-pct">100%</span>
    <button type="button" id="zoom-in" title="放大">+</button>
    <button type="button" id="zoom-reset" title="重置缩放">重置</button>
  </div>
  <div id="mindmap-wrap">
    <div id="mindmap-scale">
      <pre class="mermaid">
{safe_code}
      </pre>
    </div>
  </div>
  <script>
    mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});
    let mindmapScale = 1;
    const MIN_SCALE = 0.25;
    const MAX_SCALE = 3;
    const scaleEl = document.getElementById('mindmap-scale');
    const wrapEl = document.getElementById('mindmap-wrap');
    const pctEl = document.getElementById('zoom-pct');
    const hidePageChrome = {hide_page_chrome};

    function applyMindmapZoom() {{
      scaleEl.style.transform = 'scale(' + mindmapScale + ')';
      if (pctEl) pctEl.textContent = Math.round(mindmapScale * 100) + '%';
    }}
    function mindmapZoomBy(delta) {{
      mindmapScale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, mindmapScale + delta));
      applyMindmapZoom();
    }}
    function mindmapZoomIn() {{ mindmapZoomBy(0.15); }}
    function mindmapZoomOut() {{ mindmapZoomBy(-0.15); }}
    function mindmapZoomReset() {{
      mindmapScale = 1;
      applyMindmapZoom();
    }}
    window.mindmapZoomIn = mindmapZoomIn;
    window.mindmapZoomOut = mindmapZoomOut;
    window.mindmapZoomReset = mindmapZoomReset;

    if (!hidePageChrome) {{
      document.getElementById('zoom-in').addEventListener('click', mindmapZoomIn);
      document.getElementById('zoom-out').addEventListener('click', mindmapZoomOut);
      document.getElementById('zoom-reset').addEventListener('click', mindmapZoomReset);
    }}

    wrapEl.addEventListener('wheel', (e) => {{
      if (e.ctrlKey || e.metaKey) {{
        e.preventDefault();
        mindmapZoomBy(e.deltaY < 0 ? 0.1 : -0.1);
      }}
    }}, {{ passive: false }});

    let panning = false;
    let panStartX = 0;
    let panStartY = 0;
    let scrollLeft0 = 0;
    let scrollTop0 = 0;
    wrapEl.addEventListener('pointerdown', (e) => {{
      if (e.button !== 0) return;
      panning = true;
      panStartX = e.clientX;
      panStartY = e.clientY;
      scrollLeft0 = wrapEl.scrollLeft;
      scrollTop0 = wrapEl.scrollTop;
      wrapEl.classList.add('is-panning');
      wrapEl.setPointerCapture(e.pointerId);
    }});
    wrapEl.addEventListener('pointermove', (e) => {{
      if (!panning) return;
      wrapEl.scrollLeft = scrollLeft0 - (e.clientX - panStartX);
      wrapEl.scrollTop = scrollTop0 - (e.clientY - panStartY);
    }});
    function endPan(e) {{
      if (!panning) return;
      panning = false;
      wrapEl.classList.remove('is-panning');
      try {{ wrapEl.releasePointerCapture(e.pointerId); }} catch (_) {{}}
    }}
    wrapEl.addEventListener('pointerup', endPan);
    wrapEl.addEventListener('pointercancel', endPan);
  </script>
</body>
</html>"""
