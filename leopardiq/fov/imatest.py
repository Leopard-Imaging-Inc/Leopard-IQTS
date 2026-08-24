"""
Imatest FOV 数据解析（辅助工具）。

提取自 LeopardIQ0529/leopardiq/fov/getfov_data.py（原为脚本，重构为函数）。

用于从外部 Imatest 导出的 checkerboard JSON 结果中读取 FOV 与光心偏移，
并与 EOL 判定标准比较。非核心功能，供需要兼容 Imatest 流程时使用。
"""

import json
from typing import Optional, Union

import numpy as np


def parse_imatest_fov(json_path: str) -> dict:
    """
    解析 Imatest checkerboard 结果 JSON。

    Args:
        json_path: Imatest 导出的 JSON 文件路径

    Returns:
        {
            "dfov": float, "hfov": float, "vfov": float,   # 度
            "x_decenter": float, "y_decenter": float,      # 畸变中心偏移
            "oc_shift": float,                             # 光心偏移量
        }
    """
    with open(json_path, "r") as stream:
        fov_data = json.load(stream)
    results = fov_data["checkerboardResults"]
    dfov, hfov, vfov = results["FieldofView_DiagHV_degrees"]
    x_shift = results["x_distortion_decenter"][0]
    y_shift = results["y_distortion_decenter"][0]
    return {
        "dfov": float(dfov),
        "hfov": float(hfov),
        "vfov": float(vfov),
        "x_decenter": float(x_shift),
        "y_decenter": float(y_shift),
        "oc_shift": float(np.sqrt(x_shift * x_shift + y_shift * y_shift)),
    }


def evaluate_imatest_fov(
    json_path: str,
    hfov_criteria: tuple,
    vfov_criteria: tuple,
    dfov_criteria: tuple,
    angular_res: float,
    oc_shift_criteria: float,
) -> dict:
    """
    解析 Imatest JSON 并与 EOL 判定标准比较（原 getfov_data.py 流程）。

    Args:
        json_path: Imatest JSON 路径
        hfov_criteria / vfov_criteria / dfov_criteria: (min, max) 度
        angular_res: 每度对应的像素数（光心偏移 px → 度的换算）
        oc_shift_criteria: 光心偏移角度上限（度）

    Returns:
        {"metrics": {...}, "pass": bool, "details": {...}}
    """
    data = parse_imatest_fov(json_path)
    ang_oc_shift = data["oc_shift"] / angular_res

    metrics = {}
    for key in ("dfov", "hfov", "vfov"):
        criteria = {
            "dfov": dfov_criteria,
            "hfov": hfov_criteria,
            "vfov": vfov_criteria,
        }[key]
        status = "PASS" if criteria[0] <= data[key] <= criteria[1] else "FAIL"
        metrics[key] = {"value": data[key], "status": status, "unit": "deg"}
    metrics["ang_oc_shift"] = {
        "value": ang_oc_shift,
        "status": "PASS" if ang_oc_shift <= oc_shift_criteria else "FAIL",
        "unit": "deg",
    }

    return {
        "metrics": metrics,
        "pass": all(m["status"] == "PASS" for m in metrics.values()),
        "details": data,
    }
