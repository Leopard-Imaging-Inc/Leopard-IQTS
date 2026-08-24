"""M3 冒烟验证：MTF/SFR GUI 全链路 —— 载入图像 → 框选 ROI → ANALYZE → MTF 曲线 Figure。

用法（Git Bash，项目根目录）：
    QT_QPA_PLATFORM=offscreen "D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe" scripts/screenshot_m3.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from iqtest.figures.mtf_figure import MtfResultView  # noqa: E402
from iqtest.main_window import MainWindow  # noqa: E402
from iqtest.style import APP_QSS  # noqa: E402
from test_m3_1 import make_mono_chart_file, top_edge_rois  # noqa: E402

OUT_DIR = ROOT / "tests" / "_m3_smoke"


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_QSS)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    window = MainWindow()
    window.resize(1400, 900)
    window.show()

    chart = make_mono_chart_file()
    window.session.add_images([chart])
    options = window.analysis_options

    def step1_setup_panel() -> None:
        # 勾选 MTF/SFR → panel 载入图像 → 框选 ROI
        for i in range(options._list.count()):
            item = options._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == "mtf":
                item.setCheckState(Qt.CheckState.Checked)
                break
        assert options.selected_keys() == ["mtf"]

        panel = options._panels["mtf"]
        # 查看/框选互斥单选：仅「查看」默认激活（有颜色），「框选…」无常驻主色
        assert panel._mode_group.exclusive()
        assert panel._btn_view.isChecked() and not panel._btn_draw.isChecked()
        panel._btn_draw.setChecked(True)   # 互斥：「查看」自动取消
        assert not panel._btn_view.isChecked() and panel._btn_draw.isChecked()
        panel._btn_view.setChecked(True)
        assert panel._btn_view.isChecked() and not panel._btn_draw.isChecked()
        assert not hasattr(panel, "_btn_tune")  # 「精细调整…」已移除
        panel._on_load_image()
        assert panel._loaded_name == chart.name
        assert panel.roi_view.has_image()

        panel.roi_view.set_rois(top_edge_rois())
        assert len(panel.roi_view.rois()) == 5

        # config 注入 ROI
        cfg = panel.config()
        assert len(cfg["params"]["rois"]) == 5
        assert cfg["params"]["rois"][0]["image"] == chart.name
        assert cfg["criteria"]["readout1_min"] == 0.10
        print("panel ROI 框选 + config 注入: OK")

        window._set_step(1)
        QTimer.singleShot(400, step2_grab_panel)

    def step2_grab_panel() -> None:
        out = OUT_DIR / "m3_mtf_panel.png"
        window.grab().save(str(out))
        print("screenshot:", out)

        window._on_analyze()
        assert window.runner.is_running
        QTimer.singleShot(4000, step3_verify_figure)

    def step3_verify_figure() -> None:
        assert not window.runner.is_running
        assert not window._run_errors, window._run_errors
        assert window.figure_manager.count == 1
        fig = window.figure_manager._figures["mtf"]
        content = fig.findChild(MtfResultView)
        assert content is not None, "Figure content 应为 MtfResultView"
        fig.resize(1100, 640)
        out = OUT_DIR / "m3_mtf_figure.png"
        fig.grab().save(str(out))
        print("screenshot:", out)

        n = window.figure_manager.close_all()
        assert n == 1 and window.figure_manager.count == 0
        print("ANALYZE → MTF 曲线 Figure → CLOSE FIGURES: OK")
        step4_raw_and_dialog()

    def step4_raw_and_dialog() -> None:
        """真实 RAW（自动识别分辨率 + 去马赛克）+ ROI 精调弹框截图。"""
        raw = (
            ROOT / "assets/data/MTF/camera_0/1/2-0.6"
            / "SN_2-0.6_D_07_28_2026_T_16_37_32.raw"
        )
        if not raw.exists():
            print("真实 RAW 不存在，跳过 step4")
            app.quit()
            return
        window.session.clear()
        window.session.add_images([raw])
        panel = options._panels["mtf"]
        panel._on_load_image()
        assert panel._loaded_name == raw.name
        assert panel._loaded_image.shape == (1200, 1920), panel._loaded_image.shape
        print("真实 RAW 载入（自动识别 1920×1200 + 去马赛克）: OK")

        boxes = [
            (298, 338, 244, 284), (361, 401, 181, 221),
            (1555, 1595, 262, 302), (1507, 1547, 187, 227),
            (871, 911, 586, 626), (935, 975, 535, 575),
            (295, 335, 922, 962), (359, 399, 985, 1025),
            (1573, 1613, 955, 995), (1493, 1533, 1003, 1043),
        ]
        panel.roi_view.set_rois([[x1, y1, x2 - x1, y2 - y1]
                                 for x1, x2, y1, y2 in boxes])
        window._set_step(1)
        out = OUT_DIR / "m3_mtf_panel_raw.png"
        window.grab().save(str(out))
        print("screenshot:", out)

        # ROI 精调弹框（非模态打开 → 截图 → 关闭）
        from iqtest.widgets.roi_dialog import RoiFineTuneDialog

        dialog = RoiFineTuneDialog(
            panel._loaded_image, panel.roi_view.rois(), current=0, parent=window
        )
        dialog.show()

        def grab_dialog() -> None:
            out = OUT_DIR / "m3_roi_dialog.png"
            dialog.grab().save(str(out))
            print("screenshot:", out)
            # 模拟精调：整体右移（1px + 5px 步长各一次）、右边缘外扩 5px，验证回写
            dialog._move(1, 0)  # 步长默认 1px → x=299
            dialog._step_group.button(1).setChecked(True)  # 切到 5px
            dialog._move(1, 0)  # → x=304
            dialog._adjust_edge("r", 1)  # → w=45
            assert dialog.rois()[0][:2] == [304, 244], dialog.rois()[0]
            assert dialog.rois()[0][2] == 45, dialog.rois()[0]
            dialog.accept()
            # 回写路径（面板 _exec_tune_dialog 内同款逻辑）
            panel.roi_view.set_rois(dialog.rois())
            assert panel.roi_view.rois()[0] == [304, 244, 45, 40]
            print("ROI 精调弹框（移动/边缘/步长/回写）: OK")
            step5_draw_dialog()

        QTimer.singleShot(500, grab_dialog)

    def step5_draw_dialog() -> None:
        """框选入口：draw_new=True 弹框内画粗 ROI → 精调合一 → 回写。"""
        from iqtest.widgets.roi_dialog import RoiFineTuneDialog

        panel = options._panels["mtf"]
        before = panel.roi_view.rois()
        dialog = RoiFineTuneDialog(
            panel._loaded_image, before, parent=window, draw_new=True
        )
        # 画框前：精调控件与「确定」禁用
        assert not dialog._btn_ok.isEnabled()
        dialog.show()

        def grab_draw() -> None:
            out = OUT_DIR / "m3_roi_dialog_draw.png"
            dialog.grab().save(str(out))
            print("screenshot:", out)
            dialog._view.roi_drawn.emit([100, 100, 60, 50])  # 模拟弹框内画框
            assert dialog._btn_ok.isEnabled()
            assert dialog.rois()[-1] == [100, 100, 60, 50]
            assert len(dialog.rois()) == len(before) + 1
            dialog.accept()
            panel.roi_view.set_rois(dialog.rois())
            assert panel.roi_view.rois()[-1] == [100, 100, 60, 50]
            print("框选弹框（draw_new 画框 → 精调合一 → 回写）: OK")
            app.quit()

        QTimer.singleShot(500, grab_draw)

    QTimer.singleShot(300, step1_setup_panel)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
