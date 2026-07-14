#!/usr/bin/env python3
"""本地同声传译播放器 — 入口."""

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# macOS 上部分 Python 环境需显式指定 Qt 插件路径
import PyQt6  # noqa: E402

# Anaconda 自带 Qt5 插件会干扰 PyQt6，需指向 Qt6 的 platforms 目录
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(
    os.path.dirname(PyQt6.__file__), "Qt6", "plugins", "platforms"
)

from PyQt6.QtWidgets import QApplication  # noqa: E402

from src.ui.main_window import MainWindow
from src.ui.theme import application_qss


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("本地同声传译播放器")
    app.setStyle("Fusion")
    app.setStyleSheet(application_qss())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
