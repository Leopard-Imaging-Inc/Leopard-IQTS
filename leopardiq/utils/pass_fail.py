"""
PASS/FAIL criteria evaluation utilities.

Extracted from LeopardIQ0529/leopardiq/utils/val_status.py and refactored:
- 抽象出通用判定器 evaluate_pass_fail()，支持多种比较模式
- 保留与原 val_status() / val_status_dict() 语义一致的兼容接口

判定规则（与原实现一致）：
- 普通指标: max(abs(value)) <= criteria  → PASS，否则 FAIL
- 相对照度指标 (key 含 "ri" 且不含 "diff"): 数值需 >= criteria（下限判定）
- 光心偏移指标 (key 含 "oc"): 允许 ±criteria 范围内波动

Original: val_status.py (leopard, 2021-4-23 yunlong)
"""

from typing import Any, Dict, List, Sequence, Tuple

import numpy as np


def evaluate_pass_fail(
    value: Any,
    criterion: Any,
    mode: str = "upper",
) -> str:
    """
    通用单指标判定器（新增接口）。

    Args:
        value: 测量值，标量或数组
        criterion: 阈值，标量或与 value 等长的列表
        mode: 判定模式
            - "upper": max(abs(value)) <= criterion → PASS（默认，上限判定）
            - "lower": value >= criterion → PASS（下限判定，如相对照度）
            - "range": -criterion <= value <= criterion → PASS（对称区间判定）

    Returns:
        "PASS" 或 "FAIL"
    """
    if mode not in ("upper", "lower", "range"):
        raise ValueError(f"Unknown comparison mode: {mode}")

    arr = np.atleast_1d(np.asarray(value, dtype=float))

    if mode == "upper":
        return "PASS" if np.max(np.abs(arr)) <= criterion else "FAIL"

    if mode == "lower":
        if isinstance(criterion, (list, tuple, np.ndarray)):
            for v, c in zip(arr, criterion):
                if v < c:
                    return "FAIL"
            return "PASS"
        return "PASS" if np.min(arr) >= criterion else "FAIL"

    # mode == "range"
    if np.max(np.abs(arr)) > criterion:
        return "FAIL"
    return "PASS"


def _infer_mode(key: str) -> str:
    """按原 val_status 的 key 命名规则推断判定模式。"""
    if "ri" in key and "diff" not in key:
        return "lower"
    if "oc" in key:
        return "range"
    return "upper"


def validate_metrics(
    criteria: Dict[str, Any],
    values: Dict[str, Any],
) -> Tuple[str, List[str], List[str]]:
    """
    按配置阈值逐项判定（兼容原 val_status_dict 的语义）。

    Args:
        criteria: {metric_key: threshold}，如 {"dp_cold": 10, "ri_tl": [0.8, 0.8]}
        values: {metric_key: measured_value}

    Returns:
        (overall_status, metric_keys, statuses)
        overall_status 为 "PASS"/"FAIL"（任一项 FAIL 则整体 FAIL）
    """
    overall_status = "PASS"
    metric_keys: List[str] = []
    statuses: List[str] = []

    for key, criterion in criteria.items():
        metric_keys.append(key)
        status = evaluate_pass_fail(values[key], criterion, _infer_mode(key))
        if status == "FAIL":
            overall_status = "FAIL"
        statuses.append(status)

    return overall_status, metric_keys, statuses


def validate_metrics_ordered(
    criteria: Dict[str, Any],
    values: Sequence[Any],
) -> Tuple[str, List[str], List[str]]:
    """
    按顺序对齐的判定接口（兼容原 val_status 的语义）。

    criteria 的 key 顺序与 values 顺序一一对应。

    Args:
        criteria: {metric_key: threshold}
        values: 与 criteria 的 key 顺序对齐的测量值列表

    Returns:
        (overall_status, metric_keys, statuses)
    """
    if len(values) != len(criteria):
        raise ValueError(
            f"values count ({len(values)}) does not match criteria count ({len(criteria)})"
        )

    overall_status = "PASS"
    metric_keys: List[str] = []
    statuses: List[str] = []

    for (key, criterion), value in zip(criteria.items(), values):
        metric_keys.append(key)
        status = evaluate_pass_fail(value, criterion, _infer_mode(key))
        if status == "FAIL":
            overall_status = "FAIL"
        statuses.append(status)

    return overall_status, metric_keys, statuses
