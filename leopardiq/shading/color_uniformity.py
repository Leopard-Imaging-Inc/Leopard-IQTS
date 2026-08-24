"""
Color 比例 / 色彩均匀性分析。

提取自 LeopardIQ0529/leopardiq/light/lens_shading.py 的 calculate_channel_shift，
并按软件规划扩展为统一的 Color 模块：

- compute_channel_ratios()：Bayer 四通道均值比例（R:Gr:Gb:B）
- compute_wb_gains()：白平衡增益（R/G, B/G）
- compute_color_shading()：Color Shading（green_red/blue_shift，全画面分布）

注：若"Color 比例"指色彩还原准确度（ΔE），算法库未实现，列入 Phase 3。
"""

from typing import Optional

import numpy as np

from leopardiq.utils.image_preprocess import get_bayer_index, split_bayer_channels

from .shading_profile import calculate_channel_shift


def _prepare_channel_image(image: np.ndarray, cfa: list) -> np.ndarray:
    """接受 RAW (H,W) 或已拆分 (H/2,W/2,4)，返回 (h, w, 4) float 图像。"""
    image = np.asarray(image, dtype=np.float64)
    if image.ndim == 2:
        image = split_bayer_channels(image)
    if image.ndim != 3 or image.shape[-1] != 4:
        raise ValueError(
            f"Expected RAW Bayer or 4-channel image, got shape {image.shape}"
        )
    return image


def compute_channel_ratios(image: np.ndarray, cfa: list) -> dict:
    """
    Bayer 四通道均值及比例。

    Args:
        image: RAW Bayer (H, W) 或拆分后 (H/2, W/2, 4)
        cfa: Bayer 顺序

    Returns:
        {
            "means": {"R": ..., "Gr": ..., "Gb": ..., "B": ...},
            "ratios": {"R": ..., "Gr": ..., "Gb": ..., "B": ...},  # 占总和比例
            "ratios_to_g": {"R/G": ..., "B/G": ..., "Gb/Gr": ...},
        }
    """
    image = _prepare_channel_image(image, cfa)
    gr_index, red_index, blue_index, gb_index = get_bayer_index(cfa)

    means = {
        "R": float(np.nanmean(image[:, :, red_index])),
        "Gr": float(np.nanmean(image[:, :, gr_index])),
        "Gb": float(np.nanmean(image[:, :, gb_index])),
        "B": float(np.nanmean(image[:, :, blue_index])),
    }
    total = sum(means.values())
    green = (means["Gr"] + means["Gb"]) / 2
    ratios = {k: v / total for k, v in means.items()}
    ratios_to_g = {
        "R/G": means["R"] / green if green else np.nan,
        "B/G": means["B"] / green if green else np.nan,
        "Gb/Gr": means["Gb"] / means["Gr"] if means["Gr"] else np.nan,
    }
    return {"means": means, "ratios": ratios, "ratios_to_g": ratios_to_g}


def compute_wb_gains(image: np.ndarray, cfa: list) -> dict:
    """
    白平衡增益：使 R、B 通道与 G 通道相等所需的增益。

    Returns:
        {"r_gain": G/R, "b_gain": G/B, "g_gain": 1.0}
    """
    ratios = compute_channel_ratios(image, cfa)
    means = ratios["means"]
    green = (means["Gr"] + means["Gb"]) / 2
    return {
        "r_gain": green / means["R"] if means["R"] else np.nan,
        "g_gain": 1.0,
        "b_gain": green / means["B"] if means["B"] else np.nan,
    }


