"""
Phase 2.2 + 2.3 验证测试：Lens Shading 与 Color 比例模块。

测试内容：
[1/5] 模块导入
[2/5] 平场掩膜与 bin 均值（create_flat_field_mask / bin_image_means）
[3/5] 相对照度分析（analyze_lens_shading / analyze_relative_illumination）
[4/5] LSC 校正（apply_lsc）
[5/5] Color 比例与多光源（color_uniformity / analyze_multi_light）

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_phase2_2.py
"""

import sys
from pathlib import Path

import numpy as np

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


CFA = ["Gr", "R", "B", "Gb"]


def make_flat_field(h=64, w=64, corner_falloff=0.7):
    """合成平场图：中心亮、四角按径向衰减（模拟 shading），含噪声。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cx, cy = w / 2, h / 2
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r_max = np.sqrt(cx ** 2 + cy ** 2)
    falloff = 1.0 - (1.0 - corner_falloff) * (r / r_max) ** 2

    # Bayer 四通道，G 略亮（模拟真实 sensor）
    rng = np.random.default_rng(7)
    img = np.zeros((h, w, 4))
    base = {"Gr": 210.0, "R": 200.0, "B": 190.0, "Gb": 208.0}
    for i, ch in enumerate(CFA):
        img[:, :, i] = base[ch] * falloff + rng.normal(0, 0.5, (h, w))
    return img


def test_imports():
    print("[1/5] 模块导入")
    from leopardiq.shading import (  # noqa: F401
        analyze_color_uniformity,
        analyze_lens_shading,
        analyze_multi_light,
        analyze_relative_illumination,
        apply_lsc,
        bin_image_means,
        calculate_channel_shift,
        compute_channel_ratios,
        compute_color_shading,
        compute_quadrant_ri,
        compute_wb_gains,
        create_flat_field_mask,
        interp_shading_profile,
    )

    check("leopardiq.shading 全部导入成功", True)


def test_mask_and_binning():
    print("[2/5] 平场掩膜与 bin 均值")
    from leopardiq.shading import bin_image_means, create_flat_field_mask

    img = make_flat_field()
    mask = create_flat_field_mask(img, thresh=100, gr_index=0)
    check("掩膜为 uint8 二值图", mask.dtype == np.uint8
          and set(np.unique(mask)) <= {0, 1})
    check("掩膜保留中心区域", mask[32, 32] == 1)

    mask_all = create_flat_field_mask(img, thresh=0, gr_index=0)
    check("thresh=0 时全 1 掩膜", mask_all.sum() == 64 * 64)

    axisx = np.array(range(0, 64, 16))
    axisy = np.array(range(0, 64, 16))
    means = bin_image_means(axisx, axisy, 16, img, mask_all)
    check("bin 均值形状 (4,4,4)", means.shape == (4, 4, 4))
    # 左上角 bin 的均值应低于中心 bin（shading 衰减）
    check("角落 bin 均值 < 中心 bin",
          means[0, 0, 0] < means[2, 2, 0],
          f"{means[0, 0, 0]:.1f} < {means[2, 2, 0]:.1f}")


def test_relative_illumination():
    print("[3/5] 相对照度分析")
    from leopardiq.shading import analyze_lens_shading, analyze_relative_illumination

    img = make_flat_field(corner_falloff=0.7)
    result = analyze_lens_shading(img, bin_size=16, thresh=0, cfa=CFA)
    check("返回四象限 RI", all(
        k in result for k in ("ri_tl", "ri_tr", "ri_bl", "ri_br")))
    ri_vals = [float(np.atleast_1d(result[k])[0])
               for k in ("ri_tl", "ri_tr", "ri_bl", "ri_br")]
    # bin 网格采样到的最远角落衰减约 0.77（falloff=1-0.3*(r/rmax)^2）
    check("RI 反映角落衰减（0.7~0.95）",
          all(0.7 < v < 0.95 for v in ri_vals),
          f"{[f'{v:.3f}' for v in ri_vals]}")
    check("shading_profile 分辨率一致",
          result["shading_profile"].shape == (64, 64, 4))
    check("color shift 已计算",
          result["green_red_shift"] is not None
          and result["green_blue_shift"] is not None)
    check("G/R shift 较小（均匀场）",
          result["green_red_shift"] < 0.2,
          f"{result['green_red_shift']:.4f}")

    # 标准接口 + criteria
    config = {
        "cfa": CFA, "bin_size": 16, "thresh": 0,
        "criteria": {"ri": 0.6, "ri_diff": 0.2},
    }
    std = analyze_relative_illumination(img, config)
    check("标准接口返回结构", all(k in std for k in ("metrics", "pass", "details")))
    check("RI >= 0.6 判定 PASS", std["pass"])

    config["criteria"]["ri"] = 0.9  # 不可能达到的阈值
    std_fail = analyze_relative_illumination(img, config)
    check("RI >= 0.9 判定 FAIL", not std_fail["pass"])


def test_lsc():
    print("[4/5] LSC 校正")
    from leopardiq.shading import analyze_lens_shading, apply_lsc

    img = make_flat_field(corner_falloff=0.7)
    result = analyze_lens_shading(img, bin_size=16, thresh=0, cfa=CFA)
    corrected = apply_lsc(img, result["shading_profile"])
    check("校正后形状一致", corrected.shape == img.shape)

    # 校正后角落与中心亮度应接近
    center_before = img[28:36, 28:36, 0].mean()
    corner_before = img[2:10, 2:10, 0].mean()
    center_after = corrected[28:36, 28:36, 0].mean()
    corner_after = corrected[2:10, 2:10, 0].mean()
    ratio_before = corner_before / center_before
    ratio_after = corner_after / center_after
    check("校正后角落/中心比值更接近 1",
          abs(1 - ratio_after) < abs(1 - ratio_before),
          f"before={ratio_before:.3f} after={ratio_after:.3f}")

    try:
        apply_lsc(img, result["shading_profile"][:32])
        check("分辨率不匹配抛异常", False)
    except ValueError:
        check("分辨率不匹配抛异常", True)


def test_color_uniformity_and_multi_light():
    print("[5/5] Color 比例与多光源")
    from leopardiq.shading import (
        analyze_color_uniformity,
        analyze_multi_light,
        compute_channel_ratios,
        compute_color_shading,
        compute_wb_gains,
    )

    img = make_flat_field()
    ratios = compute_channel_ratios(img, CFA)
    # 全场平均衰减 ≈ 0.90（E[(r/rmax)^2] ≈ 1/3），Gr≈210*0.90=189, B≈190*0.90=171
    check("四通道均值正确",
          abs(ratios["means"]["Gr"] - 189) < 3
          and abs(ratios["means"]["B"] - 171) < 3,
          f"Gr={ratios['means']['Gr']:.1f} B={ratios['means']['B']:.1f}")
    check("比例和为 1", abs(sum(ratios["ratios"].values()) - 1.0) < 1e-9)

    wb = compute_wb_gains(img, CFA)
    check("r_gain ≈ G/R",
          abs(wb["r_gain"] - 209 / 200) < 0.02, f"{wb['r_gain']:.4f}")

    shading = compute_color_shading(img, CFA, bin_size=16)
    check("均匀场 color shift < 0.2",
          shading["green_red_shift"] < 0.2
          and shading["green_blue_shift"] < 0.2,
          f"gr={shading['green_red_shift']:.4f} gb={shading['green_blue_shift']:.4f}")

    config = {"cfa": CFA, "bin_size": 16,
              "criteria": {"green_red_shift": 0.2, "green_blue_shift": 0.2,
                           "r_gain": [0.9, 1.2], "b_gain": [0.9, 1.3]}}
    std = analyze_color_uniformity(img, config)
    check("Color 标准接口 PASS", std["pass"],
          str({k: v["status"] for k, v in std["metrics"].items()}))

    # 多光源：两个不同衰减的"光源"
    img_d65 = make_flat_field(corner_falloff=0.7)
    img_tl84 = make_flat_field(corner_falloff=0.6)
    ri_config = {"cfa": CFA, "bin_size": 16, "thresh": 0,
                 "criteria": {"ri": 0.5}}
    multi = analyze_multi_light({"D65": img_d65, "TL84": img_tl84}, ri_config)
    check("多光源返回两个结果", set(multi["lights"].keys()) == {"D65", "TL84"})
    check("多光源整体 PASS", multi["pass"])
    check("ri_spread 已计算", "ri_spread" in multi["comparison"],
          f"{multi['comparison']['ri_spread']:.4f}")


def main():
    print("=" * 60)
    print("Phase 2.2 + 2.3 验证测试：Lens Shading / Color 比例")
    print("=" * 60)

    test_imports()
    test_mask_and_binning()
    test_relative_illumination()
    test_lsc()
    test_color_uniformity_and_multi_light()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
