"""
M4.5 验证测试：N 款镜头 MTF 比较（基准金样模式，N ≥ 2）。

设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md。

测试内容：
[1/3] 核心 multi：available_metrics_multi 交集 / check_compatibility_multi
      以首份为基准 / match_zones_multi 公共位置匹配（含缺位置补 0）/
      normalized_metric 的 LP/mm→cy/px 归一化
[2/3] 面板 3 款：动态添加槽位 c、配对表 5 列、结论「vs 基准」逐款分块、
      对比图 3 条折线、Δ 图同一张图内 2 组并排条形、切换基准重跑
[3/3] 多款保存：选目录逐款落盘 2 个 CSV、取消目录选择不写文件

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m4_5.py
"""

import os
import sys
import tempfile
import warnings
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_m4_1 as m4  # noqa: E402  复用合成标板
import test_m4_3 as m43  # noqa: E402  复用清晰/模糊 CSV 对与面板构建

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = m43.OUT_DIR

_CACHE: dict = {}


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def make_csv_third() -> Path:
    """C = 中度模糊镜头（性能介于清晰/模糊之间）。

    ROI 不加偏移：C 的五块 ROI 与 A 落在相同视场位置（B 的 +6/+5
    偏移已覆盖「摆位差异按位置配对」场景）。
    """
    if "third" in _CACHE:
        return _CACHE["third"]
    from iqtest.analysis.mtf_adapter import analyze_mtf
    from iqtest.analysis.mtf_export import write_result_csv

    blur_img = cv2.GaussianBlur(np.squeeze(m4.make_chart()), (7, 7), 2)
    path = OUT_DIR / "sfr_chart_m4_blur2.png"
    cv2.imwrite(str(path), np.clip(blur_img, 0, 255).astype(np.uint8))
    rois = [list(r) for r in m4.top_edge_rois()]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = analyze_mtf([str(path)], {
            "params": {"cfa": "Y", "freq1": 0.125,
                       "rois": [{"image": path.name, "rect": r}
                                for r in rois]},
            "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0},
        })
    csv_path = write_result_csv(
        result, OUT_DIR / "panel_c.csv", label="中度模糊镜头"
    )
    _CACHE["third"] = csv_path
    return csv_path


