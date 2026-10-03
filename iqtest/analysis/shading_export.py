"""Lens Shading 结果导出：shading_profile（npy/CSV/PNG）与指标 CSV。

定位（开发文档 §17.5/§17.6）：通用参考数据（供 tuning 团队参考），
**非**可烧录产线 OTP 表；闭环自检为主、参考导出为辅。

- `write_shading_profile_npy`：全分辨率 (H, W, C) profile 落盘（LSC 校正数据）；
- `write_shading_profile_csv`：bin 网格归一化 RI 数值表（可读，Excel 友好）；
- `save_shading_profile_image`：报告通道 shading 网格的 colormap PNG；
- `save_corrected_image`：LSC 校正后图像灰度 PNG；
- `result_to_csv` / `write_result_csv`：分节指标 CSV（四象限 RI / Color shift /
  Imatest 对标，单光源 / 多光源通用）。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

#: CSV 格式版本（2：结果 CSV 改为分节表格，新增 Color shift / Imatest 对标）
SCHEMA_VERSION = 2


def _sanitize(text) -> str:
    """清洗元数据字段：逗号/分号/换行替换为空格并折叠多余空白。"""
    return re.sub(r" +", " ", re.sub(r"[,;\r\n]+", " ", str(text))).strip()


def _fmt(value: float) -> str:
    return f"{float(value):.6f}"


def _metadata_lines(result: dict, label: str) -> list[str]:
    details = result.get("details") or {}
    images = [str(k) for k in (details.get("image_sizes") or {})]
    meta = [
        ("schema_version", SCHEMA_VERSION),
        ("label", _sanitize(label)),
        ("created", datetime.now().isoformat(timespec="seconds")),
        ("mode", str(details.get("mode", "single"))),
        ("light_source", _sanitize(details.get("light_source", ""))),
        ("image", _sanitize("; ".join(images))),
        ("cfa", _sanitize("; ".join(details.get("channels") or ["Y"]))),
        ("bin_size", int(details.get("bin_size", 0) or 0)),
        ("thresh", f"{float(details.get('thresh', 0.0) or 0.0):g}"),
    ]
    return ["# LeopardIQ Lens Shading Result CSV"] + [
        f"# {k}: {v}" for k, v in meta
    ]


def write_shading_profile_npy(profile: np.ndarray, path) -> Path:
    """全分辨率 shading_profile → .npy（float64）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(str(path), np.asarray(profile, dtype=np.float64))
    return path


def write_shading_profile_csv(result: dict, path) -> Path:
    """bin 网格归一化 RI 数值表 → CSV（utf-8-sig，Excel 直接打开）。"""
    details = result.get("details") or {}
    bin_means = details.get("bin_means")
    cfa = list(details.get("channels") or ["Y"])
    if bin_means is None:
        raise ValueError(
            "结果中没有 bin 网格数据（仅单光源分析导出 shading_profile CSV）"
        )
    grid = np.asarray(bin_means, dtype=np.float64)
    mx = np.nanmax(grid, axis=(0, 1))
    grid = grid / mx
    h, w, c = grid.shape

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["y", "x"] + [str(ch) for ch in cfa])
    for y in range(h):
        for x in range(w):
            writer.writerow(
                [y, x] + [_fmt(grid[y, x, ch]) for ch in range(c)]
            )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join(_metadata_lines(result, "")) + "\n"
    path.write_text(header + buf.getvalue(), encoding="utf-8-sig")
    return path


def save_shading_profile_image(map2d: np.ndarray, path) -> Path:
    """报告通道 shading 网格 → colormap PNG（NaN 显示为白色）。"""
    data = np.asarray(map2d, dtype=np.float64)
    valid = np.isfinite(data)
    if valid.any():
        lo = float(np.nanmin(data[valid]))
        hi = float(np.nanmax(data[valid]))
    else:
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1e-6
    norm = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
    u8 = (norm * 255).astype(np.uint8)
    colored = cv2.applyColorMap(u8, cv2.COLORMAP_TURBO)
    colored[np.isnan(data)] = (255, 255, 255)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), colored)
    return path


def save_corrected_image(image: np.ndarray, path, *, bits: int = 16) -> Path:
    """LSC 校正后图像（2D 灰度或 3 通道彩色）→ PNG（按数据范围归一化，NaN 置 0）。

    Args:
        image: 校正后图像数据（closed_loop["corrected_image"]，Bayer 时为 demosaic
            后 RGB 彩色，mono 时为灰度）。
        path: 输出 png 路径。
        bits: 输出位深（8 或 16，默认 16 保留更多层次）。
    """
    data = np.asarray(image, dtype=np.float64)
    finite = data[np.isfinite(data)]
    if finite.size:
        lo, hi = float(finite.min()), float(finite.max())
    else:
        lo, hi = 0.0, 1.0
    if hi <= lo:
        hi = lo + 1e-6
    norm = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
    norm = np.where(np.isfinite(data), norm, 0.0)
    if bits == 8:
        out = (norm * 255.0).round().astype(np.uint8)
    else:
        out = (norm * 65535.0).round().astype(np.uint16)
    if out.ndim == 3 and out.shape[-1] == 3:
        out = out[:, :, ::-1].copy()  # RGB → BGR 供 cv2.imwrite
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out)
    return path


def _metric_rows(metrics: dict, group: str = "") -> list[tuple]:
    """单个结果 metrics → (metric, group, value, status) 行（数组按通道展开）。

    当 status 为逐通道列表时，与 value 逐通道对应；为字符串时所有通道共享。
    """
    rows: list[tuple] = []
    for key, metric in metrics.items():
        value = metric.get("value")
        status = metric.get("status", "INFO")
        if isinstance(value, (list, tuple, np.ndarray)):
            vals = np.atleast_1d(value)
            stats = np.atleast_1d(status)
            for i, v in enumerate(vals):
                s = stats[i] if i < len(stats) else status
                rows.append((key, f"{group}{i}", _fmt(v), s))
        else:
            rows.append((key, group, _fmt(value), status))
    return rows


