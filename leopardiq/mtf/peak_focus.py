"""
最佳对焦位置（Peak Focus）验证。

提取自 LeopardIQ0529/leopardiq/sfr/peak_focus_sfr_main.py。

从多个不同拍摄距离的图像中计算中心方格 SFR，
SFR 最大值对应的距离即峰值对焦位置，与期望位置 ± tolerance 比较判定。

改进：
- 原函数直接 print 且不返回结构化结果，提取后返回标准结果字典
- 绘图改为可选（save_image_path 为 None 时跳过），使用 Agg 后端不弹窗
"""

import os
import warnings
from typing import Optional, Union

import numpy as np

from leopardiq.utils.image_io import read_mtf_image
from leopardiq.utils.image_preprocess import get_bayer_index, split_bayer_channels

from .centroid import find_peak_focus_centroid, sort_sfr_peak, draw_sfr_peak
from .mtf_calculator import compute_mtf_array, interpolation_nyquist


def analyze_peak_focus(
    image_dir: str,
    config_sensor: dict,
    config_data: dict,
    save_csv_path: Optional[str] = None,
    save_image_path: Optional[str] = None,
) -> dict:
    """
    峰值对焦位置分析。

    Args:
        image_dir: 不同拍摄距离的 RAW 图像目录。
                   文件名需包含 "_Di<distance>_" 或 "_Di<distance>." 字段（单位 cm）
        config_sensor: sensor 配置，需含 "peak_focus" 节：
            params: test_distances, min_patch_size, sub_patch_angles, freqs, nyq_freq
            criteria: position, tolerance
        config_data: 图像配置（cfa / width / height / black_level）
        save_csv_path: 可选，CSV 结果保存路径
        save_image_path: 可选，SFR-距离曲线图保存路径

    Returns:
        {
            "metrics": {"peak_focus_position": {"value": ..., "status": ...}},
            "pass": bool,
            "details": {
                "distance_list": [...],
                "sfr_results": [...],
                "peak_distance": int,
                "peak_sfr": float,
            },
        }
    """
    params = config_sensor["peak_focus"]["params"]
    criteria = config_sensor["peak_focus"]["criteria"]
    test_distances = params["test_distances"]
    min_patch_size = params["min_patch_size"]
    patch_angles = params["sub_patch_angles"]
    frequency = params["freqs"]
    nyquist_frequency = params["nyq_freq"]
    peak_focus_position = criteria["position"]
    tolerance = criteria["tolerance"]
    cfa = config_data["cfa"]

    image_name_list = sorted(os.listdir(image_dir))
    if len(image_name_list) < len(test_distances):
        return {
            "metrics": {
                "peak_focus_position": {"value": None, "status": "FAIL"}
            },
            "pass": False,
            "details": {
                "error": "insufficient images",
                "expected": len(test_distances),
                "found": len(image_name_list),
            },
        }

    distance_results = []
    distance_list = []
    for image_name in image_name_list:
        image_path = os.path.join(image_dir, image_name)
        if not os.path.isfile(image_path):
            continue
        image = read_mtf_image(image_path, config_data, channels=1)

        if len(cfa) == 4:
            image = split_bayer_channels(np.squeeze(image))
            gr_index, _, _, _ = get_bayer_index(cfa)

        if image.ndim == 3:
            image_height, image_width, image_channel = image.shape
        else:
            image_height, image_width = image.shape
            image_channel = 1

        distance = int(image_name.split("_Di")[-1].split(".")[0].split("_")[0])
        distance_list.append(distance)
        if distance not in test_distances:
            raise ValueError(f"{distance} is not in test_distances {test_distances}")

        if len(cfa) == 1:
            image_temp = np.copy(image)
        else:
            image_temp = np.copy(image[:, :, gr_index])

        centroid, stats = find_peak_focus_centroid(image_temp)
        patch_distance_pixel = round(np.mean([stats[2], stats[3]]) / 2)
        patch_size_pixel = round(np.mean([stats[2], stats[3]]) * 0.25)
        if patch_size_pixel < min_patch_size:
            warnings.warn("ERROR: ROI size too small, this can lead to high error")

        patch_axisx = (
            patch_distance_pixel * np.cos(np.deg2rad(patch_angles)) + centroid[0]
        )
        patch_axisy = centroid[1] - patch_distance_pixel * np.sin(
            np.deg2rad(patch_angles)
        )
        left = np.round(patch_axisx - patch_size_pixel)
        right = np.round(patch_axisx + patch_size_pixel)
        top = np.round(patch_axisy + patch_size_pixel)
        bottom = np.round(patch_axisy - patch_size_pixel)

        square_results = []
        for patch_index in range(len(patch_angles)):
            # top/bottom 为 y（行）坐标、left/right 为 x（列）坐标；
            # 后续作为切片端点使用：起点下限钳到 0，终点上限钳到图像尺寸。
            bottom[patch_index] = max(bottom[patch_index], 0)
            top[patch_index] = min(top[patch_index], image_height)
            left[patch_index] = max(left[patch_index], 0)
            right[patch_index] = min(right[patch_index], image_width)
            for channel in range(image_channel):
                if image.ndim == 3:
                    sfr_patch = image[
                        int(bottom[patch_index]): int(top[patch_index]),
                        int(left[patch_index]): int(right[patch_index]),
                        channel,
                    ]
                else:
                    sfr_patch = image[
                        int(bottom[patch_index]): int(top[patch_index]),
                        int(left[patch_index]): int(right[patch_index]),
                    ]
                sfr_patch = np.squeeze(sfr_patch).astype(np.float64)
                mtf_array = compute_mtf_array(sfr_patch)
                if mtf_array is None:
                    # 无效 ROI（预检拦截或引擎失败）：跳过该 patch，
                    # 不让 None 进入插值导致整个分析崩溃
                    warnings.warn(
                        f"peak_focus: MTF 计算失败，跳过 "
                        f"patch={patch_index} channel={channel}（{image_name}）"
                    )
                    continue
                sfr50 = interpolation_nyquist(
                    mtf_array, frequency * nyquist_frequency
                )
                if not np.all(np.isfinite(sfr50)):
                    # 插值结果 NaN（目标频率超出曲线范围等）：跳过该 patch，
                    # 不让 NaN 污染均值
                    warnings.warn(
                        f"peak_focus: SFR 插值结果无效，跳过 "
                        f"patch={patch_index} channel={channel}（{image_name}）"
                    )
                    continue
                square_results.append(sfr50)

        if square_results:
            distance_results.append(float(np.mean(square_results)))
        else:
            warnings.warn(
                f"peak_focus: {image_name} 全部 patch 无效，该距离 SFR 记 NaN"
            )
            distance_results.append(np.nan)

    if all(np.isnan(distance_results)):
        raise RuntimeError(
            "peak_focus: 所有距离的 ROI 均无效，无法确定峰值对焦位置"
        )
    # NaN 距离视为无效：nanargmax 自动忽略（全部 NaN 已在上面拦截）
    max_mtf_index = int(np.nanargmax(distance_results))
    distance_max = distance_list[max_mtf_index]
    sfr_max = float(distance_results[max_mtf_index])

    if (distance_max < peak_focus_position - tolerance) or (
        distance_max > peak_focus_position + tolerance
    ):
        status = "FAIL"
    else:
        status = "PASS"
    if status == "FAIL" and 70 in distance_list:
        # 原库特判：70cm 处 SFR 不低于峰值 95% 时仍判 PASS
        sfr_distance70 = distance_results[distance_list.index(70)]
        if sfr_distance70 > sfr_max * 0.95:
            status = "PASS"

    if save_csv_path is not None:
        from leopardiq.utils.result_saver import save_results_csv

        save_results_csv(
            save_csv_path, ["peak_focus_position"], [distance_max], [status], cfa
        )

    if save_image_path is not None:
        show_distance, show_sfr = sort_sfr_peak(distance_list, distance_results)
        draw_sfr_peak(show_distance, show_sfr, distance_max, sfr_max, save_image_path)

    return {
        "metrics": {
            "peak_focus_position": {"value": distance_max, "status": status}
        },
        "pass": status == "PASS",
        "details": {
            "distance_list": distance_list,
            "sfr_results": [float(v) for v in distance_results],
            "peak_distance": distance_max,
            "peak_sfr": sfr_max,
        },
    }
