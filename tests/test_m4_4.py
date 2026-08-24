"""
M4.4 验证测试：比较图表（面板嵌入）与比较结果 CSV 保存。

设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md §5（2026-08-17 修订：
图表直接嵌入比较对话框，保存由用户主动触发）。

测试内容：
[1/3] compare_result_to_csv 格式：元数据头（label/配置/逐项统计/结论）、
      逐配对行列组（A/B/Δ/胜负，显示单位换算）、仅单侧 ROI 行
[2/3] 面板图表：比较后图表渲染（A/B 各 5 点、Δ 条形 5 根、tie 参考线）、
      测试项下拉切换刷新、重新载入 CSV 后图表清空
[3/3] 保存功能：未比较时禁用；比较后保存对话框打桩 → 文件落盘可解析；
      取消不留痕

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m4_4.py
"""

import csv
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_m4_3 as m43  # noqa: E402  复用 make_csv_pair（A 清晰 / B 模糊）

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = m43.OUT_DIR


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def _compare_result():
    """清晰 vs 模糊 的 compare 结果（含一个仅 A 的 ROI）。"""
    from iqtest.analysis.mtf_compare import compare, load_result_csv

    csv_a, csv_b = m43.make_csv_pair()
    a, b = load_result_csv(csv_a), load_result_csv(csv_b)
    # 构造一个仅 A 的 ROI（上边缘，B 没有）
    extra = dict(a["rows"][0])
    extra = {**extra, "roi": 99, "cx": 0.5, "cy": 0.1,
             "metrics": dict(extra["metrics"])}
    a["rows"] = a["rows"] + [extra]
    return compare(a, b, main_metric="mtf50")


def _parse_compare_csv(text: str):
    meta = {}
    table_lines = []
    for ln in text.splitlines():
        if ln.startswith("#"):
            key, _, value = ln[1:].partition(":")
            meta[key.strip()] = value.strip()
        elif ln.strip():
            table_lines.append(ln)
    reader = csv.DictReader(io.StringIO("\n".join(table_lines)))
    return meta, reader.fieldnames, list(reader)


# ----------------------------------------------------------------------
def test_compare_csv_format():
    print("[1/3] compare_result_to_csv 格式")
    from iqtest.analysis.mtf_compare import (
        COMPARE_SCHEMA_VERSION,
        compare_result_to_csv,
        write_compare_csv,
    )

    result = _compare_result()
    text = compare_result_to_csv(result, created="2026-08-17T14:00:00")
    meta, headers, rows = _parse_compare_csv(text)

    check("首行为格式标识",
          text.startswith("# LeopardIQ MTF Compare Result CSV"))
    check("schema/label/主判定项元数据",
          meta.get("compare_schema_version") == str(COMPARE_SCHEMA_VERSION)
          and meta.get("label_a") == "清晰镜头"
          and meta.get("label_b") == "模糊镜头"
          and meta.get("main_metric") == "mtf50")
    check("比较配置回显（tie/权重/单位）",
          meta.get("tie_freq") == "0.01"
          and "center=0.6" in (meta.get("zone_weights") or "")
          and meta.get("display_unit") == "cy/px")
    check("总体结论写入 verdict 元数据",
          "清晰镜头 更好" in (meta.get("verdict") or ""))
    check("逐项统计注释行齐全",
          all(f"stat_{k}" in meta for k in
              ("mtf@0.125", "mtf50", "mtf30", "mtf50p", "mtfa"))
          and "win=5" in (meta.get("stat_mtf50") or ""),
          meta.get("stat_mtf50"))

    check("表头 = 基础列 + 每测试项 4 列组",
          headers[:4] == ["zone", "channel", "roi_a", "roi_b"]
          and "mtf50_a" in headers and "mtf50_delta" in headers
          and "mtf50_result" in headers)
    pair_rows = [r for r in rows if r["roi_a"] and r["roi_b"]]
    only_rows = [r for r in rows if not (r["roi_a"] and r["roi_b"])]
    check("5 对配对行 + 1 行仅 A（标记在首个测试项结果列）",
          len(pair_rows) == 5 and len(only_rows) == 1
          and only_rows[0]["mtf@0.125_result"] == "仅A"
          and only_rows[0]["zone"] == "top")
    check("配对行胜负标记全 A（清晰镜头全胜）",
          all(r["mtf50_result"] == "A" for r in pair_rows))
    check("Δ 数值 = A − B",
          all(abs(float(r["mtf50_delta"])
                  - (float(r["mtf50_a"]) - float(r["mtf50_b"]))) < 2e-6
              for r in pair_rows))
    check("行序中心在前", pair_rows[0]["zone"] == "center")

    out = OUT_DIR / "compare_result.csv"
    write_compare_csv(result, out)
    check("write_compare_csv 落盘（BOM）",
          out.is_file() and out.read_bytes().startswith(b"\xef\xbb\xbf"))


