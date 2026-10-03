"""
M3 Lens Shading GUI 验证测试（offscreen）：面板 / 结果视图 / 主窗口接线。

测试内容：
[1/3] ShadingPanel：图像→光源分配表随会话填充、config() 注入 image_lights、
      光源默认值切换与单图覆盖
[2/3] ShadingResultView：单光源（横幅/热力图/四象限/Color shift/Imatest 对标/LSC 验证/导出按钮）
      与多光源（对比视图）
[3/3] 主窗口接线：MODULE_ANALYZERS 注册、FigureManager 视图注册、
      module_finished → Figure 弹出、主窗口关闭 → 结果窗同步关闭

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_shading_gui.py
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_shading_adapter as sa  # noqa: E402  复用合成图与 config 辅助

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


def make_app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_panel():
    print("[1/3] ShadingPanel：图像→光源表 / config 注入")
    app = make_app()
    from PySide6.QtWidgets import QTableWidget

    from iqtest.panels import MODULE_PANELS
    from iqtest.panels.shading_panel import ShadingPanel
    from iqtest.session import Session

    check("ShadingPanel 注册于模块列表",
          any(p.MODULE_KEY == "shading" for p in MODULE_PANELS))

    session = Session()
    session.add_images([sa.OUT_DIR / "a.png", sa.OUT_DIR / "b.png"])
    panel = ShadingPanel(session=session)
    table = panel.findChild(QTableWidget)
    check("图像→光源表 2 行", table is not None and table.rowCount() == 2)

    cfg = panel.config()
    check("config 注入 image_lights",
          "image_lights" in cfg["params"]
          and cfg["params"]["image_lights"]["a.png"] == "D65")

    # 单图覆盖，其余跟随默认（D65）
    table.cellWidget(0, 1).setCurrentText("A")
    cfg2 = panel.config()
    check("单图覆盖 + 其余跟随默认",
          cfg2["params"]["image_lights"]["a.png"] == "A"
          and cfg2["params"]["image_lights"]["b.png"] == "D65")

    # 单光源子功能不再有「光源类型」参数
    check("single 无光源类型参数", "light_source" not in cfg["params"])
    check("面板已移除后处理/展示参数",
          all(k not in cfg["params"] for k in
              ("luminance_channel", "support_extrapolation", "enable_lsc_verify")))

    # 「图像→光源」表随测试项显隐（用 isVisibleTo 排除"面板未 show"干扰）
    check("默认 single：光源表隐藏", panel._light_group is not None
          and not panel._light_group.isVisibleTo(panel))
    panel.params_form.set_values({"test_item": "multi_light"})
    check("multi_light：光源表显示", panel._light_group.isVisibleTo(panel))
    panel.params_form.set_values({"test_item": "single"})
    check("切回 single：光源表隐藏", not panel._light_group.isVisibleTo(panel))

    panel.deleteLater()
    app.processEvents()


def test_figure():
    print("[2/3] ShadingResultView：单光源 + 多光源")
    app = make_app()
    import pyqtgraph as pg
    from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton, QTabWidget

    from iqtest.analysis.shading_adapter import analyze_shading
    from iqtest.figures.shading_figure import ShadingResultView

    png = sa.make_mono_png(corner_falloff=0.7)
    result = analyze_shading([png], sa.mono_config())
    view = ShadingResultView(result)

    check("single 显示热力图", view.findChild(pg.PlotWidget) is not None)
    check("single 浅色界面（无深色背景）", "#1e1e1e" not in view.styleSheet())
    check("导出 shading_profile 按钮启用",
          isinstance(view._export_profile_btn, QPushButton)
          and view._export_profile_btn.isEnabled())
    labels = [l.text() for l in view.findChildren(QLabel)]
    check("判定横幅 PASS", any("判定：PASS" in t for t in labels), str(labels[:3]))

    combo = view.findChild(QComboBox)
    checks = view.findChildren(QCheckBox)
    check("亮度通道下拉存在", combo is not None and combo.count() == 3)
    check("LSC/RBF 复选框存在", checks is not None and len(checks) >= 2
          and any("LSC" in c.text() for c in checks) and any("RBF" in c.text() for c in checks))

    lsc = next(c for c in checks if "LSC" in c.text())
    check("LSC 默认关闭", lsc.isChecked() is False)
    check("复选框勾选框青色", "#1b9aaa" in lsc.styleSheet())
    check("LSC 文案精简为 LSC", lsc.text() == "LSC")

    tabs = view._content.findChild(QTabWidget)
    check("默认 tabs 不含 LSC 验证（LSC 关闭）",
          tabs is not None and tabs.count() == 2
          and not any(tabs.tabText(i) == "LSC 验证" for i in range(tabs.count())))
    check("tab 页签青色主题", "#1b9aaa" in tabs.styleSheet())
    check("Tab 顺序：四象限 RI → Imatest 对标",
          tabs.tabText(0) == "四象限 RI" and tabs.tabText(1) == "Imatest 对标")
    check("LSC 关闭时校正后图片保存按钮禁用",
          not view._save_corrected_btn.isEnabled())

    # 勾选「使用 LSC」→ 即时重算并出现 LSC 验证 tab（主 RI 不变）
    before_ri = view._result["metrics"]["ri_diff"]["value"]
    lsc.setChecked(True)
    app.processEvents()
    tabs_new = view._content.findChild(QTabWidget)
    check("开启 LSC 后出现 LSC 验证 tab",
          tabs_new is not None and tabs_new.count() == 3
          and any(tabs_new.tabText(i) == "LSC 验证" for i in range(tabs_new.count())))
    check("LSC 验证 tab 展示校正后相对照度",
          view._result["details"]["closed_loop"].get("after_report", {})
          .get("shading_map") is not None)
    check("开启 LSC 后校正后图片保存按钮启用",
          view._save_corrected_btn.isEnabled())
    check("左侧图区含 LSC 校正后图片选项",
          view._left_combo is not None
          and view._left_combo.findText("LSC 校正后图片") >= 0)
    check("开启 LSC 主 RI 不变",
          abs(view._result["metrics"]["ri_diff"]["value"] - before_ri) < 1e-12)
    view.deleteLater()
    app.processEvents()

    # 多光源：无热力图（无 avg 重算），含对比 tab
    png2 = sa.make_mono_png(corner_falloff=0.65)
    cfg = sa.mono_config(criteria={"ri_corner_min": 0.4, "lum_uniformity_min": 0.5},
                         test_item="multi_light")
    cfg["params"]["image_lights"] = {png.name: "D65", png2.name: "TL84"}
    multi = analyze_shading([png, png2], cfg)
    view2 = ShadingResultView(multi)
    check("多光源不显示热力图", view2.findChild(pg.PlotWidget) is None)
    tabs2 = view2.findChild(QTabWidget)
    check("多光源含对比 tab",
          tabs2 is not None
          and any(tabs2.tabText(i) == "多光源对比" for i in range(tabs2.count())))
    # 多光源无 avg → 显示但不启用重算组件
    check("多光源重算组件禁用", view2._channel_combo is not None
          and not view2._channel_combo.isEnabled()
          and not view2._lsc_check.isEnabled()
          and not view2._rbf_check.isEnabled())
    view2.deleteLater()
    app.processEvents()


def test_main_window():
    print("[3/3] 主窗口接线：注册 + Figure 弹出")
    app = make_app()

    from iqtest.analysis.shading_adapter import analyze_shading
    from iqtest.main_window import MainWindow
    from iqtest.runner import MODULE_ANALYZERS

    check("MODULE_ANALYZERS 注册 shading", "shading" in MODULE_ANALYZERS)

    win = MainWindow()
    check("FigureManager 注册 shading 视图",
          "shading" in win.figure_manager._view_factories)

    png = sa.make_mono_png(corner_falloff=0.7)
    result = analyze_shading([png], sa.mono_config())
    win._on_module_finished("shading", result)
    app.processEvents()
    fig = win.figure_manager._figures.get("shading")
    check("module_finished → Figure 弹出", fig is not None and fig.isVisible())

    win.close()
    check("主窗口关闭 → 结果窗同步关闭",
          win.figure_manager.count == 0 and not fig.isVisible())
    win.deleteLater()
    app.processEvents()


def main():
    print("=" * 60)
    print("M3 Lens Shading GUI 验证测试")
    print("=" * 60)
    test_panel()
    test_figure()
    test_main_window()
    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
