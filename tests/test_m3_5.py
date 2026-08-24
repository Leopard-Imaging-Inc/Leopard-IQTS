"""
M3.5 验证测试：MTF 引擎前置预检 + 适配器引擎去重 + peak_focus 健壮性。

参考 lf-1.6.5《Raw数据处理流程.md》引擎健壮性一节：无效 ROI（平坦 /
水平垂直边缘 / 纯噪声）送入 C++ sfrmat5 引擎轻则抛异常、重则段错误
（0xC0000005，Python 无法捕获）。本测试覆盖新增的防护措施：

[1/5] validate_edge_patch 单元：有效斜边通过；平坦 / 纯噪声 / 尺寸过小 /
      NaN / 伪边缘（孤立亮线，无法向阶跃）拒绝
[2/5] compute_mtf_array：噪声 ROI 返回 None（不崩溃）；有效斜边正常出曲线
[3/5] 适配器引擎去重对拍：analyze_mtf（每通道单次引擎调用 + 曲线插值）
      与 compute_roi_sfr 直接调用结果一致（容差 1e-6）
[4/5] 适配器噪声 ROI 端到端：不崩溃、ROI 无效、总判定 FAIL、指标为 0
[5/5] peak_focus 健壮性：引擎返回 None 时不再 TypeError 崩溃，
      全部无效时抛出明确 RuntimeError

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m3_5.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path

import cv2
import numpy as np

# 测试与用户保存的 Read Raw 全局设置隔离（~/.leopardiqlts），保证结果可复现
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = Path(__file__).resolve().parent / "_m3_smoke"


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


# ----------------------------------------------------------------------
# 合成数据
# ----------------------------------------------------------------------
def make_edge_patch(size: int = 64, slope: float = 0.3,
                    dark: float = 20.0, bright: float = 220.0) -> np.ndarray:
    """合成含一条斜边的 patch（半平面 + 高斯模糊模拟离焦）。"""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float64)
    patch = np.where(xx + slope * yy < size / 2, dark, bright)
    return cv2.GaussianBlur(patch, (3, 3), 0)


def make_chart_png() -> tuple[Path, list]:
    """合成 800×800 斜边标板 PNG（中心旋转黑方块）+ 上边斜边 ROI。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    h = w = 800
    image = np.full((h, w), 220.0, dtype=np.float64)
    square_px = 0.06 * np.hypot(h, w)  # ≈ 67.9
    rect = ((w / 2 + 0.5, h / 2 + 0.5), (square_px, square_px), 5.0)
    box = cv2.boxPoints(rect).astype(np.int32)
    cv2.fillPoly(image, [box], 20.0)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    path = OUT_DIR / "m3_5_chart.png"
    cv2.imwrite(str(path), np.clip(image, 0, 255).astype(np.uint8))
    cx, cy = w / 2 + 0.5, h / 2 + 0.5
    roi = [int(cx - square_px * 0.35), int(cy - square_px / 2 - 12),
           int(square_px * 0.7), 40]
    return path, [roi]


# ----------------------------------------------------------------------
# [1/5] validate_edge_patch 单元测试
# ----------------------------------------------------------------------
def test_validate_edge_patch():
    print("[1/5] validate_edge_patch 单元测试")
    from leopardiq.mtf import validate_edge_patch

    ok, _ = validate_edge_patch(make_edge_patch())
    check("有效斜边 patch 通过", ok)

    ok, _ = validate_edge_patch(make_edge_patch(slope=-2.5))
    check("陡斜边 patch 通过", ok)

    ok, reason = validate_edge_patch(np.full((64, 64), 128.0))
    check("平坦 patch 拒绝", not ok, reason)

    rng = np.random.default_rng(42)
    noise = rng.normal(128.0, 3.0, (64, 64))
    ok, reason = validate_edge_patch(noise)
    check("纯噪声 patch 拒绝（防段错误）", not ok, reason)

    ok, reason = validate_edge_patch(make_edge_patch(size=6))
    check("尺寸过小（6×6 < 8）拒绝", not ok, reason)

    nan_patch = make_edge_patch()
    nan_patch[10, 10] = np.nan
    ok, reason = validate_edge_patch(nan_patch)
    check("含 NaN 拒绝", not ok, reason)

    # 孤立亮线：相干性高但沿法向无阶跃（两端都是平坦区）→ 对比度检查拒绝
    line = np.full((64, 64), 100.0)
    line[:, 30:33] = 220.0
    line = cv2.GaussianBlur(line, (3, 3), 0)
    ok, reason = validate_edge_patch(line)
    check("孤立亮线（伪边缘）拒绝", not ok, reason)

    # 1D / 3D 输入拒绝
    ok, _ = validate_edge_patch(np.zeros((64,)))
    check("非 2D 输入拒绝", not ok)


