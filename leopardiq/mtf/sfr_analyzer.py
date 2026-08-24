"""
统一 SFR 分析接口。

整合 LeopardIQ0529 中三个独立 SFR 入口：
- sfr/sfr_main.py    → chart_type="multi_square", roi_method="edge_trace"（hawk 风格）
- sfr/sfr_ov2311.py  → chart_type="multi_square", roi_method="geometry"（ov2311 风格）
- sfr/sfr_cross.py   → chart_type="cross"（十字标板模板匹配）

统一输出结构（与软件规划 2.2 节接口一致）：
{
    "metrics": {key: {"value": ..., "status": ...}},
    "pass": bool,
    "details": {...},          # centroids / tilt / falloff / per-square 数据
    "visualization": {...},    # ROI 框、质心等可视化数据（debug=True 时）
}
"""

import warnings
from typing import Optional, Sequence, Union

import numpy as np

from leopardiq.utils.image_io import read_mtf_image
from leopardiq.utils.image_preprocess import get_bayer_index, split_bayer_channels
from leopardiq.utils.common import filter_centroid, round_half_up

from .assessment import assess_patch_results, assess_tilt_falloff
from .centroid import find_square_centroids_bayer, find_square_centroids_mono
from .cross_chart import detect_sfr_cross
from .mtf_calculator import compute_roi_sfr
from .square_chart import (
    compute_chart_geometry,
    compute_geometry_patch_rois,
    extract_edge_roi_sfr,
    find_one_edge_pos,
    init_square_chart_params,
    search_edge_centers_in_binary_image,
)


