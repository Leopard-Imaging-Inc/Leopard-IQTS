"""M2 冒烟验证（单选 + 步骤点击版）：步骤点击/NEXT 切换、Analysis options 单选、
JSON 持久化、QThread runner、Figure 框架。

用法（Git Bash，项目根目录）：
    "D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe" scripts/screenshot_m2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from iqtest.config import store  # noqa: E402
from iqtest.main_window import MainWindow  # noqa: E402
from iqtest.style import APP_QSS  # noqa: E402
from screenshot_m1 import make_test_images  # noqa: E402

OUT_DIR = ROOT / "tests" / "_m2_smoke"


def check_item(options, key: str) -> None:
    for i in range(options._list.count()):
        item = options._list.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == key:
            item.setCheckState(Qt.CheckState.Checked)
            return
    raise KeyError(key)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1280, 800)
    window.show()
    window.session.add_images(make_test_images())
    options = window.analysis_options

    def step1_goto_analysis() -> None:
        # 点击步骤 ② 标题 → Analysis options 页（点击切换路径）
        QTest.mouseClick(window.workflow.step2_title, Qt.MouseButton.LeftButton)
        assert window._right_stack.currentIndex() == 1
        assert window._right_title.text() == "Analysis options"
        assert window.workflow.btn_next.text() == "PREVIOUS"

        # 单选互斥：先勾 fov，再勾 mtf，fov 应自动取消
        check_item(options, "fov")
        assert options.selected_keys() == ["fov"]
        check_item(options, "mtf")
        assert options.selected_keys() == ["mtf"], options.selected_keys()
        assert list(window.session.analyses) == ["mtf"]
        assert "MTF / SFR" in window.workflow.step2_status.text()
        assert "FOV" not in window.workflow.step2_status.text()

        # 修改一个 criteria 值验证回读
        mtf_panel = options._panels["mtf"]
        cfg = mtf_panel.config()
        cfg["criteria"]["mtf50_min"] = 0.15
        mtf_panel.set_config(cfg)
        QTimer.singleShot(400, step2_grab_options)

    def step2_grab_options() -> None:
        out = OUT_DIR / "m2_analysis_options.png"
        window.grab().save(str(out))
        print("screenshot:", out)
        step3_json_roundtrip()

    def step3_json_roundtrip() -> None:
        configs = options.selected_configs()
        assert list(configs) == ["mtf"]
        assert configs["mtf"]["criteria"]["mtf50_min"] == 0.15
        assert configs["mtf"]["params"]["cfa"] == "Y"

        path = OUT_DIR / "criteria_roundtrip.json"
        store.save_json(path, {"modules": configs})
        loaded = store.load_json(path)
        assert loaded["modules"]["mtf"]["criteria"]["mtf50_min"] == 0.15

        bad = OUT_DIR / "bad.json"
        bad.write_text('{"foo": 1}', encoding="utf-8")
        try:
            store.load_json(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("非法 JSON 未触发 ValueError")
        print("analysis options (single-select) + JSON roundtrip: OK")

        # 通过主窗口 ANALYZE 路径启动 runner。
        # 注：M3 起 mtf 接入真实算法，未框选 ROI 时会报 module_error ——
        # 此处验证「单模块失败不崩溃调度层」的错误路径；成功路径由 screenshot_m3 覆盖。
        # （_on_all_finished 会弹 QMessageBox，离屏环境下先行打桩避免阻塞）
        QMessageBox.warning = staticmethod(
            lambda *a, **k: QMessageBox.StandardButton.Ok
        )
        window._on_analyze()
        assert window.runner.is_running
        QTimer.singleShot(1500, step4_verify_run)

    def step4_verify_run() -> None:
        assert not window.runner.is_running
        assert "mtf" in window._run_errors, "未框选 ROI 应报 module_error"
        assert "ROI" in window._run_errors["mtf"]
        assert window.figure_manager.count == 0
        print("runner 错误路径（无 ROI → module_error，调度不中断）: OK")

        # 点击步骤 ① 标题回到 Source images 页
        QTest.mouseClick(window.workflow.step1_title, Qt.MouseButton.LeftButton)
        assert window._right_stack.currentIndex() == 0
        assert window.workflow.btn_next.text() == "NEXT"
        out = OUT_DIR / "m2_mainwindow.png"
        window.grab().save(str(out))
        print("screenshot:", out)

        # 会话复位（绕过确认框）
        window.session.clear()
        options.set_selected({})
        assert window.session.count == 0 and not window.session.analyses
        assert window.workflow.step2_status.text() == "Not selected"
        print("session reset: OK")
        app.quit()

    QTimer.singleShot(300, step1_goto_analysis)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
