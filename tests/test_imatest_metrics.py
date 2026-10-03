"""
Imatest 口径 Lens Shading 结果集测试（leopardiq/shading/imatest_metrics.py）。

覆盖：角区/边区区域均值、cos⁴ 衰减趋势、文本块格式、Color 比值与 corner/center、
mono 降级、NaN 鲁棒性、统一入口。

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_imatest_metrics.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leopardiq.shading.imatest_metrics import (  # noqa: E402
    _block_grid,
    _region_mean,
    compute_imatest_color_metrics,
    compute_imatest_luma_metrics,
    compute_imatest_metrics,
)

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


def _uniform_mono(nx=8, ny=8, base=65535.0):
    return np.full((ny, nx, 1), base, dtype=np.float64)


def _cos4_bin_means(ny, nx, full_scale, center_ratio=0.8):
    """在 block 网格上构造 cos⁴ 径向衰减（角落 θ=45° → cos⁴=0.25）。"""
    means = np.zeros((ny, nx, 1), dtype=np.float64)
    cx, cy = (nx - 1) / 2.0, (ny - 1) / 2.0
    rmax = np.sqrt(cx ** 2 + cy ** 2)
    for i in range(ny):
        for j in range(nx):
            r = np.sqrt((j - cx) ** 2 + (i - cy) ** 2)
            theta = np.arctan(r / rmax)
            means[i, j, 0] = center_ratio * full_scale * np.cos(theta) ** 4
    return means


def test_luma_region_accuracy():
    print("[1/7] Luma 角区/边区区域均值精度")
    full_scale = 65535.0
    bin_means = _uniform_mono(nx=8, ny=8, base=full_scale)
    # UL 角区（block[0:2, 0:2]）设为 0.25×满量程
    bin_means[0:2, 0:2, 0] = full_scale * 0.25

    luma = compute_imatest_luma_metrics(
        bin_means, ["Y"], width=128, height=128, full_scale=full_scale, bin_size=16
    )
    corners = luma["corners"]
    check("UL 角区 mean ≈ 0.25", abs(corners["UL"] - 0.25) < 1e-9, f"{corners['UL']}")
    check("UR 角区 mean ≈ 1.0", abs(corners["UR"] - 1.0) < 1e-9, f"{corners['UR']}")
    check("LL 角区 mean ≈ 1.0", abs(corners["LL"] - 1.0) < 1e-9, f"{corners['LL']}")
    check("LR 角区 mean ≈ 1.0", abs(corners["LR"] - 1.0) < 1e-9, f"{corners['LR']}")
    check("corners.worst = 0.25", abs(corners["worst"] - 0.25) < 1e-9, f"{corners['worst']}")
    check("corners.mean = 0.8125",
          abs(corners["mean"] - 0.8125) < 1e-9, f"{corners['mean']}")
    check("max_rel = 1.0", abs(luma["max_rel"] - 1.0) < 1e-9, f"{luma['max_rel']}")


def test_luma_cos4_trend():
    print("[2/7] Luma cos⁴ 衰减趋势")
    full_scale = 65535.0
    bin_means = _cos4_bin_means(ny=16, nx=16, full_scale=full_scale, center_ratio=0.8)
    luma = compute_imatest_luma_metrics(
        bin_means, ["Y"], width=512, height=512, full_scale=full_scale, bin_size=32
    )
    check("Max ≈ 0.8（中心 0.8×满量程）",
          abs(luma["max_rel"] - 0.8) < 0.02, f"{luma['max_rel']:.4f}")
    check("角区 mean < Max（暗角存在）",
          luma["corners"]["mean"] < luma["max_rel"],
          f"{luma['corners']['mean']:.4f} < {luma['max_rel']:.4f}")
    check("角区 mean > 0（有效衰减）", luma["corners"]["mean"] > 0.1,
          f"{luma['corners']['mean']:.4f}")
    check("norm_map 中心 ≈ 1", abs(float(np.nanmax(luma["norm_map"])) - 1.0) < 1e-9)
    check("角区 worst < 角区 mean（四角存在差异）",
          luma["corners"]["worst"] <= luma["corners"]["mean"])


def test_luma_text_format():
    print("[3/7] Luma 文本块格式")
    full_scale = 65535.0
    bin_means = _uniform_mono(nx=8, ny=8, base=full_scale * 0.5)
    luma = compute_imatest_luma_metrics(
        bin_means, ["Y"], width=128, height=128, full_scale=full_scale, bin_size=16
    )
    text = luma["text_block"]
    lines = text.splitlines()
    check("文本块 5 行", len(lines) == 5, f"{len(lines)}")
    check("首行 Max =", lines[0].startswith("Max = "), lines[0])
    check("次行 Corners:", lines[1].startswith("Corners: "), lines[1])
    check("三行 Sides:", lines[2].startswith("Sides: "), lines[2])
    check("四行 L R T B =", lines[3].startswith("L R T B = "), lines[3])
    check("末行 UL LL UR LR =", lines[4].startswith("UL LL UR LR = "), lines[4])


def test_color_metrics():
    print("[4/7] Color Shading 比值与 corner/center")
    cfa = ["R", "Gr", "Gb", "B"]
    bin_means = np.zeros((8, 8, 4), dtype=np.float64)
    # 通道：idx0=R, idx1=Gr, idx2=Gb, idx3=B
    bin_means[:, :, 0] = 200.0  # R
    bin_means[:, :, 1] = 100.0  # Gr
    bin_means[:, :, 2] = 100.0  # Gb
    bin_means[:, :, 3] = 100.0  # B
    bin_means[0:2, 0:2, 0] = 150.0  # R 在 UL 角区偏低 → R/G 偏低

    color = compute_imatest_color_metrics(
        bin_means, cfa, width=128, height=128, bin_size=16
    )
    check("Bayer 返回非 None", color is not None)
    check("rg/bg 均含 max/min",
          "max" in color["rg"] and "min" in color["rg"]
          and "max" in color["bg"] and "min" in color["bg"])
    check("rg 九点含 C（中心）", "C" in color["rg"] and "L" in color["rg"])
    check("corner_center 含三比值",
          set(color["corner_center"]) == {"r_b", "r_g", "b_g"})
    check("R/G 角落低于中心（corner_center.r_g < 1）",
          color["corner_center"]["r_g"] < 1.0, f"{color['corner_center']['r_g']:.4f}")
    text = color["text_block"]
    check("text 含 R/G Pixel ratio", "R/G Pixel ratio" in text)
    check("text 含 B/G Pixel ratio", "B/G Pixel ratio" in text)
    check("text 含 Minimum corner", "Minimum corner / center" in text)


def test_mono_degrade():
    print("[5/7] mono 降级（无 Color 指标）")
    bin_means = _uniform_mono(nx=8, ny=8, base=32768.0)
    color = compute_imatest_color_metrics(
        bin_means, ["Y"], width=128, height=128, bin_size=16
    )
    check("mono 时 color 返回 None", color is None)


def test_nan_robustness():
    print("[6/7] NaN 鲁棒性")
    full_scale = 65535.0
    bin_means = _uniform_mono(nx=8, ny=8, base=full_scale)
    bin_means[4:6, 4:6, 0] = np.nan  # 中心区域 NaN
    luma = compute_imatest_luma_metrics(
        bin_means, ["Y"], width=128, height=128, full_scale=full_scale, bin_size=16
    )
    check("含 NaN 不崩溃且 max_rel 有限",
          np.isfinite(luma["max_rel"]) and luma["max_rel"] > 0,
          f"{luma['max_rel']}")
    check("角区仍可计算（无 NaN 区域）",
          np.isfinite(luma["corners"]["mean"]), f"{luma['corners']['mean']}")


def test_unified_entry():
    print("[7/7] 统一入口 compute_imatest_metrics")
    full_scale = 65535.0
    bin_means = _uniform_mono(nx=8, ny=8, base=full_scale)
    out = compute_imatest_metrics(
        bin_means, ["Y"], width=128, height=128, full_scale=full_scale, bin_size=16
    )
    check("返回含 luma", "luma" in out and out["luma"] is not None)
    check("返回含 color（mono 为 None）", "color" in out and out["color"] is None)
    check("luma.text_block 存在", "text_block" in out["luma"])


def main():
    test_luma_region_accuracy()
    test_luma_cos4_trend()
    test_luma_text_format()
    test_color_metrics()
    test_mono_degrade()
    test_nan_robustness()
    test_unified_entry()
    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