# ----------------------------------------------------------------------
# [2/5] compute_mtf_array 预检集成
# ----------------------------------------------------------------------
def test_compute_mtf_array_guard():
    print("[2/5] compute_mtf_array 预检集成")
    from leopardiq.mtf import compute_mtf_array

    rng = np.random.default_rng(7)
    noise = rng.normal(128.0, 3.0, (64, 64))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mtf_array = compute_mtf_array(noise)
    check("噪声 ROI 返回 None（进程未崩溃）", mtf_array is None)

    mtf_array = compute_mtf_array(make_edge_patch())
    check("有效斜边正常返回 MTF 曲线",
          mtf_array is not None and mtf_array.shape[1] == 2)
    if mtf_array is not None:
        check("MTF 曲线频率从 0 开始且递增",
              mtf_array[0, 0] == 0.0
              and np.all(np.diff(mtf_array[:, 0]) > 0))


# ----------------------------------------------------------------------
# [3/5] 适配器引擎去重对拍（analyze_mtf vs compute_roi_sfr）
# ----------------------------------------------------------------------
def test_adapter_equivalence():
    print("[3/5] 适配器与 compute_roi_sfr 对拍")
    from iqtest.analysis.mtf_adapter import analyze_mtf
    from leopardiq.mtf import compute_mtf_array, compute_mtf_metrics, compute_roi_sfr

    png_path, rois = make_chart_png()
    x, y, w, h = rois[0]
    freq = np.array([0.125])

    # 参考口径：compute_roi_sfr 直接调用（与 Phase 2 脚本一致）
    img = cv2.imread(str(png_path), cv2.IMREAD_GRAYSCALE)
    img = img.astype(np.float32)[:, :, np.newaxis]
    patch = img[y:y + h, x:x + w, :]
    results_array = np.full((1, 1, 1), np.nan)
    valid_ref = compute_roi_sfr(patch, freq, 1, 0, results_array)
    sfr_ref = float(results_array[0, 0, 0])
    mtf_ref = compute_mtf_array(np.float64(np.squeeze(patch)))
    mtf50_ref = compute_mtf_metrics(mtf_ref, ("mtf50",))["mtf50"]

    # 新口径：analyze_mtf（每通道单次引擎调用 + 曲线插值）
    res = analyze_mtf(
        [str(png_path)],
        {
            "params": {
                "cfa": "Y",
                "freq1": 0.125,
                "rois": [{"image": png_path.name, "rect": rois[0]}],
            },
            "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0},
        },
    )
    sfr_new = res["metrics"]["ROI1_mtf@0.125"]["value"][0]
    mtf50_new = res["details"]["curves"][0]["mtf50"]

    check("参考 ROI 有效", valid_ref)
    check("SFR@0.125 一致（容差 1e-6）",
          abs(sfr_new - sfr_ref) < 1e-6, f"{sfr_new:.6f} vs {sfr_ref:.6f}")
    check("MTF50 一致（容差 1e-6）",
          abs(mtf50_new - mtf50_ref) < 1e-6, f"{mtf50_new:.6f} vs {mtf50_ref:.6f}")
    check("适配器判定有效且 PASS", res["pass"])


