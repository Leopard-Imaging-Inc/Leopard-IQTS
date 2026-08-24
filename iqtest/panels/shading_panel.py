"""Lens Shading 模块面板（规划 §2：RI、亮度均匀性、四象限 RI、多光源对比）。"""

from iqtest.panels.base_panel import ModulePanel


class ShadingPanel(ModulePanel):
    MODULE_KEY = "shading"
    TITLE = "Lens Shading"
    DESCRIPTION = (
        "相对照度（RI）、亮度均匀性、四象限 RI、LSC 校正表、多光源对比。\n"
        "算法接口：analyze_relative_illumination / analyze_lens_shading / "
        "analyze_multi_light（M3 接入）。"
    )

    PARAMS = [
        {
            "key": "light_source",
            "label": "光源类型",
            "type": "choice",
            "choices": ["D65", "TL84", "A", "CWF"],
            "default": "D65",
        },
        {
            "key": "luminance_channel",
            "label": "亮度通道",
            "type": "choice",
            "choices": ["Y", "G", "Gr"],
            "default": "Y",
        },
        {
            "key": "grid_size",
            "label": "网格尺寸",
            "type": "int",
            "default": 16,
            "min": 4,
            "max": 64,
            "tooltip": "RI 热力图分块粒度（grid × grid）",
        },
    ]

    CRITERIA = [
        {
            "key": "ri_corner_min",
            "label": "四象限 RI 下限",
            "type": "float",
            "default": 0.70,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "四角相对照度不得低于该比例",
        },
        {
            "key": "lum_uniformity_min",
            "label": "亮度均匀性下限",
            "type": "float",
            "default": 0.80,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
        },
    ]
