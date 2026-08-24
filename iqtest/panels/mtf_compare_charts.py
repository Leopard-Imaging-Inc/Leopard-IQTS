"""MTF 模组比较对话框的图表渲染（自 mtf_compare_panel.py 抽出）。

将「N 条折线对比 + Δ（各款 − 基准）分组条形」的 pyqtgraph 渲染逻辑
从对话框抽离为纯渲染函数：输入为数据集 / 公共位置匹配 / 测试项等纯数据，
输出渲染到传入的两个 PlotWidget。不依赖对话框状态，便于独立验证。

对话框 _render_charts 变为薄包装：从自身状态算出 (key, label, factor, unit, tie)
后调用 render_compare_charts，并把返回的横轴标签写回 self._chart_tick_labels。
"""

from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt

from iqtest.analysis import mtf_compare

#: 九宫格固定显示顺序与中文名
_ZONE_ORDER = [
    ("corner_tl", "左上角"), ("top", "上边缘"), ("corner_tr", "右上角"),
    ("left", "左边缘"), ("center", "中心"), ("right", "右边缘"),
    ("corner_bl", "左下角"), ("bottom", "下边缘"), ("corner_br", "右下角"),
]
_ZONE_CN = dict(_ZONE_ORDER)

#: 镜头折线/条形配色（按槽位轮换；基准款为第 1 色）
_LENS_COLORS = ["#1b9aaa", "#e8912d", "#2bb673", "#c0504d", "#8064a2",
                "#4bacc6"]
_LENS_STYLES = [Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine,
                Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine]
_LENS_SYMBOLS = ["o", "s", "t", "d", "x", "+"]
#: 两款时 Δ 条形按胜负着色：红 = A 优，蓝 = B 优，灰 = 平手
_DELTA_COLORS = {"A": "#c0504d", "B": "#4bacc6", "TIE": "#9aa5ad"}