# ----------------------------------------------------------------------
def test_core_multi():
    print("[1/3] 核心 multi：交集 / 口径校验 / 多路匹配 / 归一化")
    from iqtest.analysis import mtf_compare

    csv_a, csv_b = m43.make_csv_pair()
    csv_c = make_csv_third()
    ds_a = mtf_compare.load_result_csv(csv_a)
    ds_b = mtf_compare.load_result_csv(csv_b)
    ds_c = mtf_compare.load_result_csv(csv_c)

    metrics = mtf_compare.available_metrics_multi([ds_a, ds_b, ds_c])
    check("多款测试项 = 3 份交集 5 项", len(metrics) == 5,
          str([m["key"] for m in metrics]))
    ds_c2 = dict(ds_c)
    ds_c2["metric_keys"] = [k for k in ds_c["metric_keys"] if k != "mtfa"]
    metrics2 = mtf_compare.available_metrics_multi([ds_a, ds_b, ds_c2])
    check("某份缺 mtfa 列 → 交集剔除该指标",
          len(metrics2) == 4
          and all(m["key"] != "mtfa" for m in metrics2))
    try:
        mtf_compare.available_metrics_multi([ds_a])
        ok = False
    except ValueError:
        ok = True
    check("单份 CSV → 报至少需要两份", ok)

    bad = OUT_DIR / "m45_bad_unit.csv"
    bad.write_text(
        Path(csv_b).read_text(encoding="utf-8-sig").replace(
            "# freq_unit: Cycles/pixel", "# freq_unit: LP/mm"),
        encoding="utf-8-sig",
    )
    ds_bad = mtf_compare.load_result_csv(bad)
    try:
        mtf_compare.check_compatibility_multi([ds_a, ds_bad, ds_c])
        ok = False
    except ValueError as exc:
        ok = "频率单位" in str(exc)
    check("多款口径校验以首份为基准（第二款不符即报错）", ok)

    matched = mtf_compare.match_zones_multi(
        [ds_a["rows"], ds_b["rows"], ds_c["rows"]])
    n_pairs = sum(len(v) for v in matched["groups"].values())
    check("3 镜头公共位置 = 5（中心 + 四角）",
          len(matched["keys"]) == 5 and n_pairs == 5,
          str(matched["keys"]))
    check("每组含 3 镜头行",
          all(len(t) == 3 for g in matched["groups"].values() for t in g))
    check("counts 每位置 [1, 1, 1]",
          all(v == [1, 1, 1] for v in matched["counts"].values()),
          str(matched["counts"]))

    rows_b_missing = [
        r for r in ds_b["rows"]
        if not (r["cx"] is not None and r["cx"] > 2 / 3
                and r["cy"] is not None and r["cy"] > 2 / 3)
    ]
    matched2 = mtf_compare.match_zones_multi(
        [ds_a["rows"], rows_b_missing, ds_c["rows"]])
    zones2 = {z for z, _ in matched2["keys"]}
    check("镜头 B 缺 corner_br → 公共位置排除它",
          "corner_br" not in zones2 and len(matched2["keys"]) == 4)
    check("counts 缺失位置补 0",
          matched2["counts"].get("corner_br") == [1, 0, 1],
          str(matched2["counts"].get("corner_br")))

    row = {"metrics": {"mtf50": 100.0}, "valid": True}
    meta = {"freq_unit": "LP/mm", "pixel_size_um": 2.0, "picture_height": 0}
    value = mtf_compare.normalized_metric(row, meta, "mtf50")
    check("normalized_metric：100 LP/mm @2µm/px = 0.2 cy/px",
          value is not None and abs(value - 0.2) < 1e-9, str(value))
    check("normalized_metric：无效行 → None",
          mtf_compare.normalized_metric(
              {"metrics": {"mtf50": 100.0}, "valid": False}, meta, "mtf50")
          is None)


