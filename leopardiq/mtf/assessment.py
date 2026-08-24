"""
SFR 结果评估：各方格/频率点的 PASS/FAIL 判定与 Lens Tilt / SFR Falloff 计算。

提取自 LeopardIQ0529/leopardiq/utils/sfr_cross_utils.py：
- assess_patch_result_cfa()  → assess_patch_results()
- assess_tilt_falloff_cfa()  → assess_tilt_falloff()
- evaluation_mtf()           → evaluate_mtf_values()
- compare_lower_indicator()  → is_below_criteria()
- compare_bigger_indicator() → is_above_criteria()

指标定义（与原库一致）：
- Lens Tilt = max(corner SFR) - min(corner SFR)
- SFR Falloff = center SFR - mean(corner SFR)

提取后将原"传入多个 list 原地追加"的风格改为返回结构化结果，
中心/四角主频数据通过返回值的 "center_data" / "outer_data" 累计。
"""

from typing import Any, Dict, List, Tuple

import numpy as np


def is_below_criteria(data: Any, criterion: Any) -> bool:
    """
    任一值低于阈值返回 True（判定失败）。

    criterion 支持标量或与 data 等长的序列；统一用 numpy 广播比较，
    始终返回 Python bool（原实现对标量 criterion 会返回 bool 数组，
    且对 list data 只比较首元素）。
    """
    return bool(np.any(np.asarray(data, dtype=float) < criterion))


def is_above_criteria(data: Any, criterion: Any) -> bool:
    """任一值高于阈值返回 True（判定失败）。语义同 is_below_criteria。"""
    return bool(np.any(np.asarray(data, dtype=float) > criterion))


def evaluate_mtf_values(
    mtf_values: np.ndarray, min_data: Any, max_data: Any
) -> Tuple[np.ndarray, str]:
    """
    将单频率点各通道 SFR 与 [min, max] 阈值比较（原 evaluation_mtf）。

    Returns:
        (values, status)：values 为 squeeze 后的数组，status ∈ {"PASS", "FAIL"}
    """
    if (
        np.isnan(mtf_values).any()
        or is_below_criteria(mtf_values, min_data)
        or is_above_criteria(mtf_values, max_data)
    ):
        status = "FAIL"
    else:
        status = "PASS"
    return np.squeeze(mtf_values), status


def assess_patch_results(
    square_results: np.ndarray,
    square_index: int,
    square_names: List[str],
    square_distances: np.ndarray,
    center_index: np.ndarray,
    outer_index: np.ndarray,
    frequency: np.ndarray,
    main_frequency: float,
    gr_index: int,
    gb_index: int,
    config_sensor: dict,
    config_key_sfr: str,
) -> Dict[str, Any]:
    """
    评估单个方格各频率点的 SFR（原 assess_patch_result_cfa）。

    对方格内所有 ROI 按 patch 维度做 nanmean，逐频率点与 criteria 比较；
    主频率点的 Gr/Gb 均值会记入 center_data / outer_data，供 tilt/falloff 使用。

    Args:
        square_results: (num_patches, image_channel, num_freq) SFR 结果
        square_index: 当前方格下标
        square_names / square_distances: 方格名称与视场距离（ratio of DFOV）
        center_index / outer_index: 中心/最外方格布尔掩膜
        frequency: 采样频率数组
        main_frequency: 主评估频率
        gr_index / gb_index: Bayer Gr/Gb 通道下标（mono 时为 0）
        config_sensor: sensor 配置
        config_key_sfr: SFR 配置节名（"sfrnv" 或 "sfrcross"）

    Returns:
        {
            "metric_keys": [...],     # 如 "c_05nyq"
            "metric_values": [...],   # 各频率点 4 通道 SFR
            "statuses": [...],        # "PASS"/"FAIL"
            "center_data": [...],     # 中心方格主频 Gr/Gb 均值（0 或 1 个元素）
            "outer_data": [...],      # 最外方格主频 Gr/Gb 均值（0 或 1 个元素）
        }
    """
    mtf_result = np.nanmean(square_results, axis=0)

    frequency_config = config_sensor[config_key_sfr]["params"]["freqs"]
    frequency_output = [
        str(freq).replace(".", "") + "nyq" for freq in frequency_config
    ]

    metric_keys, metric_values, statuses = [], [], []
    center_data, outer_data = [], []

    for frequency_index in range(len(frequency)):
        test_name = square_names[square_index] + "_" + frequency_output[frequency_index]

        if square_distances[square_index] == 0:
            criteria = config_sensor[config_key_sfr]["criteria"]["0"][
                str(frequency_config[frequency_index])
            ]
        else:
            criteria = config_sensor[config_key_sfr]["criteria"][
                str(square_distances[square_index])
            ][str(frequency_config[frequency_index])]

        values, status = evaluate_mtf_values(
            mtf_result[:, frequency_index], criteria["min"], criteria["max"]
        )
        metric_keys.append(test_name)
        metric_values.append(values)
        statuses.append(status)

        is_main_freq = frequency[frequency_index] == main_frequency
        if center_index[square_index] == 1 and is_main_freq:
            center_data.append(
                np.nanmean(
                    [
                        mtf_result[gr_index, frequency_index],
                        mtf_result[gb_index, frequency_index],
                    ]
                )
            )
        elif outer_index[square_index] == 1 and is_main_freq:
            outer_data.append(
                np.nanmean(
                    [
                        mtf_result[gr_index, frequency_index],
                        mtf_result[gb_index, frequency_index],
                    ]
                )
            )

    return {
        "metric_keys": metric_keys,
        "metric_values": metric_values,
        "statuses": statuses,
        "center_data": center_data,
        "outer_data": outer_data,
    }


def assess_tilt_falloff(
    center_data: List[float],
    outer_data: List[float],
    config_sensor: dict,
    config_key_sfr: str,
) -> Dict[str, Any]:
    """
    计算并评估 Lens Tilt 与 SFR Falloff（原 assess_tilt_falloff_cfa）。

    - tilt = max(outer) - min(outer)
    - falloff = mean(center) - mean(outer)

    Returns:
        {
            "metric_keys": ["tilt", "falloff"],
            "metric_values": [tilt, falloff],
            "statuses": [...],
            "tilt": float,
            "falloff": float,
        }
    """
    criteria = config_sensor[config_key_sfr]["criteria"]

    tilt = float(np.max(outer_data) - np.min(outer_data))
    tilt_status = "FAIL" if tilt > criteria["tilt"] else "PASS"

    falloff = float(np.mean(center_data) - np.mean(outer_data))
    falloff_status = "FAIL" if falloff > criteria["falloff"] else "PASS"

    return {
        "metric_keys": ["tilt", "falloff"],
        "metric_values": [tilt, falloff],
        "statuses": [tilt_status, falloff_status],
        "tilt": tilt,
        "falloff": falloff,
    }
