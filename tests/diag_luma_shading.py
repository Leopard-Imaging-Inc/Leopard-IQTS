"""
Luma Shading 结果诊断脚本。

用途：当「四象限 RI」tab 的数值异常（如四角 RI 偏低、ri_diff 异常大/小）时，
输出 shading_map 的归一化基准（全局最大值落在哪）、四角分布、原图像素统计与
LSC 闭环（RBF 开/关）对比，用于判断根因是：
  (a) 图中存在孤立高亮热点/过曝块，垄断 nanmax，把整幅 shading_map 压矮；
  (b) 图本身四角极暗（真实暗角），基准正常但四角 RI 本来就低；
  (c) bin 网格 / NaN 采样问题。

用法：
    python tests/diag_luma_shading.py <图像路径> [--cfa RGGB] [--width 4032]
        [--height 3024] [--bit 16] [--bin 16] [--thresh 0]

说明：.raw 文件未给 --cfa/--width/--height/--bit 时，读取软件已保存的
Read Raw 设置；常见格式（png/jpg 等）按 mono 灰度加载。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iqtest.analysis.shading_adapter import (  # noqa: E402
    analyze_shading,
    load_shading_image,
    recompute_single,
)
from iqtest.config.read_raw_settings import get_read_raw_params  # noqa: E402
from leopardiq.utils.image_preprocess import bayer_to_luminance  # noqa: E402

PRINT_WIDTH = 66


def section(title: str) -> None:
    print("\n" + "#" * PRINT_WIDTH)
    print(title)
    print("#" * PRINT_WIDTH)


def block_stats(y0: int, y1: int, x0: int, x1: int, arr2d: np.ndarray, label: str,
                h: int, w: int) -> None:
    a = arr2d[y0:y1, x0:x1]
    if a.size == 0:
        print(f"  {label}: 空区域")
        return
    print(f"  {label}  [{y0}:{y1}, {x0}:{x1}]  mean={np.nanmean(a):10.4f} "
          f"min={np.nanmin(a):10.4f} max={np.nanmax(a):10.4f}")


def quadrant_band(sm: np.ndarray) -> None:
    """四象限：整象限 min + 最外 1/4 条带 min（区分“全象限暗” vs “仅最外圈暗”）。"""
    h, w = sm.shape
    hh, hw = h // 2, w // 2
    bands = {
        "TL": (sm[0:hh, 0:hw], sm[: max(1, hh // 4), :hw]),
        "TR": (sm[0:hh, hw:], sm[: max(1, hh // 4), hw:]),
        "BL": (sm[hh:, 0:hw], sm[max(hh - hh // 4, 0):, :hw]),
        "BR": (sm[hh:, hw:], sm[max(hh - hh // 4, 0):, hw:]),
    }
    print(f"  象限(min)           外层 {hh//4} 行条带(min)")
    for name, (q, band) in bands.items():
        print(f"  {name:<8} {np.nanmin(q):10.4f}    "
              f"    {np.nanmin(band):10.4f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Luma Shading 结果诊断")
    ap.add_argument("image", help="图像路径（.raw 走 Read Raw 参数，常见格式按 mono）")
    ap.add_argument("--cfa", default=None, help="Bayer pattern（RGGB/BGGR/GRBG/GBRG/Y）")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--height", type=int, default=None)
    ap.add_argument("--bit", default=None, help="RAW 位深，如 16")
    ap.add_argument("--bin", type=int, default=16, help="bin_size（默认 16）")
    ap.add_argument("--thresh", type=float, default=0.0)
    args = ap.parse_args()

    img_path = Path(args.image)
    if not img_path.exists():
        print(f"图像不存在：{img_path}")
        sys.exit(1)

    ext = img_path.suffix.lower()
    cfg_params = {"test_item": "single", "grid_size": args.bin, "thresh": args.thresh}
    if ext == ".raw":
        saved = get_read_raw_params()
        cfg_params.update({
            "raw_width": args.width if args.width is not None else saved["width"],
            "raw_height": args.height if args.height is not None else saved["height"],
            "bit_depth": args.bit if args.bit is not None else saved["bit_depth"],
            "cfa": args.cfa if args.cfa is not None else saved["cfa"],
            "header_bytes": saved.get("header_bytes", 0),
            "black_level": saved.get("black_level", 0.0),
        })
    config = {"params": cfg_params}

    print(f"图像：{img_path}")
    print(f"config.params：{cfg_params}")

    # ---------- 1. 加载信息 ----------
    section("[1] 加载")
    arr, cfa = load_shading_image(str(img_path), cfg_params)
    print(f"  拆分后 shape={arr.shape}  cfa={cfa}")
    mono = arr.ndim == 2
    if mono:
        ypx = np.asarray(arr, dtype=np.float64)
    else:
        ypx = bayer_to_luminance(arr, cfa)
    print(f"  Y 像素图（BT.709 合成）shape={ypx.shape}")

    # ---------- 2. 主分析报告 ----------
    section("[2] 主分析四象限 RI（recompute 前默认 Y 报告）")
    result = analyze_shading([str(img_path)], config)
    report = result["details"]["report"]
    ri = report["ri"]
    print(f"  TL={ri['tl']:.4f}  TR={ri['tr']:.4f}  BL={ri['bl']:.4f}  "
          f"BR={ri['br']:.4f}  ri_diff={report['ri_diff']:.4f}")
    sm = np.asarray(report["shading_map"], dtype=np.float64)
    print(f"  shading_map 网格 {sm.shape[0]}x{sm.shape[1]}（每个网格 = 1 个 bin）")

    # ---------- 3. shading_map 归一化基准 ----------
    section("[3] shading_map 归一化基准（= bin_means / 全局单点 max）")
    mx = float(np.nanmax(sm))
    idx = np.unravel_index(np.nanargmax(sm), sm.shape)
    print(f"  shading_map max = {mx:.4f}  @ 网格坐标 {idx}（max 应=1）")
    y, x = idx
    h_g, w_g = sm.shape
    # max 网格 3x3 邻域均值
    ys = slice(max(y - 1, 0), min(y + 2, h_g))
    xs = slice(max(x - 1, 0), min(x + 2, w_g))
    nb = sm[ys, xs]
    print(f"  max 邻域 3x3 均值 = {np.nanmean(nb):.4f}（若远小于 1 → 孤立亮点/热点）")

    per = np.nanpercentile(sm, [50, 90, 99, 99.9])
    print(f"  shading_map 分位 50%={per[0]:.4f} 90%={per[1]:.4f} 99%={per[2]:.4f} "
          f"99.9%={per[3]:.4f}")
    print(f"  低占比  <0.7:{np.nanmean(sm < 0.7) * 100:.1f}%  "
          f"<0.5:{np.nanmean(sm < 0.5) * 100:.1f}%  "
          f"<0.1:{np.nanmean(sm < 0.1) * 100:.1f}%")
    print("  四象限（整象限 min / 最外条带 min，bin 网格）：")
    quadrant_band(sm)

    # ---------- 4. 原图像素级统计（Y 合成） ----------
    section("[4] 原图像素级 Y 统计（hotspot 在像素正中会在此现形）")
    h, w = ypx.shape
    ypx_max = float(np.nanmax(ypx))
    py, px = np.unravel_index(np.nanargmax(ypx), ypx.shape)
    print(f"  Y 像素全局 max = {ypx_max:.0f}（16bit 极限 65535）")
    print(f"  全局 max 像素位置 = ({py}, {px})  图像中心 = ({h // 2}, {w // 2})")
    blk = max(8, min(h, w) // 20)
    # 中心块与二值分布（若中心也有亮块但不是全局 max，说明 max 在别处）
    block_stats(h // 2 - blk, h // 2 + blk, w // 2 - blk, w // 2 + blk, ypx,
                "中心块", h, w)
    block_stats(0, blk, 0, blk, ypx, "左上角块", h, w)
    block_stats(0, blk, w - blk, w, ypx, "右上角块", h, w)
    block_stats(h - blk, h, 0, blk, ypx, "左下角块", h, w)
    block_stats(h - blk, h, w - blk, w, ypx, "右下角块", h, w)
    # 中心块与全部像素 max 的关系
    c_region = ypx[h // 2 - blk:h // 2 + blk, w // 2 - blk:w // 2 + blk]
    c_max = float(np.nanmax(c_region))
    where = "在中心块内" if c_max >= ypx_max else "不在中心块内（热点可能在别处）"
    print(f"  中心块局部 max = {c_max:.0f}  全局 max = {ypx_max:.0f}  → 全局 max {where}")

    # ---------- 5. LSC 闭环（RBF 开/关） ----------
    section("[5] LSC 闭环：RBF 关 vs 开（校正后 Y 报告四象限）")
    for rbf in (False, True):
        r = recompute_single(result, support_extrapolation=rbf,
                             enable_lsc_verify=True, luminance_channel="Y")
        cl = r["details"]["closed_loop"]
        ar = cl.get("after_report") or {}
        ari = ar.get("ri") or {}
        print(f"  RBF={'开' if rbf else '关'}  校正前Y ri_diff={cl['before_ri_diff']:.4f}  "
              f"校正后Y ri_diff={cl['after_report'].get('ri_diff', float('nan')):.4f}  "
              f"after_ri_min={cl['after_ri_min']:.4f}  残余判定={'PASS' if cl.get('residual_pass') else 'FAIL'}")
        if ari:
            print(f"      校正后四象限  TL={ari.get('tl', float('nan')):.4f} "
                  f"TR={ari.get('tr', float('nan')):.4f} "
                  f"BL={ari.get('bl', float('nan')):.4f} "
                  f"BR={ari.get('br', float('nan')):.4f}")

    print("\n诊断完成。")


if __name__ == "__main__":
    main()