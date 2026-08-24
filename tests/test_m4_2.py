"""
M4.2 验证测试：MTF 模组比较核心（mtf_compare.py，纯函数无 GUI）。

设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md §2/§3.3/§3.4/§4。

测试内容：
[1/6] CSV 解析：类型化元数据 / 指标行 / 缺 schema_version 或口径字段报错 /
      未知 # 键忽略
[2/6] 口径校验与跨像元：freq_unit/freq1/gamma 不一致报错；LP/mm 导出归一化
      回 cy/px；跨像元 → LP/mm 展示；一侧缺像元尺寸报错
[3/6] 视场位置与 ROI 匹配：九宫格分区、摆位偏移仍按位置配对、同位置多 ROI
      按中心距排序、一侧多出的 ROI 排除
[4/6] 差异与胜负判定：已知差异方向、tie band 边界（含精确边界）、
      无效值排除计数
[5/6] 测试项交集与友好名：交集与列序、友好名（1/4 Nyquist 注解）、
      主判定项决定总体结论
[6/6] 评分与端到端：分区加权评分数值、缺区分权重归一化、评分 TIE；
      真实斜边 chart（B 加模糊 + ROI 坐标偏移模拟摆位差异）端到端比较

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m4_2.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_m4_1 as m4  # noqa: E402  复用合成标板与 CSV 导出链路

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = m4.OUT_DIR


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


# ----------------------------------------------------------------------
# 手工构造比较输入（解析后结构）
# ----------------------------------------------------------------------
def make_meta(**overrides):
    meta = {
        "label": "A", "created": "", "image": "img.raw",
        "image_width": 800, "image_height": 800,
        "freq_unit": "Cycles/pixel", "freq1": 0.125, "gamma": 1.0,
        "pixel_size_um": 2.0, "picture_height": 800,
    }
    meta.update(overrides)
    return meta


def make_row(roi, cx, cy, channel="Y", valid=True, **metrics):
    return {"roi": roi, "channel": channel, "cx": cx, "cy": cy,
            "valid": valid, "metrics": metrics}


def make_side(rows, metric_keys, **meta_overrides):
    return {"meta": make_meta(**meta_overrides), "rows": rows,
            "metric_keys": list(metric_keys)}


def five_zone_rows(mtf50_values, prefix=0):
    """5 个视场位置的行（center + 四角），mtf50 按序取值。"""
    positions = [(0.5, 0.5), (0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)]
    return [
        make_row(prefix + i + 1, cx, cy, mtf50=v)
        for i, ((cx, cy), v) in enumerate(zip(positions, mtf50_values))
    ]


# ----------------------------------------------------------------------
# [1/6] CSV 解析
# ----------------------------------------------------------------------
def test_parse():
    print("[1/6] CSV 解析")
    from iqtest.analysis.mtf_compare import load_result_csv, parse_result_csv
    from iqtest.analysis.mtf_export import result_to_csv, write_result_csv

    result, path = m4.run_analysis()
    text = result_to_csv(result, label="LensA")
    parsed = parse_result_csv(text)

    check("元数据类型化",
          parsed["meta"]["label"] == "LensA"
          and parsed["meta"]["freq1"] == 0.125
          and parsed["meta"]["gamma"] == 1.0
          and parsed["meta"]["image_width"] == 800
          and isinstance(parsed["meta"]["pixel_size_um"], float))
    check("指标列序保持", parsed["metric_keys"] == [
        "mtf@0.125", "mtf50", "mtf30", "mtf50p", "mtfa"])
    rows = parsed["rows"]
    check("5 行且数值类型化",
          len(rows) == 5 and rows[0]["roi"] == 1 and rows[0]["valid"]
          and isinstance(rows[0]["metrics"]["mtf50"], float)
          and isinstance(rows[0]["cx"], float))
    check("行数值与导出一致",
          abs(rows[0]["metrics"]["mtf50"]
              - result["details"]["curves"][0]["mtf50"]) <= 1e-6)

    out = OUT_DIR / "parse_roundtrip.csv"
    write_result_csv(result, out, label="RT")
    parsed2 = load_result_csv(out)
    check("load_result_csv（BOM）一致",
          parsed2["meta"]["label"] == "RT" and len(parsed2["rows"]) == 5)

    # 错误路径
    check("缺格式标识报错", _raises(parse_result_csv,
                                    text.replace("# LeopardIQ", "# XXX", 1)))
    check("缺 schema_version 报错", _raises(
        parse_result_csv, text.replace("# schema_version: 1\n", "")))
    check("缺 freq1 报错", _raises(
        parse_result_csv, text.replace("# freq1: 0.125\n", "")))
    check("未知 # 键静默忽略",
          parse_result_csv(text.replace("# created:", "# foo: bar\n# created:")
                           )["meta"]["label"] == "LensA")


def _raises(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return False
    except ValueError:
        return True


# ----------------------------------------------------------------------
# [2/6] 口径校验与跨像元
# ----------------------------------------------------------------------
def test_compatibility():
    print("[2/6] 口径校验与跨像元")
    from iqtest.analysis.mtf_compare import (
        available_metrics,
        check_compatibility,
        compare,
    )

    rows = five_zone_rows([0.3, 0.2, 0.2, 0.2, 0.2])
    a = make_side(rows, ["mtf50"], label="LA")
    b = make_side(five_zone_rows([0.29, 0.19, 0.19, 0.19, 0.19]),
                  ["mtf50"], label="LB")

    check_compatibility(a, b)
    check("同口径通过", True)
    check("freq_unit 不一致报错", _raises(
        check_compatibility, a, make_side(b["rows"], ["mtf50"],
                                          freq_unit="LP/mm")))
    check("freq1 不一致报错", _raises(
        check_compatibility, a, make_side(b["rows"], ["mtf50"],
                                          freq1=0.25)))
    check("gamma 不一致报错", _raises(
        check_compatibility, a, make_side(b["rows"], ["mtf50"], gamma=0.5)))
    check("指标交集为空报错", _raises(
        available_metrics, a, make_side(b["rows"], ["mtfa"])))
    check("未知频率单位报错", _raises(
        check_compatibility, a, make_side(b["rows"], ["mtf50"],
                                          freq_unit="LP/mm")))

    # LP/mm 导出 → 归一化回 cy/px：100 LP/mm @ 2µm/px = 0.2 cy/px
    a_lp = make_side(five_zone_rows([100.0, 60.0, 60.0, 60.0, 60.0]),
                     ["mtf50"], freq_unit="LP/mm", pixel_size_um=2.0)
    b_lp = make_side(five_zone_rows([100.0, 60.0, 60.0, 60.0, 60.0]),
                     ["mtf50"], freq_unit="LP/mm", pixel_size_um=2.0)
    res = compare(a_lp, b_lp, ["mtf50"])
    check("LP/mm 归一化回 cy/px",
          abs(res["pairs"][0]["values_a"]["mtf50"] - 0.2) <= 1e-9,
          f"got {res['pairs'][0]['values_a']['mtf50']}")
    check("同单位比较展示单位 = LP/mm",
          res["display_unit"] == "LP/mm" and not res["cross_pixel"])

    # 跨像元：2µm vs 4µm → cross_pixel，展示 LP/mm
    b_px = make_side(five_zone_rows([0.29, 0.19, 0.19, 0.19, 0.19]),
                     ["mtf50"], pixel_size_um=4.0)
    res2 = compare(a, b_px, ["mtf50"])
    check("跨像元标记 + LP/mm 展示",
          res2["cross_pixel"] and res2["display_unit"] == "LP/mm"
          and abs(res2["display_scale"] - 500.0) < 1e-9)
    res2_base = compare(a, b, ["mtf50"])
    st2, st2_base = res2["stats"]["mtf50"], res2_base["stats"]["mtf50"]
    check("跨像元判定口径不变（与同像素基准一致）",
          (st2["win"], st2["tie"], st2["loss"], st2["verdict"])
          == (st2_base["win"], st2_base["tie"], st2_base["loss"],
              st2_base["verdict"]),
          f"win/tie/loss = {st2['win']}/{st2['tie']}/{st2['loss']}")

    # 一侧缺像元尺寸且不一致 → 报错
    b_no_px = make_side(five_zone_rows([0.29] * 5), ["mtf50"],
                        pixel_size_um=0.0)
    check("一侧缺像元尺寸报错", _raises(compare, a, b_no_px, ["mtf50"]))


# ----------------------------------------------------------------------
# [3/6] 视场位置与 ROI 匹配
# ----------------------------------------------------------------------
def test_matching():
    print("[3/6] 视场位置与 ROI 匹配")
    from iqtest.analysis.mtf_compare import field_zone, match_rois, zone_group

    check("九宫格分区",
          field_zone(0.5, 0.5) == "center"
          and field_zone(0.1, 0.1) == "corner_tl"
          and field_zone(0.9, 0.1) == "corner_tr"
          and field_zone(0.1, 0.9) == "corner_bl"
          and field_zone(0.9, 0.9) == "corner_br"
          and field_zone(0.5, 0.1) == "top"
          and field_zone(0.5, 0.9) == "bottom"
          and field_zone(0.1, 0.5) == "left"
          and field_zone(0.9, 0.5) == "right")
    check("分区归组",
          zone_group("center") == "center"
          and zone_group("top") == "edge" and zone_group("left") == "edge"
          and zone_group("corner_tl") == "corner")

    # 摆位差异：B 坐标整体偏移 0.03，仍应按位置正确配对
    a_rows = five_zone_rows([0.3, 0.2, 0.21, 0.19, 0.2], prefix=0)
    b_rows = five_zone_rows([0.29, 0.19, 0.20, 0.18, 0.19], prefix=100)
    for r in b_rows:
        r["cx"] = min(0.99, r["cx"] + 0.03)
        r["cy"] = max(0.01, r["cy"] - 0.03)
    matched = match_rois(a_rows, b_rows)
    check("摆位偏移仍 5 对配对", len(matched["pairs"]) == 5)
    pair_map = {ra["roi"]: rb["roi"] for ra, rb, _ in matched["pairs"]}
    check("按位置配对正确（非坐标）",
          pair_map == {1: 101, 2: 102, 3: 103, 4: 104, 5: 105},
          str(pair_map))
    zones = sorted(z for _, _, z in matched["pairs"])
    check("配对位置 = 中心 + 四角",
          zones == ["center", "corner_bl", "corner_tl", "corner_tr",
                    "corner_br"] or set(zones) == {
              "center", "corner_tl", "corner_tr", "corner_bl", "corner_br"})

    # 同位置多 ROI：按到图像中心距离排序后依次配对
    a2 = [make_row(1, 0.10, 0.10, mtf50=0.2),   # corner_tl 远
          make_row(2, 0.30, 0.30, mtf50=0.25)]  # corner_tl 近（距中心更近）
    b2 = [make_row(11, 0.32, 0.32, mtf50=0.24),  # 近
          make_row(12, 0.12, 0.12, mtf50=0.19)]  # 远
    m2 = match_rois(a2, b2)
    pm = {ra["roi"]: rb["roi"] for ra, rb, _ in m2["pairs"]}
    check("同位置多 ROI 按中心距排序配对", pm == {2: 11, 1: 12}, str(pm))

    # 一侧多出的 ROI 排除；缺坐标的行列入 only
    a3 = a_rows + [make_row(9, 0.5, 0.1, mtf50=0.22)]        # A 多 top
    b3 = b_rows + [make_row(109, None, None, mtf50=0.2)]     # B 缺坐标
    m3 = match_rois(a3, b3)
    check("仅 A 的 ROI 进入 only_a",
          len(m3["only_a"]) == 1 and m3["only_a"][0]["roi"] == 9)
    check("缺坐标行进入 only_b",
          len(m3["only_b"]) == 1 and m3["only_b"][0]["roi"] == 109)
    check("多余 ROI 不影响正常配对", len(m3["pairs"]) == 5)


# ----------------------------------------------------------------------
# [4/6] 差异与胜负判定
# ----------------------------------------------------------------------
def test_win_loss():
    print("[4/6] 差异与胜负判定（tie band 边界）")
    from iqtest.analysis.mtf_compare import compare

    # B 全体低 0.02（> 默认 tie 0.01）→ A 全胜
    a = make_side(five_zone_rows([0.30, 0.20, 0.21, 0.19, 0.20]), ["mtf50"])
    b = make_side(five_zone_rows([0.28, 0.18, 0.19, 0.17, 0.18]), ["mtf50"])
    res = compare(a, b, ["mtf50"])
    st = res["stats"]["mtf50"]
    check("B 全体 -0.02 → A 胜 5",
          st["win"] == 5 and st["tie"] == 0 and st["loss"] == 0)
    deltas = [p["delta"]["mtf50"] for p in res["pairs"]]
    check("Δ 数值正确", all(abs(d - 0.02) < 1e-9 for d in deltas),
          f"{deltas[0]:.6f}")

    # tie band 精确边界（用二进制定点数避免浮点误差）：1/128 = 0.0078125
    tie = 1 / 128
    a2 = make_side([make_row(1, 0.5, 0.5, mtf50=33 / 128)], ["mtf50"])
    b2 = make_side([make_row(1, 0.5, 0.5, mtf50=32 / 128)], ["mtf50"])
    r2 = compare(a2, b2, ["mtf50"], tie_freq=tie)["stats"]["mtf50"]
    check("|Δ| == tie → 平手", r2["tie"] == 1 and r2["win"] == 0)
    a3 = make_side([make_row(1, 0.5, 0.5, mtf50=33 / 128 + 1 / 1024)],
                   ["mtf50"])
    r3 = compare(a3, b2, ["mtf50"], tie_freq=tie)["stats"]["mtf50"]
    check("|Δ| 略超 tie → A 胜", r3["win"] == 1)
    a4 = make_side([make_row(1, 0.5, 0.5, mtf50=33 / 128 - 1 / 1024)],
                   ["mtf50"])
    r4 = compare(a4, b2, ["mtf50"], tie_freq=tie)["stats"]["mtf50"]
    check("|Δ| 略低于 tie → 平手", r4["tie"] == 1)

    # 无效 ROI / 缺值 → excluded 不计胜负
    a5 = make_side(five_zone_rows([0.30, 0.20, 0.21, 0.19, 0.20]),
                   ["mtf50", "mtf@0.125"])
    b5_rows = five_zone_rows([0.28, 0.18, 0.19, 0.17, 0.18])
    b5_rows[2]["valid"] = False
    b5_rows[2]["metrics"]["mtf50"] = None
    b5 = make_side(b5_rows, ["mtf50", "mtf@0.125"])
    st5 = compare(a5, b5, ["mtf50"])["stats"]["mtf50"]
    check("无效 ROI 排除计数", st5["excluded"] == 1 and st5["win"] == 4)

    # SFR 类用 tie_sfr
    a6 = make_side([make_row(1, 0.5, 0.5, **{"mtf@0.125": 0.40})],
                   ["mtf@0.125"])
    b6 = make_side([make_row(1, 0.5, 0.5, **{"mtf@0.125": 0.395})],
                   ["mtf@0.125"])
    st6 = compare(a6, b6, ["mtf@0.125"])["stats"]["mtf@0.125"]
    check("SFR 类走 tie_sfr（0.005 差 → 平）", st6["tie"] == 1)


# ----------------------------------------------------------------------
# [5/6] 测试项交集与友好名
# ----------------------------------------------------------------------
def test_metric_selection():
    print("[5/6] 测试项交集与友好名")
    from iqtest.analysis.mtf_compare import (
        available_metrics,
        compare,
        metric_label,
    )

    check("友好名：MTF@（含 1/4 Nyquist 注解）",
          metric_label("mtf@0.125", "Cycles/pixel")
          == "MTF @ 0.125 cy/px (1/4 Nyquist)",
          metric_label("mtf@0.125", "Cycles/pixel"))
    check("友好名：MTF50 / MTF30 / MTF50P / MTFa",
          metric_label("mtf50", "Cycles/pixel") == "MTF50 (cy/px)"
          and metric_label("mtf30", "LP/mm") == "MTF30 (LP/mm)"
          and metric_label("mtf50p") == "MTF50P"
          and metric_label("mtfa") == "MTFa")

    keys = ["mtf@0.125", "mtf50", "mtf30", "mtfa"]
    a = make_side(five_zone_rows([0.3] * 5), keys)
    # B 缺 mtf30、多 mtf70p → 交集不含两者
    b = make_side(five_zone_rows([0.28] * 5),
                  ["mtf@0.125", "mtf50", "mtfa", "mtf70p"])
    avail = available_metrics(a, b)
    check("交集 = 共同列（保持 A 列序）",
          [m["key"] for m in avail] == ["mtf@0.125", "mtf50", "mtfa"])
    check("交集附带友好名与类型",
          avail[1]["label"].startswith("MTF50")
          and avail[1]["kind"] == "freq" and avail[0]["kind"] == "sfr")

    # 多测试项比较 + 主判定项
    b2_rows = five_zone_rows([0.28, 0.18, 0.18, 0.18, 0.18])
    for r in b2_rows:
        r["metrics"]["mtfa"] = 0.09
    a2_rows = five_zone_rows([0.30, 0.20, 0.20, 0.20, 0.20])
    for r in a2_rows:
        r["metrics"]["mtf50"] = r["metrics"].pop("mtf50")  # 保持
        r["metrics"]["mtfa"] = 0.10
    a2 = make_side(a2_rows, ["mtf50", "mtfa"])
    b2 = make_side(b2_rows, ["mtf50", "mtfa"])
    res = compare(a2, b2, ["mtf50", "mtfa"], main_metric="mtfa")
    check("多测试项各自统计",
          set(res["stats"]) == {"mtf50", "mtfa"})
    check("主判定项决定总体结论", res["main_verdict"] == "A"
          and res["main_metric"] == "mtfa")
    check("选中项之外的指标不参与",
          "mtf@0.125" not in res["stats"])
    check("选非交集项报错", _raises(compare, a, b, ["mtf30"]))
    check("主判定项须在所选项中",
          _raises(compare, a2, b2, ["mtf50"], main_metric="mtfa"))


# ----------------------------------------------------------------------
# [6/6] 评分与端到端
# ----------------------------------------------------------------------
def test_scoring_and_e2e():
    print("[6/6] 分区加权评分与端到端")
    from iqtest.analysis.mtf_compare import compare
    from iqtest.analysis.mtf_export import result_to_csv, write_result_csv

    # 手工评分：center A 0.4/B 0.3，corner A 0.2/B 0.18，无 edge
    # 归一化 ÷0.5 → A: 0.8/0.4，B: 0.6/0.36；权重 0.4/0.3 → 4/7、3/7
    a = make_side([make_row(1, 0.5, 0.5, mtf50=0.4),
                   make_row(2, 0.1, 0.1, mtf50=0.2)], ["mtf50"])
    b = make_side([make_row(1, 0.5, 0.5, mtf50=0.3),
                   make_row(2, 0.1, 0.1, mtf50=0.18)], ["mtf50"])
    st = compare(a, b, ["mtf50"])["stats"]["mtf50"]
    exp_a = 4 / 7 * 0.8 + 3 / 7 * 0.4
    exp_b = 4 / 7 * 0.6 + 3 / 7 * 0.36
    check("缺区分权重归一化 + 评分数值",
          abs(st["score_a"] - exp_a) < 1e-9
          and abs(st["score_b"] - exp_b) < 1e-9,
          f"score_a={st['score_a']:.6f} (exp {exp_a:.6f})")
    check("评分判定 A 优 + 主要贡献区域 = 中心",
          st["verdict"] == "A" and st["dominant_zone"] == "center")
    check("摘要文本含优胜方与区域",
          "更好" in st["summary"] and "中心" in st["summary"],
          st["summary"])

    # 评分 TIE
    same_a = make_side(five_zone_rows([0.3, 0.2, 0.2, 0.2, 0.2]), ["mtf50"])
    same_b = make_side(five_zone_rows([0.3, 0.2, 0.2, 0.2, 0.2]), ["mtf50"])
    st2 = compare(same_a, same_b, ["mtf50"])["stats"]["mtf50"]
    check("评分差 ≤ score_tie → 两者相当",
          st2["verdict"] == "TIE" and "相当" in st2["summary"])

    # 端到端：真实斜边 chart；B 加高斯模糊（模拟较差镜头）
    # + ROI 坐标偏移（模拟摆位差异）
    result_a, path_a = m4.run_analysis()
    blur_img = cv2.GaussianBlur(np.squeeze(m4.make_chart()), (9, 9), 3)
    path_b = OUT_DIR / "sfr_chart_m4_blur.png"
    cv2.imwrite(str(path_b), np.clip(blur_img, 0, 255).astype(np.uint8))
    rois_b = [[x + 6, y + 5, w, h] for x, y, w, h in m4.top_edge_rois()]

    from iqtest.analysis.mtf_adapter import analyze_mtf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result_b = analyze_mtf([str(path_b)], {
            "params": {"cfa": "Y", "freq1": 0.125,
                       "rois": [{"image": path_b.name, "rect": r}
                                for r in rois_b]},
            "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0},
        })
    csv_a = write_result_csv(result_a, OUT_DIR / "e2e_a.csv", label="清晰镜头")
    csv_b = write_result_csv(result_b, OUT_DIR / "e2e_b.csv", label="模糊镜头")

    from iqtest.analysis.mtf_compare import load_result_csv
    res = compare(load_result_csv(csv_a), load_result_csv(csv_b),
                  main_metric="mtf50")
    check("摆位差异下仍 5 对配对", len(res["pairs"]) == 5,
          f"pairs={len(res['pairs'])}")
    check("配对位置 = 中心 + 四角",
          {p["zone_group"] for p in res["pairs"]} == {"center", "corner"})
    check("模糊镜头 MTF50 全面更低（A 胜 5）",
          res["stats"]["mtf50"]["win"] == 5,
          str({k: res["stats"]["mtf50"][k] for k in ("win", "tie", "loss")}))
    check("MTFa 同样 A 胜 5", res["stats"]["mtfa"]["win"] == 5)
    check("总体结论 A 优", res["main_verdict"] == "A",
          res["main_summary"])
    check("结论摘要含 label",
          "清晰镜头" in res["main_summary"], res["main_summary"])
    check("导出文本含全部默认测试项统计",
          set(res["stats"]) >= {"mtf@0.125", "mtf50", "mtf30", "mtf50p",
                                "mtfa"})


def main():
    test_parse()
    test_compatibility()
    test_matching()
    test_win_loss()
    test_metric_selection()
    test_scoring_and_e2e()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
