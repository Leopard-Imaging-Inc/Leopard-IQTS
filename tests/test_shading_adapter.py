"""
M3 Lens Shading 适配器验证测试（iqtest/analysis/shading_adapter.py + shading_export.py）。

测试内容：
[1/5] CFA 映射与 criteria 映射
[2/5] mono 单光源：analyze_shading 与算法接口对拍（1e-6）、PASS/FAIL
[3/5] Bayer RAW 单光源：拆分/通道序正确、逐通道 RI、Color Shading
[4/5] 闭环验证（apply_lsc 残余）+ 多光源（ri_spread / color_shift_spread）
[5/5] 导出：shading_profile npy/CSV/PNG + 结果 CSV

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_shading_adapter.py
"""

import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = Path(__file__).resolve().parent / "_shading_smoke"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Read Raw 全局设置隔离到工作区内，保证可写、可复现
os.environ.setdefault("LEOPARDIQTS_CONFIG_DIR", str(OUT_DIR / "config"))


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def radial_falloff(h, w, corner_falloff=0.7):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cx, cy = w / 2.0, h / 2.0
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    rmax = np.sqrt(cx ** 2 + cy ** 2)
    return 1.0 - (1.0 - corner_falloff) * (r / rmax) ** 2


def make_mono_png(h=128, w=128, corner_falloff=0.7, base=50000.0) -> Path:
    img = base * radial_falloff(h, w, corner_falloff)
    p = OUT_DIR / f"flat_{corner_falloff}.png"
    cv2.imwrite(str(p), np.clip(img, 0, 65535).astype(np.uint16))
    return p


def make_bayer_raw(h=128, w=128, corner_falloff=0.7) -> Path:
    """RGGB mosaic（R@TL）合成平场，uint16 little-endian。"""
    falloff = radial_falloff(h, w, corner_falloff)
    mosaic = np.zeros((h, w), dtype=np.uint16)
    mosaic[0::2, 0::2] = np.clip(200.0 * falloff[0::2, 0::2], 0, 65535)  # R
    mosaic[0::2, 1::2] = np.clip(210.0 * falloff[0::2, 1::2], 0, 65535)  # Gr
    mosaic[1::2, 0::2] = np.clip(208.0 * falloff[1::2, 0::2], 0, 65535)  # Gb
    mosaic[1::2, 1::2] = np.clip(190.0 * falloff[1::2, 1::2], 0, 65535)  # B
    p = OUT_DIR / f"flat_{corner_falloff}.raw"
    mosaic.tofile(str(p))
    return p


def save_read_raw(cfa="RGGB", width=128, height=128):
    from iqtest.config.read_raw_settings import save_read_raw_params

    save_read_raw_params({
        "width": width, "height": height, "bit_depth": "16",
        "cfa": cfa, "demosaic": False, "gray_method": "BT709",
    })


def mono_config(corner_falloff=0.7, criteria=None):
    return {
        "params": {
            "light_source": "D65", "luminance_channel": "Y",
            "grid_size": 16, "thresh": 0.0,
            "support_extrapolation": False, "enable_lsc_verify": True,
        },
        "criteria": criteria or {"ri_corner_min": 0.6, "lum_uniformity_min": 0.7},
    }


# ----------------------------------------------------------------------
def test_cfa_and_criteria_mapping():
    print("[1/5] CFA 映射与 criteria 映射")
    from iqtest.analysis.shading_adapter import (
        CFA_TO_CHANNEL_ORDER,
        _criteria_from_panel,
    )

    check("RGGB → [R,Gr,Gb,B]", CFA_TO_CHANNEL_ORDER["RGGB"] == ["R", "Gr", "Gb", "B"])
    check("BGGR → [B,Gb,Gr,R]", CFA_TO_CHANNEL_ORDER["BGGR"] == ["B", "Gb", "Gr", "R"])
    check("GRBG → [Gr,R,B,Gb]", CFA_TO_CHANNEL_ORDER["GRBG"] == ["Gr", "R", "B", "Gb"])
    check("GBRG → [Gb,B,R,Gr]", CFA_TO_CHANNEL_ORDER["GBRG"] == ["Gb", "B", "R", "Gr"])

    crit = _criteria_from_panel({
        "ri_corner_min": 0.7, "lum_uniformity_min": 0.8,
        "green_red_shift_max": 0.2, "green_blue_shift_max": 0.15,
    })
    check("ri_corner_min → ri", crit["ri"] == 0.7)
    check("lum_uniformity_min → ri_diff=1-均匀性", abs(crit["ri_diff"] - 0.2) < 1e-12,
          f"{crit['ri_diff']}")
    check("green_red_shift_max → green_red_shift", crit["green_red_shift"] == 0.2)
    check("green_blue_shift_max → green_blue_shift", crit["green_blue_shift"] == 0.15)


