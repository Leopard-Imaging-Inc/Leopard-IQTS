"""
多方格（e-SFR 风格）SFR 标板几何与边缘定位。

提取自 LeopardIQ0529/leopardiq/utils/sfr_main_utils.py：
- init_main_parameter()  → init_square_chart_params()
- deal_parameter()       → compute_chart_geometry()
- find_one_edge_pos()    → find_one_edge_pos()（保持原名）
- search_edge_centers_in_binary_image()（保持原名）
- get_roi_mtf()          → extract_edge_roi_sfr()

图表参数与配置文件强绑定，因此保留 config_sensor 字典驱动方式。
"""

import math
import warnings
from typing import Dict, List, Tuple

import numpy as np

from .mtf_calculator import compute_roi_sfr


def init_square_chart_params(config_sensor: dict, config_key: str = "sfrnv") -> dict:
    """
    从 sensor 配置初始化多方格标板参数（原 init_main_parameter）。

    Args:
        config_sensor: sensor 配置字典，需包含 config_key 节
        config_key: 配置节名称（默认 "sfrnv"）

    Returns:
        参数字典：
        - frequency: 采样频率数组（freqs * nyq_freq）
        - main_frequency: 主评估频率（main_freq * nyq_freq，缺省为 max(frequency)）
        - horizontal_index / vertical_index: 水平/垂直 ROI 布尔掩膜
        - min_patch_size / patch_size / patch_angles / patch_names
        - square_size / square_names / square_distances / square_angles / square_rotations
        - nyquist_frequency / number_frequency
    """
    params = config_sensor[config_key]["params"]

    square_size = params["square_size"]
    square_names = params["square_names"]
    square_distances = np.array(params["square_distances"])
    square_angles = np.array(params["square_angles"])
    square_rotations = params["square_rotations"]
    patch_size = np.array(params["sb_patch_size"])
    min_patch_size = params["min_patch_size"]
    patch_names = params["sub_patch_names"]
    patch_angles = np.array(params["sub_patch_angles"])

    frequency = np.array(params["freqs"]) * np.array(params["nyq_freq"])
    nyquist_frequency = params["nyq_freq"]
    number_frequency = len(frequency)

    horizontal_index = np.logical_or(
        "l" == np.array(patch_names), "r" == np.array(patch_names)
    )
    vertical_index = np.logical_or(
        "t" == np.array(patch_names), "b" == np.array(patch_names)
    )
    if "main_freq" in params:
        main_frequency = params["main_freq"] * params["nyq_freq"]
    else:
        main_frequency = max(frequency)

    return {
        "frequency": frequency,
        "horizontal_index": horizontal_index,
        "min_patch_size": min_patch_size,
        "number_frequency": number_frequency,
        "patch_angles": patch_angles,
        "patch_names": patch_names,
        "patch_size": patch_size,
        "square_angles": square_angles,
        "square_distances": square_distances,
        "square_names": square_names,
        "square_rotations": square_rotations,
        "square_size": square_size,
        "vertical_index": vertical_index,
        "nyquist_frequency": nyquist_frequency,
        "main_frequency": main_frequency,
    }


def compute_chart_geometry(
    image_average: np.ndarray,
    patch_size: np.ndarray,
    square_angles: np.ndarray,
    square_distances: np.ndarray,
    square_size: float,
) -> dict:
    """
    根据图像尺寸与标板参数计算各方格的理想位置（原 deal_parameter）。

    Returns:
        字典：chart_diag, ideal_patch_axisx, ideal_patch_axisy, image_channel,
        image_height, image_width, patch_dist_pixel, patch_size_pixel,
        square_size_pixel, patch_size_major, patch_size_minor
    """
    image_height, image_width, image_channel = image_average.shape
    chart_diag = math.sqrt(image_height ** 2 + image_width ** 2)
    center_axisx = image_width / 2 + 0.5
    center_axisy = image_height / 2 + 0.5

    square_size_pixel = square_size * chart_diag
    patch_distance = 0.5 * chart_diag * square_distances
    ideal_patch_axisx = (
        patch_distance * np.cos(np.deg2rad(square_angles)) + center_axisx
    )
    ideal_patch_axisy = center_axisy - patch_distance * np.sin(
        np.deg2rad(square_angles)
    )
    patch_dist_pixel = chart_diag * square_size * 0.5
    patch_size_pixel = chart_diag * patch_size * 0.5

    if isinstance(patch_size_pixel, np.ndarray) and patch_size_pixel.size >= 2:
        patch_size_major = patch_size_pixel[0]
        patch_size_minor = patch_size_pixel[1]
    else:
        patch_size_major = patch_size_pixel
        patch_size_minor = patch_size_major

    return {
        "chart_diag": chart_diag,
        "ideal_patch_axisx": ideal_patch_axisx,
        "ideal_patch_axisy": ideal_patch_axisy,
        "image_channel": image_channel,
        "image_height": image_height,
        "image_width": image_width,
        "patch_dist_pixel": patch_dist_pixel,
        "patch_size_pixel": patch_size_pixel,
        "square_size_pixel": square_size_pixel,
        "patch_size_major": patch_size_major,
        "patch_size_minor": patch_size_minor,
    }


