"""
M3 Lens Shading GUI 验证测试（offscreen）：面板 / 结果视图 / 主窗口接线。

测试内容：
[1/3] ShadingPanel：图像→光源分配表随会话填充、config() 注入 image_lights、
      光源默认值切换与单图覆盖
[2/3] ShadingResultView：单光源（横幅/热力图/四象限/逐项判定/闭环验证/导出按钮）
      与多光源（对比视图）
[3/3] 主窗口接线：MODULE_ANALYZERS 注册、FigureManager 视图注册、
      module_finished → Figure 弹出

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

    # 光源默认值切换 → 未覆盖图像跟随
    panel.params_form.set_values({"light_source": "TL84"})
    cfg2 = panel.config()
    check("光源默认切换生效", all(
        v == "TL84" for v in cfg2["params"]["image_lights"].values()))

    # 单图覆盖
    table.cellWidget(0, 1).setCurrentText("A")
    cfg3 = panel.config()
    check("单图覆盖 + 其余跟随默认",
          cfg3["params"]["image_lights"]["a.png"] == "A"
          and cfg3["params"]["image_lights"]["b.png"] == "TL84")

    panel.deleteLater()
    app.processEvents()


def test_figure():
    print("[2/3] ShadingResultView：单光源 + 多光源")
    app = make_app()
    from PySide6.QtWidgets import QLabel, QPushButton, QTabWidget

    from iqtest.analysis.shading_adapter import analyze_shading
    from iqtest.figures.shading_figure import ShadingResultView

    png = sa.make_mono_png(corner_falloff=0.7)
    result = analyze_shading([png], sa.mono_config())
    view = ShadingResultView(result)

    check("单光源显示热力图", view._plot is not None)
    check("导出 shading_profile 按钮启用",
          isinstance(view._export_profile_btn, QPushButton)
          and view._export_profile_btn.isEnabled())
    labels = [l.text() for l in view.findChildren(QLabel)]
    check("判定横幅 PASS", any("判定：PASS" in t for t in labels), str(labels[:3]))
    tabs = view.findChild(QTabWidget)
    check("单光源 tabs 含四象限/逐项判定/闭环验证",
          tabs is not None and tabs.count() == 3
          and any(tabs.tabText(i) == "闭环验证" for i in range(tabs.count())))
    view.deleteLater()
    app.processEvents()

    # 多光源：无热力图，含对比 tab
    png2 = sa.make_mono_png(corner_falloff=0.65)
    cfg = sa.mono_config(criteria={"ri_corner_min": 0.4, "lum_uniformity_min": 0.5})
    cfg["params"]["image_lights"] = {png.name: "D65", png2.name: "TL84"}
    multi = analyze_shading([png, png2], cfg)
    view2 = ShadingResultView(multi)
    check("多光源不显示热力图", view2._plot is None)
    tabs2 = view2.findChild(QTabWidget)
    check("多光源含对比 tab",
          tabs2 is not None
          and any(tabs2.tabText(i) == "多光源对比" for i in range(tabs2.count())))
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
