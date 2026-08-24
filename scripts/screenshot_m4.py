"""M4 冒烟脚本：MTF 模组比较全链路截图。

流程：构造 A（清晰）/ B（模糊 + ROI 偏移）两份 MTF 结果 CSV
→ 打开比较对话框 → 载入 → 执行比较 → 截图保存。

运行（Git Bash，项目根，conda 环境 LpIQtest312）：
    QT_QPA_PLATFORM=offscreen "D:/ProgramData/Anaconda3/envs/LpIQtest312/python.exe" -u scripts/screenshot_m4.py
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
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_smoke_")
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import test_m4_1 as m4  # noqa: E402  复用合成标板

OUT_DIR = ROOT / "tests" / "_m4_smoke"


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from iqtest.analysis.mtf_adapter import analyze_mtf
    from iqtest.analysis.mtf_export import write_result_csv
    from iqtest.panels.mtf_compare_panel import MtfCompareDialog

    app = QApplication.instance() or QApplication([])
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 造两份结果 CSV：A 清晰，B 模糊（较差镜头）+ ROI 偏移（摆位差异）
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
            "criteria": {"mtf50_min": 0.0, "sfr_main_min": 0.0},
        })
    csv_a = write_result_csv(result_a, OUT_DIR / "smoke_a.csv", label="Lens A")
    csv_b = write_result_csv(result_b, OUT_DIR / "smoke_b.csv", label="Lens B")

    # ---- 空态
    dlg = MtfCompareDialog()
    dlg.show()
    app.processEvents()
    shot = OUT_DIR / "m4_compare_empty.png"
    dlg.grab().save(str(shot))
    print(f"screenshot: {shot}")

    # ---- 载入 + 比较
    dlg.load_csv("a", csv_a)
    dlg.load_csv("b", csv_b)
    app.processEvents()
    dlg.findChild(__import__("PySide6.QtWidgets", fromlist=["QPushButton"])
                  .QPushButton, "compareBtn").click()
    app.processEvents()
    shot = OUT_DIR / "m4_compare_result.png"
    dlg.grab().save(str(shot))
    print(f"screenshot: {shot}")

    summary = dlg.findChild(
        __import__("PySide6.QtWidgets", fromlist=["QPlainTextEdit"])
        .QPlainTextEdit, "compareSummary").toPlainText()
    ok = "Lens A 更好" in summary and dlg._last_result is not None
    print("比较结论:", summary.splitlines()[0] if summary else "(空)")

    dlg.close()
    dlg.deleteLater()
    app.processEvents()

    # ---- 三款比较（基准金样模式）：C = 中度模糊（介于 A/B 之间）
    blur_img2 = cv2.GaussianBlur(np.squeeze(m4.make_chart()), (7, 7), 2)
    path_c = OUT_DIR / "sfr_chart_m4_blur2.png"
    cv2.imwrite(str(path_c), np.clip(blur_img2, 0, 255).astype(np.uint8))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result_c = analyze_mtf([str(path_c)], {
            "params": {"cfa": "Y", "freq1": 0.125,
                       "rois": [{"image": path_c.name, "rect": list(r)}
                                for r in m4.top_edge_rois()]},
            "criteria": {"mtf50_min": 0.0, "sfr_main_min": 0.0},
        })
    csv_c = write_result_csv(result_c, OUT_DIR / "smoke_c.csv", label="Lens C")

    dlg2 = MtfCompareDialog()
    dlg2.show()
    dlg2.findChild(__import__("PySide6.QtWidgets", fromlist=["QPushButton"])
                   .QPushButton, "addSlotBtn").click()
    dlg2.load_csv("a", csv_a)
    dlg2.load_csv("b", csv_b)
    dlg2.load_csv("c", csv_c)
    app.processEvents()
    dlg2.findChild(__import__("PySide6.QtWidgets", fromlist=["QPushButton"])
                   .QPushButton, "compareBtn").click()
    app.processEvents()
    shot = OUT_DIR / "m4_compare_multi.png"
    dlg2.grab().save(str(shot))
    print(f"screenshot: {shot}")
    summary2 = dlg2.findChild(
        __import__("PySide6.QtWidgets", fromlist=["QPlainTextEdit"])
        .QPlainTextEdit, "compareSummary").toPlainText()
    ok2 = ("基准（金样）：Lens A" in summary2
           and "【Lens B vs 基准】" in summary2
           and "【Lens C vs 基准】" in summary2
           and len(dlg2._last_results) == 2)
    print("三款结论首行:", summary2.splitlines()[0] if summary2 else "(空)")
    dlg2.close()
    dlg2.deleteLater()
    app.processEvents()

    ok = ok and ok2
    print(f"EXIT={0 if ok else 1}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