# ----------------------------------------------------------------------
# [4/5] 适配器噪声 ROI 端到端
# ----------------------------------------------------------------------
def test_adapter_noise_roi():
    print("[4/5] 适配器噪声 ROI 端到端")
    from iqtest.analysis.mtf_adapter import analyze_mtf

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(13)
    noise = rng.normal(128, 3, (200, 200))
    noise_path = OUT_DIR / "m3_5_noise.png"
    cv2.imwrite(str(noise_path), np.clip(noise, 0, 255).astype(np.uint8))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = analyze_mtf(
            [str(noise_path)],
            {
                "params": {
                    "cfa": "Y",
                    "freq1": 0.125,
                    "rois": [{"image": noise_path.name, "rect": [50, 50, 80, 80]}],
                },
                "criteria": {"readout1_min": 0.10, "sfr_main_min": 0.20},
            },
        )
    check("噪声 ROI 分析未崩溃", isinstance(res, dict))
    check("总判定 FAIL", not res["pass"])
    check("ROI 记录 invalid", res["details"]["rois"][0]["valid"] is False)
    check("SFR@0.125 = 0.0 且 FAIL",
          res["metrics"]["ROI1_mtf@0.125"]["value"] == [0.0]
          and res["metrics"]["ROI1_mtf@0.125"]["status"] == "FAIL")
    check("Readout1 = 0.0 且 FAIL",
          res["metrics"]["ROI1_readout1"]["value"] == [0.0]
          and res["metrics"]["ROI1_readout1"]["status"] == "FAIL")
    check("曲线记录 valid=False",
          res["details"]["curves"][0]["valid"] is False)


# ----------------------------------------------------------------------
# [5/5] peak_focus 健壮性（引擎失败不崩溃）
# ----------------------------------------------------------------------
def test_peak_focus_robustness():
    print("[5/5] peak_focus 引擎失败防护")
    import leopardiq.mtf.peak_focus as peak_focus_mod
    from leopardiq.mtf import analyze_peak_focus

    h = w = 400
    image = np.full((h, w), 220.0, dtype=np.float64)
    square_px = 0.25 * h
    rect = ((w / 2, h / 2), (square_px, square_px), 5.0)
    box = cv2.boxPoints(rect).astype(np.int32)
    cv2.fillPoly(image, [box], 20.0)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    # 质心检测按 8bit 灰度处理（image >= 255 截断），raw 直接写 0~255 量级
    raw = np.clip(image, 0, 255).astype(np.uint16)

    img_dir = Path(tempfile.mkdtemp(prefix="lqiq_pf_"))
    for dist in (50, 70):
        raw.tofile(str(img_dir / f"SN_pf_Di{dist}_test.raw"))

    config_sensor = {
        "peak_focus": {
            "params": {
                "test_distances": [50, 70],
                "min_patch_size": 10,
                "sub_patch_angles": [0, 90, 180, 270],
                "freqs": np.array([0.5]),
                "nyq_freq": 0.5,
            },
            "criteria": {"position": 50, "tolerance": 20},
        }
    }
    config_data = {"cfa": "Y", "width": w, "height": h, "black_level": 0}

    # 引擎全部失败（模拟预检拦截）：应抛明确 RuntimeError，而非 TypeError 崩溃
    original = peak_focus_mod.compute_mtf_array
    peak_focus_mod.compute_mtf_array = lambda *a, **k: None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                analyze_peak_focus(str(img_dir), config_sensor, config_data)
                raised = None
            except RuntimeError as exc:
                raised = exc
            except Exception as exc:  # noqa: BLE001
                raised = exc
    finally:
        peak_focus_mod.compute_mtf_array = original

    check("全部 patch 无效时抛 RuntimeError（非 TypeError 崩溃）",
          isinstance(raised, RuntimeError),
          type(raised).__name__ if raised else "未抛异常")

    # 真实引擎路径：合成图标板应正常完成（回归）
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = analyze_peak_focus(str(img_dir), config_sensor, config_data)
    check("真实引擎路径正常返回结果",
          isinstance(res, dict) and "peak_focus_position" in res["metrics"],
          str(res["metrics"].get("peak_focus_position", {}).get("value")))


def main():
    print("=" * 60)
    print("M3.5 验证测试：MTF 引擎预检 + 适配器去重 + peak_focus 健壮性")
    print("=" * 60)

    test_validate_edge_patch()
    test_compute_mtf_array_guard()
    test_adapter_equivalence()
    test_adapter_noise_roi()
    test_peak_focus_robustness()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
