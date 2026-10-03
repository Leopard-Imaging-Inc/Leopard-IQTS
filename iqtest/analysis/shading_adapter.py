"""Lens Shading 模块适配器：GUI（config dict + 图像路径）→ leopardiq.shading 算法接口。

职责（规划 §19 M3 + 开发文档 §6）：
  1. 图像加载：`.raw` 走 Generalized Read Raw（demosaic=False 取 mosaic，
     按全局 CFA 拆分为 4 通道）；常见格式（PNG/TIFF/…）按 mono 灰度读入；
  2. 面板参数 → 算法 config 映射（cfa / bin_size / thresh / support_extrapolation /
     criteria.ri / criteria.ri_diff / green_red_shift / green_blue_shift）；
  3. 子功能分发（test_item）：
     - single（单光源 Shading）：所有图像归入同一光源做多帧平均，
       走 analyze_relative_illumination，含报告通道与 LSC 闭环验证；
     - multi_light（多光源对比）：按「图像 → 光源」分组，≥2 光源走
       analyze_multi_light 并补算 color_shift_spread（§16.4）；
  4. 报告通道（luminance_channel）：由 bin_means 派生 Y/G/Gr 单通道 shading 网格
     与四象限 RI，仅作展示，不改变算法判定口径；
  5. LSC 闭环自检（§17.3）：单光源时 apply_lsc 后再测残余 shading，
     并保留校正后相对照度网格与校正后图像（结果界面「LSC 验证」Tab /
     查看、保存校正后图片）。

返回结构对齐算法层 {"metrics", "pass", "details", "visualization"}，
details 统一携带 mode / lights / comparison / cfa / channels / report /
per_channel_ri / closed_loop 等展示与导出所需数据。
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

from iqtest.config.read_raw_settings import get_read_raw_params
from leopardiq.shading import (
    analyze_multi_light,
    analyze_relative_illumination,
    apply_lsc,
)
from leopardiq.utils.image_preprocess import (
    bayer_to_luminance,
    get_bayer_index,
    split_bayer_channels,
)
from leopardiq.utils.raw_reader import DEMOSAIC_CODES, RawReadConfig, read_raw

#: 全局 Read Raw 的 CFA pattern（2×2 mosaic）→ split_bayer_channels 位置序
#: [TL, TR, BL, BR] 对应的四通道颜色名（与 get_bayer_index 的取值口径一致）。
CFA_TO_CHANNEL_ORDER: dict[str, list[str]] = {
    "RGGB": ["R", "Gr", "Gb", "B"],
    "BGGR": ["B", "Gb", "Gr", "R"],
    "GRBG": ["Gr", "R", "B", "Gb"],
    "GBRG": ["Gb", "B", "R", "Gr"],
}

#: OpenCV 可直接解码的常见格式（mono 读入）
COMMON_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

#: 单光源子功能在未指定光源时的分组/展示标签（单光源模式不绑定具体光源类型）
SINGLE_LIGHT_LABEL = "单光源"

#: 多光源「图像 → 光源」组的默认光源（未单独指定时使用）
DEFAULT_LIGHT_SOURCE = "D65"

#: 报告展示通道默认值（Y=BT.709 亮度加权）；可在结果界面由用户切换 Y/G/Gr
#: 此通道仅影响热力图/四象限展示，不影响算法判定口径。
REPORT_CHANNEL = "Y"


def load_shading_image(path, params: dict) -> tuple[np.ndarray, list[str]]:
    """加载一张图像 → (分析图像 float64, cfa 通道名列表)。

    - Bayer RAW：拆分后 (H/2, W/2, 4)，cfa 为与位置序一致的四通道名列表；
    - mono（RAW cfa=Y 或常见格式）：(H, W)，cfa=["Y"]。
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext in COMMON_EXTS:
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE | cv2.IMREAD_ANYDEPTH)
        if img is None:
            raise ValueError(f"无法解码图像：{path}")
        img = img.astype(np.float64)
        gamma = float(params.get("gamma", 1.0))
        if gamma != 1.0:
            # 非 Raw 图（sRGB 编码）按 Imatest「Input gamma value」线性化：pixel^(1/gamma)
            img = np.clip(img, 0.0, None) ** (1.0 / gamma)
        return img, ["Y"]

    if ext == ".raw":
        saved = get_read_raw_params()
        mosaic, _ = read_raw(
            path,
            RawReadConfig(
                width=int(params.get("raw_width", saved["width"])),
                height=int(params.get("raw_height", saved["height"])),
                bit_depth=int(params.get("bit_depth", saved["bit_depth"])),
                header_bytes=int(params.get("header_bytes", 0)),
                black_level=float(params.get("black_level", 0.0)),
                cfa=str(params.get("cfa", saved["cfa"])),
                demosaic=False,  # Shading 需原始 mosaic，禁用去马赛克
            ),
        )
        mosaic = np.squeeze(mosaic)
        cfa_key = str(params.get("cfa", saved["cfa"]))
        if cfa_key == "Y":
            return mosaic.astype(np.float64), ["Y"]
        order = CFA_TO_CHANNEL_ORDER.get(cfa_key)
        if order is None:
            raise ValueError(
                f"Shading 暂不支持的 CFA pattern：{cfa_key!r}"
                f"（支持 {sorted(CFA_TO_CHANNEL_ORDER)} 或 Y）"
            )
        return split_bayer_channels(mosaic).astype(np.float64), list(order)

    raise ValueError(
        f"Lens Shading 暂不支持的格式：{ext or '(无后缀)'}（{path.name}）"
    )


