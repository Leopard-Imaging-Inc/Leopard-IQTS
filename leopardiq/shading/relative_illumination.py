"""
Relative Illumination（相对照度 / 亮度 Shading）分析。

提取自 LeopardIQ0529/leopardiq/light/lens_shading.py。

核心流程：
1. 按 thresh 生成平场掩膜（排除边缘/污染）
2. 按 bin_size 网格分块求均值
3. 归一化后取四象限最小值作为 RI
4. 插值生成全分辨率 shading profile（供 LSC 使用）
5. Bayer 输入时同时计算 Color Shading（green_red/blue_shift）

多光源扩展（软件规划"几种光源"）：
analyze_multi_light() 接受 {光源名: 图像} 字典，逐光源计算并汇总。
"""

import math
from typing import Dict, Optional, Tuple, Union

import numpy as np

from leopardiq.utils.image_preprocess import get_bayer_index, split_bayer_channels

from .shading_profile import (
    bin_image_means,
    calculate_channel_shift,
    compute_quadrant_ri,
    create_flat_field_mask,
    interp_shading_profile,
)


def analyze_lens_shading(
    imgs: np.ndarray,
    bin_size: int,
    thresh: float,
    cfa: list,
    support_extrapolation: bool = False,
) -> dict:
    """
    Lens Shading 分析（原 lens_shading()）。

    Args:
        imgs: (H, W, C) 图像，Bayer 拆分后的 4 通道或 mono 单通道。
              （RAW 单张 (H, W) 请先拆分；多帧请先平均）
        bin_size: 分块尺寸（像素）
        thresh: 平场掩膜 DN 阈值（0 = 全图有效）
        cfa: Bayer 顺序列表（mono 传 ["Y"] 等单元素列表）
        support_extrapolation: shading profile 是否使用 RBF 外插（更准但更慢）

    Returns:
        {
            "ri_tl": ..., "ri_tr": ..., "ri_bl": ..., "ri_br": ...,
                              # 四象限 RI（Bayer 时为 4 通道数组）
            "ri_diff": float,        # 四象限 RI 最大最小差（对称性指标）
            "shading_profile": ...,  # (H, W, C) 全分辨率 shading 轮廓
            "green_red_shift": float or None,
            "green_blue_shift": float or None,
            "bin_means": ...,        # 网格均值（调试用）
        }
    """
    green_red_shift = None
    green_blue_shift = None

    imgs = np.asarray(imgs, dtype=np.float64)
    if imgs.ndim == 2:
        imgs = imgs[:, :, np.newaxis]
    if imgs.ndim != 3:
        raise ValueError(f"Unsupported image shape: {imgs.shape}")

    height, width, channel = imgs.shape
    gr_index = get_bayer_index(cfa)[0] if channel == 4 else 0

    # bin 网格起点（MATLAB 1-based → Python 0-based 已换算）
    start_axisx = int(math.floor(np.mod(width, bin_size) / 2))
    start_axisy = int(math.floor(np.mod(height, bin_size) / 2))
    axisx = np.array(range(start_axisx, width, bin_size))
    axisy = np.array(range(start_axisy, height, bin_size))

    mask = create_flat_field_mask(imgs, thresh, gr_index)
    imgs = imgs.copy()
    imgs[mask == 0, :] = np.nan

    means = bin_image_means(axisx, axisy, bin_size, imgs, mask)

    bl_ri, br_ri, tl_ri, tr_ri, shading = compute_quadrant_ri(means)
    shading_profile = interp_shading_profile(
        bin_size,
        channel,
        height,
        shading,
        start_axisx,
        start_axisy,
        width,
        support_extrapolation=support_extrapolation,
    )
    if len(cfa) == 4:
        green_red_shift, green_blue_shift = calculate_channel_shift(cfa, means)

    ri_stack = np.stack(
        [np.atleast_1d(v) for v in (tl_ri, tr_ri, bl_ri, br_ri)], axis=0
    )
    ri_diff = float(np.nanmax(ri_stack) - np.nanmin(ri_stack))

    return {
        "ri_tl": np.squeeze(tl_ri),
        "ri_tr": np.squeeze(tr_ri),
        "ri_bl": np.squeeze(bl_ri),
        "ri_br": np.squeeze(br_ri),
        "ri_diff": ri_diff,
        "shading_profile": shading_profile,
        "green_red_shift": green_red_shift,
        "green_blue_shift": green_blue_shift,
        "bin_means": means,
    }


