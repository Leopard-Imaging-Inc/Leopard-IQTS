"""MTF/SFR 模块适配器：GUI（ROI 框选 + config dict）→ leopardiq 算法接口。

RAW 处理流程参考 Cal_MTF/scripts/mtf_single.py：
  uint16 读取 → 减黑电平 →（Bayer 时）cv2.demosaicing → 灰度 → 全分辨率斜边 MTF。

流程：
  1. 按 params 加载图像（常见格式走 OpenCV 灰度；.raw 按 宽/高/黑电平 读取，
     分辨率与文件大小不符时自动识别常见 sensor 分辨率）；
  2. Bayer RAW 按 CFA pattern 去马赛克并转灰度（输出始终为全分辨率单通道 Y）；
  3. 逐个 ROI 裁剪斜边 patch，**每 (ROI, 通道) 只调用一次 C++ 引擎**：
       - compute_mtf_array：MTF 曲线（前置 validate_edge_patch 预检防段错误）；
       - interpolation_nyquist：由曲线插值得 SFR@评估频率
         （与 compute_roi_sfr 同一引擎 + 同一插值函数，结果口径一致）；
       - compute_mtf_metrics：MTF50 / MTFnn / MTFnnP；
  4. criteria 下限判定（readout1_min / sfr_main_min）→ PASS/FAIL。

返回结构对齐 SFRAnalyzer：{"metrics", "pass", "details", "visualization"}。
"""

from __future__ import annotations

import warnings
from pathlib import Path

import cv2
import numpy as np

from leopardiq.mtf import (
    GAMMA_REASONABLE_RANGE,
    compute_mtf_array,
    compute_mtf_metrics,
    interpolation_nyquist,
    unit_scale,
    unit_to_cy_px,
)
from leopardiq.utils.pass_fail import evaluate_pass_fail
from leopardiq.utils.raw_reader import (
    DEMOSAIC_CODES,
    RawReadConfig,
    guess_raw_resolution,
    read_raw,
)

#: panel cfa 选项 → 通道名（Y 为 mono 或去马赛克后灰度）
CFA_PATTERNS: dict[str, list[str]] = {
    "Y": ["Y"],
    "RGGB": ["Y"],
    "BGGR": ["Y"],
    "GRBG": ["Y"],
    "GBRG": ["Y"],
}

#: OpenCV 可直接解码的常见格式
COMMON_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def load_analysis_image(path, params: dict) -> np.ndarray:
    """加载分析图像 → (H, W, 1) float32（RAW 已减黑电平、Bayer 已去马赛克转灰度）。"""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in COMMON_EXTS:
        # IMREAD_ANYDEPTH：保留 16-bit TIFF/PNG 原始位深（与 mtf_single.py 一致）
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_ANYDEPTH)
        if img is None:
            raise ValueError(f"无法解码图像：{path}")
        return img.astype(np.float32)[:, :, np.newaxis]
    if ext == ".raw":
        return load_raw_image(path, params)
    raise ValueError(f"MTF/SFR 暂不支持的格式：{ext or '(无后缀)'}（{path.name}）")


def load_raw_image(path: Path, params: dict) -> np.ndarray:
    """读取 .raw 二进制 → (H, W, 1) float32。

    读取参数优先级：模块 params（raw_width 等，向后兼容旧配置）→
    Utilities「Generalized Read Raw」全局设置（iqtest.config.read_raw_settings）。
    分辨率与文件大小不符时按常见分辨率自动识别；识别失败给出明确报错。
    实现见 leopardiq.utils.raw_reader（简化版 Generalized Read Raw）。

    字节序固定 little-endian、不扣黑电平（MTF 流程不使用这两项；
    旧配置 params 中的 byte_order / black_level 键会被忽略）。
    """
    from iqtest.config.read_raw_settings import get_read_raw_params

    saved = get_read_raw_params()
    img, _ = read_raw(
        path,
        RawReadConfig(
            width=int(params.get("raw_width", saved["width"])),
            height=int(params.get("raw_height", saved["height"])),
            bit_depth=int(params.get("bit_depth", saved["bit_depth"])),
            header_bytes=int(params.get("header_bytes", 0)),
            cfa=str(params.get("cfa", saved["cfa"])),
            demosaic=bool(params.get("demosaic", saved["demosaic"])),
            gray_method=str(params.get("gray_method", saved.get("gray_method", "BT709"))),
        ),
    )
    return img


