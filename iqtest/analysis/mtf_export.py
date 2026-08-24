"""MTF 结果 CSV 导出：`analyze_mtf` 结果 dict → 模组比较用 CSV 文本。

CSV 格式（见 `doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md` §3.2）：

- `#` 开头的元数据头：schema_version / label / created / image /
  图像尺寸 / freq_unit / freq1 / gamma / pixel_size_um / picture_height
  ——模组比较时用于同口径校验；
- 逐 (ROI, 通道) 指标表：roi, channel, cx_norm, cy_norm,
  roi_l, roi_r, roi_t, roi_b, valid,
  mtf@{评估频率}, mtf50, 各 Secondary Readout 动态列, mtfa。

`cx_norm` / `cy_norm` 为 ROI 中心坐标归一化到图像尺寸（0~1），
是比较功能按视场位置（中心/四角）匹配 ROI 的唯一依据；
`roi_l / roi_r / roi_t / roi_b` 为所选 ROI 框的真实像素坐标
（L=Left 左、R=Right 右、T=Top 上、B=Bottom 下），用于还原/核对
实际选中的检测框位置；
`mtfa` 为 MTF 曲线下面积（0~Nyquist 梯形积分），导出时趁内存中
尚有完整曲线算好（CSV 不含曲线数据）。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import numpy as np

#: CSV 格式版本（比较功能加载时校验，缺失/不符报明确错误）
SCHEMA_VERSION = 1

#: Nyquist 频率（cy/px），MTFa 积分上限
NYQUIST_CY_PX = 0.5

# numpy 2.x 为 trapezoid，1.x 为 trapz（pyd 环境 numpy<2 兼容）
_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def compute_mtfa(freq, mtf, nyquist: float = NYQUIST_CY_PX) -> float:
    """MTF 曲线下面积：0 ~ Nyquist 的梯形积分（cy/px 口径）。

    有效采样点 < 2 时返回 NaN。MTFa 对单频率点噪声不敏感，
    作为整体锐度度量参与模组比较。
    """
    f = np.asarray(freq, dtype=np.float64).ravel()
    m = np.asarray(mtf, dtype=np.float64).ravel()
    sel = np.isfinite(f) & np.isfinite(m) & (f <= nyquist)
    if int(sel.sum()) < 2:
        return float("nan")
    return float(_trapezoid(m[sel], f[sel]))


def _sanitize(text) -> str:
    """清洗元数据字段：逗号/分号/换行替换为空格并折叠多余空白。"""
    return re.sub(r" +", " ", re.sub(r"[,;\r\n]+", " ", str(text))).strip()


def _fmt(value: float) -> str:
    return f"{float(value):.6f}"


def result_to_csv(result: dict, label: str = "", created: str | None = None) -> str:
    """`analyze_mtf` 结果 dict → CSV 文本（纯函数，不落盘）。

    Args:
        result: `analyze_mtf` 返回 dict（需含 details.curves / rois /
                image_sizes 等）
        label: 模组标签（显示在对比结果的 A/B 表头）；
               为空时取首个源图像文件名主干
        created: 创建时间字符串，默认当前时间（ISO 秒级）；测试可注入

    Raises:
        ValueError: 结果中没有曲线数据
    """
    details = result.get("details") or {}
    curves = details.get("curves") or []
    if not curves:
        raise ValueError("结果中没有 MTF 曲线数据（details.curves 为空），无法导出")

    freq1 = float((details.get("frequency") or [0.125])[0])
    readouts = details.get("readouts") or []
    rois = details.get("rois") or []
    image_sizes = details.get("image_sizes") or {}
    roi_map = {int(r["roi"]): r for r in rois}

    # 源图像与尺寸元数据（多图时取首个 ROI 的图像；归一化坐标逐行按各自图像算）
    images: list[str] = []
    for r in rois:
        name = str(r.get("image") or "")
        if name and name not in images:
            images.append(name)
    first_size = image_sizes.get(images[0], []) if images else []

    if not label:
        label = Path(images[0]).stem if images else "MTF"
    if created is None:
        created = datetime.now().isoformat(timespec="seconds")

    # ---- 元数据头
    meta = [
        ("schema_version", SCHEMA_VERSION),
        ("label", _sanitize(label)),
        ("created", created),
        ("image", _sanitize("; ".join(images))),
        ("image_width", first_size[0] if len(first_size) == 2 else ""),
        ("image_height", first_size[1] if len(first_size) == 2 else ""),
        ("freq_unit", str(details.get("freq_unit", "Cycles/pixel"))),
        ("freq1", f"{freq1:g}"),
        ("gamma", f"{float(details.get('gamma', 1.0)):g}"),
        ("pixel_size_um", f"{float(details.get('pixel_size_um', 0.0) or 0.0):g}"),
        ("picture_height", int(details.get("picture_height", 0) or 0)),
    ]
    lines = ["# LeopardIQ MTF Result CSV"]
    lines += [f"# {k}: {v}" for k, v in meta]

    # ---- 指标表
    headers = ["roi", "channel", "cx_norm", "cy_norm",
               "roi_l", "roi_r", "roi_t", "roi_b", "valid",
               f"mtf@{freq1:g}", "mtf50"]
    headers += [str(r["key"]) for r in readouts]
    headers.append("mtfa")

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)

    # 基础列（含新增 ROI 框坐标与 valid）之后的指标单元格数
    base_count = len(["roi", "channel", "cx_norm", "cy_norm",
                      "roi_l", "roi_r", "roi_t", "roi_b", "valid"])

    for curve in curves:
        valid = bool(curve.get("valid")) and bool(curve.get("freq"))
        # 归一化中心坐标 + ROI 框像素坐标（L R T B）
        cx_norm = cy_norm = ""
        roi_l = roi_r = roi_t = roi_b = ""
        record = roi_map.get(int(curve["roi"]))
        if record is not None:
            size = image_sizes.get(str(record.get("image") or ""), [])
            if len(size) == 2 and size[0] > 0 and size[1] > 0:
                x, y, w, h = record["rect"]
                cx_norm = _fmt((x + w / 2) / size[0])
                cy_norm = _fmt((y + h / 2) / size[1])
                roi_l, roi_r, roi_t, roi_b = (int(x), int(x + w),
                                              int(y), int(y + h))
        if valid:
            sfr = curve.get("sfr", [float("nan")])[0]
            readout_vals = curve.get("readouts", [])
            metric_cells = [_fmt(sfr), _fmt(curve.get("mtf50", 0.0))]
            metric_cells += [
                _fmt(readout_vals[i]) if i < len(readout_vals) else ""
                for i in range(len(readouts))
            ]
            metric_cells.append(
                _fmt(compute_mtfa(curve["freq"], curve["mtf"]))
            )
        else:
            metric_cells = [""] * (len(headers) - base_count)
        writer.writerow([
            int(curve["roi"]), str(curve["channel"]), cx_norm, cy_norm,
            roi_l, roi_r, roi_t, roi_b, 1 if valid else 0, *metric_cells,
        ])

    lines.append(buf.getvalue().rstrip("\n"))
    return "\n".join(lines) + "\n"


def write_result_csv(result: dict, path, label: str = "") -> Path:
    """导出结果 CSV 到文件（utf-8-sig 带 BOM，Excel 直接打开不乱码）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result_to_csv(result, label=label), encoding="utf-8-sig")
    return path
