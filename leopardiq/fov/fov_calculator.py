"""
FOV 计算统一接口。

提取自 LeopardIQ0529/leopardiq/fov/calculate_FOV.py（几何法）并整合棋盘格法。

- 几何法：已知视场范围与拍摄距离，直接由三角函数计算（适合标定后的固定场景）
- 棋盘格法：见 fov_from_chessboard.py（更实用，无需预知视场范围）
"""

from typing import Optional, Sequence, Tuple, Union

import numpy as np

from .fov_from_chessboard import compute_fov_from_chessboard


def angle_of_triangle(opposite: float, adjacent: float) -> float:
    """直角三角形中对边/邻边求角度（度）。"""
    return float(np.rad2deg(np.arctan(opposite / adjacent)))


def compute_fov_from_geometry(
    h_range: Sequence[float],
    v_range: Sequence[float],
    focal_distance: float,
) -> dict:
    """
    几何法计算 FOV（原 calculation_FoV，改为返回结果而非 print）。

    Args:
        h_range: [h_min, h_max] 相机水平视距范围（与 focal_distance 同单位）
        v_range: [v_min, v_max] 相机垂直视距范围
        focal_distance: 相机到标定物的距离

    Returns:
        {"hfov": ..., "vfov": ..., "dfov": ...}（单位：度）

    注：DFOV 沿用原库定义 norm([HFOV, VFOV])；
    棋盘格法（compute_fov_from_chessboard）使用对角线视场尺寸计算 DFOV。
    """
    h_dist = (h_range[1] - h_range[0]) / 2
    v_dist = (v_range[1] - v_range[0]) / 2
    hfov = 2 * angle_of_triangle(h_dist, focal_distance)
    vfov = 2 * angle_of_triangle(v_dist, focal_distance)
    dfov = float(np.linalg.norm([hfov, vfov]))
    return {"hfov": hfov, "vfov": vfov, "dfov": dfov}


class FOVCalculator:
    """
    统一 FOV 计算器。

    Args:
        criteria: 可选，PASS/FAIL 阈值
            {"hfov": [min, max], "vfov": [min, max], "dfov": [min, max]}
    """

    def __init__(self, criteria: Optional[dict] = None):
        self.criteria = criteria or {}

    def from_geometry(
        self,
        h_range: Sequence[float],
        v_range: Sequence[float],
        focal_distance: float,
    ) -> dict:
        """几何法。返回标准结果字典。"""
        fov = compute_fov_from_geometry(h_range, v_range, focal_distance)
        return self._build_result(fov, {"method": "geometry"})

    def from_chessboard(
        self,
        image: np.ndarray,
        grid_size_mm: float,
        board_size: Tuple[int, int],
        dist_to_checkerboard_mm: float,
        use_griddata: bool = True,
        use_median_line: bool = True,
    ) -> dict:
        """棋盘格法。返回标准结果字典。"""
        result = compute_fov_from_chessboard(
            image, grid_size_mm, board_size, dist_to_checkerboard_mm,
            use_griddata=use_griddata, use_median_line=use_median_line,
        )
        fov = {"hfov": result["hfov"], "vfov": result["vfov"], "dfov": result["dfov"]}
        details = {
            "method": "chessboard",
            "width_mm": result["width_mm"],
            "height_mm": result["height_mm"],
            "ratios_x": result["ratios_x"],
            "ratios_y": result["ratios_y"],
        }
        return self._build_result(fov, details)

    def _build_result(self, fov: dict, details: dict) -> dict:
        metrics = {}
        for key in ("hfov", "vfov", "dfov"):
            status = "PASS"
            if key in self.criteria:
                lo, hi = self.criteria[key]
                status = "PASS" if lo <= fov[key] <= hi else "FAIL"
            metrics[key] = {"value": fov[key], "status": status, "unit": "deg"}
        return {
            "metrics": metrics,
            "pass": all(m["status"] == "PASS" for m in metrics.values()),
            "details": details,
        }


def analyze_fov(images: Union[np.ndarray, None], config: dict) -> dict:
    """
    标准接口的 FOV 分析（软件规划统一接口）。

    Args:
        images: 棋盘格图像（method="chessboard" 时必需；geometry 可传 None）
        config: {
            "method": "geometry" | "chessboard",
            # geometry
            "h_range": [min, max], "v_range": [min, max],
            "focal_distance": float,
            # chessboard
            "grid_size_mm": float, "board_size": (cols, rows),
            "dist_to_checkerboard_mm": float,
            # 可选
            "criteria": {"hfov": [min,max], "vfov": [min,max], "dfov": [min,max]},
        }

    Returns:
        {"metrics": {...}, "pass": bool, "details": {...}}
    """
    calculator = FOVCalculator(criteria=config.get("criteria"))
    method = config.get("method", "chessboard")
    if method == "geometry":
        return calculator.from_geometry(
            config["h_range"], config["v_range"], config["focal_distance"]
        )
    if method == "chessboard":
        if images is None:
            raise ValueError("chessboard method requires an input image")
        if isinstance(images, (list, tuple)):
            images = images[0]
        return calculator.from_chessboard(
            np.asarray(images),
            config["grid_size_mm"],
            tuple(config["board_size"]),
            config["dist_to_checkerboard_mm"],
            use_griddata=config.get("use_griddata", True),
            use_median_line=config.get("use_median_line", True),
        )
    raise ValueError(f"Unknown FOV method: {method}")
