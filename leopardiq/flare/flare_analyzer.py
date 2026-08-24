"""
Flare 分析统一接口（ISO 9358 Type A / B / C）。

提取自 LeopardIQ0529/leopardiq/flare/type_flare.py 的 get_flare 与
calcularion_flare.py / calculation_type_C.py 的流程逻辑。

三种测量方法（与原库一致）：
- Type A（可手动曝光）：
    F = ((YB3/H2) - (YB2/H2)) / (YW1/H1) * 100
    需要 3 张图：Chart1@H1、Chart2@H2、Chart1@H2（H2 = 8×H1 ± 10%）
    标板对比度 ≥ 40:1
- Type B（不可手动曝光）：
    F = ((YB1/H1) - (YB2/H2)) / (YW1/H1) * 100
    需要 2 张图：Chart1@H1、Chart2@H2
    标板对比度 ≥ 40:1
- Type C（简化方法）：
    F = YB1 / YW1 * 100
    需要 1 张图：Chart1@H1
    标板对比度 ≥ 3000:1（建议 ≥ 10000:1）

修复：原 calcularion_flare.py 引用了未定义的 img_path 变量且混杂
脚本级代码，提取后全部封装为类方法；plt.show 可视化改为可选 debug 输出。
"""

import warnings
from typing import Optional, Sequence, Union

import cv2
import numpy as np

from .flare_regions import (
    REGION_BLACK,
    REGION_WHITE_DOWN,
    REGION_WHITE_LEFT,
    REGION_WHITE_RIGHT,
    REGION_WHITE_UP,
    compute_d70,
    compute_region_luma,
    detect_flare_circles,
    render_debug_overlay,
)


def _load_image(image: Union[str, np.ndarray]) -> np.ndarray:
    """支持文件路径或 ndarray 输入。"""
    if isinstance(image, str):
        img = cv2.imread(image, 1)
        if img is None:
            raise ValueError(f"Failed to read image: {image}")
        return img
    return np.asarray(image)


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img.astype(np.uint8) if img.dtype != np.uint8 else img


