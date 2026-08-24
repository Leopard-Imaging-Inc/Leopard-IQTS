"""
M4.1 验证测试：MTF 结果 CSV 导出（模组比较前置功能）。

设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md §3.2 / §6.1。

测试内容：
[1/6] 导入与 CSV 基本格式（元数据头 + 表头列序 + 行数）
[2/6] 数值一致性（CSV 与 analyze_mtf 结果对拍，容差 1e-6；归一化坐标）
[3/6] MTFa 与手工梯形积分对拍 + 边界行为
[4/6] 动态 Readout 列 + 无效 ROI 标记
[5/6] label 默认/自定义/清洗 + write_result_csv 落盘（utf-8-sig）往返
[6/6] MtfResultView「导出结果 CSV…」按钮端到端（offscreen，对话框打桩）

运行：
    QT_QPA_PLATFORM=offscreen D:\\ProgramData\\Anaconda3\\envs\\LpIQtest312\\python.exe tests/test_m4_1.py
"""

import csv
import io
import os
import sys
import tempfile
import warnings
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 测试与用户保存的 Read Raw 全局设置隔离，保证结果可复现
os.environ.setdefault(
    "LEOPARDIQTS_CONFIG_DIR", tempfile.mkdtemp(prefix="lqiq_test_")
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS_COUNT = 0
FAIL_COUNT = 0
OUT_DIR = Path(__file__).resolve().parent / "_m4_smoke"

_trapezoid = getattr(np, "trapezoid", None) or np.trapz


def check(name: str, condition: bool, detail: str = ""):
    global PASS_COUNT, FAIL_COUNT
    if condition:
        PASS_COUNT += 1
        print(f"    ✅ {name}" + (f" ({detail})" if detail else ""))
    else:
        FAIL_COUNT += 1
        print(f"    ❌ {name}" + (f" ({detail})" if detail else ""))


# ----------------------------------------------------------------------
# 合成数据（与 test_m3_1 同款的 5 方格斜边标板）
# ----------------------------------------------------------------------
IMG_H, IMG_W = 800, 800
SQUARE_SIZE = 0.06
SQUARE_DISTANCES = [0, 0.4, 0.4, 0.4, 0.4]
SQUARE_ANGLES = [0, 45, 135, 225, 315]
SQUARE_ROTATION = 5.0


def square_centers():
    chart_diag = np.hypot(IMG_H, IMG_W)
    cx, cy = IMG_W / 2 + 0.5, IMG_H / 2 + 0.5
    pts = []
    for dist, ang in zip(SQUARE_DISTANCES, SQUARE_ANGLES):
        d = 0.5 * chart_diag * dist
        pts.append((d * np.cos(np.deg2rad(ang)) + cx,
                    cy - d * np.sin(np.deg2rad(ang))))
    return pts


def make_chart():
    h, w = IMG_H, IMG_W
    image = np.full((h, w), 220.0, dtype=np.float64)
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    for x, y in square_centers():
        rect = ((x, y), (square_px, square_px), SQUARE_ROTATION)
        box = cv2.boxPoints(rect).astype(np.int32)
        cv2.fillPoly(image, [box], 20.0)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    return image[:, :, np.newaxis].astype(np.float32)


def top_edge_rois():
    chart_diag = np.hypot(IMG_H, IMG_W)
    square_px = SQUARE_SIZE * chart_diag
    rois = []
    for x, y in square_centers():
        rois.append([
            int(x - square_px * 0.35),
            int(y - square_px / 2 - 12),
            int(square_px * 0.7),
            40,
        ])
    return rois


def make_mono_chart_file() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "sfr_chart_m4.png"
    img = np.squeeze(make_chart())
    cv2.imwrite(str(path), np.clip(img, 0, 255).astype(np.uint8))
    return path


_RESULT_CACHE: dict = {}


def run_analysis(rois=None, **param_overrides):
    """mono 标板端到端分析（结果按参数组合缓存，避免重复跑引擎）。"""
    from iqtest.analysis.mtf_adapter import analyze_mtf

    path = make_mono_chart_file()
    rois = rois if rois is not None else top_edge_rois()
    params = {"cfa": "Y", "freq1": 0.125,
              "rois": [{"image": path.name, "rect": r} for r in rois]}
    params.update(param_overrides)
    key = str(sorted(params.items(), key=lambda kv: kv[0]))
    if key not in _RESULT_CACHE:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _RESULT_CACHE[key] = analyze_mtf([str(path)], {
                "params": params,
                "criteria": {"readout1_min": 0.0, "sfr_main_min": 0.0},
            })
    return _RESULT_CACHE[key], path


def parse_csv_text(text: str):
    """CSV 文本 → (metadata dict, header list, rows list[dict])。"""
    meta_lines = [ln for ln in text.splitlines() if ln.startswith("#")]
    table_text = "\n".join(
        ln for ln in text.splitlines() if not ln.startswith("#")
    )
    meta = {}
    for ln in meta_lines[1:]:  # 首行为格式标识
        body = ln[2:]
        key, _, value = body.partition(": ")
        meta[key.strip()] = value.strip()
    reader = csv.DictReader(io.StringIO(table_text))
    rows = list(reader)
    return meta, reader.fieldnames, rows


# ----------------------------------------------------------------------
# 测试
# ----------------------------------------------------------------------
def test_format():
    print("[1/6] 导入与 CSV 基本格式")
    from iqtest.analysis.mtf_export import (
        SCHEMA_VERSION,
        compute_mtfa,  # noqa: F401
        result_to_csv,
        write_result_csv,  # noqa: F401
    )

    result, path = run_analysis()
    text = result_to_csv(result, label="LensA_SN001")
    meta, headers, rows = parse_csv_text(text)

    check("首行为格式标识",
          text.startswith("# LeopardIQ MTF Result CSV"))
    check("schema_version", meta.get("schema_version") == str(SCHEMA_VERSION))
    check("label 写入", meta.get("label") == "LensA_SN001")
    check("created 存在", bool(meta.get("created")))
    check("image 为源图像名", meta.get("image") == path.name)
    check("图像尺寸元数据",
          meta.get("image_width") == str(IMG_W)
          and meta.get("image_height") == str(IMG_H))
    check("口径元数据（freq_unit/freq1/gamma）",
          meta.get("freq_unit") == "Cycles/pixel"
          and meta.get("freq1") == "0.125" and meta.get("gamma") == "1")
    check("表头列序正确",
          headers == ["roi", "channel", "cx_norm", "cy_norm",
                      "roi_l", "roi_r", "roi_t", "roi_b", "valid",
                      "mtf@0.125", "mtf50", "mtf30", "mtf50p", "mtfa"],
          str(headers))
    check("5 ROI × 1 通道 = 5 行", len(rows) == 5, f"got {len(rows)}")
    check("空结果报错", _raises_value_error(result_to_csv, {}, "x"))


def _raises_value_error(fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return False
    except ValueError:
        return True


def test_values():
    print("[2/6] 数值一致性（对拍容差 1e-6）与归一化坐标")
    from iqtest.analysis.mtf_export import result_to_csv

    result, _ = run_analysis()
    _, _, rows = parse_csv_text(result_to_csv(result, label="A"))
    curves = result["details"]["curves"]
    metrics = result["metrics"]

    max_diff = 0.0
    for row, curve in zip(rows, curves):
        i = int(row["roi"])
        check(f"ROI{i} 通道与有效标记",
              row["channel"] == curve["channel"] and row["valid"] == "1")
        max_diff = max(
            max_diff,
            abs(float(row["mtf@0.125"])
                - metrics[f"ROI{i}_mtf@0.125"]["value"][0]),
            abs(float(row["mtf50"]) - curve["mtf50"]),
            abs(float(row["mtf30"]) - curve["readouts"][0]),
            abs(float(row["mtf50p"]) - curve["readouts"][1]),
        )
    check("CSV 数值与结果对拍一致", max_diff <= 1e-6,
          f"max_diff={max_diff:.2e}")

    # 归一化坐标 = ROI 中心 / 图像尺寸；ROI 框像素坐标 = L R T B
    roi_records = {r["roi"]: r for r in result["details"]["rois"]}
    coord_ok = True
    box_ok = True
    for row in rows:
        x, y, w, h = roi_records[int(row["roi"])]["rect"]
        coord_ok &= abs(float(row["cx_norm"]) - (x + w / 2) / IMG_W) <= 1e-6
        coord_ok &= abs(float(row["cy_norm"]) - (y + h / 2) / IMG_H) <= 1e-6
        l, r, t, b = (int(row["roi_l"]), int(row["roi_r"]),
                      int(row["roi_t"]), int(row["roi_b"]))
        box_ok &= (l, r, t, b) == (int(x), int(x + w), int(y), int(y + h))
    check("cx_norm/cy_norm 与 ROI 中心一致", coord_ok)
    check("roi_l/r/t/b 与 ROI 框 L R T B 一致", box_ok)

    centers = square_centers()
    check("中心 ROI 归一化坐标 ≈ (0.5, 0.5)",
          abs(float(rows[0]["cx_norm"]) - centers[0][0] / IMG_W) < 0.05
          and abs(float(rows[0]["cy_norm"]) - centers[0][1] / IMG_H) < 0.05,
          f"({rows[0]['cx_norm']}, {rows[0]['cy_norm']})")


def test_mtfa():
    print("[3/6] MTFa 对拍与边界行为")
    from iqtest.analysis.mtf_export import compute_mtfa, result_to_csv

    result, _ = run_analysis()
    _, _, rows = parse_csv_text(result_to_csv(result, label="A"))
    curves = result["details"]["curves"]

    max_diff = 0.0
    for row, curve in zip(rows, curves):
        f = np.asarray(curve["freq"])
        m = np.asarray(curve["mtf"])
        sel = np.isfinite(f) & np.isfinite(m) & (f <= 0.5)
        manual = float(_trapezoid(m[sel], f[sel]))
        max_diff = max(max_diff, abs(float(row["mtfa"]) - manual))
        check(f"ROI{row['roi']} MTFa 范围 (0, 0.5]",
              0.0 < float(row["mtfa"]) <= 0.5,
              f"mtfa={row['mtfa']}")
    check("MTFa 与手工梯形积分一致", max_diff <= 1e-6,
          f"max_diff={max_diff:.2e}")

    check("MTFa 采样点不足 → NaN",
          not np.isfinite(compute_mtfa([0.1], [0.5])))
    check("MTFa 空曲线 → NaN",
          not np.isfinite(compute_mtfa([], [])))
    check("MTFa 忽略 Nyquist 之外的点",
          abs(compute_mtfa([0.0, 0.5, 0.9], [1.0, 1.0, 0.0]) - 0.5) < 1e-9)


def test_dynamic_columns_and_invalid():
    print("[4/6] 动态 Readout 列 + 无效 ROI 标记")
    from iqtest.analysis.mtf_export import result_to_csv

    # 自定义两个 Readout 槽位 → 动态列
    result, _ = run_analysis(mtfnn1_type="MTFnn", mtfnn1_value=20.0,
                             mtfnn2_type="MTFnnP", mtfnn2_value=70.0)
    _, headers, _ = parse_csv_text(result_to_csv(result, label="A"))
    check("自定义 Readout 成为动态列",
          "mtf20" in headers and "mtf70p" in headers
          and "mtf30" not in headers, str(headers))

    # 4 个正常斜边 ROI + 1 个平坦区域 ROI（背景区，预检拦截 → 无效）
    rois = top_edge_rois()[:4] + [[2, 2, 40, 40]]
    result2, _ = run_analysis(rois=rois)
    _, _, rows = parse_csv_text(result_to_csv(result2, label="B"))
    invalid = [r for r in rows if r["valid"] == "0"]
    valid = [r for r in rows if r["valid"] == "1"]
    check("4 有效 + 1 无效", len(valid) == 4 and len(invalid) == 1,
          f"valid={len(valid)} invalid={len(invalid)}")
    check("无效行指标列为空",
          all(r["mtf@0.125"] == "" and r["mtf50"] == "" and r["mtfa"] == ""
              for r in invalid))
    check("无效行仍保留归一化坐标",
          all(r["cx_norm"] and r["cy_norm"] for r in invalid))


def test_label_and_file():
    print("[5/6] label 默认/自定义/清洗 + 落盘往返")
    from iqtest.analysis.mtf_export import result_to_csv, write_result_csv

    result, path = run_analysis()

    meta, _, _ = parse_csv_text(result_to_csv(result))
    check("默认 label = 图像文件名主干", meta.get("label") == path.stem,
          meta.get("label"))

    meta2, _, _ = parse_csv_text(
        result_to_csv(result, label="供应商A, 批次1\n改")
    )
    check("label 逗号/换行被清洗", meta2.get("label") == "供应商A 批次1 改",
          meta2.get("label"))

    out = OUT_DIR / "roundtrip.csv"
    write_result_csv(result, out, label="LensX")
    check("write_result_csv 落盘", out.is_file())
    raw = out.read_bytes()
    check("文件带 utf-8-sig BOM（Excel 兼容）",
          raw.startswith(b"\xef\xbb\xbf"))
    meta3, headers3, rows3 = parse_csv_text(
        raw.decode("utf-8-sig")
    )
    check("落盘读回解析一致",
          meta3.get("label") == "LensX" and len(rows3) == 5
          and headers3[0] == "roi")


def test_figure_button():
    print("[6/6] MtfResultView 导出按钮端到端（对话框打桩）")
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QInputDialog,
        QMessageBox,
        QPushButton,
    )

    from iqtest.figures.mtf_figure import MtfResultView

    app = QApplication.instance() or QApplication([])
    result, _ = run_analysis()
    view = MtfResultView(result)
    btn = view.findChild(QPushButton, "exportCsvBtn")
    check("存在「导出结果 CSV…」按钮", btn is not None)

    out = OUT_DIR / "figure_export.csv"
    if out.exists():
        out.unlink()
    with mock.patch.object(QInputDialog, "getText",
                           return_value=("TestLens", True)), \
         mock.patch.object(QFileDialog, "getSaveFileName",
                           return_value=(str(out), "CSV 文件 (*.csv)")), \
         mock.patch.object(QMessageBox, "information", return_value=None):
        btn.click()
        app.processEvents()
    check("点击按钮完成导出", out.is_file())
    if out.is_file():
        meta, _, rows = parse_csv_text(out.read_text(encoding="utf-8-sig"))
        check("导出内容正确（label + 5 行）",
              meta.get("label") == "TestLens" and len(rows) == 5)

    # 用户在标签对话框点取消 → 不产生文件
    out2 = OUT_DIR / "should_not_exist.csv"
    with mock.patch.object(QInputDialog, "getText",
                           return_value=("", False)), \
         mock.patch.object(QFileDialog, "getSaveFileName",
                           return_value=(str(out2), "")):
        btn.click()
        app.processEvents()
    check("取消导出不留痕", not out2.exists())
    view.close()
    view.deleteLater()
    app.processEvents()


def main():
    test_format()
    test_values()
    test_mtfa()
    test_dynamic_columns_and_invalid()
    test_label_and_file()
    test_figure_button()
    print(f"\n结果：{PASS_COUNT} 通过 / {FAIL_COUNT} 失败")
    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
