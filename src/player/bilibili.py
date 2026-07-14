"""视频直链解析 (yt-dlp)：支持 Bilibili、YouTube 及 yt-dlp 常见站点."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

_log = logging.getLogger(__name__)

_YT_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)

_FORMAT = (
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
    "bestvideo[vcodec^=avc1]+bestaudio/"
    "best[vcodec^=avc1][height<=720]/"
    "bestvideo[height<=720]+bestaudio/"
    "best"
)


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

    for fmt in info.get("requested_formats") or []:
        if ok(fmt) and str(fmt.get("vcodec", "")).startswith(("avc", "h264")):
            return (fmt["url"], *_fmt_meta(fmt))

    for fmt in info.get("requested_formats") or []:
        if ok(fmt):
            return (fmt["url"], *_fmt_meta(fmt))

    url = info.get("url")
    if url and info.get("vcodec") not in (None, "none"):
        return (url, *_fmt_meta(info))

    formats = [f for f in (info.get("formats") or []) if ok(f)]
    avc = [
        f
        for f in formats
        if str(f.get("vcodec", "")).startswith(("avc", "h264"))
    ]
    pool = avc or formats
    if not pool:
        return None, None, None, None

    def rank(f: dict) -> tuple:
        h = f.get("height") or 0
        return (abs(h - 720), -h)

    best = sorted(pool, key=rank)[0]
    return (best["url"], *_fmt_meta(best))


def _host(page_url: str) -> str:
    try:
        return (urlparse(page_url).hostname or "").lower()
    except Exception:
        return ""


def is_youtube_url(page_url: str) -> bool:
    host = _host(page_url)
    return host in _YT_HOSTS or host.endswith(".youtube.com")


def _impersonate_target():
    """Chrome TLS 指纹，缓解部分环境访问 YouTube 时的 SSL EOF."""
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget

        return ImpersonateTarget("chrome")
    except Exception:
        return None


def _base_opts() -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": _FORMAT,
    }
    target = _impersonate_target()
    if target is not None:
        # 需安装 curl_cffi；未安装时 yt-dlp 会忽略/报错，由调用方降级
        opts["impersonate"] = target
    return opts


def _youtube_client_opts(*, impersonate: bool = True) -> dict:
    """Anaconda OpenSSL 访问默认 web 客户端偶发 SSL EOF 时，改用 android 客户端."""
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": _FORMAT,
        "extractor_args": {
            "youtube": {"player_client": ["android", "web"]},
        },
    }
    if impersonate:
        target = _impersonate_target()
        if target is not None:
            opts["impersonate"] = target
    return opts


def _is_ssl_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "ssl",
            "unexpected_eof",
            "eof occurred in violation",
            "certificate",
            "sslerror",
        )
    )


def _is_unsupported(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "unsupported url",
            "no suitable extractor",
            "is not a valid url",
        )
    )


def _friendly_error(page_url: str, exc: BaseException) -> ValueError:
    if _is_ssl_error(exc):
        hint = (
            "网络/SSL 握手失败（常见于本机 Python OpenSSL 访问 YouTube）。"
            "已尝试 Chrome impersonate 与备用播放客户端仍失败。"
            "请检查网络/代理，或执行: pip install -U yt-dlp 'curl_cffi>=0.10'"
        )
        return ValueError(f"{hint}\n原始错误: {exc}")
    if _is_unsupported(exc):
        return ValueError(
            f"无法识别该链接，请粘贴 Bilibili / YouTube 等 yt-dlp 支持的视频 URL。"
            f"\n原始错误: {exc}"
        )
    return ValueError(f"视频解析失败: {exc}")


def _extract(page_url: str, opts: dict) -> dict:
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(page_url, download=False)


def resolve_video_url(page_url: str) -> VideoInfo:
    """解析任意 yt-dlp 支持站点的可播放视频直链."""
    page_url = (page_url or "").strip()
    if not page_url:
        raise ValueError("请输入视频链接")
    if not re.match(r"^https?://", page_url, re.I):
        raise ValueError("请输入以 http:// 或 https:// 开头的视频链接")

    attempts: list[tuple[str, dict]] = [
        ("impersonate", _base_opts()),
    ]
    if is_youtube_url(page_url):
        # YouTube：保留 impersonate 换 android 客户端，再无指纹兜底
        attempts.append(("youtube+impersonate", _youtube_client_opts(impersonate=True)))
        attempts.append(("youtube", _youtube_client_opts(impersonate=False)))
    plain = _base_opts()
    plain.pop("impersonate", None)
    attempts.append(("plain", plain))

    errors: list[BaseException] = []
    info: dict | None = None
    used = ""

    for name, opts in attempts:
        try:
            info = _extract(page_url, opts)
            used = name
            break
        except Exception as exc:  # noqa: BLE001 — 需分类后转友好错误
            errors.append(exc)
            _log.warning("resolve attempt %s failed: %s", name, exc)

    if info is None:
        raise _friendly_error(page_url, errors[-1] if errors else RuntimeError("unknown"))

    stream_url, vcodec, height, format_id = _pick_video(info)
    if not stream_url:
        raise ValueError("无法解析视频直链，请检查链接是否有效或更换画质后重试")

    _log.info(
        "Video stream via %s: title=%s vcodec=%s height=%s format_id=%s url=%s…",
        used,
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


# 兼容旧调用名
resolve_bilibili_url = resolve_video_url
