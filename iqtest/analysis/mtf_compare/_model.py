"""MTF 模组比较的领域模型与口径校验（纯函数，不依赖 GUI、不做 CSV 读写）。

自 iqtest/analysis/mtf_compare.py 拆分出的「视场 / 指标模型 + 口径校验」部分：
- field_zone / zone_group：视场位置与分区
- metric_kind / metric_label / available_metrics：指标类型与友好名
- match_rois / normalized_metric：ROI 配对与指标归一化
- check_compatibility：两款口径校验
- available_metrics_multi / check_compatibility_multi / match_zones_multi：多款辅助

本模块不导入 _csv_io / _core，避免循环依赖。
"""

from __future__ import annotations

import math
import re

from leopardiq.mtf import unit_label, unit_scale, unit_to_cy_px

#: 默认打平阈值：频率类（cy/px）/ SFR 类（0~1）——必须大于测量
#: 不确定度 ±0.003（见 MTF 开发文档 §13），否则差异无意义
DEFAULT_TIE_FREQ = 0.01
DEFAULT_TIE_SFR = 0.01
#: 总体评分打平阈值（归一化评分差）
DEFAULT_SCORE_TIE = 0.01
#: 默认分区权重：中心 / 边缘 / 四角
DEFAULT_ZONE_WEIGHTS = {"center": 0.4, "edge": 0.3, "corner": 0.3}

#: 视场位置 → 分区（评分加权用）
ZONE_GROUP = {
    "center": "center",
    "top": "edge", "bottom": "edge", "left": "edge", "right": "edge",
    "corner_tl": "corner", "corner_tr": "corner",
    "corner_bl": "corner", "corner_br": "corner",
}

#: 分区中文名（摘要文本用）
ZONE_GROUP_CN = {"center": "中心", "edge": "边缘", "corner": "四角"}

_FREQ_TOL = 1e-6
_GAMMA_TOL = 1e-9
_PIXEL_TOL = 1e-9

#: 配对行的固定排序：中心优先，其后四角、边缘
_ZONE_SORT = ["center", "corner_tl", "corner_tr", "corner_bl", "corner_br",
              "top", "bottom", "left", "right"]


# ----------------------------------------------------------------------
# 视场位置
# ----------------------------------------------------------------------
def field_zone(cx: float, cy: float) -> str:
    """归一化坐标 → 3×3 九宫格视场位置标签。

    五黑块 chart 的实际结果 = center + corner_tl/tr/bl/br。
    """
    col = 0 if cx < 1 / 3 else (2 if cx >= 2 / 3 else 1)
    row = 0 if cy < 1 / 3 else (2 if cy >= 2 / 3 else 1)
    if col == 1 and row == 1:
        return "center"
    if col == 1:
        return "top" if row == 0 else "bottom"
    if row == 1:
        return "left" if col == 0 else "right"
    return f"corner_{'t' if row == 0 else 'b'}{'l' if col == 0 else 'r'}"


def zone_group(zone: str) -> str:
    """视场位置 → 分区（center / edge / corner）。"""
    return ZONE_GROUP[zone]


# ----------------------------------------------------------------------
# 测试项（指标）
# ----------------------------------------------------------------------
def metric_kind(key: str) -> str:
    """指标类型："freq"（频率类：mtf50/mtfNN/mtfNNP）或 "sfr"（0~1 无单位）。"""
    if key == "mtfa" or key.startswith("mtf@"):
        return "sfr"
    if re.fullmatch(r"mtf\d+p?", key):
        return "freq"
    raise ValueError(f"未知指标列：{key!r}")


def metric_label(key: str, freq_unit: str = "") -> str:
    """指标列的友好显示名（如 mtf@0.125 → 'MTF @ 0.125 cy/px (1/4 Nyquist)'）。"""
    if key.startswith("mtf@"):
        freq_str = key[4:]
        label = f"MTF @ {freq_str}"
        if freq_unit:
            label += f" {unit_label(freq_unit)}"
            if freq_unit == "Cycles/pixel":
                try:
                    k = 0.5 / float(freq_str)
                except (ValueError, ZeroDivisionError):
                    k = 0.0
                if 2 <= round(k) <= 8 and abs(k - round(k)) < 1e-3:
                    label += f" (1/{round(k)} Nyquist)"
        return label
    if key == "mtfa":
        return "MTFa"
    m = re.fullmatch(r"mtf(\d+)(p?)", key)
    if m:
        label = f"MTF{m.group(1)}{'P' if m.group(2) else ''}"
        if freq_unit:
            label += f" ({unit_label(freq_unit)})"
        return label
    return key