# ----------------------------------------------------------------------
def test_panel_multi():
    print("[2/3] 面板 3 款：动态槽位 / 基准切换 / N 折线 + 分组 Δ")
    from PySide6.QtWidgets import (
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QTableWidget,
    )

    app, dlg = m43.make_dialog()
    csv_a, csv_b = m43.make_csv_pair()
    csv_c = make_csv_third()

    check("初始 2 槽位，移除按钮禁用",
          len(dlg._slots) == 2
          and not dlg.findChild(QPushButton, "remove_a").isEnabled())
    dlg.findChild(QPushButton, "addSlotBtn").click()
    check("添加槽位 c → 3 槽位",
          len(dlg._slots) == 3
          and dlg.findChild(QLineEdit, "path_c") is not None)

    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)
    dlg.load_csv("c", csv_c)
    status = dlg.findChild(QLabel, "compareStatus")
    check("状态含基准（金样）与口径、配对数",
          "基准（金样）" in status.text() and "清晰镜头" in status.text()
          and "配对 5 对" in status.text(), status.text())

    table = dlg.findChild(QTableWidget, "pairTable")
    check("配对表 5 列（位置 + 3 镜头 + 共同）", table.columnCount() == 5)
    center = [table.item(4, c).text() for c in range(1, 5)]
    check("配对预览中心行 1/1/1/1", center == ["1", "1", "1", "1"],
          str(center))

    emitted: list[dict] = []
    dlg.compared.connect(emitted.append)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()

    summary = dlg.findChild(QPlainTextEdit, "compareSummary").toPlainText()
    check("结论含基准行", "基准（金样）：清晰镜头" in summary,
          summary.splitlines()[0] if summary else "")
    check("结论按「vs 基准」逐款分块",
          "【模糊镜头 vs 基准】" in summary
          and "【中度模糊镜头 vs 基准】" in summary)
    check("compared 信号（首组 = 基准 vs 第 1 款非基准）",
          len(emitted) == 1 and emitted[0]["main_verdict"] == "A")
    check("_last_results = 2 组 pairwise 结果",
          len(dlg._last_results) == 2)

    curves = dlg._plot_compare.listDataItems()
    check("对比图 3 条折线（基准 + 2 款）", len(curves) == 3,
          str(len(curves)))
    ditems = dlg._plot_delta.getPlotItem().items
    bars = [it for it in ditems if it.__class__.__name__ == "BarGraphItem"]
    n_bars = sum(len(it.opts["height"]) for it in bars)
    check("Δ 图同一张图内 2 组条形共 10 根（每位置并排）",
          len(bars) == 2 and n_bars == 10, f"{len(bars)} 组 / {n_bars} 根")
    xs = sorted(float(x) for it in bars for x in it.opts["x"])
    check("两组条形围绕整数位置对称偏移 ±0.2",
          len(xs) == 10
          and all(abs(abs(x - round(x)) - 0.2) < 1e-6 for x in xs),
          str(xs[:4]))
    n_lines = sum(1 for it in ditems if it.__class__.__name__ == "InfiniteLine")
    check("Δ 图含 ±tie 参考线与零线（3 条）", n_lines == 3)

    # 切换基准到槽位 b（模糊镜头）→ 其余两款均优于基准（verdict = B）
    dlg.findChild(QRadioButton, "ref_b").setChecked(True)
    app.processEvents()
    check("切基准后状态更新为模糊镜头",
          "基准（金样）= 模糊镜头" in status.text(), status.text())
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    summary2 = dlg.findChild(QPlainTextEdit, "compareSummary").toPlainText()
    check("重新比较后基准变为模糊镜头",
          "基准（金样）：模糊镜头" in summary2
          and "【清晰镜头 vs 基准】" in summary2)
    check("新基准下两款均优于基准（verdict 全 B）",
          len(dlg._last_results) == 2
          and all(r["main_verdict"] == "B" for r in dlg._last_results))
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


# ----------------------------------------------------------------------
def test_multi_save():
    print("[3/3] 多款保存：目录选择逐款落盘 / 取消不留痕")
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

    app, dlg = m43.make_dialog()
    csv_a, csv_b = m43.make_csv_pair()
    csv_c = make_csv_third()
    dlg.findChild(QPushButton, "addSlotBtn").click()
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)
    dlg.load_csv("c", csv_c)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    check("比较后保存按钮启用",
          dlg.findChild(QPushButton, "saveCompareBtn").isEnabled())

    out = Path(tempfile.mkdtemp(prefix="lqiq_m45_save_"))
    with mock.patch.object(QFileDialog, "getExistingDirectory",
                           return_value=str(out)), \
         mock.patch.object(QMessageBox, "information", return_value=None):
        dlg.findChild(QPushButton, "saveCompareBtn").click()
        app.processEvents()
    files = sorted(out.glob("*.csv"))
    check("落盘 2 个 CSV（基准 vs 各款）", len(files) == 2,
          str([f.name for f in files]))
    names = {f.name for f in files}
    check("文件名 = MTF比较_基准_vs_各款",
          names == {"MTF比较_清晰镜头_vs_模糊镜头.csv",
                    "MTF比较_清晰镜头_vs_中度模糊镜头.csv"}, str(names))
    text = files[0].read_text(encoding="utf-8-sig") if files else ""
    check("CSV 含比较格式标识与基准 label",
          "# LeopardIQ MTF Compare Result CSV" in text
          and "# label_a: 清晰镜头" in text)

    with mock.patch.object(QFileDialog, "getExistingDirectory",
                           return_value=""), \
         mock.patch(
             "iqtest.panels.mtf_compare_panel.mtf_compare.write_compare_csv"
         ) as write_csv:
        dlg.findChild(QPushButton, "saveCompareBtn").click()
        app.processEvents()
    check("取消目录选择不写文件", not write_csv.called)
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def main():
    test_core_multi()
    test_panel_multi()
    test_multi_save()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