def test_mono_single():
    print("[2/5] mono 单光源：对拍 + PASS/FAIL")
    from iqtest.analysis.shading_adapter import (
        _criteria_from_panel,
        analyze_shading,
        load_shading_image,
    )
    from leopardiq.shading import analyze_relative_illumination

    png = make_mono_png(corner_falloff=0.7)
    config = mono_config()
    params = config["params"]

    img, cfa = load_shading_image(png, params)
    check("mono 图像 cfa=['Y']", cfa == ["Y"] and img.shape == (128, 128))

    alg_config = {
        "cfa": cfa, "bin_size": 16, "thresh": 0.0,
        "support_extrapolation": False,
        "criteria": _criteria_from_panel(config["criteria"]),
    }
    direct = analyze_relative_illumination(img, alg_config)
    result = analyze_shading([png], config)

    check("单光源 mode", result["details"]["mode"] == "single")
    check("与算法接口对拍（1e-6）", all(
        np.allclose(result["metrics"][k]["value"], direct["metrics"][k]["value"],
                    atol=1e-6)
        for k in direct["metrics"]
    ))
    check("整体 PASS", result["pass"] is True)

    report = result["details"]["report"]
    check("report 通道 Y 网格存在", report["shading_map"].shape == (8, 8))
    check("report 四象限 RI 有值", all(k in report["ri"] for k in ("tl", "tr", "bl", "br")))

    # 更严格 criteria → FAIL
    config_fail = mono_config(criteria={"ri_corner_min": 0.95, "lum_uniformity_min": 0.9})
    fail = analyze_shading([png], config_fail)
    check("严格 criteria → FAIL", fail["pass"] is False)


def test_bayer_single():
    print("[3/5] Bayer RAW 单光源：通道序 / 逐通道 RI / Color Shading")
    from iqtest.analysis.shading_adapter import (
        _criteria_from_panel,
        analyze_shading,
        load_shading_image,
    )
    from leopardiq.shading import analyze_relative_illumination

    save_read_raw(cfa="RGGB", width=128, height=128)
    raw = make_bayer_raw(corner_falloff=0.7)
    config = mono_config(criteria={
        "ri_corner_min": 0.5, "lum_uniformity_min": 0.6,
        "green_red_shift_max": 0.5, "green_blue_shift_max": 0.5,
    })
    params = config["params"]

    img, cfa = load_shading_image(raw, params)
    check("Bayer 拆分 (64,64,4) + cfa 序", cfa == ["R", "Gr", "Gb", "B"]
          and img.shape == (64, 64, 4), f"{img.shape} {cfa}")

    alg_config = {
        "cfa": cfa, "bin_size": 16, "thresh": 0.0,
        "support_extrapolation": False,
        "criteria": _criteria_from_panel(config["criteria"]),
    }
    direct = analyze_relative_illumination(img, alg_config)
    result = analyze_shading([raw], config)

    check("与算法接口对拍（1e-6）", all(
        np.allclose(result["metrics"][k]["value"], direct["metrics"][k]["value"],
                    atol=1e-6)
        for k in direct["metrics"]
    ))
    check("含 Color Shading 指标",
          "green_red_shift" in result["metrics"]
          and "green_blue_shift" in result["metrics"])
    check("逐通道四象限 RI 存在",
          result["details"]["per_channel_ri"] is not None
          and len(result["details"]["per_channel_ri"]["tl"]) == 4)
    check("shading_profile 分辨率 (64,64,4)",
          result["details"]["shading_profile"].shape == (64, 64, 4))