def _criteria_from_panel(panel_criteria: dict) -> dict:
    """面板 criteria → 算法 criteria（§7 映射口径）。

    lum_uniformity_min（均匀性下限）→ ri_diff 上限 = 1 - 均匀性。
    """
    out: dict = {}
    if "ri_corner_min" in panel_criteria:
        out["ri"] = float(panel_criteria["ri_corner_min"])
    if "lum_uniformity_min" in panel_criteria:
        out["ri_diff"] = 1.0 - float(panel_criteria["lum_uniformity_min"])
    if "green_red_shift_max" in panel_criteria:
        out["green_red_shift"] = float(panel_criteria["green_red_shift_max"])
    if "green_blue_shift_max" in panel_criteria:
        out["green_blue_shift"] = float(panel_criteria["green_blue_shift_max"])
    return out


def _report_channel(bin_means: np.ndarray, cfa: list, choice: str) -> np.ndarray:
    """由 bin 网格均值派生报告通道（Y/G/Gr）单通道数组。"""
    if bin_means.shape[-1] == 1:
        return bin_means[:, :, 0].astype(np.float64)
    gr, _red, _blue, gb = get_bayer_index(cfa)
    if choice == "Gr":
        return bin_means[:, :, gr].astype(np.float64)
    if choice == "G":
        return ((bin_means[:, :, gr] + bin_means[:, :, gb]) / 2.0).astype(np.float64)
    return bayer_to_luminance(bin_means, cfa).astype(np.float64)


def _quadrant_min(map2d: np.ndarray) -> dict[str, float]:
    """2D 归一化 shading 网格的四象限最小值（与 compute_quadrant_ri 同口径）。"""
    h, w = map2d.shape
    hh, hw = h // 2, w // 2
    return {
        "tl": float(np.nanmin(map2d[0:hh, 0:hw])),
        "tr": float(np.nanmin(map2d[0:hh, hw:])),
        "bl": float(np.nanmin(map2d[hh:, 0:hw])),
        "br": float(np.nanmin(map2d[hh:, hw:])),
    }


def _attach_roi_boxes(report: dict, orig_w: int, orig_h: int,
                      orig_block: float, corner_region_pct: float) -> dict:
    """为报告热力图附加九点 ROI 红框（网格坐标，1 单位 = ``orig_block`` 原始像素）。

    与 Imatest Luma/Color 的九点采样为同一物理区域，供结果界面热力图叠加红框。
    """
    from leopardiq.shading.imatest_metrics import imatest_roi_boxes_in_grid

    shading_map = report.get("shading_map")
    if shading_map is not None:
        report["boxes"] = imatest_roi_boxes_in_grid(
            shading_map.shape, orig_w, orig_h, orig_block, corner_region_pct
        )
    return report


