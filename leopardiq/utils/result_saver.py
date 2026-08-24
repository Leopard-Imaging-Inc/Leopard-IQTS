"""
Test result persistence utilities.

Extracted from LeopardIQ0529/leopardiq/utils/save_result.py and extended:
- CSV 保存（与原 save_result 行为一致，但不再原地修改调用方传入的列表）
- 新增 JSON 输出，便于后续报告系统/前端消费

Original: save_result.py (leopard, 2021)
"""

import csv
import json
from pathlib import Path
from typing import Any, Sequence, Union

import numpy as np


def _to_serializable(value: Any) -> Any:
    """Convert numpy scalars/arrays to plain Python types for JSON output."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    return value


def pad_channel_data(
    val_data_list: list, cfa_len: int
) -> list:
    """
    处理数据维度不一致的数据：多通道保存时，单通道数据（如 SFR falloff）
    用 0 填充至 cfa_len，保持整体数据结构一致。

    对应原 save_result.py 中的 deal_val_data()。

    Args:
        val_data_list: 各测试项数据列表，元素为标量或 np.ndarray
        cfa_len: CFA 通道数（1 或 4）

    Returns:
        新的填充后的列表（不修改输入）
    """
    padded = []
    for val_data in val_data_list:
        if isinstance(val_data, np.ndarray) and val_data.ndim == 2:
            val_data = np.squeeze(val_data)
        arr = np.atleast_1d(val_data)
        if arr.size != cfa_len:
            padded.append(np.concatenate([arr, np.zeros(cfa_len - arr.size)]))
        else:
            padded.append(arr)
    return padded


def save_results_csv(
    save_path: Union[str, Path],
    metric_keys: Sequence[str],
    metric_values: Sequence[Any],
    statuses: Sequence[str],
    cfa: Union[str, Sequence[str]],
) -> Path:
    """
    将测试结果保存为 CSV 文件。

    对应原 save_result()，改进点：
    - 不再原地修改传入的列表（原函数会 insert 导致调用方数据被污染）
    - cfa 支持字符串（如 "RGGB"）或列表（如 ["R","Gr","Gb","B"]）

    Args:
        save_path: 输出 CSV 路径
        metric_keys: 测试项名称列表，如 ['blemish_count', 'particle_count']
        metric_values: 各测试项数据，元素为标量或数组
        statuses: 各测试项判定结果，如 ['PASS', 'FAIL']
        cfa: CFA 配置，用于判断单通道还是四通道

    Returns:
        实际写入的文件路径
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    keys = ["Row", *metric_keys]
    status_row = ["status", *statuses]

    # cfa 支持字符串（如 "RGGB" → ["R","G","G","B"]）或列表（如 ["R","Gr","Gb","B"]）
    cfa_channels = list(cfa)
    cfa_len = len(cfa_channels)

    if cfa_len == 1:
        rows = [keys, ["C", *metric_values], status_row]
    elif cfa_len == 4:
        values = pad_channel_data(list(metric_values), cfa_len)
        values.insert(0, np.array(cfa_channels))
        transposed = np.array(values, dtype=object).transpose().tolist()
        rows = [keys, *transposed, status_row]
    else:
        raise ValueError(f"Unsupported CFA channel count: {cfa_len}")

    with open(save_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerows(rows)

    return save_path


def save_results_json(
    save_path: Union[str, Path],
    metric_keys: Sequence[str],
    metric_values: Sequence[Any],
    statuses: Sequence[str],
    overall_status: str = None,
    extra: dict = None,
) -> Path:
    """
    将测试结果保存为 JSON 文件（新增接口，原算法库无此功能）。

    输出结构：
    {
        "overall_status": "PASS",
        "metrics": {"blemish_count": {"value": ..., "status": "PASS"}, ...},
        "extra": {...}            # 可选附加信息
    }

    Args:
        save_path: 输出 JSON 路径
        metric_keys: 测试项名称列表
        metric_values: 各测试项数据
        statuses: 各测试项判定结果
        overall_status: 总体判定结果，None 时自动由 statuses 推导
        extra: 可选附加信息（如测试时间、固件版本等）

    Returns:
        实际写入的文件路径
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    if overall_status is None:
        overall_status = "FAIL" if "FAIL" in statuses else "PASS"

    metrics = {}
    for key, value, status in zip(metric_keys, metric_values, statuses):
        metrics[key] = {
            "value": _to_serializable(value),
            "status": status,
        }

    payload = {
        "overall_status": overall_status,
        "metrics": metrics,
    }
    if extra:
        payload["extra"] = {k: _to_serializable(v) for k, v in extra.items()}

    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return save_path
