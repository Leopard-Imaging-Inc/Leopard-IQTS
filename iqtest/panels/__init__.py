"""iqtest.panels — 分析项配置面板注册表。"""

from iqtest.panels.color_panel import ColorPanel
from iqtest.panels.flare_panel import FlarePanel
from iqtest.panels.fov_panel import FovPanel
from iqtest.panels.mtf_panel import MtfPanel
from iqtest.panels.shading_panel import ShadingPanel

#: 全部模块面板（顺序即 ② Select Analysis 对话框中的显示顺序）
MODULE_PANELS = [MtfPanel, ShadingPanel, ColorPanel, FlarePanel, FovPanel]

#: key → 面板类
MODULE_PANEL_MAP = {p.MODULE_KEY: p for p in MODULE_PANELS}


def module_title(key: str) -> str:
    panel = MODULE_PANEL_MAP.get(key)
    return panel.TITLE if panel else key
