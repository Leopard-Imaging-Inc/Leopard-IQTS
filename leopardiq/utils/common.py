"""
Common morphological / geometry utility functions.

Extracted from LeopardIQ0529/leopardiq/utils/utils.py:
- generate_strel_disk()  → create_disk_structuring_element()
- bwareafilt_py()        → extract_largest_region()
- round_integral()       → round_half_up()
- filter_centroid()      → filter_centroid()（保持原名）

Original: utils.py (leopard)
"""

from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Tuple

import numpy as np


def create_disk_structuring_element(radius: int = 10) -> np.ndarray:
    """
    生成圆盘状结构元素（对应 MATLAB: se = strel('disk', radius)）。

    OpenCV 的 cv2.getStructuringElement() 仅支持矩形/交叉/椭圆，
    此函数生成与 MATLAB disk 更接近的八边形近似。

    Args:
        radius: 圆盘半径

    Returns:
        (2*radius-1, 2*radius-1) 的 uint8 掩膜（1 为结构元素内部）
    """
    size = 2 * radius - 1
    strel = np.ones((size, size), dtype=np.uint8)
    border_width = int(radius / 2 - 1)
    for i in range(border_width):
        for j in range(border_width - i):
            strel[i, j] = 0
            strel[i, size - 1 - j] = 0
            strel[size - 1 - i, j] = 0
            strel[size - 1 - i, size - 1 - j] = 0
    return strel


def extract_largest_region(mask: np.ndarray) -> np.ndarray:
    """
    保留二值掩膜中面积最大的连通区域，其余置 0
    （对应 MATLAB bwareafilt 的单区域模式）。

    Args:
        mask: 二值图（白底黑图需先反转为"黑底白图"，OpenCV 以白色为前景）

    Returns:
        与原图同尺寸的 int8 掩膜，最大连通区域为 1，其余为 0

    Note:
        此函数惰性导入 opencv-python（cv2），仅在调用时要求安装。
    """
    import cv2

    height, width = mask.shape
    _, labels, stats, centroids = cv2.connectedComponentsWithStats(mask)
    # stats[0] 是背景，排除后选择面积最大的前景连通域
    largest_index = 1 + int(np.argsort(stats[1:, -1])[::-1][0])
    centroid_x, centroid_y = centroids[largest_index]
    label = labels[int(centroid_y), int(centroid_x)]
    mask_out = np.zeros((height, width), dtype=np.int8)
    mask_out[np.where(labels == label)] = 1
    return mask_out


def round_half_up(number: float) -> int:
    """
    四舍五入取整（0.5 向上）。

    Python 内置 round() 采用 banker's rounding：
        round(1.5) == 2, round(2.5) == 2
    本函数保证 round_half_up(2.5) == 3，与 MATLAB round 行为一致。

    Args:
        number: 待取整的数

    Returns:
        取整后的整数
    """
    with localcontext() as ctx:
        ctx.rounding = ROUND_HALF_UP
        return int(Decimal(number).to_integral_value())


def filter_centroid(
    centroid_choose: np.ndarray,
    chart_diag: float,
    ideal_point: np.ndarray,
    stats: np.ndarray,
    distance_percentage: float = 0.05,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    根据质心与理想点的归一化距离筛选有效质心。

    判定条件：min(||centroid - ideal_point||) / chart_diag < distance_percentage

    Args:
        centroid_choose: 候选质心坐标数组 (N, M, 2)
        chart_diag: 图像对角线长度（用于归一化）
        ideal_point: 理想质心坐标
        stats: 候选区域统计信息（与 centroid_choose 对齐，同步筛选）
        distance_percentage: 距离阈值（占对角线比例），默认 5%

    Returns:
        (filtered_centroids, filtered_stats)
    """
    index_choose = []
    for index, centroid_point in enumerate(centroid_choose):
        distances = np.linalg.norm(centroid_point - ideal_point, axis=1)
        if np.min(distances) / chart_diag < distance_percentage:
            index_choose.append(index)
    return centroid_choose[index_choose], stats[index_choose]
