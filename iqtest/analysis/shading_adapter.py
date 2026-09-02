"""Lens Shading 模块适配器：GUI（config dict + 图像路径）→ leopardiq.shading 算法接口。

职责（规划 §19 M3 + 开发文档 §6）：
  1. 图像加载：`.raw` 走 Generalized Read Raw（demosaic=False 取 mosaic，
     按全局 CFA 拆分为 4 通道）；常见格式（PNG/TIFF/…）按 mono 灰度读入；
  2. 面板参数 → 算法 config 映射（cfa / bin_size / thresh / support_extrapolation /
     criteria.ri / criteria.ri_diff / green_red_shift / green_blue_shift）；
  3. 多光源：按「图像 → 光源」分组，组内多帧平均，≥2 光源走 analyze_multi_light
     并在本层补算 color_shift_spread（§16.4，算法层零改动）；
  4. 报告通道（luminance_channel）：由 bin_means 派生 Y/G/Gr 单通道 shading 网格
     与四象限 RI，仅作展示，不改变算法判定口径；
  5. 闭环验证（§17.3）：单光源时 apply_lsc 后再测残余 shading。

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
from leopardiq.utils.raw_reader import RawReadConfig, read_raw

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
        return img.astype(np.float64), ["Y"]

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
    """Bayer 输入时从算法 metrics 提取逐通道四象限 RI（展示用）。"""
    if len(cfa) != 4:
        return None

    def vals(key: str) -> list[float]:
        value = (metrics.get(key) or {}).get("value", [])
        return [float(x) for x in np.atleast_1d(value)]

    return {
        "channels": list(cfa),
        "tl": vals("ri_tl"),
        "tr": vals("ri_tr"),
        "bl": vals("ri_bl"),
        "br": vals("ri_br"),
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


def _compute_closed_loop(before_metrics: dict, avg: np.ndarray,
                         profile: np.ndarray, alg_config: dict) -> dict:
    """apply_lsc 后残余 shading 再测（§17.3 闭环自检，单光源）。"""
    try:
        corrected = apply_lsc(avg, profile)
    except ValueError as exc:
        return {"enabled": False, "note": f"apply_lsc 不可用：{exc}"}
    after = analyze_relative_illumination(corrected, alg_config)
    return {
        "enabled": True,
        "before_ri_min": _ri_min(before_metrics),
        "after_ri_min": _ri_min(after["metrics"]),
        "before_ri_diff": float(before_metrics["ri_diff"]["value"]),
        "after_ri_diff": float(after["metrics"]["ri_diff"]["value"]),
        "before_green_red_shift": _shift_value(before_metrics, "green_red_shift"),
        "after_green_red_shift": _shift_value(after["metrics"], "green_red_shift"),
        "before_green_blue_shift": _shift_value(before_metrics, "green_blue_shift"),
        "after_green_blue_shift": _shift_value(after["metrics"], "green_blue_shift"),
        "residual_pass": bool(after["pass"]),
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


def analyze_shading(images: list, config: dict) -> dict:
    """Lens Shading 分析入口（runner 约定签名：fn(images, config) -> dict）。

    config["params"]["image_lights"] = {图像名: 光源}（缺省时全部归入 light_source）。
    """
    if not images:
        raise ValueError("请先在 ① Select Images 加载至少一张图像")

    params = config.get("params") or {}
    panel_criteria = config.get("criteria") or {}

    light_source = str(params.get("light_source", "D65"))
    luminance_channel = str(params.get("luminance_channel", "Y"))
    bin_size = int(params.get("grid_size", 16))
    thresh = float(params.get("thresh", 0.0))
    support_extrapolation = bool(params.get("support_extrapolation", False))
    enable_lsc_verify = bool(params.get("enable_lsc_verify", True))

    if bin_size < 1:
        raise ValueError(f"网格尺寸需 ≥ 1（当前 {bin_size}）")

    criteria = _criteria_from_panel(panel_criteria)

    # ---- 图像 → 光源分组（多帧平均）
    image_lights = params.get("image_lights") or {}
    groups: OrderedDict[str, list[Path]] = OrderedDict()
    for p in images:
        p = Path(p)
        groups.setdefault(image_lights.get(p.name, light_source), []).append(p)

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
        "support_extrapolation": support_extrapolation,
    }
    if criteria:
        alg_config["criteria"] = criteria

    mode = "single" if len(light_images) == 1 else "multi"

    common = {
        "mode": mode,
        "cfa": channels,
        "channels": channels,
        "bin_size": bin_size,
        "thresh": thresh,
        "support_extrapolation": support_extrapolation,
        "luminance_channel": luminance_channel,
        "criteria": criteria,
        "image_sizes": image_sizes,
        "image_lights": {name: image_lights.get(name, light_source)
                         for name in image_sizes},
    }

    if mode == "single":
        light_name, avg = next(iter(light_images.items()))
        single = analyze_relative_illumination(avg, alg_config)
        report = _compute_report(
            single["details"]["bin_means"], cfa_list, luminance_channel
        )
        per_channel_ri = _extract_per_channel_ri(single["metrics"], cfa_list)
        closed_loop = None
        if enable_lsc_verify:
            closed_loop = _compute_closed_loop(
                single["metrics"], avg, single["details"]["shading_profile"],
                alg_config,
            )
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
