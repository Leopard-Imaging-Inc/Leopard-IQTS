"""MTF 模组比较的 CSV 读写（纯函数，不依赖 GUI）。

自 iqtest/analysis/mtf_compare.py 拆分出的「CSV 进出」部分：
- parse_result_csv / load_result_csv：解析 MTF 结果 CSV（输入）
- compare_result_to_csv / write_compare_csv：比较结果 CSV（输出）

依赖 _model 中的 field_zone / pair_outcome / 默认配置常量。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from leopardiq.mtf import unit_label

from ._model import (
    DEFAULT_SCORE_TIE,
    DEFAULT_TIE_FREQ,
    DEFAULT_TIE_SFR,
    DEFAULT_ZONE_WEIGHTS,
    _ZONE_SORT,
    field_zone,
    pair_outcome,
)

#: 期望的 CSV 格式版本（缺失或不符时报错）
SCHEMA_VERSION = 1

#: 指标表的基础列（其余列均为指标列）
_BASE_COLUMNS = {"roi", "channel", "cx_norm", "cy_norm",
                 "roi_l", "roi_r", "roi_t", "roi_b", "valid"}

#: 比较结果 CSV 格式版本
COMPARE_SCHEMA_VERSION = 1


# ----------------------------------------------------------------------
# CSV 解析
# ----------------------------------------------------------------------
def parse_result_csv(text: str) -> dict:
    """解析 MTF 结果 CSV 文本 → {"meta": {...}, "rows": [...]}。

    meta 为类型化字典：label/image/freq_unit 为 str，freq1/gamma/
    pixel_size_um 为 float，picture_height/image_width/image_height 为
    int（可缺省为空）。未知 `#` 键静默忽略（向后兼容）。

    rows 逐 (ROI, 通道)：
    {"roi": int, "channel": str, "cx": float|None, "cy": float|None,
     "valid": bool, "metrics": {指标 key: float|None}}

    Raises:
        ValueError: 缺格式标识 / schema_version / 关键口径字段，
                    或表结构非法
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or lines[0].strip() != "# LeopardIQ MTF Result CSV":
        raise ValueError("不是 LeopardIQ MTF 结果 CSV（缺格式标识行）")

    meta_raw: dict[str, str] = {}
    table_lines: list[str] = []
    for ln in lines[1:]:
        if ln.startswith("#"):
            key, _, value = ln[1:].partition(":")
            meta_raw[key.strip()] = value.strip()
        else:
            table_lines.append(ln)

    if meta_raw.get("schema_version") != str(SCHEMA_VERSION):
        raise ValueError(
            f"MTF 结果 CSV 缺 schema_version 或版本不符"
            f"（期望 {SCHEMA_VERSION}，实际 {meta_raw.get('schema_version')!r}）"
        )

    def _float(key: str, required: bool = False, default: float = 0.0) -> float:
        raw = meta_raw.get(key, "")
        if raw == "":
            if required:
                raise ValueError(f"MTF 结果 CSV 缺关键口径字段：{key}")
            return default
        try:
            return float(raw)
        except ValueError:
            raise ValueError(f"MTF 结果 CSV 元数据 {key} 非法：{raw!r}") from None

    def _int(key: str) -> int:
        raw = meta_raw.get(key, "")
        if raw == "":
            return 0
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"MTF 结果 CSV 元数据 {key} 非法：{raw!r}") from None

    freq_unit = meta_raw.get("freq_unit", "")
    if not freq_unit:
        raise ValueError("MTF 结果 CSV 缺关键口径字段：freq_unit")
    unit_label(freq_unit)  # 校验单位名合法性（未知单位抛 ValueError）

    meta = {
        "label": meta_raw.get("label", ""),
        "created": meta_raw.get("created", ""),
        "image": meta_raw.get("image", ""),
        "image_width": _int("image_width"),
        "image_height": _int("image_height"),
        "freq_unit": freq_unit,
        "freq1": _float("freq1", required=True),
        "gamma": _float("gamma", required=True),
        "pixel_size_um": _float("pixel_size_um"),
        "picture_height": _int("picture_height"),
    }

    reader = csv.DictReader(io.StringIO("\n".join(table_lines)))
    if not reader.fieldnames or not _BASE_COLUMNS.issubset(reader.fieldnames):
        raise ValueError(
            f"MTF 结果 CSV 表头缺基础列（需含 {sorted(_BASE_COLUMNS)}）"
        )
    metric_keys = [c for c in reader.fieldnames if c not in _BASE_COLUMNS]
    if not metric_keys:
        raise ValueError("MTF 结果 CSV 没有任何指标列")

    rows: list[dict] = []
    for raw in reader:
        try:
            roi = int(raw["roi"])
            valid = raw["valid"] == "1"
        except (TypeError, ValueError):
            raise ValueError(f"MTF 结果 CSV 行非法：{raw!r}") from None
        cx, cy = raw.get("cx_norm") or "", raw.get("cy_norm") or ""
        metrics = {}
        for key in metric_keys:
            cell = raw.get(key) or ""
            metrics[key] = float(cell) if cell else None
        rows.append({
            "roi": roi,
            "channel": raw["channel"],
            "cx": float(cx) if cx else None,
            "cy": float(cy) if cy else None,
            "valid": valid,
            "metrics": metrics,
        })
    if not rows:
        raise ValueError("MTF 结果 CSV 没有数据行")
    return {"meta": meta, "rows": rows, "metric_keys": metric_keys}


