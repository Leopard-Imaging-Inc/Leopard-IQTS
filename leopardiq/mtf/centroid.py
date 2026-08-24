"""
SFR 标板方格质心检测。

提取自 LeopardIQ0529/leopardiq/utils/utils.py：
- get_centroid_hawk()   → find_square_centroids_bayer()
- get_centroid_ov2311() → find_square_centroids_mono()
- get_centroid()        → find_square_centroids_generic()
- get_centroid_peak()   → find_peak_focus_centroid()
- sort_sfr_peak / draw_sfr_peak（峰值对焦辅助）

注意：原 get_centroid_ov2311() 只返回 2 个值，而 sfr_main 按 3 个值解包（潜在 bug），
提取后统一返回 (centroids, stats, binary_image) 三元组。
"""

import warnings
from typing import Tuple

import cv2
import numpy as np


def find_square_centroids_mono(
    image: np.ndarray, square_size_pixel: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    单通道（mono）传感器多方格标板质心检测（原 get_centroid_ov2311）。

    通过 1.4 倍提亮 + Otsu 二值化寻找黑色方格连通域。

    Args:
        image: 灰度图 (H, W) 或 (H, W, 1)
        square_size_pixel: 方格估计边长（像素），用于筛选连通域

    Returns:
        (centroids, stats, binary_image)
        stats 每行为 (x, y, width, height, area)
    """
    if image.ndim == 3 and image.shape[-1] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    image = np.squeeze(image).astype(np.float32)

    # 提亮以拉大方格与背景差异（连通域为黑色区域）
    image = image * 1.4
    image[image >= 255] = 255
    image_gray = image.astype(np.uint8)

    _, binary_image = cv2.threshold(
        image_gray, 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    # 黑方格是背景，需反转为前景
    binary_image = 1 - binary_image

    _, _, stats, centroid = cv2.connectedComponentsWithStats(binary_image)
    index = np.logical_and(
        stats[:, -1] > (square_size_pixel * 0.5) ** 2,
        stats[:, -1] < (square_size_pixel * 1.5) ** 2,
    )
    stats = stats[index]
    centroid = centroid[index]
    index_ratio = np.logical_and(
        stats[:, 2] / stats[:, 3] > 0.6, stats[:, 2] / stats[:, 3] < 1.5
    )
    return centroid[index_ratio], stats[index_ratio], binary_image


def find_square_centroids_bayer(
    image: np.ndarray, square_size_pixel: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Bayer 传感器多方格标板质心检测（原 get_centroid_hawk）。

    针对大标板四角暗角做分区亮度补偿，再用 Otsu + 直方图自适应阈值二值化。

    Args:
        image: 单通道图 (H, W)（通常取 Gr 通道）
        square_size_pixel: 方格估计边长（像素）

    Returns:
        (centroids, stats, binary_image)
    """
    if image.ndim == 3 and image.shape[-1] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    image = np.squeeze(image).astype(np.float32).copy()

    image_height, image_width = image.shape
    # 四角暗角补偿（×2.5），中间过曝区域衰减（×0.6）
    image_height_choose = int(image_height * 0.4)
    image_width_choose = int(image_width * 0.2)
    image[0:image_height_choose, 0:image_width_choose] *= 2.5
    image[0:image_height_choose, -image_width_choose:] *= 2.5
    image[-image_height_choose:, 0:image_width_choose] *= 2.5
    image[-image_height_choose:, -image_width_choose:] *= 2.5
    image[image_height_choose:-image_height_choose, image_width_choose:-image_width_choose] *= 0.6
    image[image >= 255] = 255
    image_gray = image.astype(np.uint8)

    _, binary_image = cv2.threshold(
        image_gray.copy(), 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    binary_image = 1 - binary_image

    _, _, stats, centroid = cv2.connectedComponentsWithStats(binary_image)
    index = np.logical_and(
        stats[:, -1] > (square_size_pixel * 0.5) ** 2,
        stats[:, -1] < (square_size_pixel * 1.5) ** 2,
    )
    stats = stats[index]
    centroid = centroid[index]
    index_ratio = np.logical_and(
        stats[:, 2] / stats[:, 3] > 0.2, stats[:, 2] / stats[:, 3] < 2.5
    )
    centroid_choose = centroid[index_ratio]
    stats = stats[index_ratio]

    # 直方图自适应阈值二值化（供后续边缘追踪使用）
    gaussian_ksize = 9
    hist_distance = 80
    thresh_val = 255 / 2
    image_gray = cv2.GaussianBlur(image_gray, (gaussian_ksize, gaussian_ksize), 0)
    img_hist = cv2.calcHist([image_gray], [0], None, [256], [0, 256])
    img_hist[0] = 255
    sort_hist = np.argsort(img_hist.flatten())[::-1]
    for index in range(1, 255):
        if abs(sort_hist[0] - sort_hist[index]) > hist_distance:
            thresh_val = (sort_hist[0] + sort_hist[index]) / 2
            break
    _, binary_image = cv2.threshold(image_gray, thresh_val, 255, cv2.THRESH_BINARY)

    return centroid_choose, stats, binary_image


def find_square_centroids_generic(
    image: np.ndarray, square_size_pixel: float
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    通用多方格质心检测（原 get_centroid，1.5 倍提亮 + Otsu）。
    """
    if image.ndim == 3 and image.shape[-1] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    image = np.squeeze(image).astype(np.float32)

    image = image * 1.5
    image[image >= 255] = 255
    image_gray = image.astype(np.uint8)

    _, binary_image = cv2.threshold(
        image_gray, 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    binary_image = 1 - binary_image

    _, _, stats, centroid = cv2.connectedComponentsWithStats(binary_image)
    index = np.logical_and(
        stats[:, -1] > (square_size_pixel * 0.5) ** 2,
        stats[:, -1] < (square_size_pixel * 1.5) ** 2,
    )
    stats = stats[index]
    centroid = centroid[index]
    index_ratio = np.logical_and(
        stats[:, 2] / stats[:, 3] > 0.6, stats[:, 2] / stats[:, 3] < 1.5
    )
    return centroid[index_ratio], stats[index_ratio], binary_image


def find_peak_focus_centroid(
    image: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    峰值对焦标板中心方格检测（原 get_centroid_peak）。

    筛选高度为图像高度 5%~40% 的连通域，取离图像中心最近的一个。

    Returns:
        (centroid, stats)：centroid 为 (x, y)，stats 为 (x, y, w, h, area)
    """
    if image.ndim == 3 and image.shape[-1] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    image = np.squeeze(image).astype(np.float32)
    image_height, image_width = image.shape[:2]

    image[image >= 255] = 255
    image_gray = image.astype(np.uint8)
    _, binary_image = cv2.threshold(
        image_gray, 0, 1, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    binary_image = 1 - binary_image

    _, _, stats, centroid = cv2.connectedComponentsWithStats(binary_image)
    index = np.logical_and(
        stats[:, 3] > image_height * 0.05, stats[:, 3] < image_height * 0.4
    )
    stats_choose = stats[index]
    centroid_choose = centroid[index]
    if stats_choose.shape[0] == 0:
        raise RuntimeError(
            "peak_focus: 未检测到符合尺寸要求的标板方格"
            f"（连通域高度需在图像高度的 5%~40% 内，图像 {image_width}×{image_height}），"
            "请检查标板是否完整入镜后重新拍摄"
        )

    distance = np.sqrt(
        np.square(centroid_choose[:, 0] - image_width / 2)
        + np.square(centroid_choose[:, 1] - image_height / 2)
    )
    index_min = int(np.argmin(distance))
    if distance[index_min] > np.sqrt(image_height ** 2 + image_width ** 2) * 0.05:
        warnings.warn(
            "The MTF chart is not well centered in the frame. Please recapture."
        )
    return centroid_choose[index_min], stats_choose[index_min]


def sort_sfr_peak(
    distance_list: list, distance_results: list
) -> Tuple[np.ndarray, np.ndarray]:
    """按拍摄距离升序排列 SFR 结果。"""
    index = np.argsort(distance_list)
    return np.array(distance_list)[index], np.array(distance_results)[index]


def draw_sfr_peak(
    show_distance: np.ndarray,
    show_sfr: np.ndarray,
    distance_max: float,
    sfr_max: float,
    save_image_path: str,
) -> None:
    """绘制 SFR-距离曲线并标记峰值对焦位置，保存到文件。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots()
    axis.plot(show_distance, show_sfr)
    axis.set_title(
        f"Peak Focus Position = {distance_max} cm    "
        f"Peak MTF @ NYQ / 2 = {sfr_max}"
    )
    axis.set_xlabel("Chart to Camera Distance (cm)")
    axis.set_ylabel("MTF @ NYQ / 2")
    figure.savefig(save_image_path)
    plt.close(figure)
