"""
Lens Shading Correction（LSC，镜头阴影校正）。

提取自 LeopardIQ0529/leopardiq/light/lsc.py。

修复：原实现会将结果写入硬编码路径 'data/PI/output_image.jpg'，
提取后移除该副作用，仅返回校正后的图像。
"""

import numpy as np


def apply_lsc(img: np.ndarray, shading_profile: np.ndarray) -> np.ndarray:
    """
    应用镜头阴影校正。

    校正方式：img_out = img / shading_profile
    （shading_profile 为相对照度图，中心≈1，边缘<1）

    Args:
        img: 输入图像 (H, W, C)
        shading_profile: 相对照度图，分辨率须与 img 相同

    Returns:
        校正后的图像（float）
    """
    img = np.asarray(img, dtype=np.float64)
    shading_profile = np.asarray(shading_profile, dtype=np.float64)
    if img.shape[:2] != shading_profile.shape[:2]:
        raise ValueError(
            f"shading_profile resolution {shading_profile.shape[:2]} "
            f"does not match image {img.shape[:2]}"
        )
    with np.errstate(divide="ignore", invalid="ignore"):
        falloff = np.divide(1.0, shading_profile)
        img_out = np.multiply(img, falloff)
    # shading_profile 中的 NaN/0 区域保持为 NaN，便于后续掩膜处理
    return img_out
