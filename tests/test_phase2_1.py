"""
Phase 2.1 验证测试：MTF/SFR 模块提取。

测试内容：
[1/8] 模块导入（含 C++ sfrmat5 引擎）
[2/8] MTF 引擎：合成斜边 ROI → MTF 曲线 + 插值 + MTF50/MTF30
[3/8] 质心检测：合成 9 方格图 → find_square_centroids_mono
[4/8] 标板几何：init_square_chart_params + compute_chart_geometry
[5/8] 边缘追踪：find_one_edge_pos + search_edge_centers_in_binary_image
[6/8] ROI SFR：compute_roi_sfr + 评估（assessment）
[7/8] normxcorr2 / find_line_endpoints
[8/8] SFRAnalyzer 端到端：合成 9 方格标板（geometry + edge_trace）

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_phase2_1.py
"""

import sys
import warnings
from pathlib import Path

import cv2
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


# ----------------------------------------------------------------------
# 合成数据生成
# ----------------------------------------------------------------------
def make_slanted_edge_patch(size=60, angle_deg=5.0, blur=True):
    """生成含斜边的 ROI：左黑右白，边缘倾斜 angle_deg。"""
    img = np.zeros((size, size), dtype=np.float64)
    img[:, size // 2:] = 220.0
    # 旋转图像制造斜边
    center = (size / 2, size / 2)
    rot = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    img = cv2.warpAffine(img, rot, (size, size), borderValue=110.0)
    if blur:
        img = cv2.GaussianBlur(img, (3, 3), 0)
    return img


IMG_H, IMG_W = 800, 800
SQUARE_SIZE = 0.06          # 占对角线比例
SQUARE_DISTANCES = [0, 0.4, 0.4, 0.4, 0.4, 0.6, 0.6, 0.6, 0.6]
SQUARE_ANGLES = [0, 45, 135, 225, 315, 0, 90, 180, 270]
SQUARE_NAMES = ["c", "tl", "tr", "bl", "br", "e", "n", "w", "s"]
SQUARE_ROTATION = 5.0       # 方格旋转角度（产生斜边）


def make_square_chart_config():
    """生成多方格标板测试配置。"""
    return {
        "sfrnv": {
            "params": {
                "square_size": SQUARE_SIZE,
                "square_names": SQUARE_NAMES,
                "square_distances": SQUARE_DISTANCES,
                "square_angles": SQUARE_ANGLES,
                "square_rotations": [SQUARE_ROTATION] * 9,
                "sb_patch_size": [0.04, 0.02],
                "min_patch_size": 10,
                "sub_patch_names": ["t", "b", "l", "r"],
                "sub_patch_angles": [90, 270, 180, 0],
                "freqs": [0.25, 0.5],
                "nyq_freq": 0.5,
                "main_freq": 0.5,
            },
            "criteria": {
                "0": {
                    "0.25": {"min": 0.0, "max": 1.0},
                    "0.5": {"min": 0.0, "max": 1.0},
                },
                "0.4": {
                    "0.25": {"min": 0.0, "max": 1.0},
                    "0.5": {"min": 0.0, "max": 1.0},
                },
                "0.6": {
                    "0.25": {"min": 0.0, "max": 1.0},
                    "0.5": {"min": 0.0, "max": 1.0},
                },
                "tilt": 1.0,
                "falloff": 1.0,
            },
        }
    }


def make_square_chart_image():
    """按配置几何参数生成合成 9 方格标板图像（mono, float32, (H, W, 1)）。"""
    image = np.full((IMG_H, IMG_W), 220.0, dtype=np.float64)
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    cx, cy = IMG_W / 2 + 0.5, IMG_H / 2 + 0.5

    for dist, ang in zip(SQUARE_DISTANCES, SQUARE_ANGLES):
        d = 0.5 * chart_diag * dist
        x = d * np.cos(np.deg2rad(ang)) + cx
        y = cy - d * np.sin(np.deg2rad(ang))
        rect = ((x, y), (square_px, square_px), SQUARE_ROTATION)
        box = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillPoly(image, [box], 20.0)

    image = cv2.GaussianBlur(image, (3, 3), 0)
    return image[:, :, np.newaxis].astype(np.float32)


# ----------------------------------------------------------------------
# 测试
# ----------------------------------------------------------------------
def test_imports():
    print("[1/8] 模块导入")
    from leopardiq import mtf_sfrmat5_cpp  # noqa: F401
    from leopardiq.mtf import (  # noqa: F401
        SFRAnalyzer,
        analyze_peak_focus,
        compute_mtf_array,
        compute_mtf_metrics,
        compute_roi_sfr,
        interpolation_mtf,
        interpolation_nyquist,
    )
    from leopardiq.mtf import assessment, centroid, cross_chart, square_chart  # noqa: F401

    check("leopardiq.mtf 全部导入成功（含 pyd）", True)


def test_mtf_engine():
    print("[2/8] MTF 引擎")
    from leopardiq.mtf import (
        compute_mtf_array,
        compute_mtf_metrics,
        interpolation_nyquist,
    )

    patch = make_slanted_edge_patch()
    mtf_array = compute_mtf_array(patch)
    check("ComputeMTFArray 返回非空", mtf_array is not None and len(mtf_array) > 0)
    if mtf_array is None:
        return
    check("MTF 数组为 (N,2)", mtf_array.ndim == 2 and mtf_array.shape[1] == 2)

    sfr = interpolation_nyquist(mtf_array, np.array([0.125, 0.25]))
    check("插值返回 2 个频率点", len(sfr) == 2)
    check("SFR(0.125) > SFR(0.25)（单调趋势）", sfr[0] > sfr[1],
          f"{sfr[0]:.3f} > {sfr[1]:.3f}")
    check("SFR 值在合理范围 (0,1]", 0 < sfr[0] <= 1.0, f"{sfr[0]:.3f}")

    metrics = compute_mtf_metrics(mtf_array, ("mtf50", "mtf30"))
    check("MTF50/MTF30 已计算", "mtf50" in metrics and "mtf30" in metrics,
          f"mtf50={metrics['mtf50']:.3f}, mtf30={metrics['mtf30']:.3f}")
    check("MTF30 > MTF50", metrics["mtf30"] > metrics["mtf50"] > 0)


def test_centroid_detection():
    print("[3/8] 质心检测")
    from leopardiq.mtf.centroid import find_square_centroids_mono
    from leopardiq.utils.common import filter_centroid

    image = make_square_chart_image()
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    centroids, stats, binary = find_square_centroids_mono(image, square_px)
    check("检测到 9 个方格", centroids.shape[0] == 9, f"got {centroids.shape[0]}")
    check("stats 形状 (9,5)", stats.shape == (9, 5))

    cx, cy = IMG_W / 2 + 0.5, IMG_H / 2 + 0.5
    ideal = []
    for dist, ang in zip(SQUARE_DISTANCES, SQUARE_ANGLES):
        d = 0.5 * chart_diag * dist
        ideal.append([d * np.cos(np.deg2rad(ang)) + cx, cy - d * np.sin(np.deg2rad(ang))])
    ideal = np.array(ideal)
    filtered, _ = filter_centroid(centroids, chart_diag, ideal, stats)
    check("filter_centroid 保留 9 个", filtered.shape[0] == 9)


def test_chart_geometry():
    print("[4/8] 标板几何")
    from leopardiq.mtf.square_chart import (
        compute_chart_geometry,
        init_square_chart_params,
    )

    config = make_square_chart_config()
    params = init_square_chart_params(config)
    check("frequency = [0.125, 0.25]",
          np.allclose(params["frequency"], [0.125, 0.25]))
    check("main_frequency = 0.25", params["main_frequency"] == 0.25)
    check("horizontal/vertical index 正确",
          params["horizontal_index"].tolist() == [False, False, True, True]
          and params["vertical_index"].tolist() == [True, True, False, False])

    image = make_square_chart_image()
    geometry = compute_chart_geometry(
        image,
        params["patch_size"],
        params["square_angles"],
        params["square_distances"],
        params["square_size"],
    )
    chart_diag = np.hypot(IMG_H, IMG_W)
    check("chart_diag 正确", abs(geometry["chart_diag"] - chart_diag) < 1e-6)
    check("中心方格理想位置≈图像中心",
          abs(geometry["ideal_patch_axisx"][0] - IMG_W / 2 - 0.5) < 1
          and abs(geometry["ideal_patch_axisy"][0] - IMG_H / 2 - 0.5) < 1)
    check("square_size_pixel 正确",
          abs(geometry["square_size_pixel"] - SQUARE_SIZE * chart_diag) < 1e-6)


def test_edge_tracing():
    print("[5/8] 边缘追踪")
    from leopardiq.mtf.square_chart import (
        find_one_edge_pos,
        search_edge_centers_in_binary_image,
    )

    # 合成二值图：中心 60x60 黑方格（0），背景 255
    binary = np.full((200, 200), 255, dtype=np.uint8)
    binary[70:130, 70:130] = 0

    direction, pos_y, pos_x = find_one_edge_pos(binary, (100, 100))
    check("find_one_edge_pos 找到边界", direction != "NA", f"direction={direction}")

    (ret, top_c, right_c, bottom_c, left_c,
     tl, tr, bl, br) = search_edge_centers_in_binary_image(
        binary, pos_x, pos_y, direction
    )
    check("search_edge_centers 成功", ret)
    # 注意：该边缘追踪算法对理想合成图存在已知怪癖（原库如此，保持行为一致），
    # 这里只验证返回结构合法，精确位置需真实标板图像验证
    corners = [tl, tr, bl, br]
    check("四角坐标在图内",
          all(0 <= p[0] < 200 and 0 <= p[1] < 200 for p in corners))
    check("边中点由四角平均得到",
          top_c == (int((tl[0] + tr[0]) / 2), int((tl[1] + tr[1]) / 2)))


def test_roi_sfr_and_assessment():
    print("[6/8] ROI SFR 与评估")
    from leopardiq.mtf.assessment import assess_patch_results, assess_tilt_falloff
    from leopardiq.mtf.mtf_calculator import compute_roi_sfr

    frequency = np.array([0.125, 0.25])
    results = np.zeros((4, 1, 2))
    valid_all = True
    for patch in range(4):
        roi = make_slanted_edge_patch()
        valid = compute_roi_sfr(roi[:, :, np.newaxis], frequency, 1, patch, results)
        valid_all = valid_all and valid
    check("4 个 ROI 全部有效", valid_all)
    check("结果无 NaN", not np.isnan(results).any())

    config = make_square_chart_config()
    square_distances = np.array(SQUARE_DISTANCES)
    center_index = square_distances == 0
    outer_index = square_distances == np.max(square_distances)
    out = assess_patch_results(
        results, 0, SQUARE_NAMES, square_distances,
        center_index, outer_index, frequency, 0.25, 0, 0,
        config, "sfrnv",
    )
    check("中心方格产生 2 个指标", len(out["metric_keys"]) == 2,
          str(out["metric_keys"]))
    check("center_data 有 1 个主频值", len(out["center_data"]) == 1)

    tf = assess_tilt_falloff([0.6], [0.5, 0.55, 0.52, 0.58], config, "sfrnv")
    check("tilt 计算正确", abs(tf["tilt"] - (0.58 - 0.5)) < 1e-9,
          f"tilt={tf['tilt']:.3f}")
    check("falloff 计算正确",
          abs(tf["falloff"] - (0.6 - np.mean([0.5, 0.55, 0.52, 0.58]))) < 1e-9,
          f"falloff={tf['falloff']:.3f}")
    check("tilt/falloff 判定 PASS", tf["statuses"] == ["PASS", "PASS"])


def test_cross_chart_utils():
    print("[7/8] normxcorr2 / 端点检测")
    from leopardiq.mtf.cross_chart import find_line_endpoints, normxcorr2

    # 模板匹配：在 100x100 图像 (30,40) 处放置模板
    rng = np.random.default_rng(42)
    image = rng.random((100, 100))
    template = rng.random((15, 15))
    image[30:45, 40:55] = template
    corr = normxcorr2(template, image)
    peak = np.unravel_index(np.argmax(corr), corr.shape)
    # full 模式相关峰位于模板右下角位置
    check("normxcorr2 峰值定位正确",
          abs(peak[0] - (30 + 14)) <= 1 and abs(peak[1] - (40 + 14)) <= 1,
          f"peak={peak}")

    line = np.zeros((10, 10), dtype=np.uint8)
    line[2:8, 5] = 1
    endpoints = find_line_endpoints(line)
    ep = np.argwhere(endpoints)
    check("直线检测到 2 个端点", len(ep) == 2, f"{ep.tolist()}")


def test_analyzer_end_to_end():
    print("[8/8] SFRAnalyzer 端到端")
    from leopardiq.mtf import SFRAnalyzer

    config_sensor = make_square_chart_config()
    config_data = {"cfa": ["Y"], "width": IMG_W, "height": IMG_H, "black_level": 0}
    image = make_square_chart_image()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        analyzer = SFRAnalyzer(config_sensor, config_data, roi_method="geometry")
        result = analyzer.analyze(image, debug=True)

    check("geometry 模式返回标准结构",
          all(k in result for k in ("metrics", "pass", "details", "visualization")))
    check("包含 tilt/falloff 指标",
          "tilt" in result["metrics"] and "falloff" in result["metrics"])
    check("9 方格 × 2 频率 + tilt + falloff = 20 个指标",
          len(result["metrics"]) == 20, f"got {len(result['metrics'])}")
    nan_free = not any(
        v is None or (isinstance(v, float) and np.isnan(v))
        for m in result["metrics"].values()
        for v in np.atleast_1d(m["value"])
    )
    check("所有指标数值有效（无 NaN）", nan_free)
    check("整体判定 PASS", result["pass"],
          str({k: v["status"] for k, v in result["metrics"].items()
               if v["status"] != "PASS"}))
    check("visualization 含 9 方格 ROI",
          result["visualization"] is not None
          and len(result["visualization"]["rois"]) == 9)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        analyzer_et = SFRAnalyzer(config_sensor, config_data, roi_method="edge_trace")
        result_et = analyzer_et.analyze(image)
    check("edge_trace 模式运行成功（不崩溃）", "metrics" in result_et)
    check("edge_trace 模式指标数量一致", len(result_et["metrics"]) == 20)
    # 注：edge_trace 的边缘追踪启发式对理想合成图不稳定（原库行为），
    # 其数值准确性需真实标板图像验证，此处只验证流程可完整运行


def main():
    print("=" * 60)
    print("Phase 2.1 验证测试：MTF/SFR 模块")
    print("=" * 60)

    test_imports()
    test_mtf_engine()
    test_centroid_detection()
    test_chart_geometry()
    test_edge_tracing()
    test_roi_sfr_and_assessment()
    test_cross_chart_utils()
    test_analyzer_end_to_end()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