def _compute_report(bin_means: np.ndarray, cfa: list, choice: str) -> dict:
    ch = _report_channel(bin_means, cfa, choice)
    mx = float(np.nanmax(ch))
    shading_map = ch / mx if mx > 0 and np.isfinite(mx) else ch
    ri = _quadrant_min(shading_map)
    ri_vals = [ri["tl"], ri["tr"], ri["bl"], ri["br"]]
    return {
        "channel": choice,
        "shading_map": shading_map,
        "ri": ri,
        "ri_diff": float(np.nanmax(ri_vals) - np.nanmin(ri_vals)),
    }


def _extract_per_channel_ri(metrics: dict, cfa: list) -> dict | None:
    """Bayer 输入时从算法 metrics 提取逐通道四象限 RI 与判定（展示用）。"""
    if len(cfa) != 4:
        return None

    def vals(key: str) -> list[float]:
        value = (metrics.get(key) or {}).get("value", [])
        return [float(x) for x in np.atleast_1d(value)]

    def statuses(key: str) -> list[str]:
        status = (metrics.get(key) or {}).get("status", [])
        return [str(s) for s in np.atleast_1d(status)]

    return {
        "channels": list(cfa),
        "tl": vals("ri_tl"),
        "tr": vals("ri_tr"),
        "bl": vals("ri_bl"),
        "br": vals("ri_br"),
        "status": {
            "tl": statuses("ri_tl"),
            "tr": statuses("ri_tr"),
            "bl": statuses("ri_bl"),
            "br": statuses("ri_br"),
        },
    }


def _ri_min(metrics: dict) -> float:
    vals: list[float] = []
    for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
        value = (metrics.get(key) or {}).get("value", [])
        vals.extend(np.atleast_1d(value))
    return float(np.nanmin(vals)) if vals else float("nan")


def _shift_value(metrics: dict, key: str) -> float | None:
    metric = metrics.get(key)
    if metric is None:
        return None
    return float(metric["value"])


def _display_image(img: np.ndarray, cfa: list | None = None) -> np.ndarray:
    """分析图像 → 原始 RAW 全分辨率展示图。

    - Bayer（4 通道且 cfa 可反查 pattern）：逆拆分回 mosaic → cv2 双线性 demosaic →
      转 RGB 彩色图 (H, W, 3)（供结果界面直接展示原始彩色图像）；
    - mono / 无法识别 pattern：返回灰色图原样（逆拆分回 mosaic 或直接返回）。

    与 load_shading_image 的 split_bayer_channels 互为逆运算，输出与原始 RAW 全分辨率
    mosaic（Generalized Read Raw / CFA=Y 所见）同尺寸，便于与原图逐像素对照。
    """
    arr = np.asarray(img, dtype=np.float64)
    if arr.ndim == 3 and arr.shape[-1] == 4:
        h, w, _ = arr.shape
        out = np.zeros((h * 2, w * 2), dtype=np.float64)
        out[0::2, 0::2] = arr[:, :, 0]
        out[0::2, 1::2] = arr[:, :, 1]
        out[1::2, 0::2] = arr[:, :, 2]
        out[1::2, 1::2] = arr[:, :, 3]
        if cfa:
            pattern = next(
                (p for p, order in CFA_TO_CHANNEL_ORDER.items() if list(order) == list(cfa)),
                None,
            )
            code = DEMOSAIC_CODES.get(pattern) if pattern else None
            if code is not None:
                clipped = np.clip(out, 0, np.iinfo(np.uint16).max).astype(np.uint16)
                bgr = cv2.demosaicing(clipped, code).astype(np.float64)
                return np.ascontiguousarray(bgr[:, :, ::-1])  # BGR → RGB 供界面显示
        return out
    return np.squeeze(arr).astype(np.float64)


