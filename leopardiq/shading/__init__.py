"""
LeopardIQ Lens Shading 模块。

提供：
- analyze_lens_shading / analyze_relative_illumination：相对照度（RI）分析
- analyze_multi_light：多光源 Shading 分析
- analyze_color_uniformity / compute_channel_ratios / compute_wb_gains /
  compute_color_shading：Color 比例与色彩均匀性
- apply_lsc：镜头阴影校正
- interp_shading_profile：shading 轮廓插值
"""

from .relative_illumination import (
    analyze_lens_shading,
    analyze_multi_light,
    analyze_relative_illumination,
)
from .color_uniformity import (
    analyze_color_uniformity,
    compute_channel_ratios,
    compute_color_shading,
    compute_wb_gains,
)
from .lsc import apply_lsc
from .shading_profile import (
    bin_image_means,
    calculate_channel_shift,
    compute_quadrant_ri,
    create_flat_field_mask,
    interp_shading_profile,
)

__all__ = [
    "analyze_lens_shading",
    "analyze_multi_light",
    "analyze_relative_illumination",
    "analyze_color_uniformity",
    "compute_channel_ratios",
    "compute_color_shading",
    "compute_wb_gains",
    "apply_lsc",
    "bin_image_means",
    "calculate_channel_shift",
    "compute_quadrant_ri",
    "create_flat_field_mask",
    "interp_shading_profile",
]