def find_one_edge_pos(input_array: np.ndarray, center: tuple) -> Tuple[str, int, int]:
    """
    从二值图中心向四方向扫描，找到第一个黑白边界像素。

    Returns:
        (direction, posY, posX)：direction ∈ {"Up", "Down", "Left", "Right", "NA"}
    """
    array_height, array_width = input_array.shape
    pos_x, pos_y = center
    left_y = right_y = up_y = down_y = pos_y
    left_x = right_x = up_x = down_x = pos_x
    moving = True
    move_left = move_right = move_up = move_down = True
    while moving:
        if move_left:
            if input_array[left_y, left_x] == 0 and input_array[left_y, left_x - 1] == 255:
                return "Up", left_y, left_x
            left_x -= 1
            if left_x <= 1:
                move_left = False
        if move_right:
            if input_array[right_y, right_x] == 0 and input_array[right_y, right_x + 1] == 255:
                return "Down", right_y, right_x
            right_x += 1
            if right_x >= array_width - 1:
                move_right = False
        if move_up:
            if input_array[up_y, up_x] == 0 and input_array[up_y - 1, up_x] == 255:
                return "Right", up_y, up_x
            up_y -= 1
            if up_y <= 1:
                move_up = False
        if move_down:
            if input_array[down_y, down_x] == 0 and input_array[down_y + 1, down_x] == 255:
                return "Left", down_y, down_x
            down_y += 1
            if down_y >= array_height - 1:
                move_down = False
        if not move_left and not move_right and not move_up and not move_down:
            moving = False
    return "NA", pos_y, pos_x


def search_edge_centers_in_binary_image(
    input_array: np.ndarray,
    pos_x: int,
    pos_y: int,
    search_direction: str,
    search_range: tuple = (0, -1, 1, -2, 2),
) -> Tuple[bool, tuple, tuple, tuple, tuple, tuple, tuple, tuple, tuple]:
    """
    从单个边缘点出发沿黑色方格边缘追踪，求四条边的中点与四角坐标。

    Returns:
        (status, top_center, right_center, bottom_center, left_center,
         top_left, top_right, bottom_left, bottom_right)
    """
    array_height, array_width = input_array.shape
    search_done = False
    search_edge_count = 0
    top_left = top_right = bottom_left = bottom_right = (0, 0)

    while not search_done and search_edge_count < 5:
        while search_direction == "Right" and search_edge_count < 5 and not search_done:
            pos_x += 1
            if pos_x >= array_width:
                search_done = True
                break
            for i in search_range:
                if input_array[pos_y + i, pos_x] == 0 and input_array[pos_y + i - 1, pos_x] == 255:
                    pos_y += i
                    break
            if not (input_array[pos_y, pos_x] == 0 and input_array[pos_y - 1, pos_x] == 255):
                search_direction = "Down"
                search_edge_count += 1
                top_right = (pos_x, pos_y)
        while search_direction == "Down" and search_edge_count < 5 and not search_done:
            pos_y += 1
            if pos_y >= array_height - 5:
                search_done = True
                break
            for i in search_range:
                if input_array[pos_y, pos_x + i] == 0 and input_array[pos_y, pos_x + i + 1] == 255:
                    pos_x += i
                    break
            if not (input_array[pos_y, pos_x] == 0 and input_array[pos_y, pos_x + 1] == 255):
                search_direction = "Left"
                search_edge_count += 1
                bottom_right = (pos_x, pos_y)
        while search_direction == "Left" and search_edge_count < 5 and not search_done:
            pos_x -= 1
            if pos_x <= 5:
                search_done = True
                break
            for i in search_range:
                if input_array[pos_y + i, pos_x] == 0 and input_array[pos_y + i + 1, pos_x] == 255:
                    pos_y += i
                    break
            if not (input_array[pos_y + 1, pos_x] == 0 and input_array[pos_y, pos_x] == 255):
                search_direction = "Up"
                search_edge_count += 1
                bottom_left = (pos_x, pos_y)
        while search_direction == "Up" and search_edge_count < 5 and not search_done:
            pos_y -= 1
            if pos_y <= 5:
                search_done = True
                break
            for i in search_range:
                if input_array[pos_y, pos_x + i] == 0 and input_array[pos_y, pos_x + i - 1] == 255:
                    pos_x += i
                    break
            if not (input_array[pos_y, pos_x] == 0 and input_array[pos_y, pos_x - 1] == 255):
                search_direction = "Right"
                search_edge_count += 1
                top_left = (pos_x, pos_y)

    ret_top = (int((top_left[0] + top_right[0]) / 2), int((top_left[1] + top_right[1]) / 2))
    ret_right = (int((top_right[0] + bottom_right[0]) / 2), int((top_right[1] + bottom_right[1]) / 2))
    ret_bottom = (int((bottom_left[0] + bottom_right[0]) / 2), int((bottom_left[1] + bottom_right[1]) / 2))
    ret_left = (int((top_left[0] + bottom_left[0]) / 2), int((top_left[1] + bottom_left[1]) / 2))

    if search_edge_count >= 5:
        return True, ret_top, ret_right, ret_bottom, ret_left, top_left, top_right, bottom_left, bottom_right
    return False, ret_top, ret_right, ret_bottom, ret_left, top_left, top_right, bottom_left, bottom_right