def _compute_closed_loop(before_metrics: dict, avg: np.ndarray, profile: np.ndarray,
                         alg_config: dict,
                         luminance_channel: str = REPORT_CHANNEL,
                         corner_region_pct: float = 0.05) -> dict:
    """apply_lsc 后残余 shading 再测（§17.3 闭环自检，单光源）。

    除校正前/后标量对比外，同时保留校正后数据供结果界面展示：
      - after_report：校正后相对照度网格 + 四象限 RI（LSC 验证 Tab）；
      - corrected_image：校正后原始 RAW 全分辨率灰度图（左下角下拉列表查看 / 保存，
        与 details["source_image"] 校正前原图逐像素对照）。
    """
    # mono 时 avg 为 2D、profile 为 3D(H,W,1)；先对齐通道维避免广播成 (H,W,W)，再还原为 2D
    avg_arr = np.asarray(avg)
    profile = np.asarray(profile)
    mono = avg_arr.ndim == 2
    avg_for_lsc = avg_arr[:, :, None] if mono else avg_arr
    try:
        corrected = apply_lsc(avg_for_lsc, profile)
    except ValueError as exc:
        return {"enabled": False, "note": f"apply_lsc 不可用：{exc}"}
    if mono:
        corrected = corrected[:, :, 0]
    cfa = list(alg_config["cfa"])
    after = analyze_relative_illumination(corrected, alg_config)
    scale = 2 if len(cfa) == 4 else 1
    orig_h, orig_w = avg_arr.shape[0] * scale, avg_arr.shape[1] * scale
    after_report = _compute_report(
        after["details"]["bin_means"], cfa, luminance_channel
    )
    _attach_roi_boxes(after_report, orig_w, orig_h,
                      int(alg_config["bin_size"]) * scale, corner_region_pct)
    return {
        "enabled": True,
        "luminance_channel": luminance_channel,
        "before_ri_min": _ri_min(before_metrics),
        "after_ri_min": _ri_min(after["metrics"]),
        "before_ri_diff": float(before_metrics["ri_diff"]["value"]),
        "after_ri_diff": float(after["metrics"]["ri_diff"]["value"]),
        "before_green_red_shift": _shift_value(before_metrics, "green_red_shift"),
        "after_green_red_shift": _shift_value(after["metrics"], "green_red_shift"),
        "before_green_blue_shift": _shift_value(before_metrics, "green_blue_shift"),
        "after_green_blue_shift": _shift_value(after["metrics"], "green_blue_shift"),
        "residual_pass": bool(after["pass"]),
        "after_report": after_report,
        "corrected_image": _display_image(corrected, cfa=cfa),
    }


def _compute_color_shift_spread(lights: dict) -> dict | None:
    """各光源 green_red/blue_shift 的 max−min（§16.4，算法层零改动）。"""
    gr_vals: list[float] = []
    gb_vals: list[float] = []
    for res in lights.values():
        metrics = res.get("metrics", {})
        gr = _shift_value(metrics, "green_red_shift")
        gb = _shift_value(metrics, "green_blue_shift")
        if gr is not None:
            gr_vals.append(gr)
        if gb is not None:
            gb_vals.append(gb)
    if not gr_vals or not gb_vals:
        return None
    return {
        "green_red": float(max(gr_vals) - min(gr_vals)),
        "green_blue": float(max(gb_vals) - min(gb_vals)),
    }


def _compute_imatest_bin_means(avg: np.ndarray, cfa: list, thresh: float,
                               grid_block: int):
    """复用 bin_image_means 以目标 block 尺寸（拆分后像素）重算 Imatest 对标均值网格。

    Returns:
        ``(bin_means, y_pixels)``：block 均值网格 + 拆分后 Y 通道像素（含 NaN，
        供 Corners/Sides 做像素级 ROI 均值）。
    """
    from leopardiq.shading.shading_profile import (
        bin_image_means,
        create_flat_field_mask,
    )
    from leopardiq.shading.imatest_metrics import _luminance

    height, width = avg.shape[:2]
    gr_index = get_bayer_index(cfa)[0] if avg.shape[-1] == 4 else 0
    mask = create_flat_field_mask(avg, thresh, gr_index)

    start_axisx = grid_block // 2
    start_axisy = grid_block // 2
    axisx = np.array(range(start_axisx, width, grid_block))
    axisy = np.array(range(start_axisy, height, grid_block))

    avg_masked = avg.copy()
    if avg_masked.ndim == 2:
        avg_masked = avg_masked[:, :, np.newaxis]
    avg_masked[mask == 0, :] = np.nan
    means = bin_image_means(axisx, axisy, grid_block, avg_masked, mask)
    y_pixels = _luminance(avg_masked, cfa)
    return means, y_pixels


