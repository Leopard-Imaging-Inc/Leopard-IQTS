"""MTF 模组比较主入口：compare() 差异计算与胜负判定。

自 iqtest/analysis/mtf_compare.py 拆分出的「比较计算」部分。
依赖 _model 的模型与口径校验，不直接读写 CSV、不依赖 GUI。
"""

from __future__ import annotations

from leopardiq.mtf import unit_label, unit_scale, unit_to_cy_px

from ._model import (
    DEFAULT_SCORE_TIE,
    DEFAULT_TIE_FREQ,
    DEFAULT_TIE_SFR,
    DEFAULT_ZONE_WEIGHTS,
    ZONE_GROUP_CN,
    _PIXEL_TOL,
    available_metrics,
    check_compatibility,
    match_rois,
    metric_kind,
    zone_group,
)


# ----------------------------------------------------------------------
# 比较主入口（两款 A/B）
# ----------------------------------------------------------------------
def compare(
    a: dict,
    b: dict,
    metric_keys: list[str] | None = None,
    main_metric: str | None = None,
    tie_freq: float = DEFAULT_TIE_FREQ,
    tie_sfr: float = DEFAULT_TIE_SFR,
    zone_weights: dict | None = None,
    score_tie: float = DEFAULT_SCORE_TIE,
) -> dict:
    """比较两份 MTF 结果（parse_result_csv 的返回），输出差异与优劣结论。

    Args:
        a / b: 两份解析后的 MTF 结果（A / B 模组）
        metric_keys: 要比较的测试项（默认全部共同项；必须是交集子集）
        main_metric: 主判定项（默认 metric_keys 第一个），决定总体结论
        tie_freq / tie_sfr: 频率类 / SFR 类打平阈值（cy/px 与 0~1 口径）
        zone_weights: 评分分区权重（center/edge/corner，默认 0.4/0.3/0.3）
        score_tie: 评分打平阈值（归一化评分差）

    Returns:
        比较结果 dict（pairs / only_a / only_b / stats / main_verdict /
        main_summary / display_unit / display_scale / cross_pixel）
    """
    check_compatibility(a, b)
    avail = {m["key"]: m for m in available_metrics(a, b)}
    if metric_keys is None:
        metric_keys = list(avail)
    else:
        unknown = [k for k in metric_keys if k not in avail]
        if unknown:
            raise ValueError(
                f"所选测试项不在两份 CSV 的共同项中：{unknown}"
            )
    if not metric_keys:
        raise ValueError("至少选择一个比较测试项")
    if main_metric is None:
        main_metric = metric_keys[0]
    if main_metric not in metric_keys:
        raise ValueError(f"主判定项 {main_metric!r} 不在所选测试项中")
    weights = dict(zone_weights or DEFAULT_ZONE_WEIGHTS)

    ma, mb = a["meta"], b["meta"]
    label_a, label_b = ma.get("label") or "A", mb.get("label") or "B"

    # 跨像元处理（§3.4）：像元尺寸不同 → 频率类展示统一换算 LP/mm
    pa, pb = ma["pixel_size_um"], mb["pixel_size_um"]
    differ = abs(pa - pb) > _PIXEL_TOL
    if differ and not (pa > 0 and pb > 0):
        raise ValueError(
            "两模组像元尺寸不同且至少一侧未填写有效 pixel_size_um，"
            "无法统一口径比较（请在 MTF 参数中填写像元尺寸后重新导出）"
        )
    cross_pixel = differ
    if cross_pixel:
        display_unit = "LP/mm"
        display_scale = 1000.0 / pa  # cy/px → LP/mm（按 A 侧像元）
    else:
        display_unit = unit_label(ma["freq_unit"])
        display_scale = unit_scale(
            ma["freq_unit"], pa or None, ma["picture_height"] or None
        )

    def _norm(row: dict, meta: dict, key: str):
        """指标值归一化到比较口径（频率类 → cy/px）。"""
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

    matched = match_rois(a["rows"], b["rows"])
    if not matched["pairs"]:
        raise ValueError("没有可按视场位置配对的 ROI，无法比较")

    pairs = []
    for row_a, row_b, zone in matched["pairs"]:
        values_a = {k: _norm(row_a, ma, k) for k in metric_keys}
        values_b = {k: _norm(row_b, mb, k) for k in metric_keys}
        delta = {
            k: (values_a[k] - values_b[k])
            if values_a[k] is not None and values_b[k] is not None else None
            for k in metric_keys
        }
        pairs.append({
            "zone": zone,
            "zone_group": zone_group(zone),
            "channel": row_a["channel"],
            "roi_a": row_a["roi"], "roi_b": row_b["roi"],
            "values_a": values_a, "values_b": values_b, "delta": delta,
        })

    # ---- 逐测试项统计：胜负计数 + 分区加权评分
    stats: dict[str, dict] = {}
    for key in metric_keys:
        kind = avail[key]["kind"]
        tie = tie_freq if kind == "freq" else tie_sfr
        norm_scale = 0.5 if kind == "freq" else 1.0  # 归一化：频率类 ÷ Nyquist

        win = tie_n = loss = excluded = 0
        # 分区均值：{zone_group: ([A 值...], [B 值...])}
        zone_vals: dict[str, tuple[list, list]] = {}
        for pair in pairs:
            va, vb = pair["values_a"][key], pair["values_b"][key]
            if va is None or vb is None:
                excluded += 1
                continue
            diff = va - vb
            if abs(diff) <= tie:
                tie_n += 1
            elif diff > 0:
                win += 1
            else:
                loss += 1
            entry = zone_vals.setdefault(pair["zone_group"], ([], []))
            entry[0].append(va / norm_scale)
            entry[1].append(vb / norm_scale)

        # 分区加权评分（无配对的分区剔除后权重归一化）
        present = [g for g in ("center", "edge", "corner") if g in zone_vals]
        wsum = sum(weights.get(g, 0.0) for g in present) or 1.0
        zone_mean = {
            g: (sum(v[0]) / len(v[0]), sum(v[1]) / len(v[1]))
            for g, v in zone_vals.items()
        }
        score_a = sum(weights.get(g, 0.0) / wsum * zone_mean[g][0]
                      for g in present)
        score_b = sum(weights.get(g, 0.0) / wsum * zone_mean[g][1]
                      for g in present)

        score_diff = score_a - score_b
        if abs(score_diff) <= score_tie:
            verdict = "TIE"
        else:
            verdict = "A" if score_diff > 0 else "B"
        zone_delta = {g: zone_mean[g][0] - zone_mean[g][1] for g in present}
        dominant = max(present, key=lambda g: abs(zone_delta[g])) if present else ""

        disp = display_scale if kind == "freq" else 1.0
        wl = f"胜 {win} / 平 {tie_n} / 负 {loss}"
        if verdict == "TIE":
            summary = f"两者相当（{wl}）"
        else:
            winner = label_a if verdict == "A" else label_b
            dz = zone_delta.get(dominant, 0.0) * norm_scale * disp
            summary = (
                f"{winner} 更好（{wl}），优势主要在"
                f"{ZONE_GROUP_CN.get(dominant, dominant)}"
                f"（Δ = {abs(dz):.4g} {display_unit if kind == 'freq' else ''}）"
            ).replace("  ", " ").strip()

        stats[key] = {
            "label": avail[key]["label"], "kind": kind,
            "win": win, "tie": tie_n, "loss": loss, "excluded": excluded,
            "score_a": score_a, "score_b": score_b,
            "zone_delta": zone_delta, "dominant_zone": dominant,
            "verdict": verdict, "summary": summary,
        }

    return {
        "labels": {"a": label_a, "b": label_b},
        "cross_pixel": cross_pixel,
        "display_unit": display_unit,
        "display_scale": display_scale,
        "metrics": [avail[k] for k in metric_keys],
        "main_metric": main_metric,
        "main_verdict": stats[main_metric]["verdict"],
        "main_summary": stats[main_metric]["summary"],
        "pairs": pairs,
        "only_a": matched["only_a"],
        "only_b": matched["only_b"],
        "stats": stats,
        # 比较配置回显（结果 CSV 导出与复现用）
        "config_echo": {
            "tie_freq": tie_freq, "tie_sfr": tie_sfr,
            "score_tie": score_tie, "zone_weights": weights,
        },
    }