def load_result_csv(path) -> dict:
    """从文件加载 MTF 结果 CSV（自动处理 utf-8-sig BOM）。"""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"MTF 结果 CSV 不存在：{path}")
    return parse_result_csv(path.read_text(encoding="utf-8-sig"))


# ----------------------------------------------------------------------
# 比较结果 CSV 导出（用户主动保存，面板「保存比较结果 CSV…」）
# ----------------------------------------------------------------------
def compare_result_to_csv(result: dict, created: str | None = None) -> str:
    """`compare` 返回 dict → 比较结果 CSV 文本（纯函数，不落盘）。

    格式：`#` 元数据头（双方 label、比较配置、逐项统计与总体结论）
    + 逐配对行表（zone / channel / roi_a / roi_b + 每个测试项的
    A 值 / B 值 / Δ / 胜负，频率类按 display_unit 显示单位换算）。
    仅单侧存在的 ROI 附在表尾（结果列标「仅A」/「仅B」）。
    """
    from datetime import datetime

    if created is None:
        created = datetime.now().isoformat(timespec="seconds")
    keys = [m["key"] for m in result["metrics"]]
    kinds = {m["key"]: m["kind"] for m in result["metrics"]}
    echo = result.get("config_echo") or {}
    tie = {"freq": float(echo.get("tie_freq", DEFAULT_TIE_FREQ)),
           "sfr": float(echo.get("tie_sfr", DEFAULT_TIE_SFR))}
    scale = float(result.get("display_scale", 1.0))
    stats = result.get("stats", {})

    def _disp(key: str, value: float | None) -> str:
        if value is None:
            return ""
        factor = scale if kinds[key] == "freq" else 1.0
        return f"{value * factor:.6f}"

    lines = ["# LeopardIQ MTF Compare Result CSV"]
    weights = echo.get("zone_weights", DEFAULT_ZONE_WEIGHTS)
    meta = [
        ("compare_schema_version", COMPARE_SCHEMA_VERSION),
        ("created", created),
        ("label_a", result["labels"]["a"]),
        ("label_b", result["labels"]["b"]),
        ("main_metric", result["main_metric"]),
        ("tie_freq", f"{tie['freq']:g}"),
        ("tie_sfr", f"{tie['sfr']:g}"),
        ("score_tie", f"{float(echo.get('score_tie', DEFAULT_SCORE_TIE)):g}"),
        ("zone_weights",
         ";".join(f"{g}={weights.get(g, 0.0):g}"
                  for g in ("center", "edge", "corner"))),
        ("display_unit", result.get("display_unit", "")),
        ("cross_pixel", int(bool(result.get("cross_pixel")))),
        ("verdict", result.get("main_summary", "")),
    ]
    lines += [f"# {k}: {v}" for k, v in meta]
    for key in keys:
        st = stats[key]
        lines.append(
            f"# stat_{key}: win={st['win']};tie={st['tie']};loss={st['loss']}"
            f";excluded={st['excluded']};score_a={st['score_a']:.6f}"
            f";score_b={st['score_b']:.6f};verdict={st['verdict']}"
        )

    headers = ["zone", "channel", "roi_a", "roi_b"]
    for key in keys:
        headers += [f"{key}_a", f"{key}_b", f"{key}_delta", f"{key}_result"]

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)

    def _sort_key(pair):
        return (_ZONE_SORT.index(pair["zone"])
                if pair["zone"] in _ZONE_SORT else len(_ZONE_SORT),
                pair["roi_a"])

    for pair in sorted(result["pairs"], key=_sort_key):
        row = [pair["zone"], pair["channel"], pair["roi_a"], pair["roi_b"]]
        for key in keys:
            delta = pair["delta"][key]
            row += [
                _disp(key, pair["values_a"][key]),
                _disp(key, pair["values_b"][key]),
                _disp(key, delta),
                pair_outcome(delta, tie[kinds[key]]),
            ]
        writer.writerow(row)

    for side, rows, mark in (("a", result.get("only_a", []), "仅A"),
                             ("b", result.get("only_b", []), "仅B")):
        other = "" if side == "a" else ""
        for r in rows:
            zone = (field_zone(r["cx"], r["cy"])
                    if r["cx"] is not None and r["cy"] is not None else "")
            row = [zone, r["channel"],
                   r["roi"] if side == "a" else "",
                   r["roi"] if side == "b" else ""]
            row += ["", "", "", mark] + ["", "", "", ""] * (len(keys) - 1)
            writer.writerow(row)

    lines.append(buf.getvalue().rstrip("\n"))
    return "\n".join(lines) + "\n"


def write_compare_csv(result: dict, path) -> Path:
    """比较结果 CSV 落盘（utf-8-sig 带 BOM，Excel 直接打开不乱码）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compare_result_to_csv(result), encoding="utf-8-sig")
    return path