def available_metrics(a: dict, b: dict) -> list[dict]:
    """可比较的测试项 = 两份 CSV 指标列的交集（保持 A 的列序）。

    Returns:
        [{"key", "label", "kind"}]，交集为空时抛 ValueError
    """
    keys = [k for k in a["metric_keys"] if k in set(b["metric_keys"])]
    if not keys:
        raise ValueError(
            "两份 CSV 没有共同的 MTF 测试项（指标列交集为空），无法比较"
        )
    return [
        {"key": k, "label": metric_label(k, a["meta"]["freq_unit"]),
         "kind": metric_kind(k)}
        for k in keys
    ]


# ----------------------------------------------------------------------
# 口径校验
# ----------------------------------------------------------------------
def check_compatibility(a: dict, b: dict) -> None:
    """同口径校验（模组比较设计文档 §2），不满足抛 ValueError。"""
    la, lb = a["meta"].get("label") or "A", b["meta"].get("label") or "B"
    ma, mb = a["meta"], b["meta"]
    if ma["freq_unit"] != mb["freq_unit"]:
        raise ValueError(
            f"频率单位不一致，禁止混单位比较：{la} = {ma['freq_unit']}，"
            f"{lb} = {mb['freq_unit']}"
        )
    if abs(ma["freq1"] - mb["freq1"]) > _FREQ_TOL:
        raise ValueError(
            f"评估频率不一致：{la} = {ma['freq1']:g} cy/px，"
            f"{lb} = {mb['freq1']:g} cy/px"
        )
    if abs(ma["gamma"] - mb["gamma"]) > _GAMMA_TOL:
        raise ValueError(
            f"Gamma 不一致（影响 MTF 曲线形状）：{la} = {ma['gamma']:g}，"
            f"{lb} = {mb['gamma']:g}"
        )
    available_metrics(a, b)  # 交集为空时抛错


# ----------------------------------------------------------------------
# ROI 配对（按视场位置，不用坐标）
# ----------------------------------------------------------------------
def match_rois(rows_a: list[dict], rows_b: list[dict]) -> dict:
    """按视场位置配对两份结果的 ROI。

    规则（设计文档 §3.3）：同一 (视场位置, 通道) 内配对；同位置多 ROI
    按到图像中心的归一化距离排序后依次配对；一侧多出的 ROI 进入
    only_a / only_b 不参与比较。缺归一化坐标的行无法配对，列入 only。

    Returns:
        {"pairs": [(row_a, row_b, zone)], "only_a": [...], "only_b": [...]}
    """
    def _group(rows):
        groups: dict[tuple[str, str], list[dict]] = {}
        unmatched: list[dict] = []
        for row in rows:
            if row["cx"] is None or row["cy"] is None:
                unmatched.append(row)
                continue
            zone = field_zone(row["cx"], row["cy"])
            key = (zone, row["channel"])
            groups.setdefault(key, []).append(row)
        for rows_in_group in groups.values():
            rows_in_group.sort(
                key=lambda r: math.hypot(r["cx"] - 0.5, r["cy"] - 0.5)
            )
        return groups, unmatched

    groups_a, unmatched_a = _group(rows_a)
    groups_b, unmatched_b = _group(rows_b)

    pairs: list[tuple[dict, dict, str]] = []
    only_a = list(unmatched_a)
    only_b = list(unmatched_b)
    for key in sorted(set(groups_a) | set(groups_b)):
        list_a = groups_a.get(key, [])
        list_b = groups_b.get(key, [])
        for row_a, row_b in zip(list_a, list_b):
            pairs.append((row_a, row_b, key[0]))
        only_a.extend(list_a[len(list_b):])
        only_b.extend(list_b[len(list_a):])
    return {"pairs": pairs, "only_a": only_a, "only_b": only_b}


