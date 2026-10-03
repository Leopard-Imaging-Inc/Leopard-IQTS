"""
多光源 Shading 对比分析（Lens Shading 子功能）。

衡量同一款镜头在不同光源下的表现一致性：对每种光源分别执行
`analyze_relative_illumination`，再汇总跨光源对比指标（ri_spread /
color_shift_spread）。

提取自 LeopardIQ0529，原与 `analyze_relative_illumination` 同处
`relative_illumination.py`；解耦后独立为「多光源对比」子功能模块，
与单光源 Shading 分析物理分离。
"""

from typing import Dict, Union

import numpy as np

from .relative_illumination import analyze_relative_illumination


def analyze_multi_light(
    images_by_light: Dict[str, Union[np.ndarray, list]],
    config: dict,
) -> dict:
    """
    多光源 Shading 对比分析。

    对每种光源分别执行 analyze_relative_illumination 并汇总。

    Args:
        images_by_light: {光源名: 图像或图像列表}，如 {"D65": img1, "TL84": img2}
        config: 同 analyze_relative_illumination

    Returns:
        {
            "lights": {光源名: analyze_relative_illumination 结果},
            "pass": bool,            # 所有光源均 PASS 才为 True
            "comparison": {          # 跨光源比较
                "ri_min_per_light": {光源名: float},
                "ri_spread": float,  # 各光源最差 RI 的离散度（max-min）
            },
        }
    """
    lights = {}
    ri_min_per_light = {}
    for light_name, images in images_by_light.items():
        result = analyze_relative_illumination(images, config)
        lights[light_name] = result
        ri_values = []
        for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
            ri_values.extend(np.atleast_1d(result["metrics"][key]["value"]))
        ri_min_per_light[light_name] = float(np.nanmin(ri_values))

    overall_pass = all(r["pass"] for r in lights.values())
    ri_values = list(ri_min_per_light.values())
    return {
        "lights": lights,
        "pass": overall_pass,
        "comparison": {
            "ri_min_per_light": ri_min_per_light,
            "ri_spread": float(max(ri_values) - min(ri_values)) if ri_values else 0.0,
        },
    }