def analyze_relative_illumination(
    images: Union[np.ndarray, list],
    config: dict,
) -> dict:
    """
    标准接口的相对照度分析（软件规划统一接口）。

    Args:
        images: 输入图像（RAW (H,W)、Bayer 拆分 (H/2,W/2,4)，或多帧列表）
        config: {
            "cfa": [...],
            "bin_size": int,
            "thresh": float,
            "support_extrapolation": bool (可选),
            "criteria": {              # 可选，PASS/FAIL 阈值
                "ri": float,           # 四象限 RI 下限
                "ri_diff": float,      # 四象限差异上限
                "green_red_shift": float,
                "green_blue_shift": float,
            },
        }

    Returns:
        {"metrics": {...}, "pass": bool, "details": {...}}
    """
    cfa = config["cfa"]
    bin_size = config["bin_size"]
    thresh = config.get("thresh", 0)
    support_extrapolation = config.get("support_extrapolation", False)
    criteria = config.get("criteria")

    if isinstance(images, (list, tuple)):
        images = np.mean(np.stack([np.asarray(i, dtype=np.float64) for i in images]), axis=0)
    images = np.asarray(images, dtype=np.float64)

    # RAW Bayer 图（2D）自动拆分 4 通道
    if images.ndim == 2 and len(cfa) == 4:
        images = split_bayer_channels(images)

    result = analyze_lens_shading(
        images, bin_size, thresh, cfa, support_extrapolation
    )

    metrics = {}
    ri_min = float(np.nanmin(np.stack([
        np.atleast_1d(result["ri_tl"]),
        np.atleast_1d(result["ri_tr"]),
        np.atleast_1d(result["ri_bl"]),
        np.atleast_1d(result["ri_br"]),
    ])))
    metrics["ri_tl"] = {"value": np.atleast_1d(result["ri_tl"]).tolist(), "status": "PASS"}
    metrics["ri_tr"] = {"value": np.atleast_1d(result["ri_tr"]).tolist(), "status": "PASS"}
    metrics["ri_bl"] = {"value": np.atleast_1d(result["ri_bl"]).tolist(), "status": "PASS"}
    metrics["ri_br"] = {"value": np.atleast_1d(result["ri_br"]).tolist(), "status": "PASS"}
    metrics["ri_diff"] = {"value": result["ri_diff"], "status": "PASS"}
    if result["green_red_shift"] is not None:
        metrics["green_red_shift"] = {
            "value": result["green_red_shift"], "status": "PASS"
        }
        metrics["green_blue_shift"] = {
            "value": result["green_blue_shift"], "status": "PASS"
        }

    if criteria:
        if "ri" in criteria:
            ri_status = "PASS" if ri_min >= criteria["ri"] else "FAIL"
            for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
                metrics[key]["status"] = ri_status
        if "ri_diff" in criteria:
            metrics["ri_diff"]["status"] = (
                "PASS" if result["ri_diff"] <= criteria["ri_diff"] else "FAIL"
            )
        if "green_red_shift" in criteria and result["green_red_shift"] is not None:
            metrics["green_red_shift"]["status"] = (
                "PASS" if result["green_red_shift"] <= criteria["green_red_shift"] else "FAIL"
            )
            metrics["green_blue_shift"]["status"] = (
                "PASS" if result["green_blue_shift"] <= criteria["green_blue_shift"] else "FAIL"
            )

    overall_pass = all(m["status"] == "PASS" for m in metrics.values())
    return {
        "metrics": metrics,
        "pass": overall_pass,
        "details": {
            "shading_profile": result["shading_profile"],
            "bin_means": result["bin_means"],
        },
    }


def analyze_multi_light(
    images_by_light: Dict[str, Union[np.ndarray, list]],
    config: dict,
) -> dict:
    """
    多光源 Shading 分析（软件规划"几种光源"扩展接口）。

    对每种光源分别执行 analyze_relative_illumination 并汇总。

    Args:
        images_by_light: {光源名: 图像或图像列表}，如 {"D65": img1, "TL84": img2}
        config: 同 analyze_relative_illumination

    Returns:
        {
            "lights": {光源名: analyze_relative_illumination 结果},
            "pass": bool,            # 所有光源均 PASS 才为 True
            "comparison": {          # 跨光源比较
                "ri_min_per_light": {光源名: float},
                "ri_spread": float,  # 各光源最差 RI 的离散度（max-min）
            },
        }
    """
    lights = {}
    ri_min_per_light = {}
    for light_name, images in images_by_light.items():
        result = analyze_relative_illumination(images, config)
        lights[light_name] = result
        ri_values = []
        for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
            ri_values.extend(np.atleast_1d(result["metrics"][key]["value"]))
        ri_min_per_light[light_name] = float(np.nanmin(ri_values))

    overall_pass = all(r["pass"] for r in lights.values())
    ri_values = list(ri_min_per_light.values())
    return {
        "lights": lights,
        "pass": overall_pass,
        "comparison": {
            "ri_min_per_light": ri_min_per_light,
            "ri_spread": float(max(ri_values) - min(ri_values)) if ri_values else 0.0,
        },
    }