def extract_edge_roi_sfr(
    image_average: np.ndarray,
    edge_center: tuple,
    padding_height: int,
    padding_width: int,
    patch_index: int,
    square_results: np.ndarray,
    frequency: np.ndarray,
    image_channel: int,
    gamma: float = 1.0,
) -> bool:
    """
    以边缘中点为中心截取 ROI 并计算 SFR（原 get_roi_mtf，去除 matplotlib 耦合）。

    Args:
        gamma: 编码 Gamma，计算前按 pixel^(1/gamma) 线性化
               （默认 1.0 = 不线性化，与旧行为一致）

    Returns:
        True 表示 ROI 计算有效（原实现中用于决定绘图颜色）
    """
    roi = image_average[
        edge_center[1] - padding_height: edge_center[1] + padding_height,
        edge_center[0] - padding_width: edge_center[0] + padding_width,
        :,
    ]
    return compute_roi_sfr(
        roi, frequency, image_channel, patch_index, square_results, gamma=gamma
    )


def compute_geometry_patch_rois(
    centroid: np.ndarray,
    patch_dist_pixel: float,
    patch_angles: np.ndarray,
    square_rotation: float,
    patch_size_major: float,
    patch_size_minor: float,
) -> List[Tuple[int, int, int, int]]:
    """
    按几何法计算方格四周 ROI 的边界框（原 sfr_ov2311 中的 patch 定位逻辑）。

    Returns:
        [(left, right, bottom, top), ...] 与 patch_angles 对齐
    """
    patch_axisx = (
        patch_dist_pixel * np.cos(np.deg2rad(patch_angles + square_rotation))
        + centroid[0]
    )
    patch_axisy = centroid[1] - patch_dist_pixel * np.sin(
        np.deg2rad(patch_angles + square_rotation)
    )
    boxes = []
    for patch in range(len(patch_angles)):
        if np.mod(patch_angles[patch] / 90, 2) == 1:
            left = np.round(patch_axisx[patch] - patch_size_major).astype(np.int64)
            right = np.round(patch_axisx[patch] + patch_size_major).astype(np.int64)
            top = np.round(patch_axisy[patch] + patch_size_minor).astype(np.int64)
            bottom = np.round(patch_axisy[patch] - patch_size_minor).astype(np.int64)
        else:
            left = np.round(patch_axisx[patch] - patch_size_minor).astype(np.int64)
            right = np.round(patch_axisx[patch] + patch_size_minor).astype(np.int64)
            top = np.round(patch_axisy[patch] + patch_size_major).astype(np.int64)
            bottom = np.round(patch_axisy[patch] - patch_size_major).astype(np.int64)
        boxes.append((int(left), int(right), int(bottom), int(top)))
    return boxes
