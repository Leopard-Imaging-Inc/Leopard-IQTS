"""
十字（SFR cross / reg 风格）标板检测与定位。

提取自 LeopardIQ0529：
- leopardiq/sfr/normxcorr2.py      → normxcorr2()（替代 pymlfunc 依赖）
- leopardiq/sfr/detect_sfr_cross.py → detect_sfr_cross(), imregionalmax()
- leopardiq/utils/line_endpoint.py  → find_line_endpoints()
- leopardiq/utils/sfr_cross_utils.py → edge_operator_vertical/horizontal,
  get_edge_line_endpoints(), get_edge_axis_data()

兼容性修复：
- 原 line_endpoint 使用 np.int / np.bool（NumPy 1.24+ 已移除），改为 int / bool
- 原 scipy.ndimage.filters.maximum_filter 已废弃，改为 scipy.ndimage.maximum_filter
- 原 skimage.filters.sobel 依赖，改为 cv2.Sobel 实现（去除 scikit-image 依赖）
- 模板支持直接传入 ndarray，也支持 .mat 文件路径（key="template"）
"""

import warnings
from typing import Optional, Tuple, Union

import numpy as np
import scipy.ndimage
from scipy.signal import fftconvolve


def normxcorr2(template: np.ndarray, image: np.ndarray, mode: str = "full") -> np.ndarray:
    """
    归一化互相关（MATLAB normxcorr2 的 Python 实现）。

    原作者: Ujash Joshi, University of Toronto, 2017
    与 MATLAB 结果在 3 位有效数字内一致。

    Args:
        template: 模板数组（各维度不得大于 image）
        image: 待搜索图像
        mode: "full" | "valid" | "same"

    Returns:
        互相关系数矩阵
    """
    if np.ndim(template) > np.ndim(image) or len(
        [i for i in range(np.ndim(template)) if template.shape[i] > image.shape[i]]
    ) > 0:
        warnings.warn("normxcorr2: TEMPLATE larger than IMG. Arguments may be swapped.")

    template = template - np.mean(template)
    image = image - np.mean(image)

    a1 = np.ones(template.shape)
    ar = np.flipud(np.fliplr(template))
    out = fftconvolve(image, ar.conj(), mode=mode)

    image = fftconvolve(np.square(image), a1, mode=mode) - np.square(
        fftconvolve(image, a1, mode=mode)
    ) / np.prod(template.shape)
    image[np.where(image < 0)] = 0

    template_energy = np.sum(np.square(template))
    out = out / np.sqrt(image * template_energy)
    out[np.where(np.logical_not(np.isfinite(out)))] = 0
    return out


def imregionalmax(image: np.ndarray) -> np.ndarray:
    """区域极大值掩膜（对应 MATLAB imregionalmax）。"""
    local_max = scipy.ndimage.maximum_filter(image, size=3)
    return image == local_max


def _load_template(template: Union[str, np.ndarray]) -> np.ndarray:
    """加载十字标板模板：支持 .mat 路径或 ndarray。"""
    if isinstance(template, np.ndarray):
        return template
    import scipy.io as scio

    return scio.loadmat(template)["template"]


def detect_sfr_cross(
    search_region: np.ndarray,
    roi_size: Union[list, tuple],
    center_bias: float,
    number_charts: int,
    template: Union[str, np.ndarray],
) -> Tuple[list, np.ndarray]:
    """
    用模板匹配检测十字标板中心并生成 4 个测量 ROI。

    模板为正/反两种黑白顺序各匹配一次，取相关度更高的结果。

    Args:
        search_region: 待搜索区域（灰度图）
        roi_size: [major, minor] ROI 尺寸；长度为 1 时 minor = major / 2
        center_bias: 中心到 ROI 起始边的距离（像素）
        number_charts: 需检测的标板数量
        template: 十字模板（.mat 文件路径或 ndarray）

    Returns:
        (center, rois)
        - center: [center_axisx, center_axisy]，各标板十字交界点
        - rois: (4, 4, number_charts)，每页为 4 个 ROI 的
          (top, bottom, left, right)（t/b/l/r 顺序）
    """
    template = _load_template(template)

    if len(search_region.shape) == 3:
        # 多通道输入：选通道均值最大的单通道继续匹配。
        # 原实现为「数组自比较 + 对标量取下标的错误逻辑」（命中必崩），等价修复。
        index = int(
            np.argmax(search_region.reshape(-1, search_region.shape[-1]).mean(axis=0))
        )
        search_region = search_region[:, :, index]
    search_region_gray = np.power(search_region, 0.2)

    # 模板黑白顺序可能与图像相反，正/反模板各匹配一次取更优
    correlation1 = normxcorr2(template, search_region_gray)
    correlation2 = normxcorr2(template[:, ::-1], search_region_gray)
    correlation = (
        correlation1
        if np.max(correlation1) >= np.max(correlation2)
        else correlation2
    )

    mask = imregionalmax(correlation)
    peaks = sorted(correlation[mask], reverse=True)
    peaks_index = np.where(correlation == peaks[:number_charts])
    peak_axisy = peaks_index[0]
    peak_axisx = peaks_index[1]

    center_axisx = np.round(peak_axisx - template.shape[0] / 2)
    center_axisy = np.round(peak_axisy - template.shape[1] / 2)
    center = [center_axisx, center_axisy]

    if len(roi_size) == 1:
        roi_size = [roi_size[0], roi_size[0] / 2]

    rois = np.zeros((4, 4, number_charts))
    for chart_index in range(number_charts):
        rois[:, :, chart_index] = [
            [
                center_axisy[chart_index] - center_bias - roi_size[0],
                center_axisy[chart_index] - center_bias,
                center_axisx[chart_index] - roi_size[1] / 2,
                center_axisx[chart_index] + roi_size[1] / 2,
            ],
            [
                center_axisy[chart_index] + center_bias,
                center_axisy[chart_index] + center_bias + roi_size[0],
                center_axisx[chart_index] - roi_size[1] / 2,
                center_axisx[chart_index] + roi_size[1] / 2,
            ],
            [
                center_axisy[chart_index] - roi_size[1] / 2,
                center_axisy[chart_index] + roi_size[1] / 2,
                center_axisx[chart_index] - center_bias - roi_size[0],
                center_axisx[chart_index] - center_bias,
            ],
            [
                center_axisy[chart_index] - roi_size[1] / 2,
                center_axisy[chart_index] + roi_size[1] / 2,
                center_axisx[chart_index] + center_bias,
                center_axisx[chart_index] + center_bias + roi_size[0],
            ],
        ]
    rois[rois < 1] = 1
    return center, rois


