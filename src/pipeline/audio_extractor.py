"""从视频流实时提取 PCM 音频 chunk (yt-dlp → ffmpeg)."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from typing import Callable

import numpy as np

from src.config import settings_manager
from src.utils.cpu_throttle import subprocess_low_priority

_POPEN_KWARGS: dict = {}
if sys.platform != "win32":
    _POPEN_KWARGS["preexec_fn"] = subprocess_low_priority


class AudioExtractor:
    """用 yt-dlp 拉取 B 站音频并解码为 int16 PCM；失败时回退 ffmpeg + Referer."""

    def __init__(
        self,
        page_url: str,
        on_chunk: Callable[[np.ndarray, float], None],
        *,
        on_log: Callable[[str], None] | None = None,
        start_offset: float = 0.0,
        stream_url: str | None = None,
        referer: str | None = None,
        startup_delay: float = 4.0,
    ):
        self.page_url = page_url
        self.on_chunk = on_chunk
        self.on_log = on_log
        self.start_offset = start_offset
        self.stream_url = stream_url
        self.referer = referer or page_url
        self.startup_delay = startup_delay
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._procs: list[subprocess.Popen] = []

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        for proc in self._procs:
            try:
                proc.terminate()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        self._procs.clear()

    def _log(self, msg: str) -> None:
        if self.on_log:
            self.on_log(msg)

    def _read_stderr(self, proc: subprocess.Popen, label: str) -> None:
        if proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                if self._stop.is_set():
                    break
                line = raw.decode(errors="replace").strip()
                if line:
                    self._log(f"{label}: {line}")
        except OSError:
            pass

    def _spawn_pipeline(self) -> tuple[subprocess.Popen, subprocess.Popen] | None:
        sample_rate = settings_manager.data.sample_rate

        ytdlp_cmd = [
            "yt-dlp",
            "-f",
            "bestaudio",
            "-o",
            "-",
            "--no-playlist",
            "--no-warnings",
            "--quiet",
            "--limit-rate",
            "2M",
        ]
        if self.start_offset > 0:
            ytdlp_cmd += ["--download-sections", f"*{self.start_offset}-"]
        ytdlp_cmd.append(self.page_url)

        ffmpeg_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]

        self._log(
            "INFO 启动 yt-dlp (限速 2M/s, 低优先级) 以避免与视频播放争抢带宽"
        )
        self._log(f"INFO 启动 yt-dlp: {' '.join(ytdlp_cmd[:8])}… {self.page_url[:60]}…")
        try:
            ytdlp_proc = subprocess.Popen(
                ytdlp_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_POPEN_KWARGS,
            )
            ffmpeg_proc = subprocess.Popen(
                ffmpeg_cmd,
                stdin=ytdlp_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_POPEN_KWARGS,
            )
        except FileNotFoundError as exc:
            self._log(f"ERROR 启动音频管道失败: {exc}")
            return None

        if ytdlp_proc.stdout:
            ytdlp_proc.stdout.close()

        self._procs = [ytdlp_proc, ffmpeg_proc]
        self._log("INFO yt-dlp / ffmpeg 管道进程已启动，等待音频数据…")
        threading.Thread(
            target=self._read_stderr, args=(ytdlp_proc, "yt-dlp"), daemon=True
        ).start()
        threading.Thread(
            target=self._read_stderr, args=(ffmpeg_proc, "ffmpeg"), daemon=True
        ).start()
        return ytdlp_proc, ffmpeg_proc

    def _spawn_ffmpeg_direct(self) -> subprocess.Popen | None:
        if not self.stream_url:
            return None

        sample_rate = settings_manager.data.sample_rate
        headers = (
            f"Referer: {self.referer}\r\n"
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)\r\n"
        )
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-headers",
            headers,
            "-ss",
            str(self.start_offset),
            "-i",
            self.stream_url,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-f",
            "s16le",
            "pipe:1",
        ]

        self._log(f"INFO 启动 ffmpeg 直链 (低优先级): {self.stream_url[:80]}…")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                **_POPEN_KWARGS,
            )
        except FileNotFoundError as exc:
            self._log(f"ERROR 启动 ffmpeg 失败: {exc}")
            return None

        self._procs = [proc]
        threading.Thread(
            target=self._read_stderr, args=(proc, "ffmpeg"), daemon=True
        ).start()
        return proc

    def _wait_proc(self, proc: subprocess.Popen, label: str) -> None:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if not self._stop.is_set():
                self._log(f"WARN {label} 未在 5s 内退出，强制终止")
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass

    def _pump_pcm(self, stdout) -> int:
        chunk_samples = int(
            settings_manager.data.sample_rate * settings_manager.data.chunk_seconds
        )
        bytes_per_chunk = chunk_samples * 2
        buffer = b""
        chunk_index = 0
        chunks_sent = 0

        while not self._stop.is_set():
            data = stdout.read(4096)
            if not data:
                break
            buffer += data
            while len(buffer) >= bytes_per_chunk:
                raw = buffer[:bytes_per_chunk]
                buffer = buffer[bytes_per_chunk:]
                pcm = np.frombuffer(raw, dtype=np.int16)
                timestamp = self.start_offset + chunk_index * (
                    settings_manager.data.chunk_seconds
                    - settings_manager.data.chunk_overlap
                )
                self.on_chunk(pcm, timestamp)
                chunk_index += 1
                chunks_sent += 1
                if not self._stop.is_set():
                    if chunks_sent == 1:
                        self._log("INFO 首个 PCM 片段已输出")
                    time.sleep(
                        settings_manager.data.chunk_seconds
                        - settings_manager.data.chunk_overlap
                    )

        return chunks_sent

    def _run(self) -> None:
        if self.startup_delay > 0:
            self._log(
                f"INFO 延迟 {self.startup_delay:.0f}s 启动音频提取，"
                "优先让视频缓冲…"
            )
            if self._stop.wait(self.startup_delay):
                return

        self._log("音频提取启动 (yt-dlp → ffmpeg)…")

        pipeline = self._spawn_pipeline()
        chunks_sent = 0

        if pipeline:
            ytdlp_proc, ffmpeg_proc = pipeline
            if ffmpeg_proc.stdout:
                chunks_sent = self._pump_pcm(ffmpeg_proc.stdout)

            self._wait_proc(ytdlp_proc, "yt-dlp")
            self._wait_proc(ffmpeg_proc, "ffmpeg")
            ytdlp_rc = ytdlp_proc.returncode

            if ytdlp_rc not in (0, None) and ytdlp_rc != 255:
                self._log(f"WARN yt-dlp 退出码 {ytdlp_rc}")

        if chunks_sent == 0 and not self._stop.is_set():
            self._log("yt-dlp 管道无音频数据，尝试 ffmpeg 直链回退…")
            proc = self._spawn_ffmpeg_direct()
            if proc and proc.stdout:
                chunks_sent = self._pump_pcm(proc.stdout)
                self._wait_proc(proc, "ffmpeg")
                if proc.returncode not in (0, None) and chunks_sent == 0:
                    self._log(f"ERROR ffmpeg 直链失败，退出码 {proc.returncode}")

        if chunks_sent == 0 and not self._stop.is_set():
            self._log(
                "ERROR 未能提取到音频。请确认链接有效、已安装 yt-dlp/ffmpeg，"
                "且网络可访问 B 站。"
            )
        elif chunks_sent > 0:
            self._log(f"音频提取结束，共输出 {chunks_sent} 个片段")
