"""Flare 模块面板（规划 §2：Type A / B / C 眩光）。"""

from iqtest.panels.base_panel import ModulePanel


class FlarePanel(ModulePanel):
    MODULE_KEY = "flare"
    TITLE = "Flare"
    DESCRIPTION = (
        "眩光 / 杂散光评估（Type A / B / C）；Type A/B 需加载双图。\n"
        "算法接口：analyze_flare（M3 接入）。"
    )

    PARAMS = [
        {
            "key": "flare_type",
            "label": "测试类型",
            "type": "choice",
            "choices": ["Type A", "Type B", "Type C"],
            "default": "Type C",
            "tooltip": "Type A/B 需要两张图像（亮场 + 点源），Type C 单图",
        },
        {
            "key": "debug_overlay",
            "label": "生成 debug 叠加图",
            "type": "bool",
            "default": False,
        },
    ]

    CRITERIA = [
        {
            "key": "flare_max_pct",
            "label": "Flare 上限 (%)",
            "type": "float",
            "default": 1.0,
            "min": 0.0,
            "max": 100.0,
            "step": 0.1,
        },
    ]