def find_line_endpoints(image: np.ndarray) -> np.ndarray:
    """
    二值图中直线端点检测（对应 MATLAB bwmorph(bw, 'endpoints')）。

    修复：原实现使用 np.int / np.bool，NumPy 1.24+ 已移除。
    """
    image = image.astype(int)
    kernel = np.array([[1, 1, 1], [1, 0, 1], [1, 1, 1]])
    neighborhood_count = scipy.ndimage.convolve(
        image, kernel, mode="constant", cval=0
    )
    neighborhood_count[~image.astype(bool)] = 0
    return neighborhood_count == 1


def edge_operator_vertical(image: np.ndarray, thresh: float = 50) -> np.ndarray:
    """
    垂直斜边位置检测（每行取垂直梯度最大值位置）。

    原实现基于 skimage.filters.sobel_v，提取后改用 cv2.Sobel，
    去除 scikit-image 依赖。
    """
    import cv2

    edge_mask = cv2.Sobel(image, cv2.CV_64F, 1, 0, ksize=3)
    maximum_column_per_row = np.argmax(np.abs(edge_mask), axis=1)
    max_row_data = edge_mask[range(0, edge_mask.shape[0]), maximum_column_per_row]
    delete_flag = np.where(np.abs(max_row_data) > thresh)
    if delete_flag[0].size != maximum_column_per_row.size:
        warnings.warn(
            "There is a problem with the selected region, "
            "and there is an undemarcated region"
        )
    maximum_column_per_row = maximum_column_per_row[delete_flag]
    row_index = np.array(range(0, image.shape[0]))[delete_flag]
    mask = np.zeros(image.shape)
    mask[row_index, maximum_column_per_row] = 1
    return mask


def edge_operator_horizontal(image: np.ndarray, thresh: float = 50) -> np.ndarray:
    """水平斜边位置检测（每列取水平梯度最大值位置）。"""
    import cv2

    edge_mask = cv2.Sobel(image, cv2.CV_64F, 0, 1, ksize=3)
    maximum_row_per_column = np.argmax(np.abs(edge_mask), axis=0)
    max_column_data = edge_mask[maximum_row_per_column, range(0, edge_mask.shape[1])]
    delete_flag = np.where(np.abs(max_column_data) > thresh)
    if delete_flag[0].size != maximum_row_per_column.size:
        warnings.warn(
            "There is a problem with the selected region, "
            "and there is an undemarcated region"
        )
    maximum_row_per_column = maximum_row_per_column[delete_flag]
    column_index = np.array(range(0, image.shape[1]))[delete_flag]
    mask = np.zeros(image.shape)
    mask[maximum_row_per_column, column_index] = 1
    return mask


def get_edge_line_endpoints(
    edge_mask: np.ndarray,
) -> Tuple[Optional[list], Optional[list], tuple]:
    """
    由斜边掩膜求直线两端点（原 get_point，去除绘图逻辑）。

    Returns:
        (point1, point2, point_data)
        point1 = [column, row]，row 较小的端点；point2 为 row 较大的端点；
        未找到恰好 2 个端点时返回 (None, None, point_data)
    """
    end_point = find_line_endpoints(edge_mask)
    point_data = np.where(end_point == 1)
    if len(point_data) == 2 and point_data[0].size == 2:
        point1 = [point_data[1][np.argmin(point_data[0])], np.min(point_data[0])]
        point2 = [point_data[1][np.argmax(point_data[0])], np.max(point_data[0])]
        return point1, point2, point_data
    return None, None, point_data


def get_edge_axis_data(
    bottom_decimal: float,
    left_decimal: float,
    point1: list,
    point2: list,
    right_decimal: float,
    top_decimal: float,
) -> Tuple[float, float, float, float]:
    """
    将 ROI 内端点坐标映射回原图坐标系，用于与中心点计算向量夹角（原 get_axis_data）。
    """
    if (point2[1] - point1[1]) != 0:
        angle = 180 - np.rad2deg(
            np.arctan2((point2[1] - point1[1]), (point2[0] - point1[0]))
        )
    else:
        angle = 90
    if angle < 45 or angle > 135:
        axisx1 = left_decimal
        axisx2 = right_decimal
        if point1[0] > point2[0]:
            axisy1 = top_decimal + point2[1]
            axisy2 = top_decimal + point1[1]
        else:
            axisy1 = top_decimal + point1[1]
            axisy2 = top_decimal + point2[1]
    else:
        axisx1 = left_decimal + point2[0]
        axisy1 = bottom_decimal
        axisx2 = left_decimal + point1[0]
        axisy2 = top_decimal
    return axisx1, axisx2, axisy1, axisy2
