"""Lens Shading 结果导出：shading_profile（npy/CSV/PNG）与指标 CSV。

定位（开发文档 §17.5/§17.6）：通用参考数据（供 tuning 团队参考），
**非**可烧录产线 OTP 表；闭环自检为主、参考导出为辅。

- `write_shading_profile_npy`：全分辨率 (H, W, C) profile 落盘（LSC 校正数据）；
- `write_shading_profile_csv`：bin 网格归一化 RI 数值表（可读，Excel 友好）；
- `save_shading_profile_image`：报告通道 shading 网格的 colormap PNG；
- `result_to_csv` / `write_result_csv`：指标判定 CSV（单光源 / 多光源通用）。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

#: CSV 格式版本
SCHEMA_VERSION = 1


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


def _metric_rows(metrics: dict, group: str = "") -> list[tuple]:
    """单个结果 metrics → (metric, group, value, status) 行（数组按通道展开）。"""
    rows: list[tuple] = []
    for key, metric in metrics.items():
        value = metric.get("value")
        status = metric.get("status", "INFO")
        if isinstance(value, (list, tuple, np.ndarray)):
            for i, v in enumerate(np.atleast_1d(value)):
                rows.append((key, f"{group}{i}", _fmt(v), status))
        else:
            rows.append((key, group, _fmt(value), status))
    return rows


def result_to_csv(result: dict, label: str = "", created: str | None = None) -> str:
    """analyze_shading 结果 → CSV 文本（纯函数）。

    单光源：逐 metric（四象限 RI 按通道展开 + ri_diff + shift）；
    多光源：逐光源逐 metric 展开。
    """
    details = result.get("details") or {}
    mode = details.get("mode", "single")

    if not label:
        images = list((details.get("image_sizes") or {}).keys())
        label = Path(images[0]).stem if images else "Shading"
    if created is None:
        created = datetime.now().isoformat(timespec="seconds")

    lines = _metadata_lines(result, label)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")

    if mode == "multi":
        writer.writerow(["light", "metric", "value", "status"])
        for light_name, res in (details.get("lights") or {}).items():
            for metric, _group, value, status in _metric_rows(
                res.get("metrics", {})
            ):
                writer.writerow([light_name, metric, value, status])
    else:
        writer.writerow(["metric", "channel", "value", "status"])
        metrics = result.get("metrics") or {}
        cfa = list(details.get("channels") or ["Y"])
        for metric, group, value, status in _metric_rows(metrics):
            channel = cfa[int(group)] if group.isdigit() and int(group) < len(cfa) else ""
            writer.writerow([metric, channel, value, status])

    lines.append(buf.getvalue().rstrip("\n"))
    return "\n".join(lines) + "\n"


def write_result_csv(result: dict, path, label: str = "") -> Path:
    """指标 CSV 落盘（utf-8-sig 带 BOM）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_to_csv(result, label=label), encoding="utf-8-sig")
    return path
