"""
M3.3 验证测试：MTF/SFR Secondary Readout 读数类型（MTF @ nn / MTFnn / MTFnnP）。

测试内容：
[1/4] compute_mtf_metrics 泛化：mtfNN / mtfNNp 任意百分比（含旧名兼容）
[2/4] 指标名校验：nn 越界 / 非法名称 → 明确报错
[3/4] 适配器端到端：MTFnn / MTFnnP 配置、默认兼容 MTF30、nn=50 不覆盖判定
[4/4] 面板 schema：新参数默认值与 config 往返

运行：
    D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m3_3.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path

# 测试与用户保存的 Read Raw 全局设置隔离（~/.leopardiqlts），保证结果可复现
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from test_m3_1 import make_mono_chart_file, top_edge_rois  # noqa: E402

PASS_COUNT = 0
FAIL_COUNT = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def _run(config, path):
    from iqtest.analysis.mtf_adapter import analyze_mtf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return analyze_mtf([path], config)


# ----------------------------------------------------------------------
# [1/4] compute_mtf_metrics 泛化
# ----------------------------------------------------------------------
def test_metrics_generalization():
    print("[1/4] compute_mtf_metrics 泛化（mtfNN / mtfNNp）")
    from leopardiq.mtf import compute_mtf_metrics

    # 线性下降曲线：mtf = 1 - 0.8f → MTFnn 处频率 = (1 - nn/100) / 0.8
    freq = np.linspace(0.0, 1.0, 501)
    mtf = 1.0 - 0.8 * freq
    curve = np.column_stack([freq, mtf])
    m = compute_mtf_metrics(curve, ("mtf50", "mtf30", "mtf70", "mtf12"))
    check("mtf50 = 0.625", abs(m["mtf50"] - 0.625) < 2e-3, f"{m['mtf50']:.4f}")
    check("mtf30 = 0.875", abs(m["mtf30"] - 0.875) < 2e-3, f"{m['mtf30']:.4f}")
    check("mtf70 = 0.375", abs(m["mtf70"] - 0.375) < 2e-3, f"{m['mtf70']:.4f}")
    check("mtf12 = 1.1（超量程 → 0.0）", m["mtf12"] == 0.0, f"{m['mtf12']:.4f}")

    # 单调曲线峰值=低频值 → MTFnnP 与 MTFnn 一致
    mp = compute_mtf_metrics(curve, ("mtf50p", "mtf30p"))
    check("单调曲线 mtf50p == mtf50", abs(mp["mtf50p"] - m["mtf50"]) < 1e-6)
    check("单调曲线 mtf30p == mtf30", abs(mp["mtf30p"] - m["mtf30"]) < 1e-6)

    # 过锐化曲线：峰值 1.25 在 f=0.2 → MTFnnP 阈值按峰值归一化
    freq2 = np.linspace(0.0, 1.0, 11)
    mtf2 = np.array([1.0, 1.1, 1.25, 1.1, 0.9, 0.7, 0.5, 0.35, 0.2, 0.1, 0.05])
    curve2 = np.column_stack([freq2, mtf2])
    m2 = compute_mtf_metrics(curve2, ("mtf50", "mtf50p", "mtf30p"))
    check("过锐化 mtf50 = 0.6（绝对 0.5）", abs(m2["mtf50"] - 0.6) < 1e-6,
          f"{m2['mtf50']:.4f}")
    # mtf50p：阈值 1.25×0.5=0.625，f=0.5(0.7) 与 0.6(0.5) 间插值 → 0.5375
    check("过锐化 mtf50p = 0.5375（峰值归一化）",
          abs(m2["mtf50p"] - 0.5375) < 1e-6, f"{m2['mtf50p']:.4f}")
    # mtf30p：阈值 1.25×0.3=0.375，f=0.6(0.5) 与 0.7(0.35) 间插值 → 0.6833
    check("过锐化 mtf30p = 0.6833", abs(m2["mtf30p"] - 0.683333) < 1e-3,
          f"{m2['mtf30p']:.4f}")


# ----------------------------------------------------------------------
# [2/4] 指标名校验
# ----------------------------------------------------------------------
def test_metrics_validation():
    print("[2/4] 指标名校验")
    from leopardiq.mtf import compute_mtf_metrics

    freq = np.linspace(0.0, 1.0, 101)
    curve = np.column_stack([freq, 1.0 - 0.8 * freq])
    for bad, kw in (("mtf0", "(0, 100)"), ("mtf100", "(0, 100)"),
                    ("mtfabc", "Unknown"), ("mtf50pp", "Unknown")):
        try:
            compute_mtf_metrics(curve, (bad,))
        except ValueError as e:
            check(f"{bad!r} → ValueError", kw in str(e), str(e)[:32])
        else:
            check(f"{bad!r} → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [3/4] 适配器端到端
# ----------------------------------------------------------------------
def test_adapter_readouts():
    print("[3/4] 适配器：MTFnn / MTFnnP 端到端（双槽位）")
    path = make_mono_chart_file()
    rois = [{"image": path.name, "rect": r} for r in top_edge_rois()[:1]]

    def cfg(**params):
        p = {"cfa": "Y", "freq1": 0.125, "rois": rois}
        p.update(params)
        return {"params": p, "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0}}

    # 默认（向后兼容）：槽位1 MTF30、槽位2 MTF50P
    base = _run(cfg(), path)
    check("默认 readouts 为 MTF30 + MTF50P",
          [r["key"] for r in base["details"]["readouts"]] == ["mtf30", "mtf50p"]
          and [r["label"] for r in base["details"]["readouts"]]
          == ["MTF30", "MTF50P"])
    check("默认 metrics 含 ROI1_mtf30 / ROI1_mtf50p (INFO)",
          base["metrics"]["ROI1_mtf30"]["status"] == "INFO"
          and base["metrics"]["ROI1_mtf50p"]["status"] == "INFO")
    check("曲线携带 readouts 值",
          len(base["details"]["curves"][0]["readouts"]) == 2)
    check("默认 readout1 值 == 旧 mtf30 口径（0, 0.6）",
          0 < base["details"]["curves"][0]["readouts"][0] < 0.6)

    # MTF @ 评估频率参与判定
    check("MTF@ 评估频率键参与判定",
          base["metrics"]["ROI1_mtf@0.125"]["status"] == "PASS")

    # 槽位1 MTFnn 10
    r10 = _run(cfg(mtfnn1_type="MTFnn", mtfnn1_value=10), path)
    check("槽位1 MTFnn 10 → ROI1_mtf10",
          r10["metrics"]["ROI1_mtf10"]["status"] == "INFO"
          and r10["details"]["readouts"][0]["label"] == "MTF10")
    # MTF10 频率应高于 MTF50（MTF 越低对应频率越高）
    v50 = base["details"]["curves"][0]["mtf50"]
    v10 = r10["metrics"]["ROI1_mtf10"]["value"][0]
    check("MTF10 频率 > MTF50 频率", v10 > v50, f"{v10:.3f} > {v50:.3f}")

    # 槽位2 MTFnnP 20
    r20p = _run(cfg(mtfnn2_type="MTFnnP", mtfnn2_value=20), path)
    check("槽位2 MTFnnP 20 → ROI1_mtf20p",
          r20p["metrics"]["ROI1_mtf20p"]["status"] == "INFO"
          and r20p["details"]["readouts"][1]["label"] == "MTF20P")

    # 两槽位独立：MTFnn 10 + MTFnnP 20 同时存在
    rboth = _run(cfg(mtfnn1_type="MTFnn", mtfnn1_value=10,
                     mtfnn2_type="MTFnnP", mtfnn2_value=20), path)
    check("双槽位独立并存",
          "ROI1_mtf10" in rboth["metrics"]
          and "ROI1_mtf20p" in rboth["metrics"])

    # 两槽位相同读数 → 自动去重为单键
    rdup = _run(cfg(mtfnn1_type="MTFnn", mtfnn1_value=10,
                    mtfnn2_type="MTFnn", mtfnn2_value=10), path)
    check("重复读数自动去重",
          [r["key"] for r in rdup["details"]["readouts"]] == ["mtf10"])

    # nn=50：Readout1=MTF50，不新增 INFO 键；仍由 Readout1 判据判定
    r50 = _run(cfg(mtfnn1_type="MTFnn", mtfnn1_value=50,
                   mtfnn2_type="MTFnn", mtfnn2_value=50), path)
    check("nn=50 判定键仍为 ROI1_readout1",
          r50["metrics"]["ROI1_readout1"]["status"] in ("PASS", "FAIL"))

    # 非法配置
    for bad_params, kw in (
        ({"mtfnn1_value": 0}, "(0, 100)"),
        ({"mtfnn2_value": 100}, "(0, 100)"),
        ({"mtfnn1_type": "MTFArea"}, "类型"),
    ):
        try:
            _run(cfg(**bad_params), path)
        except ValueError as e:
            check(f"{bad_params} → ValueError", kw in str(e), str(e)[:36])
        else:
            check(f"{bad_params} → ValueError", False, "未抛出")


# ----------------------------------------------------------------------
# [4/4] 面板 schema
# ----------------------------------------------------------------------
def test_panel_schema():
    print("[4/4] 面板 schema 与 config 往返")
    from PySide6.QtWidgets import QApplication

    from iqtest.panels.mtf_panel import MtfPanel

    app = QApplication.instance() or QApplication([])
    del app

    defaults = MtfPanel.default_config()
    check("默认 params 含双 readout 槽位键",
          {"mtfnn1_type", "mtfnn1_value", "mtfnn2_type", "mtfnn2_value"}
          <= set(defaults["params"]))
    check("默认槽位1 MTFnn / 30%，槽位2 MTFnnP / 30%",
          defaults["params"]["mtfnn1_type"] == "MTFnn"
          and defaults["params"]["mtfnn1_value"] == 30.0
          and defaults["params"]["mtfnn2_type"] == "MTFnnP"
          and defaults["params"]["mtfnn2_value"] == 30.0)
    check("默认 params 不含 freq2", "freq2" not in defaults["params"])

    panel = MtfPanel(session=None)
    panel.params_form.set_values({"mtfnn1_type": "MTFnnP", "mtfnn1_value": 20.0,
                                  "mtfnn2_type": "MTFnn", "mtfnn2_value": 10.0})
    cfg = panel.config()
    check("config 存储双槽位配置",
          cfg["params"]["mtfnn1_type"] == "MTFnnP"
          and cfg["params"]["mtfnn1_value"] == 20.0
          and cfg["params"]["mtfnn2_type"] == "MTFnn"
          and cfg["params"]["mtfnn2_value"] == 10.0)

    panel2 = MtfPanel(session=None)
    panel2.set_config(cfg)
    check("set_config 往返一致",
          panel2.params_form.values()["mtfnn1_type"] == "MTFnnP"
          and panel2.params_form.values()["mtfnn1_value"] == 20.0
          and panel2.params_form.values()["mtfnn2_value"] == 10.0)


def main():
    print("=" * 60)
    print("M3.3 验证测试：Secondary Readout 读数类型")
    print("=" * 60)

    test_metrics_generalization()
    test_metrics_validation()
    test_adapter_readouts()
    test_panel_schema()

    print("=" * 60)
    print(f"结果：{PASS_COUNT} 通过, {FAIL_COUNT} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL_COUNT else 0)


if __name__ == "__main__":
    main()