class SFRAnalyzer:
    """
    统一 SFR 分析器。

    Args:
        config_sensor: sensor 配置字典（含 sfrnv / sfrcross 节）
        config_data: 图像配置字典（cfa / width / height / black_level）
        chart_type: "multi_square"（多方格标板）或 "cross"（十字标板）
        roi_method: 仅 multi_square 有效：
            - "edge_trace"：二值图边缘追踪定位 ROI（原 sfr_main，hawk）
            - "geometry"：按标板几何参数定位 ROI（原 sfr_ov2311）
        template: chart_type="cross" 时的十字模板（.mat 路径或 ndarray）
        config_key_sfr: 配置节名（默认 "sfrnv"；cross 模式默认 "sfrcross"）
        gamma: 编码 Gamma，SFR 计算前按 pixel^(1/gamma) 线性化
            （Imatest「Input gamma value」；默认 1.0 = 不线性化，
            适用于线性 RAW 数据）
    """

    def __init__(
        self,
        config_sensor: dict,
        config_data: dict,
        chart_type: str = "multi_square",
        roi_method: str = "edge_trace",
        template: Union[str, np.ndarray, None] = None,
        config_key_sfr: Optional[str] = None,
        gamma: float = 1.0,
    ):
        if chart_type not in ("multi_square", "cross"):
            raise ValueError(f"Unknown chart_type: {chart_type}")
        if roi_method not in ("edge_trace", "geometry"):
            raise ValueError(f"Unknown roi_method: {roi_method}")
        if chart_type == "cross" and template is None:
            raise ValueError("chart_type='cross' requires a template")
        if float(gamma) <= 0.0:
            raise ValueError(f"gamma 必须为正数（当前 {gamma}）")

        self.config_sensor = config_sensor
        self.config_data = config_data
        self.chart_type = chart_type
        self.roi_method = roi_method
        self.template = template
        self.gamma = float(gamma)
        if config_key_sfr is None:
            config_key_sfr = "sfrcross" if chart_type == "cross" else "sfrnv"
        self.config_key_sfr = config_key_sfr

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------
    def analyze(
        self,
        image: Union[str, np.ndarray],
        debug: bool = False,
        save_csv_path: Optional[str] = None,
    ) -> dict:
        """
        运行 SFR 分析。

        Args:
            image: RAW 文件路径（str，按 config_data 读取并做黑电平校正）
                   或已加载的图像 ndarray（(H, W) / (H, W, 1) / Bayer 拆分后 (H/2, W/2, 4)）
            debug: 是否在返回的 "visualization" 中附带 ROI/质心数据
            save_csv_path: 可选，结果 CSV 保存路径

        Returns:
            {"metrics": {...}, "pass": bool, "details": {...}, "visualization": {...}}
        """
        image_average = self._prepare_image(image)

        if self.chart_type == "multi_square":
            result = self._analyze_multi_square(image_average, debug)
        else:
            result = self._analyze_cross(image_average, debug)

        if save_csv_path is not None:
            from leopardiq.utils.result_saver import save_results_csv

            save_results_csv(
                save_csv_path,
                result["details"]["metric_keys"],
                result["details"]["metric_values"],
                result["details"]["statuses"],
                self.config_data["cfa"],
            )
        return result

    # ------------------------------------------------------------------
    # image preparation
    # ------------------------------------------------------------------
    def _prepare_image(self, image: Union[str, np.ndarray]) -> np.ndarray:
        """读取图像并按 CFA 拆分通道，返回 (H, W, C) 的 float 图像。"""
        if isinstance(image, str):
            image_average = read_mtf_image(image, self.config_data, channels=1)
        else:
            image_average = np.asarray(image, dtype=np.float32)
            if image_average.ndim == 2:
                image_average = image_average[:, :, np.newaxis]

        cfa = self.config_data["cfa"]
        if len(cfa) == 4 and image_average.shape[-1] != 4:
            # RAW Bayer 图：先 squeeze 再拆 4 通道
            image_average = split_bayer_channels(np.squeeze(image_average))
        return image_average

    def _bayer_indices(self) -> tuple:
        cfa = self.config_data["cfa"]
        if len(cfa) == 4:
            gr_index, _, _, gb_index = get_bayer_index(cfa)
            return gr_index, gb_index
        return 0, 0

    @staticmethod
    def _build_result(
        metric_keys: Sequence[str],
        metric_values: Sequence,
        statuses: Sequence[str],
        details: dict,
        visualization: Optional[dict] = None,
    ) -> dict:
        metrics = {
            key: {"value": np.asarray(value).tolist(), "status": status}
            for key, value, status in zip(metric_keys, metric_values, statuses)
        }
        details = dict(details)
        details["metric_keys"] = list(metric_keys)
        details["metric_values"] = [
            np.asarray(v).tolist() for v in metric_values
        ]
        details["statuses"] = list(statuses)
        return {
            "metrics": metrics,
            "pass": "FAIL" not in statuses,
            "details": details,
            "visualization": visualization,
        }

    # ------------------------------------------------------------------
    # multi-square chart
    # ------------------------------------------------------------------
    def _analyze_multi_square(self, image_average: np.ndarray, debug: bool) -> dict:
        params = init_square_chart_params(self.config_sensor, self.config_key_sfr)
        gr_index, gb_index = self._bayer_indices()

        square_distances = params["square_distances"]
        center_index = square_distances == 0
        outer_index = square_distances == np.max(square_distances)

        geometry = compute_chart_geometry(
            image_average,
            params["patch_size"],
            params["square_angles"],
            square_distances,
            params["square_size"],
        )
        if np.min(geometry["patch_size_major"]) < params["min_patch_size"]:
            warnings.warn(
                "ERROR: ROI size too small, this can lead to high error",
                RuntimeWarning,
            )

        cfa_size = len(self.config_data["cfa"])
        if cfa_size == 4:
            image_temp = np.copy(image_average[:, :, gr_index])
            centroid_choose, stats, binary_image = find_square_centroids_bayer(
                image_temp, geometry["square_size_pixel"]
            )
        else:
            image_temp = np.copy(image_average)
            centroid_choose, stats, binary_image = find_square_centroids_mono(
                image_temp, geometry["square_size_pixel"]
            )
            # 边缘追踪要求"方格=0、背景=255"的二值图；
            # mono 检测输出为"方格=1、背景=0"，需反转并放大到 0/255
            # （原库 sfr_main 的 mono 路径存在此隐患）
            binary_image = np.where(binary_image == 0, 255, 0).astype(np.uint8)

        ideal_point = np.transpose(
            np.array([geometry["ideal_patch_axisx"], geometry["ideal_patch_axisy"]])
        )
        centroid, stats = filter_centroid(
            centroid_choose, geometry["chart_diag"], ideal_point, stats
        )
        if centroid.shape[0] != len(params["square_names"]):
            raise RuntimeError(
                f"Expected {len(params['square_names'])} chart squares, "
                f"detected {centroid.shape[0]}. Please recapture."
            )

        metric_keys, metric_values, statuses = [], [], []
        center_data, outer_data = [], []
        visualization = {"centroids": centroid.tolist(), "rois": []} if debug else None

        for index in range(len(params["square_names"])):
            square_results = np.zeros(
                (
                    len(params["patch_names"]),
                    geometry["image_channel"],
                    params["number_frequency"],
                )
            )
            distance = np.sqrt(
                (geometry["ideal_patch_axisx"][index] - centroid[:, 0]) ** 2
                + (geometry["ideal_patch_axisy"][index] - centroid[:, 1]) ** 2
            )
            index_minimum = int(np.argmin(distance))
            if distance[index_minimum] > geometry["chart_diag"] * 0.05:
                if params["square_names"][index] == "c":
                    warnings.warn(
                        "The MTF chart is not well centered in the frame. "
                        "Please recapture",
                        RuntimeWarning,
                    )
                else:
                    warnings.warn(
                        "The MTF chart is not well aligned and may be rotated. "
                        "Please recapture.",
                        RuntimeWarning,
                    )

            center = centroid[index_minimum, :]
            if self.roi_method == "edge_trace":
                roi_boxes = self._locate_rois_by_edge_trace(
                    image_average, binary_image, center, geometry, index,
                    square_results, params["frequency"],
                )
            else:
                roi_boxes = self._locate_rois_by_geometry(
                    image_average, center, geometry, params, index, square_results,
                )
            if debug:
                visualization["rois"].append(
                    {"square": params["square_names"][index], "boxes": roi_boxes}
                )

            patch_result = assess_patch_results(
                square_results,
                index,
                params["square_names"],
                square_distances,
                center_index,
                outer_index,
                params["frequency"],
                params["main_frequency"],
                gr_index,
                gb_index,
                self.config_sensor,
                self.config_key_sfr,
            )
            metric_keys.extend(patch_result["metric_keys"])
            metric_values.extend(patch_result["metric_values"])
            statuses.extend(patch_result["statuses"])
            center_data.extend(patch_result["center_data"])
            outer_data.extend(patch_result["outer_data"])

        tilt_falloff = assess_tilt_falloff(
            center_data, outer_data, self.config_sensor, self.config_key_sfr
        )
        metric_keys.extend(tilt_falloff["metric_keys"])
        metric_values.extend(tilt_falloff["metric_values"])
        statuses.extend(tilt_falloff["statuses"])

        details = {
            "tilt": tilt_falloff["tilt"],
            "falloff": tilt_falloff["falloff"],
            "chart_type": self.chart_type,
            "roi_method": self.roi_method,
        }
        return self._build_result(
            metric_keys, metric_values, statuses, details, visualization
        )

    def _locate_rois_by_edge_trace(
        self, image_average, binary_image, center, geometry, index,
        square_results, frequency,
    ) -> list:
        """原 sfr_main 的 ROI 定位：二值图边缘追踪四条边中点。"""
        center = (int(center[0]), int(center[1]))
        image_height, image_width = geometry["image_height"], geometry["image_width"]

        left = max(center[0] - 100, 0)
        right = min(center[0] + 100, image_width)
        top = max(center[1] - 100, 0)
        bottom = min(center[1] + 100, image_height)
        box_img = np.copy(binary_image)[top:bottom, left:right]

        direction, pos_y, pos_x = find_one_edge_pos(box_img, (100, 100))
        if direction == "NA":
            raise RuntimeError(
                f"Failed to locate chart square edge near {center}. Please recapture."
            )

        (
            ret, top_edge_center, right_edge_center, bottom_edge_center,
            left_edge_center, top_left, top_right, bottom_left, bottom_right,
        ) = search_edge_centers_in_binary_image(
            box_img, pos_x, pos_y, direction, (0, -1, 1, -2, 2)
        )

        top_edge = np.hypot(top_left[0] - top_right[0], top_left[1] - top_right[1])
        bottom_edge = np.hypot(
            bottom_left[0] - bottom_right[0], bottom_left[1] - bottom_right[1]
        )
        left_edge = np.hypot(top_left[0] - bottom_left[0], top_left[1] - bottom_left[1])
        right_edge = np.hypot(
            top_right[0] - bottom_right[0], top_right[1] - bottom_right[1]
        )
        if (
            abs((top_edge - bottom_edge) / top_edge) > 0.5
            or abs((left_edge - right_edge) / left_edge) > 0.5
        ):
            (
                ret, top_edge_center, right_edge_center, bottom_edge_center,
                left_edge_center, top_left, top_right, bottom_left, bottom_right,
            ) = search_edge_centers_in_binary_image(
                box_img, pos_x, pos_y, direction, (0, -1, 1)
            )

        offset_x, offset_y = center[0] - 100, center[1] - 100
        top_edge_center = (top_edge_center[0] + offset_x, top_edge_center[1] + offset_y)
        right_edge_center = (
            right_edge_center[0] + offset_x, right_edge_center[1] + offset_y
        )
        bottom_edge_center = (
            bottom_edge_center[0] + offset_x, bottom_edge_center[1] + offset_y
        )
        left_edge_center = (
            left_edge_center[0] + offset_x, left_edge_center[1] + offset_y
        )

        if top_edge_center[0] < image_width * 0.2 or top_edge_center[0] > image_width * 0.8:
            padding_width_tb, padding_height_tb = 15, 20
            padding_width_lr, padding_height_lr = 25, 25
        else:
            padding_width_tb, padding_height_tb = 25, 25
            padding_width_lr, padding_height_lr = 25, 25

        channel = geometry["image_channel"]
        extract_edge_roi_sfr(
            image_average, top_edge_center, padding_height_tb, padding_width_tb,
            0, square_results, frequency, channel, gamma=self.gamma,
        )
        extract_edge_roi_sfr(
            image_average, bottom_edge_center, padding_height_tb, padding_width_tb,
            1, square_results, frequency, channel, gamma=self.gamma,
        )
        extract_edge_roi_sfr(
            image_average, left_edge_center, padding_height_lr, padding_width_lr,
            3, square_results, frequency, channel, gamma=self.gamma,
        )
        extract_edge_roi_sfr(
            image_average, right_edge_center, padding_height_lr, padding_width_lr,
            2, square_results, frequency, channel, gamma=self.gamma,
        )
        return [
            {"edge": "t", "center": list(top_edge_center)},
            {"edge": "b", "center": list(bottom_edge_center)},
            {"edge": "l", "center": list(left_edge_center)},
            {"edge": "r", "center": list(right_edge_center)},
        ]

    def _locate_rois_by_geometry(
        self, image_average, center, geometry, params, index, square_results
    ) -> list:
        """原 sfr_ov2311 的 ROI 定位：按标板几何参数计算 ROI 框。"""
        boxes = compute_geometry_patch_rois(
            center,
            geometry["patch_dist_pixel"],
            params["patch_angles"],
            params["square_rotations"][index],
            geometry["patch_size_major"],
            geometry["patch_size_minor"],
        )
        for patch, (left, right, bottom, top) in enumerate(boxes):
            sfr_patch = image_average[bottom: top + 1, left: right + 1, :]
            compute_roi_sfr(
                sfr_patch,
                params["frequency"],
                geometry["image_channel"],
                patch,
                square_results,
                gamma=self.gamma,
            )
        return [
            {"patch": p, "box": [int(v) for v in box]}
            for p, box in enumerate(boxes)
        ]

    # ------------------------------------------------------------------
    # cross chart
    # ------------------------------------------------------------------
    def _analyze_cross(self, image_average: np.ndarray, debug: bool) -> dict:
        params = self.config_sensor[self.config_key_sfr]["params"]
        chart_distance = np.array(params["chart_dist"])
        chart_name = params["chart_name"]
        center_index = chart_distance == 0
        outer_index = chart_distance == np.max(chart_distance)
        frequency = params["freqs"] * params["nyq_freq"]
        chart_angle = params["chart_angle"]
        number_charts = params["num_charts"]
        roi_size = params["roi_size"]
        center_bias = params["center_bias"]
        if "main_freq" in params:
            main_frequency = params["main_freq"] * params["nyq_freq"]
        else:
            main_frequency = max(frequency)

        gr_index, gb_index = self._bayer_indices()

        image_height, image_width, image_channel = image_average.shape
        image_diag = np.sqrt(image_height ** 2 + image_width ** 2)
        center_axisx = image_width / 2 - 1
        center_axisy = image_height / 2 - 1
        ideal_patch_distance = 0.5 * image_diag * chart_distance
        ideal_axisx = np.floor(
            ideal_patch_distance * np.cos(np.deg2rad(chart_angle)) + center_axisx
        )
        ideal_axisy = np.floor(
            center_axisy - ideal_patch_distance * np.sin(np.deg2rad(chart_angle))
        )

        metric_keys, metric_values, statuses = [], [], []
        center_data, outer_data = [], []
        visualization = {"centers": [], "rois": []} if debug else None

        size_data = np.floor(image_diag * 0.1)
        for chart_index in range(number_charts):
            top = int(max(ideal_axisy[chart_index] - size_data, 1))
            bottom = int(min(ideal_axisy[chart_index] + size_data, image_height))
            left = int(max(ideal_axisx[chart_index] - size_data, 1))
            right = int(min(ideal_axisx[chart_index] + size_data, image_width))

            search_region = image_average[top - 1: bottom, left - 1: right, gr_index]
            center_point, rois = detect_sfr_cross(
                search_region, roi_size, center_bias, 1, self.template
            )
            center_point[0] = center_point[0] + left
            center_point[1] = center_point[1] + top
            rois[:, 0:2, :] = rois[:, 0:2, :] + top
            rois[:, 2:4, :] = rois[:, 2:4, :] + left

            distance = np.sqrt(
                (ideal_axisx[chart_index] - center_point[0]) ** 2
                + (ideal_axisy[chart_index] - center_point[1]) ** 2
            )
            if distance > image_diag * 0.05:
                if chart_distance[chart_index] == 0:
                    warnings.warn(
                        "The MTF chart is not well centered in the frame. "
                        "Please recapture."
                    )
                else:
                    warnings.warn(
                        "The MTF chart is not well aligned and may be rotated. "
                        "Please recapture."
                    )

            rois_height = rois.shape[0]
            chart_results = np.zeros((rois_height, image_channel, len(frequency)))
            roi_boxes = []
            for patch in range(rois_height):
                top = round_half_up(rois[patch, 0, 0])
                bottom = round_half_up(rois[patch, 1, 0])
                left = round_half_up(rois[patch, 2, 0])
                right = round_half_up(rois[patch, 3, 0])
                sfr_patch = image_average[top: bottom + 1, left: right + 1, :]
                compute_roi_sfr(
                    sfr_patch, frequency, image_channel, patch, chart_results,
                    gamma=self.gamma,
                )
                roi_boxes.append(
                    {"patch": patch, "box": [int(left), int(right), int(top), int(bottom)]}
                )
            if debug:
                visualization["centers"].append(
                    [float(center_point[0]), float(center_point[1])]
                )
                visualization["rois"].append(
                    {"chart": chart_name[chart_index], "boxes": roi_boxes}
                )

            patch_result = assess_patch_results(
                chart_results,
                chart_index,
                chart_name,
                chart_distance,
                center_index,
                outer_index,
                frequency,
                main_frequency,
                gr_index,
                gb_index,
                self.config_sensor,
                self.config_key_sfr,
            )
            metric_keys.extend(patch_result["metric_keys"])
            metric_values.extend(patch_result["metric_values"])
            statuses.extend(patch_result["statuses"])
            center_data.extend(patch_result["center_data"])
            outer_data.extend(patch_result["outer_data"])

        tilt_falloff = assess_tilt_falloff(
            center_data, outer_data, self.config_sensor, self.config_key_sfr
        )
        metric_keys.extend(tilt_falloff["metric_keys"])
        metric_values.extend(tilt_falloff["metric_values"])
        statuses.extend(tilt_falloff["statuses"])

        details = {
            "tilt": tilt_falloff["tilt"],
            "falloff": tilt_falloff["falloff"],
            "chart_type": self.chart_type,
        }
        return self._build_result(
            metric_keys, metric_values, statuses, details, visualization
        )