def _compute_imatest(avg: np.ndarray, cfa: list, params: dict,
                     file_label: str = "") -> dict:
    """计算 Imatest 口径结果集（Luma + Color），供结果界面展示与对标。

    Luma 用原始像素基准的独立 block 网格（复用 bin_image_means 改 bin_size 再算一次）；
    Color Shading 用 Bayer 拆分的 R/G、B/G（线性域，不做去马赛克/gamma），对齐 Imatest 口径。
    ``file_label`` 为原始文件名，透传给比值等值线图标题。
    """
    from leopardiq.shading.imatest_metrics import (
        compute_imatest_color_metrics,
        compute_imatest_luma_metrics,
    )

    saved_bd = int(get_read_raw_params().get("bit_depth", 16))
    bit_depth = int(params.get("bit_depth", saved_bd))
    # 满量程对齐 Imatest 16bit 口径：read_raw 会把 10/12/14-bit 数据左移到 16bit，
    # 因此满量程为 65535（Imatest "relative to 1 for pixel 65535"），而非
    # sensor 原始位深的 1023/4095/16383；8bit 保持 255。
    full_scale = 65535.0 if bit_depth != 8 else 255.0
    corner_region_pct = float(params.get("corner_region_pct", 0.05))
    imatest_block_size = int(params.get("imatest_block_size", 32))  # 原始像素
    contour_levels = max(2, int(params.get("contour_levels", 10)))  # 等值线级数
    thresh = float(params.get("thresh", 0.0))
    scale = 2 if len(cfa) == 4 else 1
    orig_h = avg.shape[0] * scale
    orig_w = avg.shape[1] * scale

    # Luma：原始像素基准网格（Bayer 拆分后 block 尺寸 = imatest_block_size / 2）
    luma_bin_means, y_pixels = _compute_imatest_bin_means(
        avg, cfa, thresh, imatest_block_size // scale
    )
    luma = compute_imatest_luma_metrics(
        luma_bin_means, cfa, orig_w, orig_h, full_scale,
        imatest_block_size, corner_region_pct, y_pixels,
        file_label=file_label,
    )
    luma["contour_levels"] = contour_levels  # 供结果界面绘制等高线

    # Color Shading：Bayer 拆分的 R/G、B/G（线性域，无去马赛克/gamma）
    color = compute_imatest_color_metrics(
        luma_bin_means, cfa, orig_w, orig_h,
        imatest_block_size, corner_region_pct,
        file_label=file_label,
        contour_step=float(params.get("color_contour_step", 0.05)),
        alpha=float(params.get("color_alpha", 4.0)),
        gamma=float(params.get("gamma", 1.0)),
    )
    return {"luma": luma, "color": color}


