"""M1 冒烟验证：离屏实例化主窗口 → 加载合成测试图 → 截图存盘。

用法（Git Bash，项目根目录）：
    QT_QPA_PLATFORM=offscreen "D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe" scripts/screenshot_m1.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import cv2  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from iqtest.main_window import MainWindow  # noqa: E402
from iqtest.style import APP_QSS  # noqa: E402

OUT_DIR = ROOT / "tests" / "_m1_smoke"


def make_test_images() -> list[Path]:
    """生成 3 张合成测试图（灰阶渐变 / 棋盘格 / 均匀亮场）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    grad = np.tile(np.linspace(0, 255, 640, dtype=np.uint8), (480, 1))
    p1 = OUT_DIR / "gradient.png"
    cv2.imwrite(str(p1), grad)
    paths.append(p1)

    chess = (np.indices((480, 640)).sum(axis=0) // 60 % 2 * 255).astype(np.uint8)
    p2 = OUT_DIR / "chessboard.png"
    cv2.imwrite(str(p2), chess)
    paths.append(p2)

    flat = np.full((480, 640, 3), 200, dtype=np.uint8)
    p3 = OUT_DIR / "flatfield.png"
    cv2.imwrite(str(p3), flat)
    paths.append(p3)
    return paths


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.resize(1280, 800)
    window.show()

    def grab() -> None:
        empty = OUT_DIR / "m1_empty.png"
        window.grab().save(str(empty))
        print("screenshot:", empty)

        images = make_test_images()
        added = window.session.add_images(images)
        assert added == 3, f"预期加载 3 张，实际 {added}"
        assert "3 image(s)" in window.workflow.step1_status.text()
        # NEXT / ANALYZE 始终可点；NEXT 切换页面与文案
        assert window.workflow.btn_next.isEnabled()
        assert window.workflow.btn_analyze.isEnabled()
        window.workflow.btn_next.click()
        assert window._right_stack.currentIndex() == 1
        assert window.workflow.btn_next.text() == "PREVIOUS"
        window.workflow.btn_next.click()
        assert window._right_stack.currentIndex() == 0
        assert window.workflow.btn_next.text() == "NEXT"

        # 等缩略图网格刷新后再截有图态
        QTimer.singleShot(300, lambda: grab_loaded(window, app))

    def grab_loaded(win, app) -> None:
        out = OUT_DIR / "m1_mainwindow.png"
        ok = window.grab().save(str(out))
        print("screenshot:", out, "saved:", ok)
        # 再验 START NEW ANALYSIS 的清空逻辑（绕过确认框，直接 clear）
        window.session.clear()
        assert window.session.count == 0
        assert "3 image(s)" not in window.workflow.step1_status.text()
        assert window.workflow.step1_status.text() == "No images selected"
        print("session clear: OK")
        app.quit()

    QTimer.singleShot(300, grab)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
