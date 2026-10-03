"""
Relative Illumination（相对照度 / 亮度 Shading）分析 —— 单光源 Shading 子功能。

提取自 LeopardIQ0529/leopardiq/light/lens_shading.py。

核心流程：
1. 按 thresh 生成平场掩膜（排除边缘/污染）
2. 按 bin_size 网格分块求均值
3. 归一化后取四象限最小值作为 RI
4. 插值生成全分辨率 shading profile（供 LSC 使用）
5. Bayer 输入时同时计算 Color Shading（green_red/blue_shift）

多光源对比分析已解耦至 `multi_light.py`（`analyze_multi_light`）。
"""

import math
from typing import Tuple, Union

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


def _is_pass(status) -> bool:
    """判断指标是否 PASS；status 可为字符串或逐通道列表。"""
    if isinstance(status, (list, tuple, np.ndarray)):
        return all(s == "PASS" for s in status)
    return status == "PASS"


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
    for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
        vals = np.atleast_1d(result[key])
        metrics[key] = {"value": vals.tolist(), "status": ["PASS"] * len(vals)}
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
            for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
                metrics[key]["status"] = [
                    "PASS" if float(v) >= criteria["ri"] else "FAIL"
                    for v in np.atleast_1d(result[key])
                ]
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

    overall_pass = all(_is_pass(m["status"]) for m in metrics.values())
    return {
        "metrics": metrics,
        "pass": overall_pass,
        "details": {
            "shading_profile": result["shading_profile"],
            "bin_means": result["bin_means"],
        },
    }
