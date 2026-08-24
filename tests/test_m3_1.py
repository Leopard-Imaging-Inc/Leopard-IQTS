"""
M3 验证测试：MTF/SFR 模块接入（ROI 框选 → compute_roi_sfr 适配器 → 结果判定）。

测试内容：
[1/7] 适配器导入与 runner 注册
[2/7] mono 斜边标板端到端：analyze_mtf vs 直接 compute_roi_sfr 对拍（容差 1e-6）
[3/7] Bayer RAW 端到端：去马赛克转灰度（参考 mtf_single.py 流程）
[4/7] criteria 判定：阈值拉高 → FAIL；错误路径（无 ROI / 频率非法）
[5/7] config schema 与 JSON 持久化（新 MTF 键往返）
[6/7] RAW 加载：分辨率自动识别 + 去马赛克 CFA 映射正确性
[7/7] 真实 RAW 数据（assets SN_2-0.6）：产线 CSV ROI 框端到端

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m3_1.py
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
IMG_H, IMG_W = 800, 800
SQUARE_SIZE = 0.06
SQUARE_DISTANCES = [0, 0.4, 0.4, 0.4, 0.4]
SQUARE_ANGLES = [0, 45, 135, 225, 315]
SQUARE_ROTATION = 5.0


def square_centers():
    chart_diag = np.hypot(IMG_H, IMG_W)
    cx, cy = IMG_W / 2 + 0.5, IMG_H / 2 + 0.5
    pts = []
    for dist, ang in zip(SQUARE_DISTANCES, SQUARE_ANGLES):
        d = 0.5 * chart_diag * dist
        pts.append((d * np.cos(np.deg2rad(ang)) + cx, cy - d * np.sin(np.deg2rad(ang))))
    return pts


def make_chart(size=(IMG_H, IMG_W)):
    """合成 5 方格斜边标板（mono, float32, (H, W, 1)），方格旋转产生斜边。"""
    h, w = size
    image = np.full((h, w), 220.0, dtype=np.float64)
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    scale_x, scale_y = w / IMG_W, h / IMG_H
    for x, y in square_centers():
        rect = ((x * scale_x, y * scale_y),
                (square_px * scale_x, square_px * scale_y), SQUARE_ROTATION)
        box = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillPoly(image, [box], 20.0)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    return image[:, :, np.newaxis].astype(np.float32)


def top_edge_rois():
    """每个方格上边（斜边）的 ROI：[x, y, w, h]。"""
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    rois = []
    for x, y in square_centers():
        rois.append([
            int(x - square_px * 0.35),
            int(y - square_px / 2 - 12),
            int(square_px * 0.7),
            40,
        ])
    return rois


def make_mono_chart_file() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "sfr_chart.png"
    img = np.squeeze(make_chart())
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8))
    return path


def make_bayer_raw_file() -> tuple[Path, int, int]:
    """合成 RGGB RAW：半分辨率标板逐像素 2×2 复制 → 各通道平面 = 半分辨率标板。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    half = np.squeeze(make_chart((IMG_H // 2, IMG_W // 2)))  # (400, 400)
    mosaic = np.repeat(np.repeat(half, 2, axis=0), 2, axis=1)  # (800, 800)
    raw = np.clip(mosaic * 256.0, 0, 65535).astype(np.uint16)  # 量化到 16bit
    path = OUT_DIR / "sfr_chart_rggb.raw"
    raw.tofile(str(path))
    return path, IMG_W, IMG_H


# ----------------------------------------------------------------------
# 测试
# ----------------------------------------------------------------------
def test_imports():
    print("[1/5] 适配器导入与注册")
    from iqtest.analysis import analyze_mtf  # noqa: F401
    from iqtest.runner import MODULE_ANALYZERS

    check("analyze_mtf 已注册进 MODULE_ANALYZERS",
          MODULE_ANALYZERS.get("mtf") is analyze_mtf)
    from iqtest.analysis.mtf_adapter import CFA_PATTERNS, load_analysis_image  # noqa: F401
    check("CFA_PATTERNS 含 Y + 4 种 Bayer", len(CFA_PATTERNS) == 5)


def test_mono_end_to_end():
    print("[2/5] mono 端到端 + 对拍")
    from iqtest.analysis.mtf_adapter import analyze_mtf
    from leopardiq.mtf import compute_roi_sfr

    path = make_mono_chart_file()
    rois = [{"image": path.name, "rect": r} for r in top_edge_rois()]
    config = {
        "params": {"cfa": "Y", "freq1": 0.125, "rois": rois},
        "criteria": {"readout1_min": 0.05, "sfr_main_min": 0.1},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = analyze_mtf([path], config)

    check("返回标准结构",
          all(k in result for k in ("metrics", "pass", "details", "visualization")))
    check("5 ROI × 4 指标 = 20 个指标",
          len(result["metrics"]) == 20, f"got {len(result['metrics'])}")
    check("5 条 MTF 曲线（mono 1 通道）",
          len(result["details"]["curves"]) == 5)
    curves_valid = all(c.get("valid") and len(c["freq"]) > 0
                       for c in result["details"]["curves"])
    check("全部曲线有效且含频率轴", curves_valid)
    check("总判定 PASS（宽松阈值）", result["pass"],
          str({k: v["status"] for k, v in result["metrics"].items()
               if v["status"] == "FAIL"}))

    # 与脚本口径对拍：直接 compute_roi_sfr 同一 patch
    # （基准图像须与适配器一致——PNG 落盘后读回的 8-bit 图，而非内存 float 图）
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE).astype(np.float32)
    frequency = np.array([0.125])
    max_diff = 0.0
    for i, record in enumerate(result["details"]["rois"]):
        x, y, w, h = record["rect"]
        patch = image[y:y + h, x:x + w, np.newaxis].astype(np.float32)
        direct = np.full((1, 1, 1), np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            compute_roi_sfr(patch, frequency, 1, 0, direct)
        gui = result["metrics"][f"ROI{i + 1}_mtf@0.125"]["value"][0]
        max_diff = max(max_diff, abs(float(direct[0, 0, 0]) - gui))
    check("GUI 与脚本 MTF@ 对拍一致（容差 1e-6）", max_diff <= 1e-6,
          f"max_diff={max_diff:.2e}")

    # MTF50 合理性：模糊斜边应有 0 < MTF50 < 0.5
    mtf50 = [c["mtf50"] for c in result["details"]["curves"]]
    check("MTF50 在合理范围 (0, 0.5)", all(0 < v < 0.5 for v in mtf50),
          f"mtf50={['%.3f' % v for v in mtf50]}")


def test_bayer_raw_end_to_end():
    print("[3/7] Bayer RAW 端到端（去马赛克转灰度）")
    from iqtest.analysis.mtf_adapter import analyze_mtf

    path, w, h = make_bayer_raw_file()
    rois = [{"image": path.name, "rect": r} for r in top_edge_rois()]
    config = {
        "params": {
            "cfa": "RGGB", "freq1": 0.125,
            "raw_width": w, "raw_height": h, "black_level": 0,
            "rois": rois,
        },
        "criteria": {"readout1_min": 0.02, "sfr_main_min": 0.0},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = analyze_mtf([path], config)

    check("5 ROI × 1 通道(Y) = 5 条曲线",
          len(result["details"]["curves"]) == 5,
          f"got {len(result['details']['curves'])}")
    channels = {c["channel"] for c in result["details"]["curves"]}
    check("去马赛克后通道为 Y", channels == {"Y"}, str(channels))
    check("指标值为单通道列表",
          all(len(m["value"]) == 1 for m in result["metrics"].values()))
    # 合成 RAW 为半分辨率逐像素 ×2 复制 → 去马赛克后 MTF50 应≈半分辨率的一半
    mtf50 = [c["mtf50"] for c in result["details"]["curves"]]
    check("MTF50 在合理范围 (0, 0.5)", all(0 < v < 0.5 for v in mtf50),
          f"mtf50={['%.3f' % v for v in mtf50]}")
    check("总判定 PASS", result["pass"],
          str({k: v["status"] for k, v in result["metrics"].items()
               if v["status"] == "FAIL"})[:200])


def test_criteria_and_errors():
    print("[4/7] criteria 判定与错误路径")
    from iqtest.analysis.mtf_adapter import analyze_mtf

    path = OUT_DIR / "sfr_chart.png"
    rois = [{"image": path.name, "rect": top_edge_rois()[0]}]

    def run(criteria):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return analyze_mtf([path], {
                "params": {"cfa": "Y", "freq1": 0.125, "rois": rois},
                "criteria": criteria,
            })

    ok = run({"readout1_min": 0.0, "sfr_main_min": 0.0})
    check("零阈值 → PASS", ok["pass"])
    hard = run({"readout1_min": 10.0, "sfr_main_min": 10.0})
    check("超高阈值 → FAIL", not hard["pass"])
    check("FAIL 指标着色正确",
          hard["metrics"]["ROI1_readout1"]["status"] == "FAIL"
          and hard["metrics"]["ROI1_mtf@0.125"]["status"] == "FAIL")
    check("INFO 指标不参与判定",
          hard["metrics"]["ROI1_mtf30"]["status"] == "INFO"
          and hard["metrics"]["ROI1_mtf50p"]["status"] == "INFO")

    try:
        analyze_mtf([path], {"params": {"cfa": "Y", "rois": []}, "criteria": {}})
    except ValueError as e:
        check("无 ROI → ValueError", "ROI" in str(e))
    else:
        check("无 ROI → ValueError", False, "未抛出")

    bad = dict(rois[0])
    try:
        analyze_mtf([path], {
            "params": {"cfa": "Y", "freq1": 1.5, "rois": [bad]},
            "criteria": {},
        })
    except ValueError as e:
        check("评估频率超界 → ValueError", "频率" in str(e))
    else:
        check("评估频率超界 → ValueError", False, "未抛出")

    try:
        analyze_mtf([path], {
            "params": {"cfa": "Y", "rois": [{"image": "missing.png", "rect": [0, 0, 40, 40]}]},
            "criteria": {},
        })
    except ValueError as e:
        check("ROI 引用未知图像 → ValueError", "不在会话中" in str(e))
    else:
        check("ROI 引用未知图像 → ValueError", False, "未抛出")


def test_schema_and_json():
    print("[5/7] config schema 与 JSON 持久化")
    from iqtest.config import store
    from iqtest.panels.mtf_panel import MtfPanel

    defaults = MtfPanel.default_config()
    check("默认 params 含评估频率键",
          {"freq1"} <= set(defaults["params"]))
    check("RAW 读取参数已移至 Read Raw 全局设置",
          not ({"cfa", "raw_width", "raw_height", "black_level"}
               & set(defaults["params"])))
    check("默认 criteria 含 readout1_min / sfr_main_min",
          set(defaults["criteria"]) == {"readout1_min", "sfr_main_min"})

    cfg = MtfPanel.default_config()
    cfg["params"]["rois"] = [{"image": "a.png", "rect": [10, 10, 60, 40]}]
    cfg["criteria"]["readout1_min"] = 0.15
    path = OUT_DIR / "criteria_m3_roundtrip.json"
    store.save_json(path, {"modules": {"mtf": cfg}})
    loaded = store.load_json(path)["modules"]["mtf"]
    check("JSON 往返 criteria 一致", loaded["criteria"]["readout1_min"] == 0.15)
    check("JSON 往返 rois 保留",
          loaded["params"]["rois"][0]["rect"] == [10, 10, 60, 40])


def test_raw_loading():
    print("[6/7] RAW 加载：分辨率识别 + 去马赛克映射")
    from iqtest.analysis.mtf_adapter import (
        DEMOSAIC_CODES,
        guess_raw_resolution,
        load_raw_image,
    )

    check("4608000 字节 → 1920×1200",
          guess_raw_resolution(4608000) == (1920, 1200))
    check("1920×1080 可识别",
          guess_raw_resolution(1920 * 1080 * 2) == (1920, 1080))
    check("奇数字节 → None", guess_raw_resolution(123) is None)
    check("未知大小 → None", guess_raw_resolution(1000 * 1000 * 2) is None)

    # 分辨率参数与文件大小不符 → 自动识别（1920×1080 参数读 1920×1200 文件）
    guess_path = OUT_DIR / "guess_1920x1200.raw"
    np.zeros((1200, 1920), dtype=np.uint16).tofile(str(guess_path))
    img = load_raw_image(guess_path, {
        "cfa": "Y", "raw_width": 1920, "raw_height": 1080, "black_level": 0,
    })
    check("参数不符时自动识别分辨率",
          img.shape == (1200, 1920, 1), f"shape={img.shape}")

    # 识别不了也不放水：参数错误且非常见大小 → 报错
    bad_path = OUT_DIR / "bad_size.raw"
    np.zeros((100, 101), dtype=np.uint16).tofile(str(bad_path))
    try:
        load_raw_image(bad_path, {
            "cfa": "Y", "raw_width": 1920, "raw_height": 1080, "black_level": 0,
        })
    except ValueError as e:
        check("错误分辨率 → 明确报错", "不符" in str(e), str(e)[:40])
    else:
        check("错误分辨率 → 明确报错", False, "未抛出")

    # 去马赛克 CFA 映射：色值按颜色身份固定（R=200, G=100, B=50），
    # 按各 pattern 摆放 → 正确解码后 R/B 通道不应串色
    patterns = {  # pattern: 2x2 tile [[p00, p01], [p10, p11]]
        "RGGB": [[200, 100], [100, 50]],
        "BGGR": [[50, 100], [100, 200]],
        "GRBG": [[100, 200], [50, 100]],
        "GBRG": [[100, 50], [200, 100]],
    }
    mapping_ok = True
    for pattern, tile_values in patterns.items():
        tile = np.array(tile_values, dtype=np.uint16)
        mosaic = np.tile(tile, (4, 4))
        bgr = cv2.demosaicing(mosaic, DEMOSAIC_CODES[pattern])
        bb, gg, rr = bgr[4, 4]
        if not (rr == 200 and bb == 50):
            mapping_ok = False
            print(f"      {pattern}: 期望 R=200 B=50，实得 R={rr} B={bb}")
    check("4 种 CFA 去马赛克 R/B 通道正确", mapping_ok)


def test_real_raw_data():
    print("[7/7] 真实 RAW 数据（assets SN_2-0.6）")
    from iqtest.analysis.mtf_adapter import analyze_mtf

    raw_path = (
        Path(__file__).resolve().parent.parent
        / "assets/data/MTF/camera_0/1/2-0.6"
        / "SN_2-0.6_D_07_28_2026_T_16_37_32.raw"
    )
    if not raw_path.exists():
        print("    ⚠️ 真实数据不存在，跳过")
        return

    # 产线 CSV 中的 10 个 ROI 框（x1, x2, y1, y2）→ [x, y, w, h]
    boxes = [
        (298, 338, 244, 284), (361, 401, 181, 221),
        (1555, 1595, 262, 302), (1507, 1547, 187, 227),
        (871, 911, 586, 626), (935, 975, 535, 575),
        (295, 335, 922, 962), (359, 399, 985, 1025),
        (1573, 1613, 955, 995), (1493, 1533, 1003, 1043),
    ]
    rois = [
        {"image": raw_path.name, "rect": [x1, y1, x2 - x1, y2 - y1]}
        for x1, x2, y1, y2 in boxes
    ]
    # 故意不填分辨率参数 → 走自动识别（1920×1200）
    config = {
        "params": {
            "cfa": "RGGB", "freq1": 0.125,
            "raw_width": 0, "raw_height": 0, "black_level": 0,
            "rois": rois,
        },
        "criteria": {"readout1_min": 0.10, "sfr_main_min": 0.20},
    }
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = analyze_mtf([raw_path], config)

    n_valid = sum(r["valid"] for r in result["details"]["rois"])
    # 产线 CSV 的个别 ROI 边缘贴近框边界（亮/暗区 < 8px），引擎判无效属正常
    # （Imatest 同样建议亮暗区 ≥ 8px、20px 为佳）；要求 ≥80% 有效即可
    check("ROI 有效率 ≥ 80%", n_valid >= 8, f"{n_valid}/10")
    check("10 条 MTF 曲线", len(result["details"]["curves"]) == 10)
    mtf50 = [c["mtf50"] for c in result["details"]["curves"]
             if c.get("valid") and c.get("mtf50", 0) > 0]
    check("有效 ROI 的 MTF50 在合理范围 (0.05, 0.6)",
          len(mtf50) >= 8 and all(0.05 < v < 0.6 for v in mtf50),
          f"mtf50={['%.3f' % v for v in mtf50]}")
    center = result["metrics"]["ROI5_readout1"]["value"][0]
    corner = result["metrics"]["ROI1_readout1"]["value"][0]
    check("中心 ROI(5/6) 不劣于四角 ROI(1/2)", center >= corner - 0.15,
          f"center={center:.3f} corner={corner:.3f}")
    print(f"    有效 ROI: {n_valid}/10，总判定: {'PASS' if result['pass'] else 'FAIL'}")


def main():
    print("=" * 60)
    print("M3 验证测试：MTF/SFR 模块接入")
    print("=" * 60)

    test_imports()
    test_mono_end_to_end()
    test_bayer_raw_end_to_end()
    test_criteria_and_errors()
    test_schema_and_json()
    test_raw_loading()
    test_real_raw_data()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
