"""
MtfResultView 交互测试：ROI 选中高亮 + MTF50/MTF30 标注开关 + 复位视图。

覆盖「优化 MTF/SFR — 分析结果页面」三处交互，纯 UI 断言（合成 result dict，
不跑 C++ 引擎）：
[1/4] 工具行按钮存在 + 勾选态（MTF50/MTF30 默认关）+ 标注可见性
      （无选中标全部 / 选中 ROI 仅标该 ROI）
[2/4] ROI 选中高亮 / 取消恢复（曲线 pen 宽度与透明度）
[3/4] 复位视图恢复初始坐标范围
[4/4] 表格列跟随开关显隐（Readout1=30/50 判定列受保护）

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_mtf_figure.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def make_result(n: int = 5, readouts=None,
                readout1_key: str | None = "mtf30") -> dict:
    """合成 result dict：n 条有效 ROI 曲线（单调下降，mtf50/mtf30 均在 (0,1)）。"""
    if readouts is None:
        readouts = [
            {"key": "mtf30", "label": "MTF30"},
            {"key": "mtf50p", "label": "MTF50P"},
        ]
    freq = np.linspace(0.0, 1.0, 50)
    curves = []
    for i in range(1, n + 1):
        slope = 0.80 + 0.02 * i
        mtf = 1.0 - slope * np.linspace(0.0, 1.0, 50)
        curves.append({
            "roi": i,
            "channel": "Y",
            "valid": True,
            "gamma": 1.0,
            "freq": np.round(freq, 6).tolist(),
            "mtf": np.round(mtf, 6).tolist(),
            "mtf50": round(0.5 / slope, 6),
            "readout1": round(0.7 / slope, 6),
            "readouts": [round(0.7 / slope, 6), round(0.55 / slope, 6)],
            "sfr": [0.85],
        })
    return {
        "metrics": {},
        "pass": True,
        "details": {
            "cfa": "Y",
            "channels": ["Y"],
            "frequency": [0.125],
            "freq_unit": "Cycles/pixel",
            "unit_scale": 1.0,
            "pixel_size_um": 2.0,
            "picture_height": 800,
            "gamma": 1.0,
            "readouts": readouts,
            "readout1_key": readout1_key,
            "criteria": {"readout1_min": 0.1, "sfr_main_min": 0.2},
            "rois": [
                {"roi": i, "image": "s.png", "rect": [0, 0, 40, 40],
                 "valid": True, "gamma": 1.0}
                for i in range(1, n + 1)
            ],
            "curves": curves,
        },
    }


def test_buttons_and_markers():
    print("[1/4] 工具行按钮存在 + 标注可见性（默认关 / 无选中全标 / 选中仅标该 ROI）")
    from PySide6.QtWidgets import QApplication, QPushButton

    from iqtest.figures.mtf_figure import MtfResultView

    app = QApplication.instance() or QApplication([])
    view = MtfResultView(make_result())

    mtf50 = view.findChild(QPushButton, "mtf50Btn")
    mtf30 = view.findChild(QPushButton, "mtf30Btn")
    reset = view.findChild(QPushButton, "resetViewBtn")
    export = view.findChild(QPushButton, "exportCsvBtn")
    check("存在 MTF50 按钮", mtf50 is not None)
    check("存在 MTF30 按钮", mtf30 is not None)
    check("存在 复位视图 按钮", reset is not None)
    check("存在 导出结果 CSV 按钮（回归）", export is not None)
    check("MTF50 可勾选且默认关",
          mtf50 is not None and mtf50.isCheckable() and not mtf50.isChecked())
    check("MTF30 可勾选且默认关",
          mtf30 is not None and mtf30.isCheckable() and not mtf30.isChecked())

    def n_points(scatter) -> int:
        return len(scatter.data)

    def lines_visible(lines, roi=None):
        if roi is None:
            return all(it.isVisible()
                       for items in lines.values() for it in items)
        return all(it.isVisible() for it in lines[roi])

    # 默认：两个散点隐藏、连线全部隐藏
    check("默认 MTF50 散点隐藏", not view._mtf50_scatter.isVisible())
    check("默认 MTF30 散点隐藏", not view._mtf30_scatter.isVisible())
    check("默认 MTF50 连线全部隐藏",
          all(not it.isVisible()
              for items in view._mtf50_lines.values() for it in items))

    # 无选中：勾选 MTF50 → 标全部 5 个点 + 全部连线
    mtf50.setChecked(True)
    check("无选中勾选 MTF50 → 散点 5 个",
          n_points(view._mtf50_scatter) == 5, str(n_points(view._mtf50_scatter)))
    check("无选中勾选 MTF50 → 散点可见", view._mtf50_scatter.isVisible())
    check("无选中勾选 MTF50 → 全部连线可见",
          lines_visible(view._mtf50_lines))

    # 选中 ROI2：仅标 ROI2 的点 + 连线
    view._select_roi(2)
    check("选中 ROI2 后 MTF50 散点仅 1 个",
          n_points(view._mtf50_scatter) == 1, str(n_points(view._mtf50_scatter)))
    check("选中 ROI2 后仅 ROI2 连线可见", lines_visible(view._mtf50_lines, 2))
    check("选中 ROI2 后其它 ROI 连线隐藏",
          all(not it.isVisible()
              for r, items in view._mtf50_lines.items() if r != 2
              for it in items))

    # 取消选中：恢复标全部
    view._select_roi(2)  # 再次点击同一 ROI → 取消选中
    check("取消选中后 MTF50 散点恢复 5 个",
          n_points(view._mtf50_scatter) == 5, str(n_points(view._mtf50_scatter)))

    # 取消勾选 MTF50 → 隐藏
    mtf50.setChecked(False)
    check("取消勾选 MTF50 → 散点隐藏", not view._mtf50_scatter.isVisible())
    check("取消勾选 MTF50 → 连线隐藏",
          all(not it.isVisible()
              for items in view._mtf50_lines.values() for it in items))

    # MTF30 同理（抽查）：无选中勾选后 5 点可见；选中后仅 1 点
    mtf30.setChecked(True)
    check("无选中勾选 MTF30 → 散点 5 个",
          n_points(view._mtf30_scatter) == 5, str(n_points(view._mtf30_scatter)))
    view._select_roi(3)
    check("选中 ROI3 后 MTF30 散点仅 1 个",
          n_points(view._mtf30_scatter) == 1, str(n_points(view._mtf30_scatter)))
    mtf30.setChecked(False)
    check("取消勾选 MTF30 → 散点隐藏", not view._mtf30_scatter.isVisible())

    view.close()
    view.deleteLater()
    app.processEvents()


def test_roi_selection():
    print("[2/4] ROI 选中高亮 / 取消恢复")
    from PySide6.QtWidgets import QApplication

    from iqtest.figures.mtf_figure import MtfResultView

    app = QApplication.instance() or QApplication([])
    view = MtfResultView(make_result())

    view._select_roi(2)
    check("选中 ROI2", view._selected_roi == 2)
    widths = {r: it.opts["pen"].width()
              for r, it in view._curve_items.items()}
    check("选中曲线加粗（宽 3）", widths.get(2) == 3, str(widths))
    check("其余曲线淡化（宽 1）",
          all(w == 1 for r, w in widths.items() if r != 2), str(widths))
    alpha = view._curve_items[1].opts["pen"].color().alpha()
    check("非选中曲线半透明（alpha 80）", alpha == 80, str(alpha))

    # 再次点击同一 ROI → 取消选中，全部恢复默认宽 2
    view._select_roi(2)
    check("再次点击同一 ROI 取消选中", view._selected_roi is None)
    widths2 = {r: it.opts["pen"].width()
               for r, it in view._curve_items.items()}
    check("取消后全部恢复默认宽 2", all(w == 2 for w in widths2.values()),
          str(widths2))

    # 表格行点击 → 选中对应 ROI
    view._on_table_cell_clicked(2, 0)  # 第 3 行 = ROI3
    check("表格点击第 3 行选中 ROI3", view._selected_roi == 3)
    check("表格第 3 行处于选中", view._table.selectionModel().selectedRows()
          and view._table.selectionModel().selectedRows()[0].row() == 2)

    # 曲线点击 → 守卫置位并选中；紧随的 scene 点击被守卫吞掉；再点空白才取消
    view._on_curve_clicked(4)
    check("曲线点击选中 ROI4 且置守卫",
          view._selected_roi == 4 and view._curve_click_guard)
    view._on_plot_clicked(None)  # 守卫吞掉，不取消
    check("守卫吞掉紧随的 scene 点击（仍选中 ROI4）",
          view._selected_roi == 4 and not view._curve_click_guard)
    view._on_plot_clicked(None)  # 空白点击 → 取消
    check("空白点击取消选中", view._selected_roi is None)

    view.close()
    view.deleteLater()
    app.processEvents()


def test_reset_view():
    print("[3/4] 复位视图恢复初始坐标范围")
    from PySide6.QtWidgets import QApplication

    from iqtest.figures.mtf_figure import MtfResultView

    app = QApplication.instance() or QApplication([])
    view = MtfResultView(make_result())
    vb = view._plot.getViewBox()
    init_x = tuple(vb.viewRange()[0])
    init_y = tuple(vb.viewRange()[1])

    view._plot.setXRange(0.3, 0.7)
    view._plot.setYRange(0.1, 0.9)
    check("手动缩放已改变 X 范围",
          abs(vb.viewRange()[0][0] - init_x[0]) > 0.01,
          str(vb.viewRange()[0]))

    view._reset_view()
    rx = tuple(vb.viewRange()[0])
    ry = tuple(vb.viewRange()[1])
    check("复位后 X 恢复初始",
          all(abs(a - b) < 1e-6 for a, b in zip(rx, init_x)),
          f"{rx} vs {init_x}")
    check("复位后 Y 恢复初始",
          all(abs(a - b) < 1e-6 for a, b in zip(ry, init_y)),
          f"{ry} vs {init_y}")

    view.close()
    view.deleteLater()
    app.processEvents()


def test_table_column_toggle():
    print("[4/4] 表格列跟随开关显隐（Readout1 保护）")
    from PySide6.QtWidgets import QApplication

    from iqtest.figures.mtf_figure import MtfResultView

    app = QApplication.instance() or QApplication([])

    def col_index(view, prefix):
        for i in range(view._table.columnCount()):
            if view._table.horizontalHeaderItem(i).text().startswith(prefix):
                return i
        return None

    # 场景 1：Readout1 = 30（默认）→ MTF30 列受保护始终可见，MTF50 列跟随按钮
    view = MtfResultView(make_result())
    i50 = col_index(view, "MTF50 (")
    i30 = col_index(view, "MTF30 (")
    check("Readout1=30：存在 MTF50/MTF30 列", i50 is not None and i30 is not None)
    check("Readout1=30：MTF30 判定列默认可见",
          not view._table.isColumnHidden(i30))
    check("Readout1=30：MTF50 列默认隐藏（按钮关）",
          view._table.isColumnHidden(i50))
    view._btn_mtf50.setChecked(True)
    check("Readout1=30：勾选 MTF50 → MTF50 列显示",
          not view._table.isColumnHidden(i50))
    view._btn_mtf50.setChecked(False)
    view._btn_mtf30.setChecked(True)
    view._btn_mtf30.setChecked(False)
    check("Readout1=30：MTF30 列不被按钮隐藏",
          not view._table.isColumnHidden(i30))
    view.close()
    view.deleteLater()

    # 场景 2：Readout1 = 50 → MTF50 判定列受保护，无 MTF30 列
    view2 = MtfResultView(make_result(
        readouts=[{"key": "mtf50p", "label": "MTF50P"}],
        readout1_key="mtf50"))
    i50b = col_index(view2, "MTF50 (")
    i30b = col_index(view2, "MTF30 (")
    check("Readout1=50：存在 MTF50 列、无 MTF30 列",
          i50b is not None and i30b is None)
    check("Readout1=50：MTF50 判定列默认可见",
          not view2._table.isColumnHidden(i50b))
    view2._btn_mtf50.setChecked(False)
    check("Readout1=50：MTF50 列不被按钮隐藏",
          not view2._table.isColumnHidden(i50b))
    view2.close()
    view2.deleteLater()

    app.processEvents()


def main():
    test_buttons_and_markers()
    test_roi_selection()
    test_reset_view()
    test_table_column_toggle()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
