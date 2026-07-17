"""Markdown → Corporate Clean HTML for summary preview & export."""

from __future__ import annotations

import html

import markdown

from src.ui.theme import (
    BLUE_50,
    BLUE_600,
    FONT_UI,
    GRAY_200,
    GRAY_500,
    GRAY_600,
    GRAY_700,
    GRAY_900,
    RADIUS_LG,
    SLATE_50,
    WHITE,
)

_MD = markdown.Markdown(
    extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
    output_format="html5",
)


def _summary_css() -> str:
    return f"""
    * {{ box-sizing: border-box; }}
    html, body {{
        margin: 0;
        padding: 0;
        background: {WHITE};
        color: {GRAY_900};
        font-family: {FONT_UI};
        font-size: 14px;
        line-height: 1.75;
    }}
    .summary-wrap {{
        max-width: 720px;
        margin: 0 auto;
        padding: 16px 20px 24px;
    }}
    .summary-placeholder {{
        color: {GRAY_500};
        font-size: 13px;
        text-align: center;
        padding: 48px 16px;
    }}
    h1 {{
        font-size: 1.35rem;
        font-weight: 600;
        color: {GRAY_900};
        margin: 0 0 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid {GRAY_200};
        letter-spacing: -0.02em;
    }}
    h2 {{
        font-size: 1.05rem;
        font-weight: 600;
        color: {GRAY_700};
        margin: 1.5rem 0 0.6rem;
    }}
    h3 {{
        font-size: 0.95rem;
        font-weight: 600;
        color: {GRAY_700};
        margin: 1.2rem 0 0.5rem;
    }}
    p {{ margin: 0.6rem 0; }}
    ul, ol {{
        margin: 0.5rem 0 0.75rem;
        padding-left: 1.4rem;
    }}
    li {{ margin: 0.25rem 0; }}
    li::marker {{ color: {GRAY_500}; }}
    blockquote {{
        margin: 0.75rem 0;
        padding: 10px 14px 10px 16px;
        border-left: 3px solid {BLUE_600};
        background: {SLATE_50};
        border-radius: 0 {RADIUS_LG} {RADIUS_LG} 0;
        color: {GRAY_600};
    }}
    blockquote p {{ margin: 0.25rem 0; }}
    code {{
        font-family: "SF Mono", Menlo, Monaco, monospace;
        font-size: 0.88em;
        background: {SLATE_50};
        padding: 2px 6px;
        border-radius: 4px;
        border: 1px solid {GRAY_200};
    }}
    pre {{
        background: {SLATE_50};
        border: 1px solid {GRAY_200};
        border-radius: {RADIUS_LG};
        padding: 12px 14px;
        overflow-x: auto;
        margin: 0.75rem 0;
    }}
    pre code {{
        background: none;
        border: none;
        padding: 0;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        margin: 0.75rem 0;
        font-size: 13px;
    }}
    th, td {{
        border: 1px solid {GRAY_200};
        padding: 8px 10px;
        text-align: left;
    }}
    th {{
        background: {SLATE_50};
        font-weight: 600;
        color: {GRAY_700};
    }}
    tr:nth-child(even) td {{ background: {SLATE_50}; }}
    a {{ color: {BLUE_600}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    hr {{
        border: none;
        border-top: 1px solid {GRAY_200};
        margin: 1.25rem 0;
    }}
    .streaming-cursor {{
        display: inline-block;
        width: 2px;
        height: 1em;
        background: {BLUE_600};
        margin-left: 2px;
        vertical-align: text-bottom;
        animation: blink 1s step-end infinite;
    }}
    @keyframes blink {{
        50% {{ opacity: 0; }}
    }}
    """


def markdown_to_html_body(md: str) -> str:
    """Convert Markdown fragment to HTML body (no document wrapper)."""
    if not md or not md.strip():
        return ""
    _MD.reset()
    return _MD.convert(md)


def summary_to_html(
    md: str,
    *,
    title: str = "",
    placeholder: str = "",
    streaming: bool = False,
) -> str:
    """Full HTML document for QWebEngineView / QTextBrowser / export."""
    safe_title = html.escape(title) if title else ""
    if not md or not md.strip():
        hint = html.escape(placeholder or "暂无内容")
        body = f'<p class="summary-placeholder">{hint}</p>'
    else:
        body_html = markdown_to_html_body(md)
        if streaming:
            body_html += '<span class="streaming-cursor"></span>'
        body = body_html

    title_tag = f"<title>{safe_title}</title>" if safe_title else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {title_tag}
  <style>{_summary_css()}</style>
</head>
<body>
  <div class="summary-wrap">{body}</div>
</body>
</html>"""


def summary_export_html(
    summary: str,
    title: str,
    exported_at: str,
) -> str:
    """HTML export with metadata header."""
    header = f"# {title}\n\n> 导出时间：{exported_at}\n\n"
    return summary_to_html(header + summary, title=title)
