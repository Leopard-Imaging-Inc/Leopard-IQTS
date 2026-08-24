"""
Image downsampling (binning) utilities.

Extracted from LeopardIQ0529/leopardiq/utils/bin_image.py.
对图像按给定因子做块平均下采样，支持单通道与多通道图像。

Original: bin_image.py (leopard, 2021-4-28 yunlong)
"""

from typing import Tuple

import numpy as np


def _bin_single_channel(img: np.ndarray, factor_x: int, factor_y: int) -> np.ndarray:
    """对单通道图像做块平均下采样，边缘不足一个 block 的部分居中裁剪。"""
    height, width = img.shape
    offset_y = int(np.mod(height, factor_y) // 2)
    offset_x = int(np.mod(width, factor_x) // 2)

    crop = img[
        offset_y: height - offset_y if offset_y else height,
        offset_x: width - offset_x if offset_x else width,
    ]
    # 裁剪到 factor 的整数倍，保证 reshape 尺寸一致
    num_y = crop.shape[0] // factor_y
    num_x = crop.shape[1] // factor_x
    crop = crop[: num_y * factor_y, : num_x * factor_x]

    # Fortran 序 reshape 与原实现保持一致：先按 factor 分块再求均值
    reshaped = np.reshape(
        crop, (factor_y, num_y, factor_x, num_x), order="F"
    )
    return np.squeeze(np.mean(np.mean(reshaped, axis=2), axis=0))


def bin_image(img: np.ndarray, factor_x: int, factor_y: int) -> np.ndarray:
    """
    块平均下采样。

    Args:
        img: 输入图像，shape 为 (H, W) 或 (H, W, C)
        factor_x: x 方向下采样因子
        factor_y: y 方向下采样因子

    Returns:
        下采样图像，shape 为 (H/factor_y, W/factor_x) 或 (H/factor_y, W/factor_x, C)

    Note:
        当图像尺寸不能被 factor 整除时，多余边缘按居中方式裁剪后再分块。
    """
    if factor_x < 1 or factor_y < 1:
        raise ValueError("Downsample factors must be >= 1")

    if img.ndim == 2:
        return _bin_single_channel(img, factor_x, factor_y)

    if img.ndim == 3:
        height, width, channels = img.shape
        num_y = (height - int(np.mod(height, factor_y))) // factor_y
        num_x = (width - int(np.mod(width, factor_x))) // factor_x
        binned = np.zeros((num_y, num_x, channels))
        for channel in range(channels):
            binned[:, :, channel] = _bin_single_channel(
                img[:, :, channel], factor_x, factor_y
            )
        return binned

    raise ValueError(f"Unsupported image dimension: {img.ndim}")