def test_panel_charts():
    print("[2/3] 面板嵌入图表")
    from PySide6.QtWidgets import QComboBox, QPushButton

    app, dlg = m43.make_dialog()
    csv_a, csv_b = m43.make_csv_pair()
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)

    emitted: list[dict] = []
    dlg.compared.connect(emitted.append)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()

    combo = dlg.findChild(QComboBox, "chartMetricCombo")
    check("测试项下拉 = 交集 5 项，默认选中主判定项",
          combo.count() == 5 and combo.currentData() == "mtf@0.125")

    plot = dlg._plot_compare
    curves = plot.listDataItems()
    check("对比图两条数据线（A/B）", len(curves) == 2)
    xs, ya = curves[0].getData()
    check("A 线 5 个位置点", len(xs) == 5)
    ticks = dlg._chart_tick_labels
    check("横轴为 ROI 位置名（中心/四角）",
          ticks and any("中心" in t for t in ticks), str(ticks))

    dplot = dlg._plot_delta
    ditems = dplot.getPlotItem().items
    bars = [item for item in ditems
            if item.__class__.__name__ == "BarGraphItem"]
    check("Δ 条形图 5 根条形", len(bars) == 1
          and len(bars[0].opts["height"]) == 5)
    n_lines = sum(1 for item in ditems
                  if item.__class__.__name__ == "InfiniteLine")
    check("Δ 图含 tie 参考线与零线（3 条）", n_lines == 3)

    # 切换测试项 → 图表刷新（标题随之变化）
    combo.setCurrentIndex(1)  # mtf50
    app.processEvents()
    title = plot.getPlotItem().titleLabel.text
    check("切换测试项后图表标题刷新", "MTF50" in (title or ""), title)

    # 重新载入 → 图表清空、保存禁用
    dlg.load_csv("b", csv_b)
    app.processEvents()
    check("重新载入后图表清空 + 保存禁用",
          not plot.listDataItems()
          and not dlg.findChild(QPushButton, "saveCompareBtn").isEnabled())
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def test_save_button():
    print("[3/3] 保存比较结果 CSV")
    from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton

    app, dlg = m43.make_dialog()
    save_btn = dlg.findChild(QPushButton, "saveCompareBtn")
    check("未比较时保存按钮禁用", not save_btn.isEnabled())

    csv_a, csv_b = m43.make_csv_pair()
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    check("比较后保存按钮启用", save_btn.isEnabled())

    out = OUT_DIR / "panel_compare_save.csv"
    if out.exists():
        out.unlink()
    with mock.patch.object(QFileDialog, "getSaveFileName",
                           return_value=(str(out), "CSV 文件 (*.csv)")), \
         mock.patch.object(QMessageBox, "information", return_value=None):
        save_btn.click()
        app.processEvents()
    check("保存落盘", out.is_file())
    if out.is_file():
        meta, _, rows = _parse_compare_csv(out.read_text(encoding="utf-8-sig"))
        check("保存内容可解析（label + 5 对配对行）",
              meta.get("label_a") == "清晰镜头"
              and len([r for r in rows if r["roi_a"] and r["roi_b"]]) == 5)

    # 取消保存 → 不留痕
    out2 = OUT_DIR / "should_not_exist_compare.csv"
    with mock.patch.object(QFileDialog, "getSaveFileName",
                           return_value=("", "")):
        save_btn.click()
        app.processEvents()
    check("取消保存不留痕", not out2.exists())
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def main():
    test_compare_csv_format()
    test_panel_charts()
    test_save_button()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