def normalized_metric(row: dict, meta: dict, key: str) -> float | None:
    """指标值归一化到比较口径（频率类 → cy/px）；无效/缺值返回 None。

    compare() 内部同款逻辑的公开版，供多款比较的图表直接使用。
    """
    value = row["metrics"].get(key)
    if value is None or not row["valid"]:
        return None
    if metric_kind(key) == "freq":
        return unit_to_cy_px(
            value, meta["freq_unit"],
            meta["pixel_size_um"] or None,
            meta["picture_height"] or None,
        )
    return float(value)


def pair_outcome(delta: float | None, tie: float) -> str:
    """单对差异 → 胜负标记："A" / "B" / "TIE" / ""（无差异值）。"""
    if delta is None:
        return ""
    if abs(delta) <= tie:
        return "TIE"
    return "A" if delta > 0 else "B"


# ----------------------------------------------------------------------
# 多款比较（N ≥ 2，基准金样模式）
# ----------------------------------------------------------------------
def available_metrics_multi(datasets: list[dict]) -> list[dict]:
    """N 份 CSV 的可比较测试项 = 全部指标列的交集（保持首份列序）。"""
    if len(datasets) < 2:
        raise ValueError("至少需要两份 MTF 结果 CSV")
    common = set(datasets[0]["metric_keys"])
    for ds in datasets[1:]:
        common &= set(ds["metric_keys"])
    keys = [k for k in datasets[0]["metric_keys"] if k in common]
    if not keys:
        raise ValueError(
            "各 CSV 没有共同的 MTF 测试项（指标列交集为空），无法比较"
        )
    return [
        {"key": k, "label": metric_label(k, datasets[0]["meta"]["freq_unit"]),
         "kind": metric_kind(k)}
        for k in keys
    ]


def check_compatibility_multi(datasets: list[dict]) -> None:
    """N 份 CSV 同口径校验：以首份为基准逐一校验。"""
    if len(datasets) < 2:
        raise ValueError("至少需要两份 MTF 结果 CSV")
    ref = datasets[0]
    for other in datasets[1:]:
        check_compatibility(ref, other)
    available_metrics_multi(datasets)


def match_zones_multi(rows_list: list[list[dict]]) -> dict:
    """N 份结果的公共视场位置匹配（多款比较用）。

    规则与 match_rois 一致：按 (视场位置, 通道) 分组，只保留**全部镜头
    都有数据**的公共组；同组多 ROI 按到图像中心的归一化距离排序，
    组数 = 各镜头该组数量的最小值。

    Returns:
        {
          "keys": [(zone, channel), ...]（按视场位置排序），
          "groups": {key: [(row_镜头0, row_镜头1, ...), ...]},
          "counts": {zone: [各镜头该位置 ROI 数]},
        }
    """
    per_lens: list[dict[tuple[str, str], list[dict]]] = []
    per_lens_zc: list[dict[str, int]] = []
    for rows in rows_list:
        groups: dict[tuple[str, str], list[dict]] = {}
        zone_count: dict[str, int] = {}
        for r in rows:
            if r["cx"] is None or r["cy"] is None:
                continue
            zone = field_zone(r["cx"], r["cy"])
            key = (zone, r["channel"])
            groups.setdefault(key, []).append(r)
            zone_count[zone] = zone_count.get(zone, 0) + 1
        for g in groups.values():
            g.sort(key=lambda r: math.hypot(r["cx"] - 0.5, r["cy"] - 0.5))
        per_lens.append(groups)
        per_lens_zc.append(zone_count)
    # counts: zone → [每镜头数量]（没有该位置的镜头补 0）
    all_zones = {z for zc in per_lens_zc for z in zc}
    counts = {z: [zc.get(z, 0) for zc in per_lens_zc] for z in all_zones}

    common = set(per_lens[0])
    for g in per_lens[1:]:
        common &= set(g)
    keys = sorted(
        common,
        key=lambda k: (_ZONE_SORT.index(k[0]) if k[0] in _ZONE_SORT else 99,
                       k[1]),
    )
    groups = {}
    for key in keys:
        n = min(len(g[key]) for g in per_lens)
        groups[key] = [tuple(g[key][i] for g in per_lens) for i in range(n)]
    return {"keys": keys, "groups": groups, "counts": counts}
