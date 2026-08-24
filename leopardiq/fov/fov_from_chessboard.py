"""
棋盘格法 FOV 计算。

提取自 LeopardIQ0529/leopardiq/fov/FOV_from_832256.py（原为脚本，重构为函数）。

原理：
1. cv2.findChessboardCorners + cornerSubPix 检测棋盘格内角点
2. 计算相邻角点的像素距离，得到每个网格中心的 pixel→mm 比例
3. 将比例插值到全图（griddata），逐行/列累加得到图像视场尺寸（mm）
4. 结合拍摄距离计算 HFOV / VFOV / DFOV

注：原脚本依赖同目录 utils 模块（create_interpolated_array / draw_point 等），
该模块不在算法库中，提取后在本文件内实现。
"""

from typing import Optional, Tuple

import cv2
import numpy as np
from scipy import interpolate


def detect_chessboard_corners(
    image: np.ndarray,
    board_size: Tuple[int, int],
    subpix_win: Tuple[int, int] = (11, 11),
) -> np.ndarray:
    """
    检测棋盘格内角点并做亚像素精化。

    Args:
        image: 输入图像（BGR 或灰度）
        board_size: (columns, rows) 内角点数量，如 (15, 8)
        subpix_win: cornerSubPix 窗口

    Returns:
        (rows, columns, 2) 角点坐标数组（棋盘格行列排列）

    Raises:
        RuntimeError: 未检测到完整棋盘格
    """
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    ret, corners = cv2.findChessboardCorners(gray, board_size, None)
    if not ret:
        raise RuntimeError(
            f"Chessboard {board_size} not found in image. Please recapture."
        )
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    corners2 = cv2.cornerSubPix(gray, corners, subpix_win, (-1, -1), criteria)
    corners2 = corners2.squeeze()
    corners_board = corners2.reshape((board_size[1], board_size[0], 2))
    return corners_board


def create_interpolated_array(
    points: np.ndarray,
    values: np.ndarray,
    shape: Tuple[int, int],
    use_griddata: bool = True,
) -> np.ndarray:
    """
    将散点 (points, values) 插值为 shape 尺寸的稠密数组。

    Args:
        points: (N, 2) 坐标 [(x, y), ...]
        values: (N,) 对应值
        shape: (width, height) 输出尺寸
        use_griddata: True 用 griddata 线性插值（边缘行为更稳定）；
                      False 用 RectBivariateSpline 规则网格插值

    Returns:
        (height, width) 插值数组（标准图像行列序，与原实现一致）；
        griddata 模式下的 NaN（凸包外）用 nearest 填充
    """
    width, height = shape
    if use_griddata:
        grid_x, grid_y = np.meshgrid(np.arange(width), np.arange(height))
        result = interpolate.griddata(
            points, values, (grid_x, grid_y), method="linear"
        )
        # 凸包外区域用最近邻填充
        nan_mask = np.isnan(result)
        if nan_mask.any():
            nearest = interpolate.griddata(
                points, values, (grid_x, grid_y), method="nearest"
            )
            result[nan_mask] = nearest[nan_mask]
        return result
    # 规则网格样条插值（points 需为规则网格）
    xs = np.unique(points[:, 0])
    ys = np.unique(points[:, 1])
    grid_values = values.reshape(len(ys), len(xs))
    spline = interpolate.RectBivariateSpline(ys, xs, grid_values, kx=1, ky=1)
    return spline(np.arange(height), np.arange(width))


def compute_pixel_to_mm_maps(
    corners_board: np.ndarray,
    grid_size_mm: float,
    image_shape: Tuple[int, int],
    use_griddata: bool = True,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    由棋盘格角点计算水平/垂直 pixel→mm 比例图。

    Args:
        corners_board: (rows, columns, 2) 角点数组
        grid_size_mm: 棋盘格单格物理尺寸（mm）
        image_shape: (width, height)
        use_griddata: 插值方式

    Returns:
        (ratios_x, ratios_y)：均为 (height, width) 的 mm/px 比例图
    """
    width, height = image_shape

    # 相邻角点像素距离
    horz_px_dists = np.linalg.norm(
        corners_board[:, 0:-1] - corners_board[:, 1:], axis=-1
    )
    vert_px_dists = np.linalg.norm(
        corners_board[0:-1, :] - corners_board[1:, :], axis=-1
    )

    # 网格中心点
    grid_centers_x = np.mean(
        (corners_board[:, 0:-1], corners_board[:, 1:]), axis=0
    ).reshape((-1, 2))
    grid_centers_y = np.mean(
        (corners_board[0:-1, :], corners_board[1:, :]), axis=0
    ).reshape((-1, 2))

    values_x = grid_size_mm / horz_px_dists.reshape(-1)
    ratios_x = create_interpolated_array(
        grid_centers_x, values_x, shape=(width, height), use_griddata=use_griddata
    )
    values_y = grid_size_mm / vert_px_dists.reshape(-1)
    ratios_y = create_interpolated_array(
        grid_centers_y, values_y, shape=(width, height), use_griddata=use_griddata
    )
    return ratios_x, ratios_y


def compute_fov_from_chessboard(
    image: np.ndarray,
    grid_size_mm: float,
    board_size: Tuple[int, int],
    dist_to_checkerboard_mm: float,
    use_griddata: bool = True,
    use_median_line: bool = True,
) -> dict:
    """
    棋盘格法计算 FOV（原 FOV_from_832256.py 脚本的核心流程）。

    Args:
        image: 棋盘格图像（BGR 或灰度）
        grid_size_mm: 单格物理尺寸（mm）
        board_size: (columns, rows) 内角点数
        dist_to_checkerboard_mm: 相机到棋盘格距离（mm）
        use_griddata: 插值方式（True 边缘更稳定）
        use_median_line: 视场尺寸取各行/列的中位数（True）或均值（False）

    Returns:
        {
            "hfov": float, "vfov": float, "dfov": float,   # 单位：度
            "width_mm": float, "height_mm": float,         # 视场尺寸
            "ratios_x": (W,H) 比例图, "ratios_y": (W,H) 比例图,
            "corners": (rows, cols, 2) 角点,
        }
    """
    height, width = image.shape[:2]
    corners_board = detect_chessboard_corners(image, board_size)
    ratios_x, ratios_y = compute_pixel_to_mm_maps(
        corners_board, grid_size_mm, (width, height), use_griddata
    )

    w_sizes_mm = ratios_x.sum(axis=1)
    h_sizes_mm = ratios_y.sum(axis=0)
    if use_median_line:
        w_size_mm = float(np.median(w_sizes_mm))
        h_size_mm = float(np.median(h_sizes_mm))
    else:
        w_size_mm = float(w_sizes_mm.mean())
        h_size_mm = float(h_sizes_mm.mean())

    h_fov = float(2 * np.rad2deg(np.arctan(w_size_mm * 0.5 / dist_to_checkerboard_mm)))
    v_fov = float(2 * np.rad2deg(np.arctan(h_size_mm * 0.5 / dist_to_checkerboard_mm)))
    d_fov = float(
        2
        * np.rad2deg(
            np.arctan(
                np.linalg.norm([w_size_mm, h_size_mm]) * 0.5 / dist_to_checkerboard_mm
            )
        )
    )

    return {
        "hfov": h_fov,
        "vfov": v_fov,
        "dfov": d_fov,
        "width_mm": w_size_mm,
        "height_mm": h_size_mm,
        "ratios_x": ratios_x,
        "ratios_y": ratios_y,
        "corners": corners_board,
    }
