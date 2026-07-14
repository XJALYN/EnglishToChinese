"""AI 思维导图生成 (Mermaid mindmap)."""

from __future__ import annotations

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


def mindmap_to_html(mermaid_code: str, title: str = "思维导图") -> str:
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    body {{ font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; padding: 24px; }}
    h1 {{ text-align: center; font-size: 1.4rem; margin-bottom: 24px; }}
    .mermaid {{ display: flex; justify-content: center; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <pre class="mermaid">
{mermaid_code}
  </pre>
  <script>mermaid.initialize({{ startOnLoad: true, theme: 'dark' }})</script>
</body>
</html>"""