def render_compare_charts(
    plot_compare: pg.PlotWidget,
    plot_delta: pg.PlotWidget,
    ordered: list[dict],
    matched: dict,
    metric_key: str,
    metric_label: str,
    factor: float,
    unit: str,
    tie: float,
) -> list[str]:
    """按当前所选测试项渲染 N 折线对比图与 Δ（vs 基准）分组条形图。

    Args:
        plot_compare / plot_delta: 待渲染的两个 PlotWidget（先 clear 再绘制）
        ordered: 槽位 dict 列表（基准排首位，含 data / key 字段）
        matched: mtf_compare.match_zones_multi 的返回
        metric_key: 测试项 key（如 "mtf@0.125" / "mtf50"）
        metric_label: 测试项友好名（图表标题用）
        factor: 展示倍率（频率类 = display_scale，SFR 类 = 1.0）
        unit: 展示单位（频率类为 display_unit，SFR 类为空 → 显示 "SFR"）
        tie: 打平阈值（与 factor 同口径的原始值，用于 Δ 参考线与胜负着色）

    Returns:
        横轴 tick 标签列表（供测试断言横轴标签）
    """
    datasets = [s["data"] for s in ordered]
    labels = [
        s["data"]["meta"].get("label") or f"模组 {s['key'].upper()}"
        for s in ordered
    ]
    n = len(datasets)
    ref_label = labels[0]

    # 公共位置（横轴）：中心优先，其后四角、边缘
    positions = []  # (zone, channel, group_index, rows_tuple)
    for zone_key in matched["keys"]:
        for gi, rows_tuple in enumerate(matched["groups"][zone_key]):
            positions.append((zone_key[0], zone_key[1], gi, rows_tuple))
    multi_channel = len({ch for _, ch, _, _ in positions}) > 1
    zone_total: dict[str, int] = {}
    for zone, _, _, _ in positions:
        zone_total[zone] = zone_total.get(zone, 0) + 1
    seen: dict[str, int] = {}
    tick_labels = []
    for zone, ch, _, _ in positions:
        text = _ZONE_CN.get(zone, zone)
        seen[zone] = seen.get(zone, 0) + 1
        if zone_total[zone] > 1:
            text += f"#{seen[zone]}"
        if multi_channel:
            text += f" {ch}"
        tick_labels.append(text)
    ticks = [list(enumerate(tick_labels))]

    # 各镜头逐位置归一化值（None → 跳过该点）
    series: list[list[tuple[int, float]]] = [[] for _ in range(n)]
    for i, (_, _, _, rows_tuple) in enumerate(positions):
        for li, (row, ds) in enumerate(zip(rows_tuple, datasets)):
            value = mtf_compare.normalized_metric(row, ds["meta"], metric_key)
            if value is not None:
                series[li].append((i, value * factor))

    # 左：N 条折线对比（基准加粗实线）
    plot = plot_compare
    plot.clear()
    title = f"{metric_label}　各款对比（基准 = {ref_label}）"
    plot.setTitle(title, color="#3a4750", size="11pt")
    plot.setLabel("left", unit or "SFR")
    plot.getAxis("bottom").setTicks(ticks)
    for li, pts in enumerate(series):
        if not pts:
            continue
        color = _LENS_COLORS[li % len(_LENS_COLORS)]
        style = _LENS_STYLES[0] if li == 0 else _LENS_STYLES[
            1 + (li - 1) % (len(_LENS_STYLES) - 1)]
        plot.plot(
            [p[0] for p in pts], [p[1] for p in pts],
            pen=pg.mkPen(color, width=3 if li == 0 else 2, style=style),
            symbol=_LENS_SYMBOLS[li % len(_LENS_SYMBOLS)],
            symbolBrush=color, symbolSize=8,
            name=labels[li] + ("（基准）" if li == 0 else ""),
        )
    if tick_labels:
        plot.setXRange(-0.5, len(tick_labels) - 0.5, padding=0.05)

    # 右：Δ（各款 − 基准）每位置分组条形
    dplot = plot_delta
    dplot.clear()
    dplot.setTitle(f"Δ（各款 − 基准 {ref_label}）",
                   color="#3a4750", size="11pt")
    dplot.setLabel("left", unit or "SFR")
    dplot.getAxis("bottom").setTicks(ticks)
    n_others = n - 1
    if n_others > 0 and positions:
        width = 0.8 / n_others
        for j in range(1, n):
            ref_vals = {i: v for i, v in series[0]}
            other_vals = {i: v for i, v in series[j]}
            common = sorted(set(ref_vals) & set(other_vals))
            if not common:
                continue
            deltas = [other_vals[i] - ref_vals[i] for i in common]
            xs = [i - 0.4 + width * (j - 0.5) for i in common]
            if n_others == 1:
                # 两款：按胜负着色（红=A 优 / 蓝=B 优 / 灰=平手）
                brushes = [
                    pg.mkBrush(_DELTA_COLORS[
                        mtf_compare.pair_outcome(d / factor
                                                 if factor else d, tie)])
                    for d in deltas
                ]
            else:
                # 多款：按镜头配色（与折线一致）
                brushes = pg.mkBrush(_LENS_COLORS[j % len(_LENS_COLORS)])
            dplot.addItem(pg.BarGraphItem(
                x=xs, height=deltas, width=width * 0.92,
                **({"brushes": brushes} if isinstance(brushes, list)
                   else {"brush": brushes}),
                pen=pg.mkPen("w", width=1),
            ))
        dplot.setXRange(-0.5, len(tick_labels) - 0.5, padding=0.05)
    tie_disp = tie * factor
    for pos in (tie_disp, -tie_disp):
        dplot.addItem(pg.InfiniteLine(
            pos=pos, angle=0, movable=False,
            pen=pg.mkPen("#8a939b", width=1, style=Qt.PenStyle.DashLine),
        ))
    dplot.addItem(pg.InfiniteLine(
        pos=0, angle=0, movable=False, pen=pg.mkPen("#5a6a75", width=1),
    ))

    return tick_labels