def recompute_single(
    result: dict,
    *,
    support_extrapolation: bool,
    enable_lsc_verify: bool,
    luminance_channel: str = REPORT_CHANNEL,
) -> dict:
    """按结果界面的 RBF / LSC / 亮度通道选择，重算单光源 result 的报告与闭环。

    主 metrics/pass 由未校正原始图决定，RBF/LSC/亮度通道不改变判定；本函数仅更新
    report（热力图/四象限展示）、shading_profile（RBF 相关）与 closed_loop（LSC 相关）。

    Args:
        result: analyze_shading(单光源) 返回的 result，需含 details.avg / details.alg_config。
        support_extrapolation: 是否 RBF 外插（重建 shading_profile）。
        enable_lsc_verify: 是否计算/展示 LSC 闭环验证。
        luminance_channel: 报告通道 Y/G/Gr（仅影响报告展示）。

    Raises:
        ValueError: 若缺失重算所需数据（非 single 分支或旧结果）。
    """
    details = result.get("details") or {}
    avg = details.get("avg")
    cfg = details.get("alg_config")
    if avg is None or cfg is None:
        raise ValueError(
            "当前结果不支持即时重算（可能为多光源对比，或缺少原始数据），"
            "请在配置后再分析一次。"
        )
    cfg = dict(cfg)
    cfg["support_extrapolation"] = support_extrapolation
    single = analyze_relative_illumination(avg, cfg)

    cfa = list(cfg["cfa"])
    scale = 2 if len(cfa) == 4 else 1
    corner_region_pct = float(details.get("corner_region_pct", 0.05))
    orig_h, orig_w = avg.shape[0] * scale, avg.shape[1] * scale
    report = _compute_report(single["details"]["bin_means"], cfa, luminance_channel)
    _attach_roi_boxes(report, orig_w, orig_h,
                      int(cfg["bin_size"]) * scale, corner_region_pct)
    closed_loop = None
    if enable_lsc_verify:
        closed_loop = _compute_closed_loop(
            result["metrics"], avg, single["details"]["shading_profile"], cfg,
            luminance_channel, corner_region_pct,
        )

    new_details = {
        **details,
        "report": report,
        "shading_profile": single["details"]["shading_profile"],
        "bin_means": single["details"]["bin_means"],
        "closed_loop": closed_loop,
        "luminance_channel": luminance_channel,
    }
    out = {
        **result,
        "details": new_details,
        "visualization": {
            **result.get("visualization", {}),
            "report": report,
            "closed_loop": closed_loop,
        },
    }
    return out


