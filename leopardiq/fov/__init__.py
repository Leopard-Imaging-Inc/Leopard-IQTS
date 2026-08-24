"""
LeopardIQ FOV 模块。

提供：
- FOVCalculator / analyze_fov：统一 FOV 计算（几何法 / 棋盘格法）
- compute_fov_from_geometry：几何法
- compute_fov_from_chessboard / detect_chessboard_corners /
  compute_pixel_to_mm_maps：棋盘格法
- parse_imatest_fov / evaluate_imatest_fov：Imatest 数据解析（辅助）
"""

from .fov_calculator import (
    FOVCalculator,
    analyze_fov,
    angle_of_triangle,
    compute_fov_from_geometry,
)
from .fov_from_chessboard import (
    compute_fov_from_chessboard,
    compute_pixel_to_mm_maps,
    create_interpolated_array,
    detect_chessboard_corners,
)
from .imatest import evaluate_imatest_fov, parse_imatest_fov

__all__ = [
    "FOVCalculator",
    "analyze_fov",
    "angle_of_triangle",
    "compute_fov_from_geometry",
    "compute_fov_from_chessboard",
    "compute_pixel_to_mm_maps",
    "create_interpolated_array",
    "detect_chessboard_corners",
    "evaluate_imatest_fov",
    "parse_imatest_fov",
]
