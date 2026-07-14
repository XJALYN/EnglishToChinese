"""mpv 视频播放器 — macOS 优先嵌入，失败则独立窗口回退."""

from __future__ import annotations

import ctypes.util
import logging
import os
import shutil
import sys
from typing import Callable

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

_log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _ensure_libmpv() -> None:
    """Homebrew libmpv on macOS is invisible to ctypes.util.find_library."""
    if getattr(_ensure_libmpv, "_patched", False):
        return

    _orig = ctypes.util.find_library

    def _find_library(name: str):
        if name == "mpv":
            for path in (
                "/opt/homebrew/lib/libmpv.dylib",
                "/usr/local/lib/libmpv.dylib",
            ):
                if os.path.isfile(path):
                    return path
        return _orig(name)

    ctypes.util.find_library = _find_library
    _ensure_libmpv._patched = True  # type: ignore[attr-defined]


def _prepare_embed_widget(widget: QWidget) -> int:
    """Ensure the Qt widget has a valid native window id for mpv wid.

    Critical on macOS: the widget MUST have no child QWidgets — they steal
    the NSView / paint over libmpv and cause a permanent black screen.
    """
    from PyQt6.QtCore import Qt

    children = [c for c in widget.findChildren(QWidget) if c.parent() is widget]
    if children:
        names = ", ".join(type(c).__name__ for c in children)
        raise RuntimeError(
            f"视频容器含有子控件 ({names})，会遮挡 mpv 画面，请勿在 embed 容器上挂载字幕"
        )

    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors, True)
    widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    widget.setAutoFillBackground(False)
    widget.show()
    app = QApplication.instance()
    if app:
        app.processEvents()
    wid = int(widget.winId())
    if wid == 0:
        raise RuntimeError("视频容器 winId 无效，无法嵌入 mpv")
    return wid


def _mpv_common_kwargs() -> dict:
    return dict(
        hwdec="auto",
        keep_open="yes",
        idle="yes",
        input_default_bindings=True,
        input_vo_keyboard=True,
        osc=True,
        cache="yes",
        cache_secs=60,
        demuxer_readahead_secs=20,
        demuxer_max_bytes=150 * 1024 * 1024,
        demuxer_max_back_bytes=75 * 1024 * 1024,
        vd_lavc_threads=4,
    )


def _set_http_headers(player, referer: str | None) -> None:
    if not referer:
        return
    player["http-header-fields"] = f"Referer: {referer}\r\nUser-Agent: {_UA}\r\n"


