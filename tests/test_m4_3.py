"""
M4.3 验证测试：MTF 模组比较面板（mtf_compare_panel.py + Utilities 菜单入口）。

设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md §6.2。

测试内容：
[1/4] 面板构建与空态（比较按钮禁用、占位提示）
[2/4] 载入 CSV A/B：口径状态、3×3 配对预览表、测试项勾选清单（交集）、
      主判定项默认
[3/4] 比较执行：摘要输出、compared 信号、主判定项切换、未勾选警告
[4/4] 阈值生效与错误路径：调大 tie → 全平手；不兼容 CSV → 红字报错禁用；
      不存在文件报错；Utilities 菜单接线（单实例复用）

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m4_3.py
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

import test_m4_1 as m4  # noqa: E402  复用合成标板与导出链路

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = m4.OUT_DIR

_CSV_CACHE: dict = {}


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


def make_csv_pair() -> tuple[Path, Path]:
    """A = 清晰标板，B = 高斯模糊（较差镜头）+ ROI 偏移（摆位差异）。"""
    if "pair" in _CSV_CACHE:
        return _CSV_CACHE["pair"]
    from iqtest.analysis.mtf_adapter import analyze_mtf
    from iqtest.analysis.mtf_export import write_result_csv

    result_a, path_a = m4.run_analysis()
    blur_img = cv2.GaussianBlur(np.squeeze(m4.make_chart()), (9, 9), 3)
    path_b = OUT_DIR / "sfr_chart_m4_blur.png"
    cv2.imwrite(str(path_b), np.clip(blur_img, 0, 255).astype(np.uint8))
    rois_b = [[x + 6, y + 5, w, h] for x, y, w, h in m4.top_edge_rois()]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result_b = analyze_mtf([str(path_b)], {
            "params": {"cfa": "Y", "freq1": 0.125,
                       "rois": [{"image": path_b.name, "rect": r}
                                for r in rois_b]},
            "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0},
        })
    csv_a = write_result_csv(result_a, OUT_DIR / "panel_a.csv", label="清晰镜头")
    csv_b = write_result_csv(result_b, OUT_DIR / "panel_b.csv", label="模糊镜头")
    _CSV_CACHE["pair"] = (csv_a, csv_b)
    return csv_a, csv_b


def make_dialog():
    from PySide6.QtWidgets import QApplication

    from iqtest.panels.mtf_compare_panel import MtfCompareDialog

    app = QApplication.instance() or QApplication([])
    return app, MtfCompareDialog()


# ----------------------------------------------------------------------
def test_empty_state():
    print("[1/4] 面板构建与空态")
    from PySide6.QtWidgets import QPushButton

    app, dlg = make_dialog()
    btn = dlg.findChild(QPushButton, "compareBtn")
    check("空态比较按钮禁用", btn is not None and not btn.isEnabled())
    from PySide6.QtWidgets import QLabel
    status = dlg.findChild(QLabel, "compareStatus")
    check("空态状态提示", "载入" in status.text())
    from PySide6.QtWidgets import QTableWidget
    table = dlg.findChild(QTableWidget, "pairTable")
    check("配对预览表 9 行 4 列",
          table is not None and table.rowCount() == 9
          and table.columnCount() == 4)
    check("中心行位置名正确", table.item(4, 0).text() == "中心")
    from PySide6.QtWidgets import QAbstractSpinBox, QDoubleSpinBox
    spins = dlg.findChildren(QDoubleSpinBox)
    check("阈值/权重输入框无上下箭头（直接键入）",
          len(spins) == 6 and all(
              s.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.NoButtons
              for s in spins))
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def test_load_and_preview():
    print("[2/4] 载入 CSV：口径状态 / 配对预览 / 测试项清单")
    from PySide6.QtWidgets import QLabel, QPushButton, QTableWidget

    app, dlg = make_dialog()
    csv_a, csv_b = make_csv_pair()

    dlg.load_csv("a", csv_a)
    status = dlg.findChild(QLabel, "compareStatus")
    check("仅载入 A 时提示再载入另一份", "另一份" in status.text())
    info_a = dlg.findChild(QLabel, "info_a")
    check("A 槽位信息行", "清晰镜头" in info_a.text() and "5 行" in info_a.text())
    check("单侧载入比较按钮仍禁用",
          not dlg.findChild(QPushButton, "compareBtn").isEnabled())

    dlg.load_csv("b", csv_b)
    check("口径一致状态（含配对数）",
          "口径一致" in status.text() and "配对 5 对" in status.text(),
          status.text())

    table = dlg.findChild(QTableWidget, "pairTable")
    center = [table.item(4, c).text() for c in range(1, 4)]
    corner_tl = [table.item(0, c).text() for c in range(1, 4)]
    edge_top = [table.item(1, c).text() for c in range(1, 4)]
    check("配对预览：中心 1/1/1", center == ["1", "1", "1"], str(center))
    check("配对预览：左上角 1/1/1", corner_tl == ["1", "1", "1"])
    check("配对预览：上边缘无 ROI 显示 —", edge_top == ["—", "—", "—"])

    check("测试项清单 = 交集 5 项", len(dlg._metric_rows) == 5,
          str([e["key"] for e in dlg._metric_rows]))
    check("默认全勾选 + 首项为主判定",
          all(e["checkbox"].isChecked() for e in dlg._metric_rows)
          and dlg._metric_rows[0]["radio"].isChecked())
    check("比较按钮启用", dlg.findChild(QPushButton, "compareBtn").isEnabled())
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def test_compare_execution():
    print("[3/4] 比较执行：摘要 / 信号 / 主判定项切换 / 未勾选警告")
    from PySide6.QtWidgets import QMessageBox, QPlainTextEdit, QPushButton

    app, dlg = make_dialog()
    csv_a, csv_b = make_csv_pair()
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)

    emitted: list[dict] = []
    dlg.compared.connect(emitted.append)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()

    summary = dlg.findChild(QPlainTextEdit, "compareSummary").toPlainText()
    check("摘要含总体结论与逐项", "总体结论" in summary and "MTF50" in summary,
          summary.splitlines()[0] if summary else "")
    check("结论正确（清晰镜头更好）",
          "清晰镜头 更好" in summary, summary.splitlines()[0] if summary else "")
    check("compared 信号发射", len(emitted) == 1
          and emitted[0]["main_verdict"] == "A"
          and emitted[0]["main_metric"] == "mtf@0.125")

    # 切换主判定项到 MTF50
    for entry in dlg._metric_rows:
        if entry["key"] == "mtf50":
            entry["radio"].setChecked(True)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    check("主判定项切换生效", emitted[-1]["main_metric"] == "mtf50")

    # 全部取消勾选 → 警告且不发射
    for entry in dlg._metric_rows:
        entry["checkbox"].setChecked(False)
    before = len(emitted)
    with mock.patch.object(QMessageBox, "warning", return_value=None) as warn:
        dlg.findChild(QPushButton, "compareBtn").click()
        app.processEvents()
    check("未勾选测试项 → 警告且不发射",
          warn.called and len(emitted) == before)
    for entry in dlg._metric_rows:
        entry["checkbox"].setChecked(True)
    dlg.close()
    dlg.deleteLater()
    app.processEvents()


def test_thresholds_and_errors():
    print("[4/4] 阈值生效 / 错误路径 / Utilities 菜单接线")
    from PySide6.QtWidgets import (
        QDoubleSpinBox,
        QLabel,
        QPlainTextEdit,
        QPushButton,
    )

    app, dlg = make_dialog()
    csv_a, csv_b = make_csv_pair()
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)

    # tie 阈值调大 → 胜负计数全部平手（总体结论仍由评分差判定，§4.3）
    dlg.findChild(QDoubleSpinBox, "tieFreqSpin").setValue(0.5)
    dlg.findChild(QDoubleSpinBox, "tieSfrSpin").setValue(0.5)
    emitted: list[dict] = []
    dlg.compared.connect(emitted.append)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    st = emitted[-1]["stats"]["mtf50"]
    check("tie=0.5 → 胜负计数全部平手",
          st["tie"] == 5 and st["win"] == 0 and st["loss"] == 0)
    # 评分打平阈值调大（评分差 ~0.7）→ 总体结论「两者相当」
    dlg.findChild(QDoubleSpinBox, "scoreTieSpin").setValue(1.0)
    dlg.findChild(QPushButton, "compareBtn").click()
    app.processEvents()
    check("score_tie=1.0 → 结论两者相当",
          emitted[-1]["main_verdict"] == "TIE"
          and "相当" in dlg.findChild(QPlainTextEdit,
                                      "compareSummary").toPlainText())
    dlg.findChild(QDoubleSpinBox, "scoreTieSpin").setValue(0.01)

    # 不兼容 CSV（freq_unit 不同）→ 红字报错 + 按钮禁用
    bad = OUT_DIR / "panel_bad_unit.csv"
    bad.write_text(
        Path(csv_a).read_text(encoding="utf-8-sig").replace(
            "# freq_unit: Cycles/pixel", "# freq_unit: LP/mm"),
        encoding="utf-8-sig",
    )
    dlg.load_csv("b", bad)
    status = dlg.findChild(QLabel, "compareStatus")
    check("口径不一致 → 报错状态",
          "口径校验失败" in status.text() and "频率单位" in status.text(),
          status.text())
    check("不兼容时比较按钮禁用",
          not dlg.findChild(QPushButton, "compareBtn").isEnabled())

    # 不存在的文件 → 载入失败提示
    dlg.load_csv("b", OUT_DIR / "not_exist.csv")
    check("不存在文件 → 载入失败提示", "载入失败" in status.text())
    dlg.close()
    dlg.deleteLater()
    app.processEvents()

    # Utilities 菜单接线（单实例复用）
    from iqtest.main_window import MainWindow

    win = MainWindow()
    actions = [a.text() for a in win.btn_utilities_menu.menu().actions()]
    check("Utilities 菜单含「MTF 模组比较…」",
          "MTF 模组比较…" in actions, str(actions))
    win._on_mtf_compare_dialog()
    app.processEvents()
    dlg2 = win._compare_dialog
    check("菜单触发创建比较对话框", dlg2 is not None and dlg2.isVisible())
    win._on_mtf_compare_dialog()
    app.processEvents()
    check("重复触发复用单实例", win._compare_dialog is dlg2)
    dlg2.close()
    dlg2.deleteLater()
    win.close()
    win.deleteLater()
    app.processEvents()


def main():
    test_empty_state()
    test_load_and_preview()
    test_compare_execution()
    test_thresholds_and_errors()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