#: Color shift 指标键（从主判定表中拆出，单列一节）
_COLOR_SHIFT_KEYS = ("green_red_shift", "green_blue_shift")


def _color_shift_rows(metrics: dict) -> list[list]:
    """Color shift 指标 → (metric, value, status) 行（缺失项跳过）。"""
    rows: list[list] = []
    for key in _COLOR_SHIFT_KEYS:
        metric = metrics.get(key)
        if metric is None:
            continue
        rows.append([key, _fmt(metric.get("value")), metric.get("status", "INFO")])
    return rows


def _imatest_blocks(imatest: dict | None) -> list[tuple]:
    """Imatest 对标结果 → [(标题, 表头, 行)]（Luma / Color 各一节，缺失则跳过）。"""
    if not imatest:
        return []
    blocks: list[tuple] = []

    luma = imatest.get("luma")
    if luma:
        rows = [
            ["max_rel", _fmt(luma.get("max_rel"))],
            ["max_pixel", _fmt(luma.get("max_pixel"))],
        ]
        corners = luma.get("corners") or {}
        rows += [[f"corners_{k}", _fmt(corners[k])]
                 for k in ("UL", "LL", "UR", "LR", "worst", "mean") if k in corners]
        sides = luma.get("sides") or {}
        rows += [[f"sides_{k}", _fmt(sides[k])]
                 for k in ("L", "R", "T", "B", "mean") if k in sides]
        for i, v in enumerate(np.atleast_1d(sides.get("worst", []))):
            rows.append([f"sides_worst{i}", _fmt(v)])
        blocks.append(("Imatest 对标：Luma 指标", ["metric", "value"], rows))

    color = imatest.get("color")
    if color:
        rows = []
        for name, ratio in (("rg", color.get("rg")), ("bg", color.get("bg"))):
            if not ratio:
                continue
            rows += [[f"{name}_{k}", _fmt(ratio[k])]
                     for k in ("max", "min", "UL", "LL", "UR", "LR", "L", "R",
                               "T", "B", "C", "corners_worst", "corners_mean")
                     if k in ratio]
        center = color.get("corner_center") or {}
        rows += [[f"corner_center_{k}", _fmt(center[k])]
                 for k in ("r_b", "r_g", "b_g") if k in center]
        blocks.append(("Imatest 对标：Color Shading（R/G、B/G）",
                       ["metric", "value"], rows))
    return blocks


def _single_blocks(result: dict, details: dict) -> list[tuple]:
    """单光源 → [(标题, 表头, 行)]：RI 判定 + Color shift + Imatest 对标。"""
    metrics = result.get("metrics") or {}
    cfa = list(details.get("channels") or ["Y"])

    ri_rows = []
    for metric, group, value, status in _metric_rows(
        {k: v for k, v in metrics.items() if k not in _COLOR_SHIFT_KEYS}
    ):
        channel = cfa[int(group)] if group.isdigit() and int(group) < len(cfa) else ""
        ri_rows.append([metric, channel, value, status])

    blocks = [
        ("四象限 RI 判定", ["metric", "channel", "value", "status"], ri_rows),
        ("Color shift", ["metric", "value", "status"], _color_shift_rows(metrics)),
    ]
    blocks.extend(_imatest_blocks(details.get("imatest")))
    return blocks


def _multi_blocks(details: dict) -> list[tuple]:
    """多光源 → [(标题, 表头, 行)]：逐光源 RI 判定 + Color shift。"""
    ri_rows: list[list] = []
    color_rows: list[list] = []
    for light_name, res in (details.get("lights") or {}).items():
        metrics = res.get("metrics", {})
        for metric, _group, value, status in _metric_rows(
            {k: v for k, v in metrics.items() if k not in _COLOR_SHIFT_KEYS}
        ):
            ri_rows.append([light_name, metric, value, status])
        for row in _color_shift_rows(metrics):
            color_rows.append([light_name, *row])
    return [
        ("四象限 RI 判定（逐光源）", ["light", "metric", "value", "status"], ri_rows),
        ("Color shift（逐光源）", ["light", "metric", "value", "status"], color_rows),
    ]


def result_to_csv(result: dict, label: str = "", created: str | None = None) -> str:
    """analyze_shading 结果 → CSV 文本（纯函数）。

    分节输出（`# ===== 标题 =====` 分隔、各节独立表头）：
    - 四象限 RI 判定：逐通道 RI + ri_diff（多光源时逐光源展开）；
    - Color shift：green_red_shift / green_blue_shift；
    - Imatest 对标：Luma / Color Shading 结构化指标（单光源且启用时）。
    """
    details = result.get("details") or {}
    mode = details.get("mode", "single")

    if not label:
        images = list((details.get("image_sizes") or {}).keys())
        label = Path(images[0]).stem if images else "Shading"
    if created is None:
        created = datetime.now().isoformat(timespec="seconds")

    lines = _metadata_lines(result, label)
    blocks = _multi_blocks(details) if mode == "multi" else _single_blocks(result, details)

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for title, header, rows in blocks:
        if not rows:
            continue
        buf.write(f"# ===== {title} =====\n")
        writer.writerow(header)
        writer.writerows(rows)

    lines.append(buf.getvalue().rstrip("\n"))
    return "\n".join(lines) + "\n"


def write_result_csv(result: dict, path, label: str = "") -> Path:
    """指标 CSV 落盘（utf-8-sig 带 BOM）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_to_csv(result, label=label), encoding="utf-8-sig")
    return path