class MpvPlayer(QObject):
    position_changed = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    playback_finished = pyqtSignal()

    def __init__(
        self,
        parent_widget,
        *,
        on_log: Callable[[str], None] | None = None,
    ):
        super().__init__()
        self._widget = parent_widget
        self._on_log = on_log
        self._player = None
        self._embedded = False
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_position)
        self._embed_check_timer = QTimer(self)
        self._embed_check_timer.setSingleShot(True)
        self._embed_check_timer.timeout.connect(self._verify_embed_or_fallback)
        self._pending_url: str | None = None
        self._pending_referer: str | None = None

    def _log(self, msg: str) -> None:
        _log.info(msg)
        if self._on_log:
            self._on_log(msg)

    @staticmethod
    def is_available() -> bool:
        if shutil.which("mpv") is None:
            return False
        try:
            _ensure_libmpv()
            import mpv  # noqa: F401
        except OSError:
            return False
        return True

    def attach(self, *, force_external: bool = False) -> None:
        if self._player is not None:
            return
        if not self.is_available():
            raise RuntimeError("未找到 mpv / libmpv，请运行: brew install mpv")

        _ensure_libmpv()
        import mpv

        kwargs = _mpv_common_kwargs()
        vo = "libmpv" if sys.platform == "darwin" else "gpu"

        # PyQt6 + wid 嵌入在 macOS 上常出现「能解码但画面全黑」。
        # 默认走独立窗口保证有画面；需要嵌入时设置环境变量 ETC_MPV_EMBED=1。
        prefer_external = (
            force_external
            or self._widget is None
            or (
                sys.platform == "darwin"
                and os.environ.get("ETC_MPV_EMBED", "").strip() != "1"
            )
        )

        if prefer_external:
            reason = "force" if force_external else (
                "无容器" if self._widget is None else "macOS 默认独立窗口"
            )
            self._log(f"INFO 使用独立 mpv 窗口播放（{reason}）")
            self._player = mpv.MPV(vo=vo, force_window="yes", **kwargs)
            self._embedded = False
        else:
            try:
                wid = _prepare_embed_widget(self._widget)
                self._log(f"INFO 尝试嵌入 mpv: vo={vo}, wid={wid}")
                self._player = mpv.MPV(
                    wid=str(wid) if sys.platform == "darwin" else wid,
                    vo=vo,
                    **kwargs,
                )
                self._embedded = True
                self._log("INFO mpv 嵌入成功，等待首帧校验…")
            except Exception as exc:
                self._log(f"WARN 视频嵌入失败，回退独立窗口: {exc}")
                self._player = mpv.MPV(vo=vo, force_window="yes", **kwargs)
                self._embedded = False

        self._player.volume = 0
        self._player.mute = True

        @self._player.property_observer("video-params")
        def _on_video_params(_name, value):
            if value:
                self._log(
                    f"INFO 视频参数就绪: "
                    f"{value.get('w')}x{value.get('h')} "
                    f"pixelformat={value.get('pixelformat')} "
                    f"embedded={self._embedded}"
                )

    def play(self, url: str, *, referer: str | None = None) -> None:
        self.attach()
        self._pending_url = url
        self._pending_referer = referer
        _set_http_headers(self._player, referer)
        self._player.play(url)
        self._timer.start()
        if self._embedded and sys.platform == "darwin":
            # Cocoa wid embed often stays black even while decoding; verify & fallback
            self._embed_check_timer.start(2500)

    def _verify_embed_or_fallback(self) -> None:
        """macOS: if embed has no usable video-params/VO, reopen as separate window."""
        if not self._player or not self._embedded:
            return
        try:
            params = self._player.video_params
            vo = self._player.current_vo
            pos = self._player.time_pos
        except Exception as exc:
            self._log(f"WARN 嵌入校验读取属性失败: {exc}")
            params, vo, pos = None, None, None

        has_video = bool(params) and bool(params.get("w"))
        # Heuristic: progressing time_pos + video-params usually means decode OK.
        # On many PyQt6+Cocoa setups current-vo is set but the Qt surface stays black.
        # Always prefer an independent window when embed is suspected black:
        # if we have video params AND time advances, still reopen external on darwin
        # ONLY when current_vo is missing. If vo exists, keep embed (overlay fix may
        # have solved black screen).
        if has_video and vo:
            self._log(
                f"INFO 嵌入校验通过: vo={vo}, pos={pos}, "
                f"size={params.get('w')}x{params.get('h')}"
            )
            return

        self._log(
            f"ERROR 视频嵌入画面不可用 (vo={vo}, params={params}, pos={pos})，"
            "切换到独立 mpv 窗口"
        )
        url = self._pending_url
        referer = self._pending_referer
        try:
            self._player.terminate()
        except Exception:
            pass
        self._player = None
        self.attach(force_external=True)
        if url:
            _set_http_headers(self._player, referer)
            self._player.play(url)
            self._timer.start()
            self._log("INFO 已在独立窗口重新开始播放 — 请查看弹出的 mpv 窗口")

    def pause(self, paused: bool) -> None:
        if self._player:
            self._player.pause = paused

    def seek(self, seconds: float) -> None:
        if self._player:
            self._player.seek(seconds, "absolute")

    def stop(self) -> None:
        self._timer.stop()
        self._embed_check_timer.stop()
        if self._player:
            self._player.stop()

    def get_position(self) -> float:
        if self._player and self._player.time_pos is not None:
            return float(self._player.time_pos)
        return 0.0

    @property
    def is_embedded(self) -> bool:
        return self._embedded

    def _poll_position(self) -> None:
        if not self._player:
            return
        pos = self._player.time_pos
        dur = self._player.duration
        if pos is not None:
            self.position_changed.emit(float(pos))
        if dur is not None:
            self.duration_changed.emit(float(dur))
        if self._player.eof_reached:
            self._timer.stop()
            self.playback_finished.emit()

    def destroy(self) -> None:
        self._timer.stop()
        self._embed_check_timer.stop()
        if self._player:
            try:
                self._player.terminate()
            except Exception:
                pass
            self._player = None
        self._embedded = False
