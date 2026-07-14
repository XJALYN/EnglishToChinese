"""Best-effort CPU / I/O priority helpers to keep video playback smooth."""

from __future__ import annotations

import os
import sys


def subprocess_low_priority() -> None:
    """preexec_fn hook: lower priority of child processes (yt-dlp, ffmpeg)."""
    try:
        os.nice(10)
    except OSError:
        pass


def lower_current_thread_priority() -> None:
    """Lower priority of the calling thread (ASR / pipeline workers)."""
    if sys.platform == "darwin":
        try:
            import ctypes
            import ctypes.util

            libc_path = ctypes.util.find_library("c")
            if not libc_path:
                return
            libc = ctypes.CDLL(libc_path)
            # QOS_CLASS_UTILITY — background work, yields to UI / playback
            QOS_CLASS_UTILITY = 0x15
            libc.pthread_set_qos_class_self_np(QOS_CLASS_UTILITY, 0)
        except (OSError, AttributeError):
            pass
    elif sys.platform.startswith("linux"):
        try:
            os.nice(5)
        except OSError:
            pass
