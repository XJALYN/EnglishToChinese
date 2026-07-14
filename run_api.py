#!/usr/bin/env python3
"""启动 FastAPI 后端 (Electron 前端用)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.api.server import run_server

if __name__ == "__main__":
    run_server()
