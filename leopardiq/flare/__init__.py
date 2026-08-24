"""
LeopardIQ Flare 模块（ISO 9358）。

提供：
- FlareAnalyzer：Type A / B / C 三种 Flare 测量方法
- analyze_flare：标准接口入口
- detect_flare_circles / compute_region_luma / render_debug_overlay：区域工具
"""

from .flare_analyzer import FlareAnalyzer, analyze_flare
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

__all__ = [
    "FlareAnalyzer",
    "analyze_flare",
    "REGION_BLACK",
    "REGION_WHITE_DOWN",
    "REGION_WHITE_LEFT",
    "REGION_WHITE_RIGHT",
    "REGION_WHITE_UP",
    "compute_d70",
    "compute_region_luma",
    "detect_flare_circles",
    "render_debug_overlay",
]
