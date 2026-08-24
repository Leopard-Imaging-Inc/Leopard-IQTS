"""Color 比例模块面板（规划 §2：Bayer 四通道比例、白平衡增益、Color Shading）。"""

from iqtest.panels.base_panel import ModulePanel


class ColorPanel(ModulePanel):
    MODULE_KEY = "color"
    TITLE = "Color 比例"
    DESCRIPTION = (
        "Bayer 四通道比例、白平衡增益、Color Shading（G/R、G/B 分布）。\n"
        "算法接口：analyze_color_uniformity（M3 接入）。"
    )

    PARAMS = [
        {
            "key": "cfa_pattern",
            "label": "CFA Pattern",
            "type": "choice",
            "choices": ["RGGB", "BGGR", "GRBG", "GBRG"],
            "default": "RGGB",
        },
        {
            "key": "border_crop_pct",
            "label": "边缘裁剪 (%)",
            "type": "float",
            "default": 5.0,
            "min": 0.0,
            "max": 25.0,
            "step": 0.5,
            "tooltip": "分析前裁掉图像边缘，规避暗角影响",
        },
    ]

    CRITERIA = [
        {
            "key": "gr_ratio_tol",
            "label": "G/R 比例容差",
            "type": "float",
            "default": 0.05,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
        },
        {
            "key": "gb_ratio_tol",
            "label": "G/B 比例容差",
            "type": "float",
            "default": 0.05,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
        },
    ]
