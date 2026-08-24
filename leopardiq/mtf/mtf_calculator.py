"""
MTF 计算封装：C++ sfrmat5 引擎接口 + Gamma 线性化 + MTF 插值/指标计算。

提取自 LeopardIQ0529：
- leopardiq/utils/mtf_utils.py (search_first, get_choose_mtf, get_mtf,
  interpolation_nyquist, interpolation_mtf 等)
- leopardiq/utils/sfr_cross_utils.py 中的 mtf_sfrmat5_cpp 调用

C++ 引擎为 leopardiq/mtf_sfrmat5_cpp.pyd（ISO 12233:2014 sfrmat5 斜边算法）。

Gamma 线性化遵循 Imatest SFR 文档（imatest.com/docs/sfr_instructions2）：
- 输入 Gamma 为「前向 / 编码」Gamma（sRGB / Adobe RGB 约 0.46 ≈ 1/2.2），
  线性化取其倒数：pixel_linear = pixel ^ (1 / gamma_encoding)；
- 线性 RAW 数据 gamma=1.0（等价于「不线性化」）；
  BMP/JPEG 等 sRGB 编码图像约 0.45~0.5（Imatest 默认 0.5）。
"""

import re
import warnings
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np
from scipy import interpolate

from leopardiq import mtf_sfrmat5_cpp

#: MTFnn / MTFnnP 指标名（nn 为百分比，如 mtf50、mtf30、mtf50p、mtf12p）
_MTFP_PATTERN = re.compile(r"mtf(\d+(?:\.\d+)?)(p?)")

#: Imatest 对输入 Gamma 的合理区间提示：超出 [0.3, 0.8] 视为异常（可能错误）
GAMMA_REASONABLE_RANGE: Tuple[float, float] = (0.3, 0.8)

#: validate_edge_patch 默认阈值
EDGE_MIN_SIZE: int = 8         # 与 compute_roi_sfr 的退化 ROI 拦截口径一致
EDGE_COHERENCE_MIN: float = 0.5  # 结构张量相干性下限（清晰斜边 >0.8，纯噪声 ~0）
EDGE_CONTRAST_MIN: float = 0.1   # 沿边缘法向的阶跃幅度 / ROI 动态范围 下限


