"""LeopardIQTS 入口。

运行（项目根目录，conda 环境 LpIQtest312）：
    python -m iqtest.main
"""

from __future__ import annotations

import sys
from pathlib import Path

# 允许 `python iqtest/main.py` 直接运行（补项目根到 sys.path）
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from iqtest.main_window import WINDOW_TITLE, MainWindow, app_icon
from iqtest.style import APP_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LeopardIQTS")
    app.setOrganizationName("LeopardImaging")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.setWindowTitle(WINDOW_TITLE)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
