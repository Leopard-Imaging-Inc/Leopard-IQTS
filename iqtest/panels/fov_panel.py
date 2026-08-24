"""FOV 模块面板（规划 §2：几何法 / 棋盘格法 FOV、Imatest JSON 导入）。"""

from iqtest.panels.base_panel import ModulePanel


class FovPanel(ModulePanel):
    MODULE_KEY = "fov"
    TITLE = "FOV"
    DESCRIPTION = (
        "视场角测量：几何法 / 棋盘格法，或导入 Imatest JSON 结果。\n"
        "算法接口：analyze_fov（M3 接入）。"
    )

    PARAMS = [
        {
            "key": "method",
            "label": "测量方法",
            "type": "choice",
            "choices": ["棋盘格法", "几何法", "Imatest JSON"],
            "default": "棋盘格法",
        },
        {
            "key": "chessboard_rows",
            "label": "棋盘格行数",
            "type": "int",
            "default": 9,
            "min": 3,
            "max": 30,
        },
        {
            "key": "chessboard_cols",
            "label": "棋盘格列数",
            "type": "int",
            "default": 12,
            "min": 3,
            "max": 40,
        },
        {
            "key": "square_size_mm",
            "label": "格尺寸 (mm)",
            "type": "float",
            "default": 20.0,
            "min": 0.1,
            "max": 1000.0,
            "step": 1.0,
        },
        {
            "key": "distance_mm",
            "label": "拍摄距离 (mm)",
            "type": "float",
            "default": 500.0,
            "min": 1.0,
            "max": 100000.0,
            "step": 10.0,
            "tooltip": "几何法必填；棋盘格法可留默认",
        },
    ]

    CRITERIA = [
        {
            "key": "hfov_min",
            "label": "HFOV 下限 (°)",
            "type": "float",
            "default": 60.0,
            "min": 0.0,
            "max": 180.0,
            "step": 1.0,
        },
        {
            "key": "hfov_max",
            "label": "HFOV 上限 (°)",
            "type": "float",
            "default": 120.0,
            "min": 0.0,
            "max": 180.0,
            "step": 1.0,
        },
    ]
