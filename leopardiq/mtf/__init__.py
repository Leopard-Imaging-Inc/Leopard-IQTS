"""
LeopardIQ MTF/SFR 模块。

提供：
- SFRAnalyzer：统一 SFR 分析接口（多方格标板 / 十字标板）
- analyze_peak_focus：最佳对焦位置验证
- mtf_calculator：C++ sfrmat5 引擎封装与 MTF 指标计算（MTF50/MTF30 等）
- units：空间频率单位换算（Cycles/pixel、Cycles/mm、LP/mm、L/mm、LP/PH、LW/PH）
"""

from .sfr_analyzer import SFRAnalyzer
from .peak_focus import analyze_peak_focus
from .mtf_calculator import (
    GAMMA_REASONABLE_RANGE,
    compute_mtf_array,
    compute_mtf_metrics,
    compute_roi_sfr,
    interpolation_mtf,
    interpolation_nyquist,
    linearize_gamma,
    validate_edge_patch,
)
from .units import (
    FREQ_UNITS,
    cy_px_to_unit,
    needs_picture_height,
    needs_pixel_pitch,
    unit_label,
    unit_scale,
    unit_to_cy_px,
)

__all__ = [
    "SFRAnalyzer",
    "analyze_peak_focus",
    "GAMMA_REASONABLE_RANGE",
    "compute_mtf_array",
    "compute_mtf_metrics",
    "compute_roi_sfr",
    "interpolation_mtf",
    "interpolation_nyquist",
    "linearize_gamma",
    "validate_edge_patch",
    "FREQ_UNITS",
    "cy_px_to_unit",
    "needs_picture_height",
    "needs_pixel_pitch",
    "unit_label",
    "unit_scale",
    "unit_to_cy_px",
]
