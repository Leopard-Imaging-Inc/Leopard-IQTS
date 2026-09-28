"""
Imatest Uniformity 口径的 Lens Shading 结果集计算。

只从现有 `details["bin_means"]`（``(ny, nx, C)`` 的 block 均值数组，含 NaN）
派生，不重新读图、不重复计算 bin 均值。

提供：
- :func:`compute_imatest_luma_metrics`：Luma 指标（Max / Corners / Sides / 九点）
- :func:`compute_imatest_color_metrics`：Color Shading（R/G、B/G 比值 + corner/center）
- :func:`compute_imatest_metrics`：统一入口

采样口径（对齐 Imatest Uniformity）：
- block 网格坐标复用 ``bin_image_means`` 的 ``axisx/axisy``；
- 角区 / 边区 / 中心区域：边长 ``s = max(32, round(corner_region_pct * min(H, W)))``
  像素的正方形区域，落入区域内的 block 均值取 ``nanmean``（NaN 由平场掩膜产生，
  天然跳过）；
- 亮度 Y = 0.2125·R + 0.7154·G + 0.0721·B，G = (Gr + Gb) / 2（mono 直接用单通道）；
- 全部计算在**线性域**进行，gamma 仅用于显示。
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from leopardiq.utils.image_preprocess import get_bayer_index


def _block_grid(width: int, height: int, bin_size: int):
    """重算与 ``bin_image_means`` 一致的 block 网格坐标 ``(axisx, axisy)``。

    起点取 ``bin_size // 2``，使第一个 block 精确覆盖 ``[0, bin_size)``，
    与 Imatest 的 ROI 边界对齐（避免 ``start=0`` 时边缘 block 被裁剪成半个）。
    """
    start_axisx = bin_size // 2
    start_axisy = bin_size // 2
    axisx = np.array(range(start_axisx, width, bin_size), dtype=np.float64)
    axisy = np.array(range(start_axisy, height, bin_size), dtype=np.float64)
    return axisx, axisy


def _luminance(bin_means: np.ndarray, cfa: list) -> np.ndarray:
    """``(ny, nx, C)`` → ``(ny, nx)`` 亮度 Y（BT.709 加权，对齐 Imatest 系数）。"""
    if bin_means.shape[-1] == 1:
        return bin_means[:, :, 0].astype(np.float64)
    gr, red, blue, gb = get_bayer_index(cfa)
    green = (bin_means[:, :, gr] + bin_means[:, :, gb]) / 2.0
    return (
        0.2125 * bin_means[:, :, red]
        + 0.7154 * green
        + 0.0721 * bin_means[:, :, blue]
    )


def _region_mean(
    map2d: np.ndarray,
    axisx: np.ndarray,
    axisy: np.ndarray,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
) -> float:
    """取落在 ``[x0, x1) × [y0, y1)`` 像素区域内的 block 均值的 ``nanmean``。"""
    cols = np.where((axisx >= x0) & (axisx < x1))[0]
    rows = np.where((axisy >= y0) & (axisy < y1))[0]
    if cols.size == 0 or rows.size == 0:
        return float("nan")
    return float(np.nanmean(map2d[np.ix_(rows, cols)]))


def _region_mean_pixels(map2d: np.ndarray, x0: float, x1: float,
                        y0: float, y1: float) -> float:
    """对像素数组的 ``[x0, x1) × [y0, y1)`` 区域取 ``nanmean``（精确 ROI 像素均值）。"""
    x0, x1 = int(round(x0)), int(round(x1))
    y0, y1 = int(round(y0)), int(round(y1))
    if x1 <= x0 or y1 <= y0:
        return float("nan")
    return float(np.nanmean(map2d[y0:y1, x0:x1]))


def _corner_region_size(width: int, height: int, corner_region_pct: float) -> float:
    return max(32, int(round(corner_region_pct * min(height, width))))


def _region_boxes(width: int, height: int, s: float) -> dict:
    """返回 UL/LL/UR/LR/L/R/T/B/C 九块区域的 (x0, x1, y0, y1) 像素坐标。"""
    cx0, cx1 = (width - s) / 2.0, (width + s) / 2.0
    cy0, cy1 = (height - s) / 2.0, (height + s) / 2.0
    return {
        "UL": (0.0, s, 0.0, s),
        "UR": (width - s, float(width), 0.0, s),
        "LL": (0.0, s, height - s, float(height)),
        "LR": (width - s, float(width), height - s, float(height)),
        "L": (0.0, s, cy0, cy1),
        "R": (width - s, float(width), cy0, cy1),
        "T": (cx0, cx1, 0.0, s),
        "B": (cx0, cx1, height - s, float(height)),
        "C": (cx0, cx1, cy0, cy1),
    }


def imatest_roi_boxes_in_grid(
    grid_shape: tuple[int, int],
    orig_w: int,
    orig_h: int,
    orig_block: float,
    corner_region_pct: float = 0.05,
) -> dict:
    """原始像素基准的九点 ROI → 指定 block 网格坐标（供视图叠加采样红框）。

    与 Luma / Color 的九点采样为**同一物理区域**，只是坐标系不同：此处 1 个网格
    单位对应 ``orig_block`` 个原始像素（相对照度热力图的 x/y 为 bin 索引时，
    ``orig_block = bin_size × Bayer 拆分倍率``）。

    Args:
        grid_shape: 目标网格 ``(ny, nx)``。
        orig_w / orig_h: 原始传感器尺寸（像素）。
        orig_block: 每个网格单位覆盖的原始像素数。
        corner_region_pct: 角区边长比例（与 Imatest 口径一致）。

    Returns:
        dict: UL/LL/UR/LR/L/R/T/B/C → ``(x0, x1, y0, y1)``（网格坐标）。
    """
    ny, nx = grid_shape
    side = _corner_region_size(orig_w, orig_h, corner_region_pct) / float(orig_block)
    return _region_boxes(nx, ny, side)


def _format_luma_text(max_rel: float, full_scale: float, bin_size: int,
                      corners: dict, sides: dict) -> str:
    def pct(v: float) -> float:
        return v / max_rel * 100.0 if max_rel and np.isfinite(max_rel) else 0.0

    s1, s2 = sides["worst"]
    lines = [
        f"Max = {max_rel:.3f} (relative to 1 for pixel {int(full_scale)}) "
        f"[{bin_size}x{bin_size} pxls areas]",
        f"Corners: worst = {corners['worst']:.4f} ({pct(corners['worst']):.2f}%); "
        f"mean = {corners['mean']:.4f} ({pct(corners['mean']):.1f}%)",
        f"Sides: {s1:.4f} ({pct(s1):.2f}%) {s2:.4f} ({pct(s2):.2f}%); "
        f"mean = {pct(sides['mean']):.2f}%",
        f"L R T B = {sides['L']:.4f} {sides['R']:.4f} {sides['T']:.4f} {sides['B']:.4f}",
        f"UL LL UR LR = {corners['UL']:.4f} {corners['LL']:.4f} "
        f"{corners['UR']:.4f} {corners['LR']:.4f}",
    ]
    return "\n".join(lines)


def compute_imatest_luma_metrics(
    bin_means: np.ndarray,
    cfa: list,
    width: int,
    height: int,
    full_scale: float,
    bin_size: int,
    corner_region_pct: float = 0.05,
    y_pixels: np.ndarray | None = None,
    file_label: str = "",
) -> dict:
    """计算 Imatest 口径的 Luma 指标（Max / Corners / Sides / 九点）。

    采样尺寸以**原始传感器像素**为基准：``width / height`` 为原始尺寸
    （Bayer 为拆分前，mono 为图像尺寸），``bin_size`` 为原始 block 尺寸
    （默认 32）。Bayer 拆分后按 1/2 换算到计算网格（block 尺寸、角区边长均 /2）。

    Args:
        bin_means: ``(ny, nx, C)`` block 均值数组（含 NaN）；其 block 尺寸须为
            ``bin_size / scale``（Bayer 时为 16，mono 为 32）。
        cfa: 通道名列表（Bayer 4 元素或 mono ``["Y"]``）。
        width / height: 原始传感器尺寸（H, W）。
        full_scale: 满量程（按输入位深，如 16bit → 65535）。
        bin_size: 原始 block 尺寸（像素，默认 32）。
        corner_region_pct: 角区边长占 min(H,W) 的比例（默认 0.05，基于原始尺寸）。
        y_pixels: 拆分后 Y 通道像素（``grid_h × grid_w``，可选）。提供时
            Corners/Sides 用像素级 ROI 均值（精确对齐 Imatest ROI 边界，
            避免 block 网格在非整除尺寸下的边界错位）；缺省回退到 block 均值。
        file_label: 原始文件名，供结果界面等高线图标题第二行使用。

    Returns:
        dict: ``max_rel`` / ``max_pixel`` / ``corners`` / ``sides`` /
        ``norm_map`` / ``axisx`` / ``axisy`` / ``boxes`` / ``region_size`` /
        ``file_label`` / ``text_block``。
    """
    scale = 2 if len(cfa) == 4 else 1
    grid_w = width // scale
    grid_h = height // scale
    grid_block = bin_size // scale

    axisx, axisy = _block_grid(grid_w, grid_h, grid_block)
    y = _luminance(np.asarray(bin_means, dtype=np.float64), cfa)
    max_pixel = float(np.nanmax(y))
    max_rel = max_pixel / full_scale if full_scale else 0.0
    norm_map = y / max_pixel if max_pixel and np.isfinite(max_pixel) else y

    # 角区边长按原始尺寸计算，再换算到拆分网格
    s_orig = _corner_region_size(width, height, corner_region_pct)
    s = s_orig // scale
    boxes = _region_boxes(grid_w, grid_h, s)

    # 角区 / 边区（相对满量程的比例）
    def region_rel(key: str) -> float:
        x0, x1, y0, y1 = boxes[key]
        if y_pixels is not None:
            return _region_mean_pixels(y_pixels, x0, x1, y0, y1) / full_scale
        return _region_mean(y, axisx, axisy, x0, x1, y0, y1) / full_scale

    corners = {k: region_rel(k) for k in ("UL", "LL", "UR", "LR")}
    corners["worst"] = min(corners[k] for k in ("UL", "LL", "UR", "LR"))
    corners["mean"] = float(np.mean([corners[k] for k in ("UL", "LL", "UR", "LR")]))

    sides = {k: region_rel(k) for k in ("L", "R", "T", "B")}
    side_vals = sorted(sides[k] for k in ("L", "R", "T", "B"))
    sides["worst"] = side_vals[:2]
    sides["mean"] = float(np.mean(side_vals[:2]))

    text_block = _format_luma_text(max_rel, full_scale, bin_size, corners, sides)
    return {
        "max_rel": max_rel,
        "max_pixel": max_pixel,
        "corners": corners,
        "sides": sides,
        "norm_map": norm_map,
        "axisx": axisx,
        "axisy": axisy,
        "boxes": boxes,
        "region_size": float(s),
        "file_label": file_label,
        "text_block": text_block,
    }


def _format_color_text(label: str, m: dict) -> str:
    return (
        f"{label} Pixel ratio: max = {m['max']:.3f} min = {m['min']:.3f}\n"
        f"UL LL UR LR | LRTB | C = {m['UL']:.3f}, {m['LL']:.3f}, {m['UR']:.3f}, "
        f"{m['LR']:.3f} | {m['L']:.3f}, {m['R']:.3f}, {m['T']:.3f}, {m['B']:.3f} "
        f"| {m['C']:.3f}\n"
        f"Corners: worst = {m['corners_worst']:.3f}  mean = {m['corners_mean']:.3f}"
    )


def _ratio_nine_points(ratio_map: np.ndarray, axisx: np.ndarray, axisy: np.ndarray,
                       boxes: dict) -> dict:
    """对单个比值图采样九点（报告原始比值，不做归一化，对齐 Imatest 报告值）。"""
    out: dict = {}
    out["max"] = float(np.nanmax(ratio_map))
    out["min"] = float(np.nanmin(ratio_map))
    for key, (x0, x1, y0, y1) in boxes.items():
        out[key] = _region_mean(ratio_map, axisx, axisy, x0, x1, y0, y1)
    out["corners_worst"] = min(out[k] for k in ("UL", "LL", "UR", "LR"))
    out["corners_mean"] = float(np.mean([out[k] for k in ("UL", "LL", "UR", "LR")]))
    return out


def compute_imatest_color_metrics(
    bin_means: np.ndarray,
    cfa: list,
    width: int,
    height: int,
    bin_size: int,
    corner_region_pct: float = 0.05,
    file_label: str = "",
    contour_step: float = 0.05,
    alpha: float = 4.0,
    gamma: float = 1.0,
) -> Optional[dict]:
    """计算 Imatest 口径的 Color Shading 指标（R/G、B/G、R/B 比值）。

    仅 Bayer 四通道输入时可用，否则返回 ``None``。采样尺寸以**原始传感器像素**
    为基准（``width/height`` 为原始尺寸，``bin_size`` 为原始 block 尺寸），
    Bayer 拆分后按 1/2 换算到计算网格。比值在线性域计算（不做 gamma）。

    Args:
        file_label: 原始文件名，供比值等值线图标题展示。
        contour_step: 等值线步进（默认 0.05），供绘图层使用。
        alpha: exaggerated color 夸大因子默认值（默认 4），供绘图层使用。
        gamma: Lens Shading 面板的输入 Gamma，绘图层据此对 ``Y0`` 做显示编码
            （默认 1.0 = 不编码），仅影响显示，不参与任何数值计算。

    Returns:
        dict: ``rg`` / ``bg`` / ``rb``（各含 max/min/九点/corners）/
        ``corner_center``（R/B、R/G、B/G 三比值）/
        ``rg_map`` / ``bg_map`` / ``rb_map``（归一化比值图，全图均值=1）/
        ``y_norm``（归一化亮度，供 exaggerated color 底色的 ``Y0``）/
        ``boxes`` / ``region_size``（九点 ROI 红框，block 网格坐标）/
        ``axisx`` / ``axisy`` / ``file_label`` / ``contour_step`` / ``alpha`` /
        ``gamma`` / ``text_block``（R/G、B/G、R/B 三段 + corner/center）。
    """
    bin_means = np.asarray(bin_means, dtype=np.float64)
    if bin_means.shape[-1] != 4:
        return None

    scale = 2 if len(cfa) == 4 else 1
    grid_w = width // scale
    grid_h = height // scale
    grid_block = bin_size // scale

    axisx, axisy = _block_grid(grid_w, grid_h, grid_block)
    gr, red, blue, gb = get_bayer_index(cfa)
    green = (bin_means[:, :, gr] + bin_means[:, :, gb]) / 2.0
    r_map = bin_means[:, :, red]
    b_map = bin_means[:, :, blue]

    rg = r_map / green  # R/G
    bg = b_map / green  # B/G
    rb = r_map / b_map  # R/B

    s_orig = _corner_region_size(width, height, corner_region_pct)
    s = s_orig // scale
    boxes = _region_boxes(grid_w, grid_h, s)

    rg_metrics = _ratio_nine_points(rg, axisx, axisy, boxes)
    bg_metrics = _ratio_nine_points(bg, axisx, axisy, boxes)
    rb_metrics = _ratio_nine_points(rb, axisx, axisy, boxes)

    # 显示亮度（归一化到峰值=1）：exaggerated color 底色的 Y0 底图
    y = _luminance(bin_means, cfa)
    y_peak = float(np.nanmax(y)) if np.isfinite(np.nanmax(y)) else 0.0
    y_norm = y / y_peak if y_peak else y

    def corner_center(ratio_map: np.ndarray) -> float:
        norm = ratio_map / np.nanmean(ratio_map)
        corner_min = min(
            _region_mean(norm, axisx, axisy, *boxes[k]) for k in ("UL", "LL", "UR", "LR")
        )
        center = _region_mean(norm, axisx, axisy, *boxes["C"])
        return corner_min / center if center and np.isfinite(center) else float("nan")

    corner_center_vals = {
        "r_b": corner_center(rb),
        "r_g": corner_center(rg),
        "b_g": corner_center(bg),
    }

    text_block = (
        _format_color_text("R/G", rg_metrics) + "\n\n"
        + _format_color_text("B/G", bg_metrics) + "\n\n"
        + _format_color_text("R/B", rb_metrics) + "\n\n"
        + "Minimum corner / center: R/B, R/G, B/G = "
        + f"{corner_center_vals['r_b']:.3f} {corner_center_vals['r_g']:.3f} "
        + f"{corner_center_vals['b_g']:.3f}"
    )

    return {
        "rg": rg_metrics,
        "bg": bg_metrics,
        "rb": rb_metrics,
        "corner_center": corner_center_vals,
        "rg_map": rg / np.nanmean(rg),
        "bg_map": bg / np.nanmean(bg),
        "rb_map": rb / np.nanmean(rb),
        "y_norm": y_norm,
        "boxes": boxes,
        "region_size": float(s),
        "axisx": axisx,
        "axisy": axisy,
        "file_label": file_label,
        "contour_step": float(contour_step),
        "alpha": float(alpha),
        "gamma": float(gamma),
        "text_block": text_block,
    }


def compute_imatest_metrics(
    bin_means: np.ndarray,
    cfa: list,
    width: int,
    height: int,
    full_scale: float,
    bin_size: int,
    corner_region_pct: float = 0.05,
) -> dict:
    """统一入口：同时计算 Luma 与 Color（Bayer 时）指标。

    Returns:
        ``{"luma": {...}, "color": {...} 或 None}``。
    """
    luma = compute_imatest_luma_metrics(
        bin_means, cfa, width, height, full_scale, bin_size, corner_region_pct
    )
    color = compute_imatest_color_metrics(
        bin_means, cfa, width, height, bin_size, corner_region_pct
    )
    return {"luma": luma, "color": color}