def _clip_rect(rect, width: int, height: int) -> list[int]:
    """将 [x, y, w, h] 裁剪到图像范围内，最小 8px（与算法层退化 ROI 阈值一致）。"""
    x, y, w, h = [int(round(float(v))) for v in rect[:4]]
    x = max(0, min(x, width - 8))
    y = max(0, min(y, height - 8))
    w = max(8, min(w, width - x))
    h = max(8, min(h, height - y))
    return [x, y, w, h]


def analyze_mtf(images: list, config: dict) -> dict:
    """MTF/SFR 分析入口（runner 约定签名：fn(images, config) -> dict）。

    config["params"]["rois"] = [{"image": 文件名, "rect": [x, y, w, h]}, ...]
    （rect 为全分辨率图像坐标，与 ROI 框选/精调弹框一致）
    """
    params = config.get("params") or {}
    criteria = config.get("criteria") or {}

    rois = params.get("rois") or []
    if not rois:
        raise ValueError(
            "尚未框选 ROI：请在 ② Select Analysis → MTF / SFR 面板"
            "载入图像并框选至少一个斜边 ROI"
        )

    cfa_key = params.get("cfa", "Y")
    if cfa_key not in CFA_PATTERNS:
        raise ValueError(f"未知 CFA pattern：{cfa_key!r}")
    channel_names = CFA_PATTERNS[cfa_key]

    # 频率单位（仿 Imatest Secondary Readout）：界面按所选单位输入，
    # 算法统一换算为规范单位 cy/px（旧配置无 freq_unit 键 → 默认 Cycles/pixel）
    freq_unit = str(params.get("freq_unit", "Cycles/pixel"))
    pixel_size_um = float(params.get("pixel_size_um", 0.0) or 0.0)
    picture_height = int(params.get("picture_height", 0) or 0)

    freq1_in = float(params.get("freq1", 0.125))
    freq1 = unit_to_cy_px(freq1_in, freq_unit, pixel_size_um, picture_height)
    if not (0.0 < freq1 <= 1.0):
        raise ValueError(
            f"评估频率需满足 0 < 频率 ≤ Nyquist×2"
            f"（当前 {freq1_in:g} {freq_unit} = {freq1:.4g} cy/px）"
        )
    frequency = np.array([freq1])

    # Readout1（Secondary Readout 1，默认 MTF30）频率即频率类判定指标，
    # readout1_min 为其下限（沿用固定的 MTF50 频率 lower-limit 语义）。
    readout1_min_in = float(criteria.get("readout1_min", 0.0))
    readout1_min = unit_to_cy_px(
        readout1_min_in, freq_unit, pixel_size_um, picture_height
    )
    sfr_main_min = float(criteria.get("sfr_main_min", 0.0))

    # Gamma 线性化（仿 Imatest「Input gamma value」，旧配置无该键 →
    # gamma=1.0 不线性化，与历史行为一致；Gamma=1 等价于不线性化）：
    # 编码 Gamma 的倒数用于线性化 pixel^(1/gamma)——RAW 线性数据 = 1.0，
    # BMP/JPEG 等 sRGB 编码图像 ≈ 0.45~0.5；设置错误会使 MTF 失真。
    gamma_in = float(params.get("gamma", 1.0))
    if not (0.1 <= gamma_in <= 2.0):
        raise ValueError(f"Gamma 需在 0.1~2.0 内（当前 {gamma_in:g}）")
    glo, ghi = GAMMA_REASONABLE_RANGE
    if not (glo <= gamma_in <= ghi) and gamma_in != 1.0:
        warnings.warn(
            f"Gamma = {gamma_in:g} 超出合理区间 [{glo}, {ghi}]，"
            "请确认输入是否正确（Imatest 将该选择标记为异常）",
            RuntimeWarning,
        )

    def resolve_gamma(patch: np.ndarray) -> float:
        """当前 ROI 实际使用的编码 Gamma（全 ROI 统一的输入值）。"""
        return gamma_in

    # Secondary Readout（仿 Imatest，2 个槽位）：Readout1（槽位 1）为判定指标，
    # 其 MTF@nn 频率下限即 readout1_min 判据；Readout2（槽位 2）仍 INFO 展示，
    # 不参与判定。与判定键 "mtf50" 重复或两槽位重复的读数自动去重。
    readouts: list[dict] = []
    seen_keys: set[str] = {"mtf50"}
    readout1_key: str | None = None
    for slot, d_type, d_value in ((1, "MTFnn", 30.0), (2, "MTFnnP", 50.0)):
        rtype = str(params.get(f"mtfnn{slot}_type", d_type))
        if rtype not in ("MTFnn", "MTFnnP"):
            raise ValueError(
                f"未知 Secondary Readout {slot} 类型：{rtype!r}"
            )
        rvalue = float(params.get(f"mtfnn{slot}_value", d_value))
        if not (0.0 < rvalue < 100.0):
            raise ValueError(
                f"Readout {slot} 百分比需在 (0, 100) 内（当前 {rvalue:g}）"
            )
        nn_str = f"{rvalue:g}"
        rkey = f"mtf{nn_str}" + ("p" if rtype == "MTFnnP" else "")
        if slot == 1:
            readout1_key = rkey
        if rkey in seen_keys:
            continue
        seen_keys.add(rkey)
        readouts.append({
            "key": rkey,
            "label": f"MTF{nn_str}" + ("P" if rtype == "MTFnnP" else ""),
        })
    if readout1_key is None:
        readout1_key = "mtf30"

    paths = {Path(p).name: Path(p) for p in images}

    cache: dict[str, np.ndarray] = {}
    image_sizes: dict[str, list[int]] = {}  # 图像名 → [W, H]（供结果导出归一化坐标）

    def get_image(name: str) -> np.ndarray:
        if name not in paths:
            raise ValueError(f"ROI 引用的图像不在会话中：{name}")
        if name not in cache:
            img = load_analysis_image(paths[name], params)
            cache[name] = img
            image_sizes[name] = [int(img.shape[1]), int(img.shape[0])]
        return cache[name]

    metrics: dict[str, dict] = {}
    curves: list[dict] = []
    roi_records: list[dict] = []
    all_valid = True

    for roi_index, roi in enumerate(rois):
        label = f"ROI{roi_index + 1}"
        image = get_image(roi.get("image"))
        n_ch = image.shape[2]
        rect = _clip_rect(roi["rect"], image.shape[1], image.shape[0])
        x, y, w, h = rect
        if min(w, h) < 20:
            warnings.warn(
                f"{label} 尺寸 {w}×{h} 偏小（斜边 ROI 建议 ≥ 40×40 px），"
                "MTF 结果误差可能偏大",
                RuntimeWarning,
            )
        patch = image[y:y + h, x:x + w, :]
        gamma_roi = resolve_gamma(patch)

        # 逐通道各调用一次 C++ 引擎得到 MTF 曲线；SFR@评估频率由曲线插值
        # 得到（与 compute_roi_sfr 同一引擎 + 同一 interpolation_nyquist，
        # 口径一致，但引擎调用次数减半——引擎是最耗时且有崩溃风险的环节）。
        # 有效性规则与 compute_roi_sfr 对齐：引擎失败或 SFR > 1.0 记无效（值置 0）。
        metric_names = list(dict.fromkeys(
            ("mtf50", readout1_key) + tuple(r["key"] for r in readouts)
        ))
        readout1_list = []
        readout_lists = [[] for _ in readouts]
        sfr1 = []
        valid = True
        for ch in range(n_ch):
            ch_patch = np.float64(np.squeeze(patch[:, :, ch]))
            mtf_array = compute_mtf_array(ch_patch, gamma=gamma_roi)
            if mtf_array is None:
                valid = False
                sfr1.append(0.0)
                readout1_list.append(0.0)
                for rl in readout_lists:
                    rl.append(0.0)
                curves.append({
                    "roi": roi_index + 1, "channel": channel_names[ch],
                    "valid": False,
                    "gamma": round(gamma_roi, 6),
                    "sfr": [0.0],
                })
                continue
            sfr_val = float(interpolation_nyquist(mtf_array, frequency)[0])
            ch_valid = bool(np.isfinite(sfr_val) and sfr_val <= 1.0)
            valid = valid and ch_valid
            sfr1.append(sfr_val if ch_valid else 0.0)
            m = compute_mtf_metrics(mtf_array, metric_names)
            readout1_list.append(m[readout1_key])
            for rl, r in zip(readout_lists, readouts):
                rl.append(m[r["key"]])
            curves.append({
                "roi": roi_index + 1,
                "channel": channel_names[ch],
                "valid": True,
                "gamma": round(gamma_roi, 6),
                "freq": np.round(mtf_array[:, 0], 6).tolist(),
                "mtf": np.round(mtf_array[:, 1], 6).tolist(),
                "mtf50": round(m["mtf50"], 6),
                "readout1": round(m[readout1_key], 6),
                "readouts": [round(m[r["key"]], 6) for r in readouts],
                "sfr": [round(sfr1[-1], 6)],
            })
        all_valid = all_valid and valid
        # MTF @ 评估频率：参与 criteria 判定（sfr_main_min）
        metrics[f"{label}_mtf@{freq1:g}"] = {
            "value": [round(float(v), 6) for v in sfr1],
            "status": evaluate_pass_fail(sfr1, sfr_main_min, mode="lower"),
        }
        # Readout1（Secondary Readout 1）频率：参与 criteria 判定（readout1_min）
        metrics[f"{label}_readout1"] = {
            "value": [round(float(v), 6) for v in readout1_list],
            "status": evaluate_pass_fail(np.asarray(readout1_list), readout1_min, mode="lower"),
        }
        for rl, r in zip(readout_lists, readouts):
            metrics[f"{label}_{r['key']}"] = {
                "value": [round(float(v), 6) for v in rl],
                "status": "INFO",
            }
        roi_records.append({
            "roi": roi_index + 1,
            "image": roi.get("image"),
            "rect": rect,
            "valid": bool(valid),
            "gamma": round(gamma_roi, 6),
        })

    judged = [m["status"] for m in metrics.values() if m["status"] in ("PASS", "FAIL")]
    details = {
        "cfa": cfa_key,
        "channels": channel_names,
        "frequency": [freq1],  # 规范单位 cy/px（算法口径）
        "freq_unit": freq_unit,
        "unit_scale": unit_scale(freq_unit, pixel_size_um, picture_height),
        "pixel_size_um": pixel_size_um,
        "picture_height": picture_height,
        "gamma": gamma_in,
        "readouts": readouts,
        "readout1_key": readout1_key,  # Readout1 指标键（判定列，如 mtf30/mtf50）
        "criteria": {"readout1_min": readout1_min, "sfr_main_min": sfr_main_min},
        "rois": roi_records,
        "curves": curves,
        "image_sizes": image_sizes,  # 图像名 → [W, H]，结果 CSV 导出归一化坐标用
        "metric_keys": list(metrics),
        "metric_values": [m["value"] for m in metrics.values()],
        "statuses": [m["status"] for m in metrics.values()],
    }
    return {
        "metrics": metrics,
        "pass": all_valid and "FAIL" not in judged,
        "details": details,
        "visualization": {"rois": roi_records},
    }
