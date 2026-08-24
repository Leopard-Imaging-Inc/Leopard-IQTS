"""空间频率单位换算（仿 Imatest Secondary Readout 的单位制）。

算法层统一使用规范单位 **Cycles/pixel（cy/px）**；其余单位仅在 GUI 参数
输入与结果展示时换算，关系如下：

    Cycles/pixel  基准单位，无需附加参数
    Cycles/mm     cy/mm  = cy/px × 1000 / pixel_size_um     （需像元尺寸）
    LP/mm         线对/毫米，与 Cycles/mm 同值（1 LP = 1 cycle）
    L/mm          线宽/毫米 = 2 × LP/mm
    LP/PH         线对/像高 = cy/px × picture_height         （需像高）
    LW/PH         线宽/像高 = 2 × LP/PH

pixel_size_um   像元尺寸（µm/px）
picture_height  像高（px），对裁剪图应填原始（未裁剪）全幅像高
"""

from __future__ import annotations

from typing import Optional

import numpy as np

#: 支持的空间频率单位（GUI 下拉框顺序）
FREQ_UNITS: list[str] = [
    "Cycles/pixel",
    "Cycles/mm",
    "LP/mm",
    "L/mm",
    "LP/PH",
    "LW/PH",
]

#: 坐标轴 / 表格使用的短标签
_AXIS_LABELS: dict[str, str] = {
    "Cycles/pixel": "cy/px",
    "Cycles/mm": "cy/mm",
    "LP/mm": "LP/mm",
    "L/mm": "L/mm",
    "LP/PH": "LP/PH",
    "LW/PH": "LW/PH",
}

_PER_MM = {"Cycles/mm", "LP/mm", "L/mm"}
_PER_PH = {"LP/PH", "LW/PH"}
_LINE_WIDTH = {"L/mm", "LW/PH"}  # 线宽单位 = 2 × 线对/循环单位


def unit_label(unit: str) -> str:
    """单位的坐标轴短标签（如 ``Cycles/pixel`` → ``cy/px``）。"""
    if unit not in _AXIS_LABELS:
        raise ValueError(
            f"未知空间频率单位：{unit!r}（可选：{', '.join(FREQ_UNITS)}）"
        )
    return _AXIS_LABELS[unit]


def needs_pixel_pitch(unit: str) -> bool:
    """该单位换算是否需要像元尺寸（pixel_size_um）。"""
    unit_label(unit)  # 校验单位名
    return unit in _PER_MM


def needs_picture_height(unit: str) -> bool:
    """该单位换算是否需要像高（picture_height）。"""
    unit_label(unit)
    return unit in _PER_PH


def unit_scale(
    unit: str,
    pixel_size_um: Optional[float] = None,
    picture_height: Optional[float] = None,
) -> float:
    """cy/px → 目标单位 的倍率：``value[unit] = value[cy/px] × scale``。

    Raises:
        ValueError: 单位需要像元尺寸 / 像高但未提供或取值非法。
    """
    unit_label(unit)  # 校验单位名
    scale = 1.0
    if unit in _PER_MM:
        if not pixel_size_um or pixel_size_um <= 0:
            raise ValueError(
                f"单位 {unit} 需要有效的像元尺寸（µm/px）"
                f"（当前 pixel_size_um={pixel_size_um!r}）"
            )
        scale = 1000.0 / float(pixel_size_um)  # px/mm
    elif unit in _PER_PH:
        if not picture_height or picture_height <= 0:
            raise ValueError(
                f"单位 {unit} 需要有效的像高 Picture Height（px）"
                f"（当前 picture_height={picture_height!r}）"
            )
        scale = float(picture_height)
    if unit in _LINE_WIDTH:
        scale *= 2.0
    return scale


def cy_px_to_unit(
    value,
    unit: str,
    pixel_size_um: Optional[float] = None,
    picture_height: Optional[float] = None,
):
    """cy/px → 目标单位（支持标量或数组）。"""
    out = np.asarray(value, dtype=np.float64) * unit_scale(
        unit, pixel_size_um, picture_height
    )
    return float(out) if out.ndim == 0 else out


def unit_to_cy_px(
    value,
    unit: str,
    pixel_size_um: Optional[float] = None,
    picture_height: Optional[float] = None,
):
    """目标单位 → cy/px（支持标量或数组）。"""
    out = np.asarray(value, dtype=np.float64) / unit_scale(
        unit, pixel_size_um, picture_height
    )
    return float(out) if out.ndim == 0 else out
