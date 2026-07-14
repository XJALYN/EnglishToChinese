"""mpv 视频播放器 — macOS 默认独立窗口出画，失败则回退系统 mpv 子进程."""

from __future__ import annotations

import ctypes.util
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
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
        self._subprocess: subprocess.Popen | None = None
        self._ipc_path: str | None = None
        self._mode = "none"  # embedded | external | subprocess
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_position)
        self._video_check_timer = QTimer(self)
        self._video_check_timer.setSingleShot(True)
        self._video_check_timer.timeout.connect(self._verify_video_or_fallback)
        self._ontop_clear_timer = QTimer(self)
        self._ontop_clear_timer.setSingleShot(True)
        self._ontop_clear_timer.timeout.connect(self._clear_ontop)
        self._pending_url: str | None = None
        self._pending_referer: str | None = None
        self._fallback_done = False

    def _log(self, msg: str) -> None:
        _log.info(msg)
        if self._on_log:
            self._on_log(msg)

    @staticmethod
    def is_available() -> bool:
        """系统有 mpv 即可（macOS 默认走子进程，不强制 python-mpv/libmpv）."""
        return shutil.which("mpv") is not None

    @staticmethod
    def python_mpv_available() -> bool:
        if shutil.which("mpv") is None:
            return False
        try:
            _ensure_libmpv()
            import mpv  # noqa: F401
        except OSError:
            return False
        return True

    def attach(self, *, force_external: bool = False) -> None:
        if self._player is not None or self._subprocess is not None:
            return
        if shutil.which("mpv") is None:
            raise RuntimeError("未找到 mpv，请运行: brew install mpv")

        # macOS: python-mpv + vo=libmpv/独立窗口会 fatal「No render context set」，
        # 嵌入也常黑屏。默认直接用系统 mpv 子进程（已验证有画面），经 IPC 同步进度。
        # ETC_MPV_EMBED=1 → 尝试 Qt 嵌入；ETC_MPV_PYTHON=1 → 尝试 python-mpv 独立窗口。
        use_subprocess = (
            force_external
            or self._widget is None
            or (
                sys.platform == "darwin"
                and os.environ.get("ETC_MPV_EMBED", "").strip() != "1"
                and os.environ.get("ETC_MPV_PYTHON", "").strip() != "1"
            )
        )
        if use_subprocess:
            reason = (
                "force"
                if force_external
                else ("无容器" if self._widget is None else "macOS 默认系统 mpv 窗口")
            )
            self._log(
                f"INFO 将使用系统 mpv 独立窗口（{reason}）；"
                "播放时弹出「本地同声传译 · 视频画面」"
            )
            self._embedded = False
            self._mode = "subprocess"
            return

        if not self.is_available():
            raise RuntimeError("未找到 mpv / libmpv，请运行: brew install mpv")

        _ensure_libmpv()
        import mpv

        kwargs = _mpv_common_kwargs()

        def _mpv_log_handler(level: str, prefix: str, text: str) -> None:
            msg = text.strip()
            if not msg:
                return
            low = msg.lower()
            if level in ("fatal", "error") or "no video" in low or "no render" in low:
                self._log(f"ERROR mpv[{level}/{prefix}]: {msg}")
            elif "vo:" in low or "video" in low:
                self._log(f"INFO mpv[{prefix}]: {msg}")

        prefer_embed = (
            self._widget is not None
            and os.environ.get("ETC_MPV_EMBED", "").strip() == "1"
        )

        if prefer_embed:
            try:
                wid = _prepare_embed_widget(self._widget)
                self._log(f"INFO 尝试嵌入 mpv: vo=libmpv, wid={wid}")
                self._player = mpv.MPV(
                    wid=str(wid) if sys.platform == "darwin" else wid,
                    vo="libmpv",
                    log_handler=_mpv_log_handler,
                    loglevel="warn",
                    **kwargs,
                )
                self._embedded = True
                self._mode = "embedded"
                self._log("INFO mpv 嵌入成功，等待首帧校验…")
            except Exception as exc:
                self._log(f"WARN 视频嵌入失败，回退 python-mpv 独立窗口: {exc}")
                prefer_embed = False

        if not prefer_embed:
            # CRITICAL: 独立窗口禁止 vo=libmpv（无 render context → 无画面）
            self._log(
                "INFO 使用 python-mpv 独立窗口; vo=gpu force-window=yes ontop=yes"
            )
            self._player = mpv.MPV(
                vo="gpu",
                force_window="yes",
                ontop="yes",
                geometry="960x540+80+80",
                log_handler=_mpv_log_handler,
                loglevel="warn",
                **kwargs,
            )
            self._embedded = False
            self._mode = "external"
            self._ontop_clear_timer.start(4000)

        self._player.volume = 0
        self._player.mute = True

        @self._player.property_observer("video-params")
        def _on_video_params(_name, value):
            if value:
                self._log(
                    f"INFO 视频参数就绪: "
                    f"{value.get('w')}x{value.get('h')} "
                    f"pixelformat={value.get('pixelformat')} "
                    f"mode={self._mode}"
                )

    def _clear_ontop(self) -> None:
        if self._player and self._mode == "external":
            try:
                self._player.ontop = False
            except Exception:
                pass

    def play(self, url: str, *, referer: str | None = None) -> None:
        self._pending_url = url
        self._pending_referer = referer
        self._fallback_done = False

        is_m4s = ".m4s" in url.lower()
        self.attach()
        self._log(
            f"INFO play(): mode={self._mode} "
            f"url_kind={'m4s-h264-video' if is_m4s else 'stream'} "
            f"url={url[:90]}…"
        )

        if self._mode == "subprocess" or self._subprocess is not None:
            self._start_subprocess(url, referer)
            # 校验子进程窗口是否解出视频
            self._video_check_timer.start(3000)
            return

        _set_http_headers(self._player, referer)
        self._player.play(url)
        self._timer.start()
        # 独立窗口与嵌入都要校验是否真的解出视频轨
        self._video_check_timer.start(2500)

    def _verify_video_or_fallback(self) -> None:
        """校验是否解出视频；python-mpv 失败则回退系统 mpv 子进程."""
        if self._fallback_done:
            return

        if self._subprocess is not None:
            params = self._ipc_get("video-params")
            vo = self._ipc_get("current-vo")
            pos = self._ipc_get("time-pos")
            has_video = bool(params) and bool(params.get("w"))
            self._log(
                f"INFO 子进程视频校验: has_video={has_video} vo={vo} "
                f"pos={pos} size="
                f"{(params or {}).get('w')}x{(params or {}).get('h')}"
            )
            if not has_video:
                self._log(
                    "ERROR 系统 mpv 仍无视频画面 — 请检查直链/Referer；"
                    "CLI 可试: mpv --referrer=… <url>"
                )
            else:
                self._log(
                    "INFO 系统 mpv 出画正常 — 请查看前置窗口"
                    "「本地同声传译 · 视频画面」"
                )
            return

        params = None
        vo = None
        pos = None
        video_codec = None
        try:
            if self._player:
                params = self._player.video_params
                vo = self._player.current_vo
                pos = self._player.time_pos
                video_codec = getattr(self._player, "video_codec", None)
        except Exception as exc:
            self._log(f"WARN 视频校验读取属性失败: {exc}")

        has_video = bool(params) and bool(params.get("w"))
        self._log(
            f"INFO 视频校验: has_video={has_video} vo={vo} "
            f"codec={video_codec} pos={pos} params={params} mode={self._mode}"
        )

        if has_video and vo:
            self._log(
                f"INFO 出画正常 ({self._mode}): vo={vo}, "
                f"size={params.get('w')}x{params.get('h')}"
            )
            return

        self._log(
            f"ERROR 无可用视频画面 (vo={vo}, params={params}, pos={pos})，"
            "回退到系统 mpv 子进程窗口"
        )
        self._fallback_to_subprocess()

    def _fallback_to_subprocess(self) -> None:
        if self._fallback_done:
            return
        self._fallback_done = True
        url = self._pending_url
        referer = self._pending_referer
        if not url:
            self._log("ERROR 无法回退：没有 pending URL")
            return

        try:
            if self._player:
                self._player.terminate()
        except Exception:
            pass
        self._player = None
        self._embedded = False
        self._start_subprocess(url, referer)

    def _start_subprocess(self, url: str, referer: str | None) -> None:
        if self._subprocess is not None:
            try:
                self._subprocess.terminate()
            except Exception:
                pass
            self._subprocess = None

        sock_dir = tempfile.mkdtemp(prefix="etc_mpv_")
        self._ipc_path = os.path.join(sock_dir, "mpv.sock")
        header = f"Referer: {referer or ''}\r\nUser-Agent: {_UA}"
        cmd = [
            "mpv",
            "--force-window=yes",
            "--ontop",
            "--geometry=960x540+80+80",
            "--keep-open=yes",
            "--mute=yes",
            "--volume=0",
            "--osc=yes",
            "--hwdec=auto",
            "--vo=gpu",
            f"--input-ipc-server={self._ipc_path}",
            f"--http-header-fields={header}",
            "--title=本地同声传译 · 视频画面",
            url,
        ]
        self._log(f"INFO 启动系统 mpv 子进程: {' '.join(cmd[:8])} …")
        try:
            self._subprocess = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except Exception as exc:
            self._log(f"ERROR 启动系统 mpv 失败: {exc}")
            return

        self._mode = "subprocess"
        self._embedded = False
        self._timer.start()
        self._log(
            "INFO 系统 mpv 已启动 — 应弹出标题为「本地同声传译 · 视频画面」的窗口"
        )
        # briefly keep ontop then release
        QTimer.singleShot(5000, self._subprocess_clear_ontop)

    def _subprocess_clear_ontop(self) -> None:
        self._ipc_command(["set_property", "ontop", False])

    def _ipc_command(self, args: list) -> dict | None:
        if not self._ipc_path or not os.path.exists(self._ipc_path):
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.4)
                sock.connect(self._ipc_path)
                payload = (json.dumps({"command": args}) + "\n").encode("utf-8")
                sock.sendall(payload)
                data = b""
                while b"\n" not in data:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                if not data:
                    return None
                return json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
        except Exception:
            return None

    def _ipc_get(self, prop: str):
        resp = self._ipc_command(["get_property", prop])
        if resp and resp.get("error") == "success":
            return resp.get("data")
        return None

    def pause(self, paused: bool) -> None:
        if self._subprocess:
            self._ipc_command(["set_property", "pause", paused])
            return
        if self._player:
            self._player.pause = paused

    def seek(self, seconds: float) -> None:
        if self._subprocess:
            self._ipc_command(["seek", seconds, "absolute"])
            return
        if self._player:
            self._player.seek(seconds, "absolute")

    def stop(self) -> None:
        self._timer.stop()
        self._video_check_timer.stop()
        self._ontop_clear_timer.stop()
        if self._subprocess:
            try:
                self._subprocess.terminate()
            except Exception:
                pass
            self._subprocess = None
        if self._player:
            self._player.stop()

    def get_position(self) -> float:
        if self._subprocess:
            pos = self._ipc_get("time-pos")
            return float(pos) if pos is not None else 0.0
        if self._player and self._player.time_pos is not None:
            return float(self._player.time_pos)
        return 0.0

    @property
    def is_embedded(self) -> bool:
        return self._embedded

    @property
    def playback_mode(self) -> str:
        return self._mode

    def _poll_position(self) -> None:
        if self._subprocess:
            if self._subprocess.poll() is not None:
                self._timer.stop()
                self.playback_finished.emit()
                return
            pos = self._ipc_get("time-pos")
            dur = self._ipc_get("duration")
            if pos is not None:
                self.position_changed.emit(float(pos))
            if dur is not None:
                self.duration_changed.emit(float(dur))
            eof = self._ipc_get("eof-reached")
            if eof:
                self._timer.stop()
                self.playback_finished.emit()
            return

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
        self._video_check_timer.stop()
        self._ontop_clear_timer.stop()
        if self._subprocess:
            try:
                self._subprocess.terminate()
                self._subprocess.wait(timeout=2)
            except Exception:
                try:
                    self._subprocess.kill()
                except Exception:
                    pass
            self._subprocess = None
        if self._player:
            try:
                self._player.terminate()
            except Exception:
                pass
            self._player = None
        self._embedded = False
        self._mode = "none"
        if self._ipc_path:
            try:
                os.unlink(self._ipc_path)
            except OSError:
                pass
            parent = os.path.dirname(self._ipc_path)
            try:
                os.rmdir(parent)
            except OSError:
                pass
            self._ipc_path = None