class FlareAnalyzer:
    """
    Flare 分析器（ISO 9358 Type A / B / C）。

    Args:
        hough_params: 可选，Hough 圆检测参数覆盖
            {"min_dist": 50, "param1": 100, "param2": 30,
             "min_radius": 10, "max_radius": 50}
        deblur: 是否去模糊后检测（适用于桶畸变图像）
    """

    def __init__(self, hough_params: Optional[dict] = None, deblur: bool = False):
        self.hough_params = hough_params or {}
        self.deblur = deblur

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _detect(self, img: np.ndarray) -> np.ndarray:
        gray = _to_gray(img)
        return detect_flare_circles(gray, deblur=self.deblur, **self.hough_params)

    def _collect_luma(self, img: np.ndarray):
        """采集单张图的黑斑与四个白色参考区域 luma。"""
        circles = self._detect(img)
        if circles is None:
            raise RuntimeError("No flare chart circles detected")
        d70 = compute_d70(img.shape)
        y_black = compute_region_luma(img, circles, d70, REGION_BLACK)
        y_white_u = compute_region_luma(img, circles, d70, REGION_WHITE_UP)
        y_white_d = compute_region_luma(img, circles, d70, REGION_WHITE_DOWN)
        y_white_l = compute_region_luma(img, circles, d70, REGION_WHITE_LEFT)
        y_white_r = compute_region_luma(img, circles, d70, REGION_WHITE_RIGHT)
        return circles, d70, y_black, y_white_r, y_white_l, y_white_d, y_white_u

    @staticmethod
    def _white_reference(y_r, y_l, y_d, y_u, i) -> float:
        return float(np.nanmean([
            np.nanmean(y_u[i]), np.nanmean(y_d[i]),
            np.nanmean(y_l[i]), np.nanmean(y_r[i]),
        ]))

    # ------------------------------------------------------------------
    # Type C
    # ------------------------------------------------------------------
    def analyze_type_c(
        self,
        img_chart1: Union[str, np.ndarray],
        criteria: Optional[float] = None,
        debug: bool = False,
    ) -> dict:
        """
        Type C 简化方法：F = YB1 / YW1 * 100

        Args:
            img_chart1: Chart1 在曝光 H1 下拍摄的图像（白色区域 luma 225±25）
            criteria: 可选，flare 上限（%）
            debug: 是否返回调试图像

        Returns:
            {"metrics": {"flare": {...}}, "pass": bool, "details": {...}}
        """
        img = _load_image(img_chart1)
        circles, d70, y_b1, y_r, y_l, y_d, y_u = self._collect_luma(img)

        flare_per_circle = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            for i in range(len(y_b1)):
                y_w1 = self._white_reference(y_r, y_l, y_d, y_u, i)
                flare_per_circle.append(float(np.nanmean(y_b1[i]) / y_w1 * 100))
        flare = float(np.nanmean(flare_per_circle))

        return self._build_result(
            flare, flare_per_circle, circles, img, d70, "C", criteria, debug
        )

    # ------------------------------------------------------------------
    # Type B
    # ------------------------------------------------------------------
    def analyze_type_b(
        self,
        img_h1_chart1: Union[str, np.ndarray],
        img_h2_chart2: Union[str, np.ndarray],
        h1: float = 1.0,
        h2: float = 1.0,
        criteria: Optional[float] = None,
        debug: bool = False,
    ) -> dict:
        """
        Type B 方法：F = ((YB1/H1) - (YB2/H2)) / (YW1/H1) * 100

        Args:
            img_h1_chart1: Chart1 @ H1（白色区域 luma 225±25）
            img_h2_chart2: Chart2 @ H2（H2 = 8×H1 ± 10%）
            h1 / h2: 曝光量
            criteria: 可选，flare 上限（%）
        """
        img1 = _load_image(img_h1_chart1)
        img2 = _load_image(img_h2_chart2)
        circles, d70, y_b1, y_r, y_l, y_d, y_u = self._collect_luma(img1)
        _, _, y_b2, _, _, _, _ = self._collect_luma(img2)

        flare_per_circle = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            for i in range(len(y_b1)):
                y_w1 = self._white_reference(y_r, y_l, y_d, y_u, i)
                f = ((np.nanmean(y_b1[i]) / h1) - (np.nanmean(y_b2[0]) / h2)) \
                    / (y_w1 / h1) * 100
                flare_per_circle.append(float(f))
        flare = float(np.nanmean(flare_per_circle))

        return self._build_result(
            flare, flare_per_circle, circles, img1, d70, "B", criteria, debug
        )

    # ------------------------------------------------------------------
    # Type A
    # ------------------------------------------------------------------
    def analyze_type_a(
        self,
        img_h1_chart1: Union[str, np.ndarray],
        img_h2_chart2: Union[str, np.ndarray],
        img_h2_chart1: Union[str, np.ndarray],
        h1: float = 1.0,
        h2: float = 1.0,
        criteria: Optional[float] = None,
        debug: bool = False,
    ) -> dict:
        """
        Type A 方法：F = ((YB3/H2) - (YB2/H2)) / (YW1/H1) * 100

        Args:
            img_h1_chart1: Chart1 @ H1（白色区域 luma 225±25）
            img_h2_chart2: Chart2 @ H2（H2 = 8×H1 ± 10%）
            img_h2_chart1: Chart1 @ H2
            h1 / h2: 曝光量
            criteria: 可选，flare 上限（%）
        """
        img1 = _load_image(img_h1_chart1)
        img2 = _load_image(img_h2_chart2)
        img3 = _load_image(img_h2_chart1)
        circles, d70, _, y_r, y_l, y_d, y_u = self._collect_luma(img1)
        _, _, y_b2, _, _, _, _ = self._collect_luma(img2)
        _, _, y_b3, _, _, _, _ = self._collect_luma(img3)

        flare_per_circle = []
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            for i in range(len(y_b3)):
                y_w1 = self._white_reference(y_r, y_l, y_d, y_u, i)
                f = ((np.nanmean(y_b3[i]) / h2) - (np.nanmean(y_b2[0]) / h2)) \
                    / (y_w1 / h1) * 100
                flare_per_circle.append(float(f))
        flare = float(np.nanmean(flare_per_circle))

        return self._build_result(
            flare, flare_per_circle, circles, img1, d70, "A", criteria, debug
        )

    # ------------------------------------------------------------------
    # 结果组装
    # ------------------------------------------------------------------
    @staticmethod
    def _build_result(
        flare, flare_per_circle, circles, img, d70, method, criteria, debug
    ) -> dict:
        if criteria is not None:
            status = "PASS" if flare <= criteria else "FAIL"
        else:
            status = "PASS"
        result = {
            "metrics": {
                "flare": {"value": flare, "status": status, "unit": "%"}
            },
            "pass": status == "PASS",
            "details": {
                "method": f"ISO 9358 Type {method}",
                "flare_per_circle": flare_per_circle,
                "num_circles": 0 if circles is None else len(circles),
            },
        }
        if debug:
            result["visualization"] = {
                "overlay": render_debug_overlay(img, circles, d70)
            }
        return result


def analyze_flare(images: Union[np.ndarray, Sequence], config: dict) -> dict:
    """
    标准接口的 Flare 分析（软件规划统一接口）。

    Args:
        images: 按 method 所需数量的图像（路径或 ndarray）：
            - "C": 单张图或 [Chart1@H1]
            - "B": [Chart1@H1, Chart2@H2]
            - "A": [Chart1@H1, Chart2@H2, Chart1@H2]
        config: {
            "method": "A" | "B" | "C",
            "h1": float, "h2": float,       # 曝光量（Type C 不需要）
            "criteria": float,              # 可选，flare 上限（%）
            "hough_params": dict,           # 可选
            "deblur": bool,                 # 可选
            "debug": bool,                  # 可选
        }

    Returns:
        {"metrics": {...}, "pass": bool, "details": {...}}
    """
    analyzer = FlareAnalyzer(
        hough_params=config.get("hough_params"),
        deblur=config.get("deblur", False),
    )
    method = config.get("method", "C").upper()
    criteria = config.get("criteria")
    debug = config.get("debug", False)

    if isinstance(images, np.ndarray) or isinstance(images, str):
        images = [images]

    if method == "C":
        return analyzer.analyze_type_c(images[0], criteria=criteria, debug=debug)
    if method == "B":
        return analyzer.analyze_type_b(
            images[0], images[1],
            h1=config.get("h1", 1.0), h2=config.get("h2", 1.0),
            criteria=criteria, debug=debug,
        )
    if method == "A":
        return analyzer.analyze_type_a(
            images[0], images[1], images[2],
            h1=config.get("h1", 1.0), h2=config.get("h2", 1.0),
            criteria=criteria, debug=debug,
        )
    raise ValueError(f"Unknown flare method: {method}")