def validate_edge_patch(
    patch: np.ndarray,
    min_size: int = EDGE_MIN_SIZE,
    coherence_min: float = EDGE_COHERENCE_MIN,
    contrast_min: float = EDGE_CONTRAST_MIN,
) -> Tuple[bool, str]:
    """
    C++ sfrmat5 引擎的斜边 ROI 前置预检（防进程崩溃）。

    参考 lf-1.6.5《Raw数据处理流程.md》引擎健壮性一节：当 ROI 内检测不到
    有效斜边时，C++ 引擎行为各异——平坦图抛 "s >= 0" 异常、水平/垂直边缘
    抛 "empty matrix" 异常（均可按 RuntimeError 捕获），但**纯噪声图直接
    段错误（0xC0000005），Python 侧 try/except 无法捕获，整个进程被杀**。
    因此在进入 C++ 引擎前先用纯 numpy/OpenCV 检查拦截无效输入：

    1. 形状：必须 2D 且短边 ≥ min_size（与 compute_roi_sfr 口径一致）；
    2. 数值：必须全部有限（NaN/Inf 会让引擎行为未定义）；
    3. 动态范围：max == min 的全平图直接拒绝；
    4. 边缘相干性：3×3 高斯降噪后 Sobel 梯度的结构张量相干性
       coh = sqrt((Jxx-Jyy)² + 4Jxy²) / (Jxx+Jyy)。
       真实斜边（即使离焦模糊）coh → 1；各向同性噪声 coh → 0；
    5. 边缘对比度：沿主梯度方向（边缘法向）投影，两端各 15% 区域的
       均值阶跃须 ≥ ROI 动态范围的 contrast_min 倍（拦极低对比度假边）。

    Returns:
        (ok, reason)：ok=False 时 reason 为中文原因说明
    """
    a = np.squeeze(np.asarray(patch, dtype=np.float64))
    if a.ndim != 2:
        return False, f"非 2D 图像（shape={a.shape}）"
    if min(a.shape) < min_size:
        return False, f"尺寸过小（shape={a.shape}，短边需 ≥ {min_size}）"
    if not np.all(np.isfinite(a)):
        return False, "含 NaN/Inf 像素"

    dynamic = float(a.max() - a.min())
    if dynamic <= 0.0:
        return False, "平坦区域（动态范围为 0，无边缘）"

    # 3×3 高斯降噪后再取梯度：压低白噪声的梯度能量，保留真实边缘
    b = cv2.GaussianBlur(a, (3, 3), 0)
    gx = cv2.Sobel(b, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(b, cv2.CV_64F, 0, 1, ksize=3)
    jxx = float((gx * gx).sum())
    jyy = float((gy * gy).sum())
    jxy = float((gx * gy).sum())
    energy = jxx + jyy
    if energy <= 0.0:
        return False, "平坦区域（无梯度能量）"

    coherence = float(np.sqrt((jxx - jyy) ** 2 + 4.0 * jxy * jxy) / energy)
    if coherence < coherence_min:
        return False, (
            f"无方向一致的斜边（相干性 {coherence:.2f} < {coherence_min:g}，"
            "疑似纯噪声/杂乱纹理）"
        )

    # 主梯度方向（边缘法向）θ = 0.5·atan2(2Jxy, Jxx-Jyy)
    theta = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    height, width = a.shape
    yy, xx = np.mgrid[0:height, 0:width]
    proj = xx * np.cos(theta) + yy * np.sin(theta)
    p_lo, p_hi = np.percentile(proj, [15.0, 85.0])
    step = abs(float(a[proj >= p_hi].mean()) - float(a[proj <= p_lo].mean()))
    if step < contrast_min * dynamic:
        return False, (
            f"边缘对比度过低（法向阶跃 {step:.3g} < "
            f"{contrast_min:g}×动态范围 {dynamic:.3g}）"
        )
    return True, ""


def linearize_gamma(patch: np.ndarray, gamma: float) -> np.ndarray:
    """
    按 Imatest 方式去除 Gamma 编码，将像素值转回线性空间。

    pixel_linear = pixel ^ (1 / gamma_encoding)

    （常数亮度缩放与幂运算可交换，SFR 对 LSF 归一化，故无需先归一化到 [0,1]；
    负值——如黑电平校正残差——先截断为 0。）

    Args:
        patch: ROI 图像（任意 shape）
        gamma: 编码 Gamma（典型值：sRGB ≈ 0.46，Imatest 默认 0.5，
               线性 RAW 为 1.0）；gamma == 1.0 时原样返回（不线性化）

    Returns:
        线性化后的 float64 图像
    """
    gamma = float(gamma)
    if gamma <= 0.0:
        raise ValueError(f"gamma 必须为正数（当前 {gamma:g}）")
    patch = np.asarray(patch, dtype=np.float64)
    if gamma == 1.0:
        return patch
    return np.clip(patch, 0.0, None) ** (1.0 / gamma)


def compute_mtf_array(
    patch: np.ndarray,
    c: int = 5,
    alpha: float = 1.0,
    est_angle: bool = False,
    gamma: float = 1.0,
) -> Optional[np.ndarray]:
    """
    调用 C++ sfrmat5 引擎计算单个斜边 ROI 的 MTF 曲线。

    Args:
        patch: 斜边 ROI 图像（2D），需包含黑白分界斜边；
               送入引擎前先经 validate_edge_patch 预检（防段错误）
        c: sfrmat5 超采样参数（默认 5，与原库一致）
        alpha: sfrmat5 参数（默认 1.0）
        est_angle: 是否由引擎估计边缘角度（默认 False）
        gamma: 编码 Gamma，计算前按 pixel^(1/gamma) 线性化
               （Imatest「Input gamma value」；默认 1.0 = 不线性化，
               与旧行为一致，适用于线性 RAW 数据）

    Returns:
        (N, 2) 数组：第 0 列为空间频率 (cy/px)，第 1 列为 MTF 值；
        计算失败时返回 None
    """
    patch = np.squeeze(np.asarray(patch, dtype=np.float64))
    if patch.size == 0:
        warnings.warn("compute_mtf_array: empty patch")
        return None
    # 引擎前置预检：拦截平坦/噪声/非 2D 等无效 ROI——纯噪声 ROI 会让
    # C++ 引擎段错误（0xC0000005），Python 无法捕获，进程直接崩溃
    ok, reason = validate_edge_patch(patch)
    if not ok:
        warnings.warn(f"compute_mtf_array: 无效斜边 ROI（{reason}），未送入引擎")
        return None
    try:
        mtf_array = mtf_sfrmat5_cpp.ComputeMTFArray(
            linearize_gamma(patch, gamma), c, alpha, est_angle
        )
    except RuntimeError as exc:
        # C++ 引擎对异常 ROI（无有效斜边等）会抛 OpenCV RuntimeError
        warnings.warn(f"compute_mtf_array: MTF engine failed: {exc}")
        return None
    if mtf_array is None:
        return None
    # 引擎输出的曲线可能含 NaN 采样点（退化频段），在引擎边界统一剔除；
    # 有效点不足 2 个（无法插值）视为计算失败
    mtf_array = np.asarray(mtf_array, dtype=np.float64)
    finite_rows = np.isfinite(mtf_array).all(axis=1)
    if not np.all(finite_rows):
        mtf_array = mtf_array[finite_rows]
    if mtf_array.shape[0] < 2:
        warnings.warn(
            "compute_mtf_array: 引擎输出有效采样点不足（疑似全 NaN 曲线），"
            "视为计算失败"
        )
        return None
    return mtf_array


def interpolation_nyquist(
    mtf_array: np.ndarray, frequency: Sequence[float]
) -> np.ndarray:
    """
    按横坐标（频率）插值 MTF 曲线，得到指定频率点的 SFR 值。

    Args:
        mtf_array: (N, 2)，第 0 列频率，第 1 列 MTF
        frequency: 目标频率（标量或数组），支持批量

    Returns:
        插值得到的 SFR 值
    """
    mtf_data = mtf_array[:, 1]
    mtf_frequency = mtf_array[:, 0]
    # 引擎输出的 MTF 曲线可能含 NaN 采样点（退化频段），
    # 直接进 interp1d 会把 NaN 扩散到所有插值结果，先剔除
    finite = np.isfinite(mtf_frequency) & np.isfinite(mtf_data)
    if not np.all(finite):
        mtf_frequency = mtf_frequency[finite]
        mtf_data = mtf_data[finite]
    if mtf_data.size < 2:
        warnings.warn("interpolation_nyquist: 有效采样点不足，返回 NaN")
        return np.full_like(np.asarray(frequency, dtype=np.float64), np.nan)
    freq_vs_mtf = interpolate.interp1d(mtf_frequency, mtf_data, kind="linear")
    return freq_vs_mtf(frequency)


def interpolation_mtf(mtf_array: np.ndarray, mtf_value: float) -> float:
    """
    按纵坐标（MTF 值）反插频率，用于求 MTF50 等对应的空间频率。

    Args:
        mtf_array: (N, 2)，第 0 列频率，第 1 列 MTF
        mtf_value: 目标 MTF 值（如 0.5）

    Returns:
        对应的频率值
    """
    mtf_data = mtf_array[:, 1]
    mtf_frequency = mtf_array[:, 0]
    # 剔除引擎输出中的 NaN 采样点（同 interpolation_nyquist）
    finite = np.isfinite(mtf_frequency) & np.isfinite(mtf_data)
    if not np.all(finite):
        mtf_frequency = mtf_frequency[finite]
        mtf_data = mtf_data[finite]
    if mtf_data.size < 2:
        warnings.warn("interpolation_mtf: 有效采样点不足，返回 NaN")
        return float("nan")
    mtf_vs_freq = interpolate.interp1d(mtf_data, mtf_frequency, kind="linear")
    return mtf_vs_freq(mtf_value)


def search_first(mtf_data: np.ndarray, thresh: float) -> int:
    """查找 mtf_data 中第一个低于 thresh 的下标；未找到返回 -1。"""
    for i in range(mtf_data.size):
        if mtf_data[i] < thresh:
            return i
    return -1


def get_choose_mtf(
    index: int, mtf_data: np.ndarray, mtf_frequency: np.ndarray
) -> Tuple[list, list]:
    """
    以 index 为中心前后各取若干点，保证所选区间单调递减（用于稳定插值）。
    """
    start = max(index - 4, 0)
    end = min(index + 4, mtf_data.size - 1)
    mtf_data_choose = [mtf_data[index]]
    mtf_frequency_choose = [mtf_frequency[index]]
    max_data = mtf_data[index]
    min_data = mtf_data[index]
    for j in range(index - 1, start, -1):
        cur = mtf_data[j]
        if cur > min_data:
            min_data = cur
            mtf_data_choose.insert(0, mtf_data[j])
            mtf_frequency_choose.insert(0, mtf_frequency[j])
        else:
            break
    for i in range(index + 1, end):
        cur = mtf_data[i]
        if cur < max_data:
            max_data = cur
            mtf_data_choose.append(mtf_data[i])
            mtf_frequency_choose.append(mtf_frequency[i])
        else:
            break
    return mtf_data_choose, mtf_frequency_choose


def interpolate_function(
    mtf_data_choose: list,
    mtf_frequency_choose: list,
    mtf_y: float,
    array_size_threshold: int = 3,
    border: float = None,
) -> float:
    """
    在单调区间内对 mtf_y 做线性插值；区间过短或不包含目标值时返回 0.0。
    """
    if border is None:
        border = mtf_y
    if (
        len(mtf_data_choose) >= array_size_threshold
        and border > min(mtf_data_choose)
        and max(mtf_data_choose) > border
    ):
        func = interpolate.interp1d(
            mtf_data_choose, mtf_frequency_choose, kind="linear"
        )
        return float(func(mtf_y))
    return 0.0


def _get_mtf_data(mtf_data: np.ndarray, mtf_frequency: np.ndarray, mtf_y: float) -> float:
    """求 MTF=mtf_y 处的频率（如 MTF50 / MTF30）。"""
    index = search_first(mtf_data, mtf_y)
    if index < 0:
        return 0.0
    data_choose, freq_choose = get_choose_mtf(index, mtf_data, mtf_frequency)
    return interpolate_function(data_choose, freq_choose, mtf_y, 3, mtf_y)


def _get_mtfp_data(
    data_size: int, mtf_data: np.ndarray, mtf_frequency: np.ndarray, upsample: float
) -> float:
    """求 MTF50P / MTF30P（峰值归一化后的 50% / 30% 频率）。"""
    mtfp_y = np.max(mtf_data[: int(data_size / 2)]) / upsample
    index = search_first(mtf_data, mtfp_y)
    if index < 0:
        return 0.0
    data_choose, freq_choose = get_choose_mtf(index, mtf_data, mtf_frequency)
    return interpolate_function(data_choose, freq_choose, mtfp_y, 3, mtfp_y)


def compute_mtf_metrics(
    mtf_array: np.ndarray,
    metrics: Sequence[str] = ("mtf50", "mtf30"),
) -> dict:
    """
    从 MTF 曲线计算常用指标。

    Args:
        mtf_array: (N, 2)，第 0 列频率 (cy/px)，第 1 列 MTF
        metrics: 需计算的指标名，可选：
            - "mtfNN"：MTF 降至低频值 NN% 处的空间频率（MTFnn，
              如 "mtf50"、"mtf30"、"mtf10"），NN ∈ (0, 100)
            - "mtfNNp"：MTF 降至峰值 NN% 处的空间频率（MTFnnP，
              如 "mtf50p"、"mtf30p"），适合强锐化（oversharpened）图像
            - "nyquist50" / "nyquist30" / "nyquist25"：
              Nyquist/2、Nyquist/3、Nyquist/4 频率处的 SFR 值
            - "mtf_120lp_mm"：0.168 cy/px 处的 SFR 值（120 lp/mm 专用）

    Returns:
        dict，如 {"mtf50": 0.31, "mtf30": 0.44}
    """
    mtf_array = np.squeeze(mtf_array)
    # 剔除引擎输出中含 NaN 的采样点（退化频段），避免污染 search/interp
    finite_rows = np.isfinite(mtf_array).all(axis=1)
    if not np.all(finite_rows):
        mtf_array = mtf_array[finite_rows]
    mtf_data = mtf_array[:, 1]
    mtf_frequency = mtf_array[:, 0]
    data_size = mtf_data.size
    if data_size < 2:
        warnings.warn("compute_mtf_metrics: 有效采样点不足，全部指标记 0.0")
        return {name: 0.0 for name in metrics}

    result = {}
    need_interp = {"nyquist50", "nyquist30", "nyquist25", "mtf_120lp_mm"}
    freq_func = None
    if need_interp.intersection(metrics):
        freq_func = interpolate.interp1d(mtf_frequency, mtf_data, kind="linear")

    for name in metrics:
        m = _MTFP_PATTERN.fullmatch(name)
        if m:
            nn = float(m.group(1))
            if not (0.0 < nn < 100.0):
                raise ValueError(f"MTFnn 百分比需在 (0, 100) 内：{name!r}")
            if m.group(2):  # MTFnnP：峰值归一化
                result[name] = _get_mtfp_data(
                    data_size, mtf_data, mtf_frequency, 100.0 / nn
                )
            else:  # MTFnn：低频值（绝对 MTF）归一化
                result[name] = _get_mtf_data(mtf_data, mtf_frequency, nn / 100.0)
        elif name == "nyquist50":
            result["nyquist50"] = float(freq_func(0.5 / 2))
        elif name == "nyquist30":
            result["nyquist30"] = float(freq_func(0.5 / 3))
        elif name == "nyquist25":
            result["nyquist25"] = float(freq_func(0.5 / 4))
        elif name == "mtf_120lp_mm":
            result["mtf_120lp_mm"] = float(freq_func(0.168))
        else:
            raise ValueError(f"Unknown MTF metric: {name}")
    return result


def compute_roi_sfr(
    sfr_patch: np.ndarray,
    frequency: np.ndarray,
    image_channel: int,
    patch_index: int,
    results_array: np.ndarray,
    gamma: float = 1.0,
) -> bool:
    """
    计算单个 ROI 所有通道在指定频率点的 SFR，写入 results_array。

    提取自 sfr_cross_utils.get_mtf_channle()，去除了 matplotlib 可视化耦合，
    返回值由绘图颜色改为有效标志。

    Args:
        sfr_patch: ROI 图像，shape (h, w, image_channel)
        frequency: 目标频率数组（已乘以 nyq_freq）
        image_channel: 通道数（1 或 4）
        patch_index: 当前 ROI 在 results_array 第 0 维的下标
        results_array: 输出数组，shape (num_patches, image_channel, num_freq)
        gamma: 编码 Gamma，计算前按 pixel^(1/gamma) 线性化
               （默认 1.0 = 不线性化，与旧行为一致）

    Returns:
        True 表示所有通道计算有效；False 表示存在 NaN（ROI 无效）
    """
    valid = True
    for channel in range(image_channel):
        patch_channel = np.float64(np.squeeze(sfr_patch[:, :, channel]))

        if patch_channel.size == 0:
            warnings.warn(
                f"ERROR: empty ROI patch={patch_index} channel={channel}"
            )
            results_array[patch_index, channel, 0] = np.nan
            results_array[patch_index, channel, len(frequency) - 1] = np.nan
            valid = False
            continue

        # 退化 ROI（非 2D 或尺寸过小）会让 C++ 引擎内部 OpenCV 断言崩溃，
        # 提前拦截为 NaN（原库无此保护，属于提取时的健壮性修复）
        if patch_channel.ndim != 2 or min(patch_channel.shape) < 8:
            warnings.warn(
                f"ERROR: degenerate ROI shape={patch_channel.shape} "
                f"patch={patch_index} channel={channel}"
            )
            results_array[patch_index, channel, 0] = np.nan
            results_array[patch_index, channel, len(frequency) - 1] = np.nan
            valid = False
            continue

        mtf_array = compute_mtf_array(patch_channel, gamma=gamma)

        if mtf_array is None:
            warnings.warn(
                f"ERROR: MTF computation failed patch={patch_index} channel={channel}"
            )
            results_array[patch_index, channel, 0] = np.nan
            results_array[patch_index, channel, len(frequency) - 1] = np.nan
            valid = False
            continue

        sfr_result = interpolation_nyquist(mtf_array, frequency)

        # 历史口径：size==2 时回填 sfr30（第 1 点）与 sfr50（第 2 点），
        # 其余情况仅回填第 1 个频率点，其它频率点保持初始化时的 0。
        # SFR > 1.0 视为无效（置 NaN）。此处仅澄清原「np.nan 当布尔旗标」的
        # 晦涩写法，回填口径不变。
        n_write = 2 if frequency.size == 2 else 1
        for freq_i in range(n_write):
            value = sfr_result[freq_i]
            results_array[patch_index, channel, freq_i] = (
                value if value <= 1.0 else np.nan
            )

        if np.isnan(results_array[patch_index, channel, :]).any():
            warnings.warn(f"ERROR: invalid ROI, SFR=NaN patch={patch_index}")
            valid = False

    return valid
