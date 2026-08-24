"""
M3.2 验证测试：MTF/SFR 频率单位（仿 Imatest Secondary Readout）。

测试内容：
[1/4] units 换算：6 种单位数值正确性 + 往返一致
[2/4] units 校验：缺像元尺寸 / 像高 / 未知单位 → 明确报错
[3/4] 适配器端到端：LP/mm、LW/PH 配置与 cy/px 基准结果一致
[4/4] 面板联动：切换单位实时换算 + config 往返 + 像高自动回填

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m3_2.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path

# 测试与用户保存的 Read Raw 全局设置隔离（~/.leopardiqlts），保证结果可复现
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from test_m3_1 import make_mono_chart_file, top_edge_rois  # noqa: E402

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


# ----------------------------------------------------------------------
# [1/4] units 换算
# ----------------------------------------------------------------------
def test_units_conversion():
    print("[1/4] units 换算数值与往返")
    from leopardiq.mtf import (
        FREQ_UNITS,
        cy_px_to_unit,
        unit_label,
        unit_scale,
        unit_to_cy_px,
    )

    check("6 种单位", FREQ_UNITS == [
        "Cycles/pixel", "Cycles/mm", "LP/mm", "L/mm", "LP/PH", "LW/PH",
    ])
    # 基准：像元 2.0 µm → 500 px/mm；像高 1000 px
    check("Cycles/pixel 倍率 1",
          unit_scale("Cycles/pixel", 2.0, 1000) == 1.0)
    check("Cycles/mm 倍率 500",
          unit_scale("Cycles/mm", 2.0, 1000) == 500.0)
    check("LP/mm 与 Cycles/mm 同值",
          unit_scale("LP/mm", 2.0, 1000) == 500.0)
    check("L/mm = 2 × LP/mm",
          unit_scale("L/mm", 2.0, 1000) == 1000.0)
    check("LP/PH 倍率 = 像高",
          unit_scale("LP/PH", 2.0, 1000) == 1000.0)
    check("LW/PH = 2 × LP/PH",
          unit_scale("LW/PH", 2.0, 1000) == 2000.0)

    # 0.25 cy/px（Nyquist/2）的期望值
    check("0.25 cy/px → 125 LP/mm",
          cy_px_to_unit(0.25, "LP/mm", 2.0, 1000) == 125.0)
    check("0.25 cy/px → 500 LW/PH",
          cy_px_to_unit(0.25, "LW/PH", 2.0, 1000) == 500.0)
    check("125 LP/mm → 0.25 cy/px",
          unit_to_cy_px(125.0, "LP/mm", 2.0, 1000) == 0.25)

    # 全单位往返一致（标量 + 数组）
    freqs = np.array([0.05, 0.125, 0.25, 0.5])
    roundtrip_ok = True
    for unit in FREQ_UNITS:
        back = unit_to_cy_px(cy_px_to_unit(freqs, unit, 2.0, 1000),
                             unit, 2.0, 1000)
        if not np.allclose(back, freqs, rtol=1e-12):
            roundtrip_ok = False
    check("6 种单位数组往返一致", roundtrip_ok)

    check("单位短标签",
          unit_label("Cycles/pixel") == "cy/px"
          and unit_label("LW/PH") == "LW/PH")


# ----------------------------------------------------------------------
# [2/4] units 校验
# ----------------------------------------------------------------------
def test_units_validation():
    print("[2/4] units 参数校验")
    from leopardiq.mtf import needs_picture_height, needs_pixel_pitch, unit_scale

    check("LP/mm 需要像元尺寸", needs_pixel_pitch("LP/mm"))
    check("L/mm 需要像元尺寸", needs_pixel_pitch("L/mm"))
    check("LW/PH 需要像高", needs_picture_height("LW/PH"))
    check("Cycles/pixel 无需附加参数",
          not needs_pixel_pitch("Cycles/pixel")
          and not needs_picture_height("Cycles/pixel"))

    for unit, kwargs, kw in (
        ("LP/mm", {"pixel_size_um": 0, "picture_height": 1000}, "像元尺寸"),
        ("L/mm", {"pixel_size_um": None, "picture_height": 1000}, "像元尺寸"),
        ("LW/PH", {"pixel_size_um": 2.0, "picture_height": 0}, "像高"),
        ("LP/PH", {"pixel_size_um": 2.0, "picture_height": None}, "像高"),
    ):
        try:
            unit_scale(unit, **kwargs)
        except ValueError as e:
            check(f"{unit} 缺参数 → ValueError", kw in str(e), str(e)[:36])
        else:
            check(f"{unit} 缺参数 → ValueError", False, "未抛出")

    try:
        unit_scale("CPI", 2.0, 1000)
    except ValueError as e:
        check("未知单位 → ValueError", "未知" in str(e))
    else:
        check("未知单位 → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [3/4] 适配器端到端
# ----------------------------------------------------------------------
def _run(config, path):
    from iqtest.analysis.mtf_adapter import analyze_mtf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_mtf([path], config)


def test_adapter_units():
    print("[3/4] 适配器：LP/mm、LW/PH 与 cy/px 基准一致")
    path = make_mono_chart_file()
    rois = [{"image": path.name, "rect": r} for r in top_edge_rois()]

    base = _run({
        "params": {"cfa": "Y", "freq1": 0.125, "rois": rois},
        "criteria": {"readout1_min": 0.05, "sfr_main_min": 0.1},
    }, path)
    check("cy/px 基准 PASS", base["pass"])
    check("基准 details 默认单位 Cycles/pixel",
          base["details"]["freq_unit"] == "Cycles/pixel"
          and base["details"]["unit_scale"] == 1.0)

    # LP/mm：像元 2.0 µm → 500 px/mm；0.125→62.5、readout1_min 0.05→25
    lpmm = _run({
        "params": {
            "cfa": "Y", "freq_unit": "LP/mm", "pixel_size_um": 2.0,
            "freq1": 62.5, "rois": rois,
        },
        "criteria": {"readout1_min": 25.0, "sfr_main_min": 0.1},
    }, path)
    check("LP/mm 结果与 cy/px 完全一致",
          lpmm["metrics"] == base["metrics"] and lpmm["pass"] == base["pass"])
    check("LP/mm details 携带单位信息",
          lpmm["details"]["freq_unit"] == "LP/mm"
          and lpmm["details"]["unit_scale"] == 500.0
          and lpmm["details"]["frequency"] == [0.125])

    # LW/PH：像高 800（测试图高）→ 0.125→200、readout1_min 0.05→80
    lwph = _run({
        "params": {
            "cfa": "Y", "freq_unit": "LW/PH", "picture_height": 800,
            "freq1": 200.0, "rois": rois,
        },
        "criteria": {"readout1_min": 80.0, "sfr_main_min": 0.1},
    }, path)
    check("LW/PH 结果与 cy/px 完全一致",
          lwph["metrics"] == base["metrics"] and lwph["pass"] == base["pass"])

    # 单位下频率超界 → 明确报错（600 LP/mm = 1.2 cy/px > 1.0）
    try:
        _run({
            "params": {
                "cfa": "Y", "freq_unit": "LP/mm", "pixel_size_um": 2.0,
                "freq1": 600.0, "rois": rois,
            },
            "criteria": {},
        }, path)
    except ValueError as e:
        check("单位换算后频率非法 → ValueError",
              "频率" in str(e) and "cy/px" in str(e), str(e)[:48])
    else:
        check("单位换算后频率非法 → ValueError", False, "未抛出")

    # LP/mm 缺像元尺寸 → 明确报错
    try:
        _run({
            "params": {
                "cfa": "Y", "freq_unit": "LP/mm", "pixel_size_um": 0,
                "freq1": 62.5, "rois": rois,
            },
            "criteria": {},
        }, path)
    except ValueError as e:
        check("LP/mm 缺像元尺寸 → ValueError", "像元尺寸" in str(e))
    else:
        check("LP/mm 缺像元尺寸 → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [4/4] 面板联动
# ----------------------------------------------------------------------
def test_panel_unit_switch():
    print("[4/4] 面板：单位切换实时换算 + config 往返")
    from PySide6.QtWidgets import QApplication

    from iqtest.panels.mtf_panel import MtfPanel

    app = QApplication.instance() or QApplication([])
    del app

    panel = MtfPanel(session=None)
    panel.params_form.set_values({
        "freq1": 0.125,
        "pixel_size_um": 2.0, "picture_height": 1000,
    })
    panel.criteria_form.set_values({"readout1_min": 0.10})

    combo = panel.params_form.widget("freq_unit")
    check("默认单位 Cycles/pixel", combo.currentText() == "Cycles/pixel")

    combo.setCurrentText("LP/mm")
    vals = panel.params_form.values()
    check("切换 LP/mm：freq1 0.125 → 62.5", vals["freq1"] == 62.5,
          f"got {vals['freq1']}")
    check("切换 LP/mm：readout1_min 0.10 → 50",
          panel.criteria_form.values()["readout1_min"] == 50.0)

    cfg = panel.config()
    check("config 按所选单位存储",
          cfg["params"]["freq_unit"] == "LP/mm"
          and cfg["params"]["freq1"] == 62.5)

    # config 往返：回填不做二次换算，显示状态同步
    panel2 = MtfPanel(session=None)
    panel2.set_config(cfg)
    vals2 = panel2.params_form.values()
    check("set_config 往返数值一致",
          vals2["freq1"] == 62.5 and vals2["freq_unit"] == "LP/mm")
    check("set_config 往返 criteria 一致",
          panel2.criteria_form.values()["readout1_min"] == 50.0)

    # 切回 Cycles/pixel 数值复原
    panel2.params_form.widget("freq_unit").setCurrentText("Cycles/pixel")
    vals3 = panel2.params_form.values()
    check("切回 cy/px 数值复原",
          abs(vals3["freq1"] - 0.125) < 1e-9,
          f"got {vals3['freq1']}")

    # LW/PH：像高 1000 → 0.125 cy/px = 250 LW/PH
    panel2.params_form.widget("freq_unit").setCurrentText("LW/PH")
    check("切换 LW/PH：freq1 0.125 → 250",
          panel2.params_form.values()["freq1"] == 250.0)

    # 默认 schema 含新键，criteria 键不变
    defaults = MtfPanel.default_config()
    check("默认 params 含单位/像元/像高键",
          {"freq_unit", "pixel_size_um", "picture_height"}
          <= set(defaults["params"]))
    check("默认 criteria 键不变",
          set(defaults["criteria"]) == {"readout1_min", "sfr_main_min"})


def main():
    print("=" * 60)
    print("M3.2 验证测试：MTF 频率单位（Secondary Readout 风格）")
    print("=" * 60)

    test_units_conversion()
    test_units_validation()
    test_adapter_units()
    test_panel_unit_switch()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