def compute_color_shading(
    image: np.ndarray,
    cfa: list,
    bin_size: int = 16,
    thresh: float = 0,
) -> dict:
    """
    Color Shading（色彩均匀性）：全画面 G/R、G/B 分布的离散程度。

    复用原 lens_shading 的 calculate_channel_shift 逻辑。

    Args:
        image: RAW Bayer (H, W) 或拆分后 (H/2, W/2, 4)
        cfa: Bayer 顺序
        bin_size: 分块尺寸
        thresh: 平场掩膜阈值（0 = 全图有效）

    Returns:
        {
            "green_red_shift": float,
            "green_blue_shift": float,
            "gr_ratio_map": (h, w) G/R 分布图,
            "gb_ratio_map": (h, w) G/B 分布图,
        }
    """
    from .shading_profile import bin_image_means, create_flat_field_mask

    image = _prepare_channel_image(image, cfa)
    height, width, channel = image.shape
    gr_index, red_index, blue_index, gb_index = get_bayer_index(cfa)

    mask = create_flat_field_mask(image, thresh, gr_index)
    image = image.copy()
    image[mask == 0, :] = np.nan

    import math

    start_axisx = int(math.floor(np.mod(width, bin_size) / 2))
    start_axisy = int(math.floor(np.mod(height, bin_size) / 2))
    axisx = np.array(range(start_axisx, width, bin_size))
    axisy = np.array(range(start_axisy, height, bin_size))
    means = bin_image_means(axisx, axisy, bin_size, image, mask)

    green_red_shift, green_blue_shift = calculate_channel_shift(cfa, means)

    green = np.nanmean(
        np.stack([means[:, :, gr_index], means[:, :, gb_index]], axis=2), axis=2
    )
    gr_ratio_map = green / means[:, :, red_index]
    gb_ratio_map = green / means[:, :, blue_index]

    return {
        "green_red_shift": green_red_shift,
        "green_blue_shift": green_blue_shift,
        "gr_ratio_map": gr_ratio_map,
        "gb_ratio_map": gb_ratio_map,
    }


def analyze_color_uniformity(image: np.ndarray, config: dict) -> dict:
    """
    标准接口的 Color 比例分析（软件规划统一接口）。

    Args:
        image: RAW Bayer (H, W) 或拆分后 (H/2, W/2, 4)
        config: {
            "cfa": [...],
            "bin_size": int (可选，默认 16),
            "thresh": float (可选，默认 0),
            "criteria": {                    # 可选
                "green_red_shift": float,    # 上限
                "green_blue_shift": float,   # 上限
                "r_gain": [min, max],        # 白平衡增益范围
                "b_gain": [min, max],
            },
        }

    Returns:
        {"metrics": {...}, "pass": bool, "details": {...}}
    """
    cfa = config["cfa"]
    bin_size = config.get("bin_size", 16)
    thresh = config.get("thresh", 0)
    criteria = config.get("criteria", {})

    shading = compute_color_shading(image, cfa, bin_size, thresh)
    ratios = compute_channel_ratios(image, cfa)
    wb = compute_wb_gains(image, cfa)

    metrics = {
        "green_red_shift": {
            "value": shading["green_red_shift"],
            "status": "PASS",
        },
        "green_blue_shift": {
            "value": shading["green_blue_shift"],
            "status": "PASS",
        },
        "r_gain": {"value": wb["r_gain"], "status": "PASS"},
        "b_gain": {"value": wb["b_gain"], "status": "PASS"},
        "channel_ratios": {"value": ratios["ratios"], "status": "PASS"},
    }

    if "green_red_shift" in criteria:
        metrics["green_red_shift"]["status"] = (
            "PASS" if shading["green_red_shift"] <= criteria["green_red_shift"] else "FAIL"
        )
    if "green_blue_shift" in criteria:
        metrics["green_blue_shift"]["status"] = (
            "PASS" if shading["green_blue_shift"] <= criteria["green_blue_shift"] else "FAIL"
        )
    for key, gain_key in (("r_gain", "r_gain"), ("b_gain", "b_gain")):
        if gain_key in criteria:
            lo, hi = criteria[gain_key]
            value = wb[gain_key]
            metrics[key]["status"] = "PASS" if lo <= value <= hi else "FAIL"

    overall_pass = all(m["status"] == "PASS" for m in metrics.values())
    return {
        "metrics": metrics,
        "pass": overall_pass,
        "details": {
            "channel_means": ratios["means"],
            "ratios_to_g": ratios["ratios_to_g"],
            "gr_ratio_map": shading["gr_ratio_map"],
            "gb_ratio_map": shading["gb_ratio_map"],
        },
    }