def test_closed_loop_and_multi_light():
    print("[4/5] 闭环验证 + 多光源")
    from iqtest.analysis.shading_adapter import analyze_shading

    # 闭环验证：校正后残余 RI 应更接近 1（≥ 校正前）
    png = make_mono_png(corner_falloff=0.6)
    result = analyze_shading([png], mono_config())
    cl = result["details"]["closed_loop"]
    check("闭环验证存在且 enabled", cl is not None and cl.get("enabled") is True)
    check("校正后最差 RI ≥ 校正前", cl["after_ri_min"] >= cl["before_ri_min"] - 1e-9,
          f"{cl['before_ri_min']:.4f} → {cl['after_ri_min']:.4f}")
    check("残余判定 PASS", cl.get("residual_pass") is True)

    # 多光源（mono）：ri_spread 计算，color_shift_spread 为 None（mono 无 shift）
    png2 = make_mono_png(corner_falloff=0.55, base=50000.0)
    cfg = mono_config(criteria={"ri_corner_min": 0.4, "lum_uniformity_min": 0.5})
    cfg["params"]["image_lights"] = {png.name: "D65", png2.name: "TL84"}
    multi = analyze_shading([png, png2], cfg)
    check("多光源 mode", multi["details"]["mode"] == "multi")
    check("ri_spread 存在", "ri_spread" in multi["details"]["comparison"])
    check("mono 无 color_shift_spread",
          multi["details"]["comparison"]["color_shift_spread"] is None)

    # 多光源（Bayer）：color_shift_spread 计算
    save_read_raw(cfa="RGGB", width=128, height=128)
    raw_a = make_bayer_raw(corner_falloff=0.7)
    raw_b = make_bayer_raw(corner_falloff=0.6)
    cfg2 = mono_config(criteria={
        "ri_corner_min": 0.4, "lum_uniformity_min": 0.5,
        "green_red_shift_max": 0.5, "green_blue_shift_max": 0.5,
    })
    cfg2["params"]["image_lights"] = {raw_a.name: "D65", raw_b.name: "TL84"}
    multi2 = analyze_shading([raw_a, raw_b], cfg2)
    spread = multi2["details"]["comparison"]["color_shift_spread"]
    check("Bayer 多光源 color_shift_spread 存在",
          spread is not None and spread["green_red"] >= 0 and spread["green_blue"] >= 0,
          str(spread))


def test_export():
    print("[5/5] 导出：npy / CSV / PNG / 结果 CSV")
    from iqtest.analysis.shading_adapter import analyze_shading
    from iqtest.analysis.shading_export import (
        result_to_csv,
        save_shading_profile_image,
        write_result_csv,
        write_shading_profile_csv,
        write_shading_profile_npy,
    )

    png = make_mono_png(corner_falloff=0.7)
    result = analyze_shading([png], mono_config())

    npy = write_shading_profile_npy(result["details"]["shading_profile"],
                                    OUT_DIR / "profile.npy")
    loaded = np.load(str(npy))
    check("npy 导出可读回", loaded.shape == (128, 128, 1))

    csv_path = write_shading_profile_csv(result, OUT_DIR / "profile.csv")
    check("profile CSV 存在且含表头", csv_path.exists()
          and "# LeopardIQ Lens Shading" in csv_path.read_text(encoding="utf-8-sig"))

    img_path = save_shading_profile_image(result["details"]["report"]["shading_map"],
                                          OUT_DIR / "profile.png")
    check("PNG 导出", img_path.exists() and img_path.stat().st_size > 0)

    text = result_to_csv(result, label="测试")
    check("结果 CSV 含元数据与指标", "# label: 测试" in text and "ri_diff" in text)

    csv2 = write_result_csv(result, OUT_DIR / "result.csv", label="测试")
    check("结果 CSV 落盘", csv2.exists())


def main():
    print("=" * 60)
    print("M3 Lens Shading 适配器验证测试")
    print("=" * 60)
    test_cfa_and_criteria_mapping()
    test_mono_single()
    test_bayer_single()
    test_closed_loop_and_multi_light()
    test_export()
    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
