"""
Flare 测量区域提取（ISO 9358）。

提取自 LeopardIQ0529/leopardiq/flare/type_flare.py 与 type_C.py：
- get_Y()      → compute_region_luma()（向量化重写，原实现逐像素 Python 循环）
- get_plot()   → render_debug_overlay()（原实现直接 plt.show，提取后返回图像）

测量区域定义（与原库一致）：
- 黑斑区域：检测到的黑色圆斑内部（半径 r - D/70）
- 白色参考区域：黑斑上下左右 2r 处的等径圆区域

输入说明：
- 彩色图（BGR，cv2.imread 读取）：Y' luma = 0.299*R + 0.587*G + 0.114*B
- 灰度图（2D）：直接使用像素值作为亮度
- RAW 图需先转换为 8bit 灰度/彩色（本模块不处理 demosaic）
"""

from typing import Optional, Tuple

import cv2
import numpy as np

# 区域标志
REGION_BLACK = 0
REGION_WHITE_RIGHT = 1
REGION_WHITE_LEFT = 2
REGION_WHITE_DOWN = 3
REGION_WHITE_UP = 4


def detect_flare_circles(
    img_gray: np.ndarray,
    min_dist: int = 50,
    param1: int = 100,
    param2: int = 30,
    min_radius: int = 10,
    max_radius: int = 50,
    deblur: bool = False,
) -> Optional[np.ndarray]:
    """
    Hough 圆检测黑色圆斑。

    Args:
        img_gray: 灰度图
        min_dist / param1 / param2 / min_radius / max_radius: cv2.HoughCircles 参数
        deblur: 先去模糊再检测（适用于桶畸变图像；平整图像会变差）

    Returns:
        (N, 3) int 数组 [(x, y, r), ...]，未检测到返回 None
    """
    if deblur:
        img_gray = cv2.medianBlur(img_gray, 15)
        min_dist = int(img_gray.shape[1] / 30)
        param1, param2 = 25, 15
        min_radius, max_radius = 0, int(img_gray.shape[1] / 40)
    circles = cv2.HoughCircles(
        img_gray, cv2.HOUGH_GRADIENT, dp=1, minDist=min_dist,
        param1=param1, param2=param2,
        minRadius=min_radius, maxRadius=max_radius,
    )
    if circles is None:
        return None
    return np.round(circles[0, :]).astype(int)


def compute_d70(img_shape: tuple) -> float:
    """图像对角线 / 70（区域半径缩边量）。"""
    from math import sqrt

    h, w = img_shape[1], img_shape[0]
    return sqrt(pow(h, 2) + pow(w, 2)) / 70


def _to_luma_image(img: np.ndarray) -> np.ndarray:
    """转换为 luma 图：彩色按 Y' = 0.299R + 0.587G + 0.114B，灰度直接返回。"""
    if img.ndim == 3:
        # cv2.imread 读取为 BGR 顺序
        b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]
        return 0.2990 * r + 0.587 * g + 0.114 * b
    return img.astype(np.float64)


def compute_region_luma(
    img: np.ndarray,
    circles: np.ndarray,
    d70: float,
    region: int,
) -> list:
    """
    提取指定区域类型的逐圆斑 luma 均值列表（原 get_Y，向量化重写）。

    Args:
        img: 图像（BGR 彩色或 2D 灰度）
        circles: (N, 3) 圆斑 [(x, y, r), ...]
        d70: 对角线 / 70
        region: REGION_BLACK / REGION_WHITE_RIGHT / REGION_WHITE_LEFT /
                REGION_WHITE_DOWN / REGION_WHITE_UP

    Returns:
        [圆斑0的区域luma均值, 圆斑1的, ...]（无圆斑时为空列表）
    """
    values = []
    if circles is None:
        return values
    luma = _to_luma_image(img)
    circles = np.round(circles).astype(int)
    for (x, y, rad) in circles:
        if region == REGION_BLACK:
            cx, cy = x, y
        elif region == REGION_WHITE_RIGHT:
            cx, cy = int(x + rad + rad), y
        elif region == REGION_WHITE_LEFT:
            cx, cy = int(x - rad - rad), y
        elif region == REGION_WHITE_DOWN:
            cx, cy = x, int(y + rad + rad)
        elif region == REGION_WHITE_UP:
            cx, cy = x, int(y - rad - rad)
        else:
            raise ValueError(f"Unknown region flag: {region}")

        mask = np.zeros(img.shape[:2], dtype=np.uint8)
        radius = int(abs(rad - d70))
        if radius <= 0:
            values.append(np.nan)
            continue
        cv2.circle(mask, (cx, cy), radius, 255, -1)
        pixels = luma[mask != 0]
        values.append(float(np.mean(pixels)) if pixels.size else np.nan)
    return values


def render_debug_overlay(
    img: np.ndarray, circles: np.ndarray, d70: float
) -> np.ndarray:
    """
    绘制测量区域调试图（原 get_plot，返回图像而非 plt.show）。

    Returns:
        标注后的 BGR 图像副本
    """
    img_copy = img.copy()
    if img_copy.ndim == 2:
        img_copy = cv2.cvtColor(img_copy, cv2.COLOR_GRAY2BGR)
    if circles is None:
        return img_copy
    circles = np.round(circles).astype(int)
    for i, (x, y, r) in enumerate(circles):
        cv2.circle(img_copy, (x, y), r, (0, 255, 255), 2)
        for cx, cy, color in (
            (int(x + r + r), y, (255, 0, 255)),   # Right
            (int(x - r - r), y, (0, 0, 255)),     # Left
            (x, int(y + r + r), (255, 0, 0)),     # Down
            (x, int(y - r - r), (0, 255, 0)),     # Up
        ):
            cv2.circle(img_copy, (cx, cy), int(abs(r - d70)), color, 2)
            cv2.circle(img_copy, (cx, cy), int(r), (255, 255, 255), 2)
        cv2.circle(img_copy, (x, y), int(abs(r - d70)), (255, 255, 255), 2)
        cv2.putText(
            img_copy, str(i), (x, y), cv2.FONT_HERSHEY_SIMPLEX,
            1.5, (0, 0, 0), 2, cv2.LINE_AA,
        )
    return img_copy
