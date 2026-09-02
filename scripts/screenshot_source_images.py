"""Source images 工具栏冒烟验证：空态 / 网格 / 列表 / 面板关闭 / 批量操作。

用法（Git Bash，项目根目录）：
    QT_QPA_PLATFORM=offscreen "D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe" scripts/screenshot_source_images.py
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


def grab(window, name: str) -> None:
    out = OUT_DIR / name
    ok = window.grab().save(str(out))
    print("screenshot:", out, "saved:", ok)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)

    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    si = window.source_images

    def step_empty() -> None:
        # 空态：大 drop zone，批量按钮隐藏，模式按钮可见
        assert si._drop_frame.isVisible()
        assert not si.btn_select_all.isVisible()
        assert not si.btn_remove_all.isVisible()
        assert not si.btn_panel_toggle.isVisible()
        assert si.btn_list_mode.isVisible() and si.btn_grid_mode.isVisible()
        grab(window, "si_1_empty.png")

        images = make_test_images()
        added = window.session.add_images(images)
        assert added == 3, f"预期加载 3 张，实际 {added}"
        assert window.workflow.step1_status.text() == "3/3 image(s) selected"
        QTimer.singleShot(300, step_grid)

    def step_grid() -> None:
        # 网格模式 + 面板开启（默认）：drop zone 收缩为顶部小条
        assert si._mode == "grid"
        assert si._view_stack.currentIndex() == 1
        assert si._drop_frame.isVisible()
        assert si._drop_frame.maximumHeight() <= 220
        assert si._btn_close_panel.isVisible()
        assert si.btn_select_all.isVisible()
        assert len(si._grid_view.cards) == 3
        grab(window, "si_2_grid.png")

        # 窗口缩小 → 网格自动减少列数、卡片换行下移
        cols_before = si._grid_view._cols
        window.resize(760, 800)
        QTimer.singleShot(300, lambda: step_grid_narrow(window, si, cols_before))

    def step_grid_narrow(win, si, cols_before) -> None:
        assert si._grid_view._cols < cols_before, (
            f"缩小窗口后列数应减少：{cols_before} → {si._grid_view._cols}"
        )
        grab(win, "si_2b_grid_narrow.png")
        win.resize(1280, 800)
        QTimer.singleShot(300, step_list_mode)

    def step_list_mode() -> None:
        # 切换列表模式
        si.btn_list_mode.click()
        assert si._mode == "list"
        assert si._view_stack.currentIndex() == 0
        assert len(si._list_view.rows) == 3
        QTimer.singleShot(300, step_list)

    def step_list() -> None:
        grab(window, "si_3_list.png")

        # 取消勾选一张 → 状态栏 2/3
        row = si._list_view.rows[0]
        row.check.setChecked(False)
        assert window.session.selected_count == 2
        assert window.workflow.step1_status.text() == "2/3 image(s) selected"
        assert si.btn_select_all.toolTip() == "选定所有图片"

        # 批量全选 → 3/3
        si.btn_select_all.click()
        assert window.session.selected_count == 3
        assert si.btn_select_all.toolTip() == "取消选定所有图片"
        assert si._list_view.rows[0].check.isChecked()

        # 关闭添加面板（⊖ → 隐藏 drop zone）
        si.btn_panel_toggle.click()
        assert not si._panel_open
        assert not si._drop_frame.isVisible()
        QTimer.singleShot(300, step_panel_closed)

    def step_panel_closed() -> None:
        grab(window, "si_4_panel_closed.png")

        # 重新打开面板（⊕）
        si.btn_panel_toggle.click()
        assert si._drop_frame.isVisible()

        # 移除全部 → 回到空态
        si.btn_remove_all.click()
        assert window.session.count == 0
        assert window.workflow.step1_status.text() == "No images selected"
        assert si._drop_frame.isVisible()
        assert si._drop_frame.maximumHeight() > 1000
        assert not si.btn_select_all.isVisible()
        print("all assertions passed")
        app.quit()

    QTimer.singleShot(300, step_empty)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
