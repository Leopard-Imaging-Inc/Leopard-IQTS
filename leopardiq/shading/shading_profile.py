"""
Lens Shading 轮廓计算与插值工具。

提取自 LeopardIQ0529/leopardiq/utils/len_shading_utils.py：
- get_mask()                    → create_flat_field_mask()
- generate_binsize_image()      → bin_image_means()
- get_choose_coordinates()      → get_bin_coordinates()
- interp_shading_profile()      → interp_shading_profile()（保持原名）
- interp_griddata / interp2d_rbf / extrapolation_*

并包含原 lens_shading.py 中的：
- get_illum()                   → compute_quadrant_ri()
- calculate_channel_shift()     → calculate_channel_shift()（保持原名）
"""

import math
from typing import Tuple

import numpy as np
import scipy.interpolate as interp

from leopardiq.utils.common import create_disk_structuring_element, extract_largest_region
from leopardiq.utils.image_preprocess import get_bayer_index


def create_flat_field_mask(
    imgs: np.ndarray, thresh: float, gr_index: int
) -> np.ndarray:
    """
    生成平场有效区域掩膜（原 get_mask）。

    thresh != 0 时：取 Gr 通道 > thresh 的区域，disk 结构元素腐蚀后保留最大连通域，
    用于排除图像边缘/污染区域；thresh == 0 时返回全 1 掩膜。

    Args:
        imgs: (H, W, C) 图像
        thresh: DN 阈值
        gr_index: Gr 通道下标（mono 传 0）

    Returns:
        (H, W) uint8 掩膜
    """
    height, width = imgs.shape[:2]
    if thresh != 0:
        import cv2

        mask = imgs[:, :, gr_index] > thresh  # TODO: 通道可配置
        strel_disk = create_disk_structuring_element(10)
        mask = np.array(mask, dtype=np.uint8)
        mask = cv2.erode(mask, strel_disk)
        mask = extract_largest_region(mask).astype(np.uint8)
    else:
        mask = np.ones((height, width), dtype=np.uint8)
    return mask


