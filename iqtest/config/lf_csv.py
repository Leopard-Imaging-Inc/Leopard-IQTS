"""LenFocus 测试结果 CSV 的 edge's center 解析。

LenFocus 每次测试输出一行 CSV，其中 "edge's center" 列记录各斜边 ROI 的
中心点坐标（图像像素坐标），格式为：

    [(318, 264)(381, 201)][(1575, 282)(1527, 207)][(891, 606)(955, 555)]...

方括号按 Box 分组，每个 (x, y) 是一条斜边的中心点 —— 与 MTF/SFR 面板
「每个 ROI 包含一条黑白斜边」的 ROI 一一对应。配合用户给定的 ROI 边长即可
还原全部 ROI 矩形：

    rect = [cx - side/2, cy - side/2, side, side]

本模块不依赖 PySide6，可独立测试。
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

#: (x, y) 坐标点（允许负数/小数/空白）
_POINT_RE = re.compile(
    r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)"
)

#: edge's center 列名（LenFocus 固定表头）
EDGE_CENTER_COLUMN = "edge's center"


def parse_lf_edge_centers(path: str | os.PathLike) -> list[tuple[float, float]]:
    """解析 LenFocus 结果 CSV 的 "edge's center" 列。

    Args:
        path: LenFocus 测试结果 CSV 路径。

    Returns:
        [(x, y), ...] 全部数据行的斜边中心点（图像像素坐标），按出现顺序。

    Raises:
        ValueError: 文件不存在 / 非合法 CSV / 缺少 edge's center 列 / 无有效坐标。
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"CSV 文件不存在：{path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise ValueError(f"无法解析 CSV 文件：{path.name}（{e}）") from e
    if not rows:
        raise ValueError(f"CSV 中没有数据行：{path.name}")

    centers: list[tuple[float, float]] = []
    for row in rows:
        if EDGE_CENTER_COLUMN not in row:
            raise ValueError(
                f"CSV 缺少 \"{EDGE_CENTER_COLUMN}\" 列：{path.name}"
                f"（现有列：{[c for c in row if c]}）"
            )
        value = row.get(EDGE_CENTER_COLUMN) or ""
        centers.extend(
            (float(x), float(y)) for x, y in _POINT_RE.findall(value)
        )

    if not centers:
        raise ValueError(
            f"\"{EDGE_CENTER_COLUMN}\" 列中未解析到任何 (x, y) 坐标：{path.name}"
        )
    return centers


def centers_to_rects(
    centers: list[tuple[float, float]],
    side: int,
    width: int | None = None,
    height: int | None = None,
) -> list[list[int]]:
    """中心点 + 边长 → [x, y, w, h] 矩形列表（可选裁剪到图像范围内）。

    Args:
        centers: parse_lf_edge_centers 返回的中心点。
        side: ROI 边长（px，正方形）。
        width / height: 图像尺寸；提供时边长先被钳到图像内，
                        矩形整体平移裁剪到 [0, width-side] × [0, height-side]。
    """
    side = int(side)
    if side < 4:
        raise ValueError(f"ROI 边长过小：{side}（至少 4px）")
    if width is not None and height is not None:
        side = min(side, int(width), int(height))
    rects: list[list[int]] = []
    for cx, cy in centers:
        x = int(round(cx - side / 2))
        y = int(round(cy - side / 2))
        if width is not None and height is not None:
            x = max(0, min(x, int(width) - side))
            y = max(0, min(y, int(height) - side))
        rects.append([x, y, side, side])
    return rects
