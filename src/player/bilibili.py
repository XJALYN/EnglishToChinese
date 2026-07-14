"""B站视频直链解析 (yt-dlp)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

_log = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    title: str
    url: str
    duration: float | None
    webpage_url: str
    vcodec: str | None = None
    height: int | None = None
    format_id: str | None = None


def _fmt_meta(fmt: dict) -> tuple[str | None, int | None, str | None]:
    return (
        fmt.get("vcodec"),
        fmt.get("height"),
        str(fmt.get("format_id")) if fmt.get("format_id") is not None else None,
    )


def _pick_video(info: dict) -> tuple[str | None, str | None, int | None, str | None]:
    """提取可播放的视频直链 (非 audio-only)，优先返回 H.264."""

    def ok(fmt: dict) -> bool:
        return bool(fmt.get("url")) and fmt.get("vcodec") not in (None, "none")

    # Prefer already-selected download formats from yt-dlp
    for fmt in info.get("requested_formats") or []:
        if ok(fmt) and str(fmt.get("vcodec", "")).startswith(("avc", "h264")):
            return (fmt["url"], *_fmt_meta(fmt))

    for fmt in info.get("requested_formats") or []:
        if ok(fmt):
            return (fmt["url"], *_fmt_meta(fmt))

    url = info.get("url")
    if url and info.get("vcodec") not in (None, "none"):
        return (url, *_fmt_meta(info))

    # Prefer avc1 / H.264 among remaining formats (macOS embed-friendly)
    formats = [f for f in (info.get("formats") or []) if ok(f)]
    avc = [
        f
        for f in formats
        if str(f.get("vcodec", "")).startswith(("avc", "h264"))
    ]
    pool = avc or formats
    if not pool:
        return None, None, None, None

    # Prefer <=720p for smoother local decode alongside ASR
    def rank(f: dict) -> tuple:
        h = f.get("height") or 0
        return (abs(h - 720), -h)

    best = sorted(pool, key=rank)[0]
    return (best["url"], *_fmt_meta(best))


def resolve_bilibili_url(page_url: str) -> VideoInfo:
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        # Prefer H.264 single/mux-friendly stream; avoid AV1 black-screen cases
        "format": (
            "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
            "bestvideo[vcodec^=avc1]+bestaudio/"
            "best[vcodec^=avc1][height<=720]/"
            "bestvideo[height<=720]+bestaudio/"
            "best"
        ),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(page_url, download=False)

    stream_url, vcodec, height, format_id = _pick_video(info)
    if not stream_url:
        raise ValueError("无法解析 B 站视频直链，请检查链接是否有效")

    _log.info(
        "Bilibili stream: title=%s vcodec=%s height=%s format_id=%s url=%s…",
        info.get("title"),
        vcodec,
        height,
        format_id,
        stream_url[:80],
    )

    return VideoInfo(
        title=info.get("title") or "未知标题",
        url=stream_url,
        duration=info.get("duration"),
        webpage_url=info.get("webpage_url") or page_url,
        vcodec=vcodec,
        height=height,
        format_id=format_id,
    )