def get_bin_coordinates(
    image_axisy: float,
    image_axisx: float,
    bin_size: int,
    width: int,
    height: int,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    以 (image_axisy, image_axisx) 为中心取 bin_size × bin_size 邻域坐标（原 get_choose_coordinates）。

    Returns:
        (range_x, range_y)，已裁剪到图像范围内
    """
    range_x = np.array(
        range(
            int(math.floor(image_axisx - bin_size / 2)),
            int(math.floor(image_axisx + bin_size / 2) + 1),
            1,
        )
    )
    range_x = range_x[np.where(range_x >= 0)]
    range_x = range_x[np.where(range_x < width)]
    range_y = np.array(
        range(
            int(math.floor(image_axisy - bin_size / 2)),
            int(math.floor(image_axisy + bin_size / 2) + 1),
            1,
        )
    )
    range_y = range_y[np.where(range_y >= 0)]
    range_y = range_y[np.where(range_y < height)]
    return range_x, range_y


def bin_image_means(
    axisx: np.ndarray,
    axisy: np.ndarray,
    bin_size: int,
    imgs: np.ndarray,
    mask: np.ndarray,
) -> np.ndarray:
    """
    按 bin_size 网格对图像分块求均值（原 generate_binsize_image）。

    mask 为 0 的网格输出 NaN（边缘/无效区域）。

    Returns:
        (len(axisy), len(axisx), C) 均值数组
    """
    height, width, channel = imgs.shape
    means = np.zeros((axisy.shape[0], axisx.shape[0], channel))
    for px in range(len(axisx)):
        for py in range(len(axisy)):
            image_axisx = axisx[px]
            image_axisy = axisy[py]
            if mask[image_axisy, image_axisx] == 1:
                range_x, range_y = get_bin_coordinates(
                    image_axisy, image_axisx, bin_size, width, height
                )
                if range_y.size > 0 and range_x.size > 0:
                    start_x, end_x = range_x[0], range_x[-1]
                    start_y, end_y = range_y[0], range_y[-1]
                    means[py, px, :] = np.nanmean(
                        imgs[start_y: end_y + 1, start_x: end_x + 1, :],
                        axis=(0, 1),
                    )
            else:
                means[py, px, :] = np.nan
    return means


def compute_quadrant_ri(
    final_pv: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    计算四象限相对照度（原 get_illum）。

    shading = final_pv / max(final_pv)，取各象限最小值为该象限 RI。

    Returns:
        (bl_ri, br_ri, tl_ri, tr_ri, shading)
    """
    max_pv = np.nanmax(final_pv, axis=(0, 1))
    shading = final_pv / max_pv
    height, img_width = final_pv.shape[:2]
    height = int(np.floor(height / 2))
    img_width = int(np.floor(img_width / 2))
    tl_rel_illum = np.nanmin(shading[0:height, 0:img_width], axis=(0, 1))
    tr_rel_illum = np.nanmin(shading[0:height, img_width:], axis=(0, 1))
    bl_rel_illum = np.nanmin(shading[height:, 0:img_width], axis=(0, 1))
    br_rel_illum = np.nanmin(shading[height:, img_width:], axis=(0, 1))
    return bl_rel_illum, br_rel_illum, tl_rel_illum, tr_rel_illum, shading


def calculate_channel_shift(cfa: list, final_pv: np.ndarray) -> Tuple[float, float]:
    """
    计算 Color Shading（原 calculate_channel_shift）。

    green_red_shift = max(|1 - max(G/R) / min(G/R)|)
    green_blue_shift = max(|1 - max(G/B) / min(G/B)|)

    Args:
        cfa: Bayer 顺序，如 ["Gr", "R", "B", "Gb"]
        final_pv: bin 均值图像 (h, w, 4)

    Returns:
        (green_red_shift, green_blue_shift)
    """
    gr_index, red_index, blue_index, gb_index = get_bayer_index(cfa)
    green = np.nanmean(
        np.stack([final_pv[:, :, gr_index], final_pv[:, :, gb_index]], axis=2), axis=2
    )
    red = final_pv[:, :, red_index]
    blue = final_pv[:, :, blue_index]
    green_red = green / red
    green_blue = green / blue
    green_red_shift = np.nanmax(np.abs(1 - np.nanmax(green_red) / np.nanmin(green_red)))
    green_blue_shift = np.nanmax(
        np.abs(1 - np.nanmax(green_blue) / np.nanmin(green_blue))
    )
    return float(green_red_shift), float(green_blue_shift)


# ----------------------------------------------------------------------
# 插值
# ----------------------------------------------------------------------
def interp_griddata(
    axisx: np.ndarray,
    axisy: np.ndarray,
    axisx2: np.ndarray,
    axisy2: np.ndarray,
    shading: np.ndarray,
) -> np.ndarray:
    """
    网格数据线性插值（支持 shading 含 NaN、非规则网格，不支持外插）。
    """
    axisxy = np.array([axisx.ravel(), axisy.ravel()]).T
    return interp.griddata(
        axisxy, shading.ravel(), (axisx2, axisy2), method="linear"
    )


def interp2d_rbf(
    axisx: np.ndarray,
    axisy: np.ndarray,
    axisx2: np.ndarray,
    axisy2: np.ndarray,
    shading: np.ndarray,
) -> np.ndarray:
    """
    RBF 插值（支持外插；shading 中不允许有 NaN）。
    """
    f_rbf = interp.Rbf(axisx, axisy, shading, function="linear", smooth=0)
    return f_rbf(axisx2, axisy2)


def _convert_one_list(input_list: list, out_list: list) -> None:
    for list_data in input_list:
        for data in list_data:
            out_list.append(data)


def _get_interp_nan_index(
    bin_size: int,
    start_x: int,
    start_y: int,
    nan_index: tuple,
    width: int,
    height: int,
) -> np.ndarray:
    """
    根据 shading（下采样网格）中 NaN 的位置，推测插值后 shading_profile 中
    对应 NaN 的坐标范围（一个网格点辐射 ±bin_size）。
    """
    interval = np.array(range(int(-bin_size), int(bin_size)))
    new_axisx, new_axisy = [], []
    new_axisx_out, new_axisy_out = [], []
    for index in range(len(nan_index[0])):
        axisx = nan_index[1][index]
        axisy = nan_index[0][index]
        choose_index_axisy = ((axisy) * bin_size + interval + start_y).tolist()
        choose_index_axisx = (axisx * bin_size + interval + start_x).tolist()
        choose_index_axisx, choose_index_axisy = np.meshgrid(
            np.array(choose_index_axisx), np.array(choose_index_axisy)
        )
        new_axisx.append(choose_index_axisx.ravel().tolist())
        new_axisy.append(choose_index_axisy.ravel().tolist())
    _convert_one_list(new_axisx, new_axisx_out)
    _convert_one_list(new_axisy, new_axisy_out)

    new_index = np.array([np.array(new_axisy_out), np.array(new_axisx_out)])
    flag_maximum = np.logical_and(new_index[0] < height, new_index[1] < width)
    new_index = new_index[:, flag_maximum]
    flag_zeros = np.logical_and(new_index[0] >= 0, new_index[1] >= 0)
    return new_index[:, flag_zeros]


def _extrapolation_without_nan(
    shading_profile: np.ndarray,
    channel: int,
    axisy: np.ndarray,
    axisx: np.ndarray,
    axisy2: np.ndarray,
    axisx2: np.ndarray,
    shading: np.ndarray,
) -> None:
    """先 griddata 整体插值，再用 RBF 填补外插区域的 NaN。"""
    shading_profile[:, :, channel] = interp_griddata(
        axisy, axisx, axisy2, axisx2, shading
    )
    nan_index = np.where(np.isnan(shading_profile[:, :, channel]))
    nan_y = nan_index[0]
    nan_x = nan_index[1]
    data_temp = interp2d_rbf(axisy, axisx, nan_y, nan_x, shading)
    shading_profile[nan_y, nan_x, channel] = data_temp


def _extrapolation_with_nan(
    axisx: np.ndarray,
    axisx2: np.ndarray,
    axisy: np.ndarray,
    axisy2: np.ndarray,
    bin_size: int,
    channel: int,
    height: int,
    shading: np.ndarray,
    shading_nan_flag: np.ndarray,
    shading_profile: np.ndarray,
    start_x: int,
    start_y: int,
    width: int,
) -> None:
    """shading 含 NaN 时的插值：取非 NaN 点插值，再把 NaN 辐射区重新置 NaN。"""
    shading_non_nan_index = np.where(~shading_nan_flag)
    shading_temp = shading[:, :, channel][shading_non_nan_index]
    axisx_temp = axisx[shading_non_nan_index]
    axisy_temp = axisy[shading_non_nan_index]

    _extrapolation_without_nan(
        shading_profile, channel, axisy_temp, axisx_temp, axisy2, axisx2, shading_temp
    )

    shading_data_nan_index = np.where(np.isnan(shading[:, :, channel]))
    nan_index_new = _get_interp_nan_index(
        bin_size, start_x, start_y, shading_data_nan_index, width, height
    )
    shading_profile[nan_index_new[0], nan_index_new[1], channel] = np.nan


def interp_shading_profile(
    bin_size: int,
    channels: int,
    height: int,
    shading: np.ndarray,
    start_x: int,
    start_y: int,
    width: int,
    support_extrapolation: bool = True,
) -> np.ndarray:
    """
    将 bin 网格 shading 插值回原图分辨率（保持原名）。

    support_extrapolation=True 时先用 griddata 内插、RBF 外插（更精确但更慢）；
    False 时仅 griddata（边缘可能含 NaN，速度快、内存省）。

    Returns:
        (height, width, channels) shading profile
    """
    shading_profile = np.zeros((height, width, channels))
    axisx, axisy = np.meshgrid(
        np.array(range(start_x, width, bin_size)),
        np.array(range(start_y, height, bin_size)),
    )
    axisx2, axisy2 = np.meshgrid(np.array(range(0, width)), np.array(range(0, height)))

    for channel in range(channels):
        if support_extrapolation:
            shading_nan_flag = np.isnan(shading[:, :, channel])
            nan_index = np.where(shading_nan_flag)
            if nan_index[0].size > 0:
                _extrapolation_with_nan(
                    axisx, axisx2, axisy, axisy2, bin_size, channel, height,
                    shading, shading_nan_flag, shading_profile, start_x, start_y,
                    width,
                )
            else:
                _extrapolation_without_nan(
                    shading_profile, channel, axisy, axisx, axisy2, axisx2,
                    shading[:, :, channel],
                )
        else:
            shading_profile[:, :, channel] = interp_griddata(
                axisy, axisx, axisy2, axisx2, shading[:, :, channel]
            )
    return shading_profile
