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
import threading
from typing import Callable
from urllib.parse import urlparse

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

_log = logging.getLogger(__name__)

WINDOW_TITLE = "本地同声传译 · 视频画面"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_YTDL_FORMAT = (
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
    "bestvideo[height<=720]+bestaudio/"
    "best[ext=mp4][height<=720]/"
    "best[height<=720]/"
    "best"
)

# YouTube 在部分环境（Anaconda OpenSSL / 代理）下，ffmpeg 直连 googlevideo TLS 失败；
# 渐进式 18/mp4 经 yt-dlp 拉流再喂给 mpv 更可靠。
_YTDL_PIPE_FORMAT = (
    "best[ext=mp4][height<=720]/"
    "best[height<=720]/"
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio/"
    "best"
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
    # 禁止在值中嵌入 \\r\\n：python-mpv / mpv 选项解析会截断，导致 HTTP 400。
    player["referrer"] = referer
    player["user-agent"] = _UA


def _is_youtube(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    return (
        host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}
        or host.endswith(".youtube.com")
    )


class MpvPlayer(QObject):
    position_changed = pyqtSignal(float)
    duration_changed = pyqtSignal(float)
    playback_finished = pyqtSignal()
    window_opened = pyqtSignal(str)  # window title
    window_failed = pyqtSignal(str)  # reason

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
        self._ytdlp_proc: subprocess.Popen | None = None
        self._ipc_path: str | None = None
        self._mode = "none"  # embedded | external | subprocess
        self._source_mode = "none"  # cdn | ytdl-page | ytdl-pipe
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
        self._pending_page_url: str | None = None
        self._fallback_stage = 0  # 0=first try, 1=after cdn, 2=after ytdl-page, 3=done
        self._window_title = WINDOW_TITLE

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
                f"播放时弹出「{WINDOW_TITLE}」"
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

        # 保留降低后的原声作保底；TTS 播配音时会再 duck
        self._player.volume = 40
        self._player.mute = False

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

    def play(
        self,
        url: str,
        *,
        referer: str | None = None,
        page_url: str | None = None,
    ) -> None:
        self._pending_url = url
        self._pending_referer = referer
        self._pending_page_url = page_url or referer
        self._fallback_stage = 0

        is_m4s = ".m4s" in url.lower()
        self.attach()
        self._log(
            f"INFO play(): mode={self._mode} "
            f"url_kind={'m4s-h264-video' if is_m4s else 'stream'} "
            f"page={((page_url or referer) or '')[:60]} "
            f"url={url[:90]}…"
        )

        if self._mode == "subprocess" or self._subprocess is not None:
            self._start_best_effort()
            return

        _set_http_headers(self._player, referer)
        self._player.play(url)
        self._timer.start()
        self._video_check_timer.start(2500)

    def _start_best_effort(self) -> None:
        """按可靠性：CDN(修 Referer) → 页面 ytdl → yt-dlp 管道."""
        page = self._pending_page_url
        url = self._pending_url
        referer = self._pending_referer

        # YouTube：本机 ffmpeg 常无法 TLS 访问 googlevideo，直接走管道
        if page and _is_youtube(page):
            self._log("INFO YouTube：优先 yt-dlp 管道喂给 mpv（规避 ffmpeg TLS）")
            self._start_ytdlp_pipe(page)
            # 管道首帧通常 8–15s，过早校验会误报失败
            self._video_check_timer.start(14000)
            return

        # 其它站点：先直链（Bilibili .m4s 需正确 Referer，通常 1–2s 出画）
        if url:
            self._start_subprocess_cdn(url, referer)
            self._video_check_timer.start(3500)
            return

        if page:
            self._start_subprocess_ytdl_page(page)
            self._video_check_timer.start(12000)
            return

        self._log("ERROR 无可用播放 URL")
        self.window_failed.emit("无可用播放 URL")

    def _verify_video_or_fallback(self) -> None:
        """校验是否解出视频；失败则按阶段回退."""
        if self._subprocess is not None:
            alive = self._subprocess.poll() is None
            params = self._ipc_get("video-params")
            vo = self._ipc_get("current-vo")
            pos = self._ipc_get("time-pos")
            track_list = self._ipc_get("track-list")
            has_video = bool(params) and isinstance(params, dict) and bool(params.get("w"))
            vid_tracks = 0
            if isinstance(track_list, list):
                vid_tracks = sum(1 for t in track_list if t.get("type") == "video")
            self._log(
                f"INFO 子进程视频校验: has_video={has_video} vo={vo} "
                f"pos={pos} size="
                f"{(params or {}).get('w') if isinstance(params, dict) else None}x"
                f"{(params or {}).get('h') if isinstance(params, dict) else None} "
                f"alive={alive} pid={self._subprocess.pid} "
                f"source={self._source_mode} video_tracks={vid_tracks}"
            )
            if has_video:
                self._log(
                    f"INFO 系统 mpv 出画正常 — 请查看前置窗口「{WINDOW_TITLE}」"
                )
                self._focus_mpv_window()
                self.window_opened.emit(WINDOW_TITLE)
                return

            # 回退链
            page = self._pending_page_url
            if self._source_mode == "cdn" and page:
                self._log("WARN CDN 直链无画面，回退 mpv --ytdl 页面 URL…")
                self._fallback_stage = 1
                self._start_subprocess_ytdl_page(page)
                self._video_check_timer.start(14000)
                return
            if self._source_mode in ("cdn", "ytdl-page") and page:
                self._log("WARN ytdl 页面模式无画面，回退 yt-dlp | mpv 管道…")
                self._fallback_stage = 2
                self._start_ytdlp_pipe(page)
                self._video_check_timer.start(14000)
                return

            # 管道仍在拉流时再给一次机会（避免刚出画前误报）
            if self._source_mode == "ytdl-pipe" and alive and self._fallback_stage < 3:
                self._fallback_stage = 3
                self._log("INFO yt-dlp 管道仍在缓冲，5s 后复检…")
                self._video_check_timer.start(5000)
                return

            reason = (
                f"系统 mpv 仍无视频画面 (source={self._source_mode}, alive={alive})"
            )
            self._log(f"ERROR {reason}")
            self.window_failed.emit(reason)
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
            self.window_opened.emit(WINDOW_TITLE)
            return

        self._log(
            f"ERROR 无可用视频画面 (vo={vo}, params={params}, pos={pos})，"
            "回退到系统 mpv 子进程窗口"
        )
        self._fallback_to_subprocess()

    def _fallback_to_subprocess(self) -> None:
        if self._fallback_stage >= 3:
            return
        self._fallback_stage = 3
        try:
            if self._player:
                self._player.terminate()
        except Exception:
            pass
        self._player = None
        self._embedded = False
        self._start_best_effort()

    def _stop_media_procs(self, *, wait: bool = False) -> None:
        procs = [p for p in (self._subprocess, self._ytdlp_proc) if p is not None]
        self._subprocess = None
        self._ytdlp_proc = None
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        if not procs:
            return

        def _reap() -> None:
            for proc in procs:
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        if wait:
            _reap()
        else:
            threading.Thread(target=_reap, daemon=True).start()

    def _base_mpv_cmd(self, sock: str) -> list[str]:
        return [
            "mpv",
            "--force-window=yes",
            "--ontop",
            "--geometry=960x540+80+80",
            "--keep-open=yes",
            "--mute=no",
            "--volume=40",
            "--osc=yes",
            "--hwdec=auto",
            "--vo=gpu",
            f"--input-ipc-server={sock}",
            f"--title={WINDOW_TITLE}",
            f"--user-agent={_UA}",
        ]

    def _spawn_mpv(
        self,
        cmd: list[str],
        *,
        stdin=None,
        source: str,
    ) -> None:
        # CRITICAL: 切勿 stderr=PIPE 且不读 — 管道塞满会使 mpv 卡死、无画面。
        self._log(
            f"INFO 启动系统 mpv ({source}) pid即将产生; args={cmd[:10]} …"
        )
        try:
            self._subprocess = subprocess.Popen(
                cmd,
                stdin=stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._log(f"ERROR 启动系统 mpv 失败: {exc}")
            self.window_failed.emit(str(exc))
            return

        self._mode = "subprocess"
        self._embedded = False
        self._source_mode = source
        self._timer.start()
        self._log(
            f"INFO 系统 mpv 已启动 pid={self._subprocess.pid} source={source} "
            f"— 应弹出标题「{WINDOW_TITLE}」"
        )
        QTimer.singleShot(800, self._focus_mpv_window)
        QTimer.singleShot(5000, self._subprocess_clear_ontop)
        # window_opened 仅在校验 has_video 后发出，避免「窗口开了但还没画面」误报

    def _start_subprocess_cdn(self, url: str, referer: str | None) -> None:
        self._stop_media_procs()
        sock_dir = tempfile.mkdtemp(prefix="etc_mpv_")
        self._ipc_path = os.path.join(sock_dir, "mpv.sock")
        cmd = self._base_mpv_cmd(self._ipc_path)
        # 使用独立 --referrer，禁止把 Referer/UA 塞进带 \\r\\n 的 http-header-fields
        # （mpv 会截断选项 → Bilibili HTTP 400 → 黑屏/秒退）
        if referer:
            cmd.append(f"--referrer={referer}")
        cmd.append(url)
        self._spawn_mpv(cmd, source="cdn")

    def _start_subprocess_ytdl_page(self, page_url: str) -> None:
        self._stop_media_procs()
        sock_dir = tempfile.mkdtemp(prefix="etc_mpv_")
        self._ipc_path = os.path.join(sock_dir, "mpv.sock")
        cmd = self._base_mpv_cmd(self._ipc_path)
        cmd += [
            "--ytdl=yes",
            f"--ytdl-format={_YTDL_FORMAT}",
        ]
        if _is_youtube(page_url):
            cmd.append(
                "--ytdl-raw-options-append=extractor-args=youtube:player_client=android"
            )
        if self._pending_referer:
            cmd.append(f"--referrer={self._pending_referer}")
        cmd.append(page_url)
        self._spawn_mpv(cmd, source="ytdl-page")

    def _start_ytdlp_pipe(self, page_url: str) -> None:
        """yt-dlp 拉流 → stdin → mpv（YouTube TLS 问题的可靠路径）."""
        self._stop_media_procs()
        ytdlp = shutil.which("yt-dlp")
        if not ytdlp:
            self._log("ERROR 未找到 yt-dlp，无法管道播放")
            self.window_failed.emit("未找到 yt-dlp")
            return

        sock_dir = tempfile.mkdtemp(prefix="etc_mpv_")
        self._ipc_path = os.path.join(sock_dir, "mpv.sock")

        ytdlp_cmd = [
            ytdlp,
            "-o",
            "-",
            "--no-playlist",
            "-f",
            _YTDL_PIPE_FORMAT,
            "--no-warnings",
        ]
        if _is_youtube(page_url):
            ytdlp_cmd += [
                "--extractor-args",
                "youtube:player_client=android,web",
            ]
            # curl_cffi 可用时减轻 YouTube SSL EOF
            ytdlp_cmd += ["--impersonate", "chrome"]
        ytdlp_cmd.append(page_url)

        self._log(f"INFO 启动 yt-dlp 管道: {' '.join(ytdlp_cmd[:8])} …")
        try:
            self._ytdlp_proc = subprocess.Popen(
                ytdlp_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._log(f"ERROR 启动 yt-dlp 失败: {exc}")
            self.window_failed.emit(str(exc))
            return

        cmd = self._base_mpv_cmd(self._ipc_path)
        # 从管道读时 keep-open 可能导致 EOF 后空窗，仍保留 force-window
        cmd.append("--demuxer-lavf-o=probesize=5M,analyzeduration=10M")
        cmd.append("-")
        self._spawn_mpv(cmd, stdin=self._ytdlp_proc.stdout, source="ytdl-pipe")
        if self._ytdlp_proc.stdout:
            self._ytdlp_proc.stdout.close()

        # 异步监视 yt-dlp 过早退出
        threading.Thread(target=self._watch_ytdlp, daemon=True).start()

    def _watch_ytdlp(self) -> None:
        proc = self._ytdlp_proc
        if not proc:
            return
        rc = proc.wait()
        if rc not in (0, None) and self._subprocess and self._subprocess.poll() is None:
            self._log(f"WARN yt-dlp 管道退出码 {rc}（若已出画可忽略）")

    def _focus_mpv_window(self) -> None:
        if sys.platform != "darwin":
            return
        # 将 mpv 窗口前置，避免藏在主界面后面
        script = f'''
        try
          tell application "mpv" to activate
        end try
        try
          tell application "System Events"
            set mpvProcs to every process whose name is "mpv"
            repeat with p in mpvProcs
              try
                set frontmost of p to true
              end try
            end repeat
          end tell
        end try
        '''
        try:
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._log(f"INFO 已请求前置 mpv 窗口「{WINDOW_TITLE}」")
        except Exception as exc:
            self._log(f"WARN 前置 mpv 窗口失败: {exc}")

    def focus_window(self) -> None:
        """供 UI 按钮调用：再次前置视频窗口."""
        self._focus_mpv_window()
        if self._subprocess and self._subprocess.poll() is None:
            self._ipc_command(["set_property", "ontop", True])
            QTimer.singleShot(3000, self._subprocess_clear_ontop)

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

    def set_volume(self, volume: float, *, mute: bool | None = None) -> None:
        """调整原声音量。volume: 0–100；mute=None 表示不改静音状态."""
        vol = max(0.0, min(100.0, float(volume)))
        if self._subprocess:
            self._ipc_command(["set_property", "volume", vol])
            if mute is not None:
                self._ipc_command(["set_property", "mute", bool(mute)])
            return
        if self._player:
            try:
                self._player.volume = vol
                if mute is not None:
                    self._player.mute = bool(mute)
            except Exception as exc:
                self._log(f"WARN 设置音量失败: {exc}")

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
        self._stop_media_procs()
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

    @property
    def source_mode(self) -> str:
        return self._source_mode

    def _poll_position(self) -> None:
        if self._subprocess:
            if self._subprocess.poll() is not None:
                self._timer.stop()
                self._log(
                    f"WARN mpv 已退出 code={self._subprocess.returncode} "
                    f"source={self._source_mode}"
                )
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
        self._stop_media_procs(wait=True)
        if self._player:
            try:
                self._player.terminate()
            except Exception:
                pass
            self._player = None
        self._embedded = False
        self._mode = "none"
        self._source_mode = "none"
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