def analyze_shading(images: list, config: dict) -> dict:
    """Lens Shading 分析入口（runner 约定签名：fn(images, config) -> dict）。

    子功能由 config["params"]["test_item"] 决定：
      - "single"（默认）：单光源 Shading，所有图像合并做多帧平均，不绑定具体光源类型；
      - "multi_light"：多光源对比，按 params["image_lights"] 分组，要求 ≥2 个不同光源。
    """
    if not images:
        raise ValueError("请先在 ① Select Images 加载至少一张图像")

    params = config.get("params") or {}
    panel_criteria = config.get("criteria") or {}

    test_item = str(params.get("test_item", "single"))
    bin_size = int(params.get("grid_size", 16))
    thresh = float(params.get("thresh", 0.0))

    if bin_size < 1:
        raise ValueError(f"网格尺寸需 ≥ 1（当前 {bin_size}）")

    if test_item not in ("single", "multi_light"):
        raise ValueError(f"未知的 Lens Shading 子功能：{test_item!r}")

    criteria = _criteria_from_panel(panel_criteria)

    # ---- 图像 → 光源分组（多帧平均）
    image_lights = params.get("image_lights") or {}
    groups: OrderedDict[str, list[Path]] = OrderedDict()
    if test_item == "single":
        # 单光源：忽略 image_lights 的多光源分配，全部归入单一标签组（不绑定具体光源）
        for p in images:
            groups.setdefault(SINGLE_LIGHT_LABEL, []).append(Path(p))
    else:
        for p in images:
            p = Path(p)
            groups.setdefault(image_lights.get(p.name, DEFAULT_LIGHT_SOURCE), []).append(p)
        distinct_lights = set(groups.keys())
        if len(distinct_lights) < 2:
            raise ValueError(
                "多光源对比子功能需要 ≥2 个不同光源；"
                f"当前仅 {len(distinct_lights)} 个（{sorted(distinct_lights)}），"
                "请在「图像 → 光源」表中为图像分配不同光源，或切换为「单光源 Shading」。"
            )

    light_images: dict[str, np.ndarray] = {}
    cfa_list: list[str] | None = None
    image_sizes: dict[str, list[int]] = {}
    for light, paths in groups.items():
        loaded = [load_shading_image(p, params) for p in paths]
        cfa_lists = [cfa for _, cfa in loaded]
        if len({tuple(c) for c in cfa_lists}) > 1:
            raise ValueError(
                f"光源 {light} 内混用了 Bayer 与 mono 图像，无法一起分析"
            )
        this_cfa = cfa_lists[0]
        if cfa_list is None:
            cfa_list = this_cfa
        elif this_cfa != cfa_list:
            raise ValueError("不同光源的 CFA pattern 不一致，无法多光源对比")
        arrs = [im for im, _ in loaded]
        shapes = {a.shape for a in arrs}
        if len(shapes) > 1:
            raise ValueError(
                f"光源 {light} 内图像尺寸不一致（{sorted(str(s) for s in shapes)}），"
                "无法多帧平均"
            )
        avg = np.mean(np.stack(arrs), axis=0) if len(arrs) > 1 else arrs[0]
        light_images[light] = avg
        for p, a in zip(paths, arrs):
            image_sizes[p.name] = [int(a.shape[1]), int(a.shape[0])]

    assert cfa_list is not None
    channels = list(cfa_list)

    alg_config: dict = {
        "cfa": cfa_list,
        "bin_size": bin_size,
        "thresh": thresh,
        # 初始生成 profile 默认不 RBF 外插；RBF 由结果界面组件选择后经 recompute_single 重算
        "support_extrapolation": False,
    }
    if criteria:
        alg_config["criteria"] = criteria

    mode = "single" if test_item == "single" else "multi"

    common = {
        "mode": mode,
        "cfa": channels,
        "channels": channels,
        "bin_size": bin_size,
        "thresh": thresh,
        "criteria": criteria,
        "image_sizes": image_sizes,
        "image_lights": {name: image_lights.get(name, DEFAULT_LIGHT_SOURCE)
                         for name in image_sizes},
    }

    if mode == "single":
        light_name, avg = next(iter(light_images.items()))
        single = analyze_relative_illumination(avg, alg_config)
        corner_region_pct = float(params.get("corner_region_pct", 0.05))
        report = _compute_report(
            single["details"]["bin_means"], cfa_list, REPORT_CHANNEL
        )
        scale = 2 if len(cfa_list) == 4 else 1
        _attach_roi_boxes(
            report, avg.shape[1] * scale, avg.shape[0] * scale,
            bin_size * scale, corner_region_pct,
        )
        per_channel_ri = _extract_per_channel_ri(single["metrics"], cfa_list)
        # LSC 闭环验证默认关闭；结果界面勾选「使用 LSC」后经 recompute_single 计算
        closed_loop = None
        imatest = None
        file_label = groups[light_name][0].name if groups.get(light_name) else ""
        if params.get("imatest_report", True):
            imatest = _compute_imatest(avg, cfa_list, params, file_label=file_label)
        details = {
            **common,
            "light_source": light_name,
            "lights": {light_name: single},
            "comparison": None,
            "report": report,
            "per_channel_ri": per_channel_ri,
            "shading_profile": single["details"]["shading_profile"],
            "bin_means": single["details"]["bin_means"],
            "closed_loop": closed_loop,
            "imatest": imatest,
            # 供结果界面重算（RBF/LSC/亮度通道）使用：原始平均图 + 算法配置
            "avg": avg,
            "alg_config": dict(alg_config),
            "luminance_channel": REPORT_CHANNEL,
            "corner_region_pct": corner_region_pct,
            # 测试图片文件名：结果界面各图标题第二行显示
            "file_label": file_label,
            # 校正前原始 RAW 图（Bayer 经 demosaic 的彩色图；mono 为灰度），
            # 下拉列表与 LSC 校正后图片逐像素对照
            "source_image": _display_image(avg, cfa=cfa_list),
        }
        return {
            "metrics": single["metrics"],
            "pass": bool(single["pass"]),
            "details": details,
            "visualization": {
                "mode": mode,
                "report": report,
                "per_channel_ri": per_channel_ri,
                "closed_loop": closed_loop,
                "imatest": imatest,
            },
        }

    multi = analyze_multi_light(light_images, alg_config)
    comparison = dict(multi["comparison"])
    comparison["color_shift_spread"] = _compute_color_shift_spread(multi["lights"])
    details = {
        **common,
        "light_source": "、".join(light_images.keys()),
        "lights": multi["lights"],
        "comparison": comparison,
        "report": None,
        "per_channel_ri": None,
        "shading_profile": None,
        "bin_means": None,
        "closed_loop": None,
    }
    return {
        "metrics": {},
        "pass": bool(multi["pass"]),
        "details": details,
        "visualization": {"mode": mode, "comparison": comparison},
    }
