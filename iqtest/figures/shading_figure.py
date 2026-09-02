"""Lens Shading 结果 Figure：RI 热力图 + 四象限数值表 + 逐项判定 + 导出。

作为 content 嵌入 FigureWindow（FigureManager.register_view("shading", ShadingResultView)）。
消费 shading_adapter.analyze_shading 的返回 dict：
    result["metrics"] / ["pass"]        判定指标与总判定（单光源）
    result["details"]["mode"]           single | multi
    result["details"]["report"]         报告通道 shading 网格 + 四象限 RI
    result["details"]["per_channel_ri"] 逐通道四象限 RI（Bayer）
    result["details"]["closed_loop"]    闭环验证（apply_lsc 残余）
    result["details"]["comparison"]     多光源对比（ri_spread / color_shift_spread）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_PASS_COLOR = "#1e8a57"
_FAIL_COLOR = "#c0504d"
_INFO_COLOR = "#333333"


def _status_color(text: str) -> str:
    if text == "PASS":
        return _PASS_COLOR
    if text == "FAIL":
        return _FAIL_COLOR
    return _INFO_COLOR


def _fmt_value(value, decimals: int = 4) -> str:
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.atleast_1d(value)
        return ", ".join(f"{float(v):.{decimals}f}" for v in arr)
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _make_table(headers: list[str], rows: list[list],
                status_col: int | None = None) -> QTableWidget:
    table = QTableWidget(len(rows), len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.Stretch
    )
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text = _fmt_value(value)
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status_col is not None and c == status_col:
                item.setForeground(pg.mkColor(_status_color(str(value))))
            table.setItem(r, c, item)
    return table


class ShadingResultView(QWidget):
    """Lens Shading 模块结果视图。"""

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result = result
        details = result.get("details", {})
        mode = details.get("mode", "single")

        overall = bool(result.get("pass"))
        verdict = QLabel("判定：PASS" if overall else "判定：FAIL")
        verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        verdict.setStyleSheet(
            "font-size: 16px; font-weight: 700; padding: 6px; border-radius: 4px;"
            + ("color: #ffffff; background: #2bb673;" if overall
               else "color: #ffffff; background: #c0504d;")
        )
        subtitle = QLabel(self._subtitle(details))
        subtitle.setObjectName("panelDesc")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        # ---- 左：RI 热力图（单光源）或占位
        self._plot = self._build_heatmap(details) if mode == "single" else None

        # ---- 右：指标/判定 tabs
        tabs = self._build_tabs(details)

        # ---- 工具行：导出
        toolbar = QHBoxLayout()
        self._export_profile_btn = QPushButton("导出 shading_profile…")
        self._export_profile_btn.setToolTip(
            "导出 shading_profile（通用参考数据：npy / CSV / PNG，非可烧录 OTP 表）"
        )
        self._export_profile_btn.setEnabled(mode == "single")
        self._export_profile_btn.clicked.connect(self._export_profile)
        export_csv_btn = QPushButton("导出结果 CSV…")
        export_csv_btn.clicked.connect(self._export_result_csv)
        toolbar.addWidget(self._export_profile_btn)
        toolbar.addWidget(export_csv_btn)
        toolbar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(toolbar)
        layout.addWidget(verdict)
        layout.addWidget(subtitle)

        if self._plot is not None:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.addWidget(self._plot)
            splitter.addWidget(tabs)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            layout.addWidget(splitter, stretch=1)
        else:
            layout.addWidget(tabs, stretch=1)

    # ------------------------------------------------------------ 副标题

    @staticmethod
    def _subtitle(details: dict) -> str:
        mode = details.get("mode", "single")
        cfa = "、".join(details.get("channels") or ["Y"])
        bin_size = details.get("bin_size")
        criteria = details.get("criteria") or {}
        parts = [
            f"光源：{details.get('light_source', '—')}",
            f"CFA：{cfa}",
            f"bin_size：{bin_size}",
            f"报告通道：{details.get('luminance_channel', 'Y')}",
        ]
        if criteria:
            crit_parts = []
            if "ri" in criteria:
                crit_parts.append(f"RI ≥ {criteria['ri']:g}")
            if "ri_diff" in criteria:
                crit_parts.append(f"ri_diff ≤ {criteria['ri_diff']:g}")
            if "green_red_shift" in criteria:
                crit_parts.append(f"G/R shift ≤ {criteria['green_red_shift']:g}")
            if "green_blue_shift" in criteria:
                crit_parts.append(f"G/B shift ≤ {criteria['green_blue_shift']:g}")
            parts.append("criteria：" + "，".join(crit_parts))
        if mode == "multi":
            parts.append("（多光源对比）")
        return "　|　".join(parts)

    # ------------------------------------------------------------ 热力图

    def _build_heatmap(self, details: dict):
        report = details.get("report") or {}
        shading_map = report.get("shading_map")
        if shading_map is None:
            return None
        plot = pg.PlotWidget(background="w")
        plot.setAspectLocked(True)
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setLabel("bottom", "网格 x")
        plot.setLabel("left", "网格 y")
        plot.setTitle(f"相对照度热力图（{report.get('channel', 'Y')}）")

        data = np.asarray(shading_map, dtype=np.float64)
        img_item = pg.ImageItem()
        cmap = pg.colormap.get("viridis")
        img_item.setLookupTable(cmap.getLookupTable(0.0, 1.0, 256))
        img_item.setImage(data.T, autoLevels=True)
        plot.addItem(img_item)

        h, w = data.shape
        for pos, angle in ((w / 2.0, 90), (h / 2.0, 0)):
            plot.addItem(pg.InfiniteLine(
                pos=pos, angle=angle, movable=False,
                pen=pg.mkPen("#8a939b", width=1, style=Qt.PenStyle.DashLine),
            ))
        plot.setXRange(0, w, padding=0.01)
        plot.setYRange(0, h, padding=0.01)
        return plot

    # ------------------------------------------------------------ Tabs

    def _build_tabs(self, details: dict) -> QTabWidget:
        tabs = QTabWidget()
        mode = details.get("mode", "single")
        if mode == "single":
            tabs.addTab(self._tab_quadrant(details), "四象限 RI")
            tabs.addTab(self._tab_judgment(), "逐项判定")
            if details.get("closed_loop"):
                tabs.addTab(self._tab_closed_loop(details["closed_loop"]), "闭环验证")
        else:
            tabs.addTab(self._tab_multi(details), "多光源对比")
            tabs.addTab(self._tab_judgment_multi(details), "逐项判定")
        return tabs

    def _tab_quadrant(self, details: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        report = details.get("report") or {}
        ri = report.get("ri") or {}

        headline = QLabel(f"报告通道（{report.get('channel', 'Y')}）四象限 RI")
        headline.setObjectName("panelDesc")
        layout.addWidget(headline)
        layout.addWidget(_make_table(
            ["象限", "RI"],
            [["TL", ri.get("tl")], ["TR", ri.get("tr")],
             ["BL", ri.get("bl")], ["BR", ri.get("br")],
             ["ri_diff", report.get("ri_diff")]],
        ))

        per_channel = details.get("per_channel_ri")
        if per_channel:
            label = QLabel("逐通道四象限 RI")
            label.setObjectName("panelDesc")
            layout.addWidget(label)
            channels = per_channel["channels"]
            rows = [[ch] + [
                per_channel[key][i] if i < len(per_channel[key]) else None
                for key in ("tl", "tr", "bl", "br")
            ] for i, ch in enumerate(channels)]
            layout.addWidget(_make_table(["通道", "TL", "TR", "BL", "BR"], rows))
        layout.addStretch(1)
        return page

    def _tab_judgment(self) -> QWidget:
        metrics = self._result.get("metrics") or {}
        rows = [[key, m.get("value"), m.get("status", "INFO")]
                for key, m in metrics.items()]
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_make_table(["指标", "值", "判定"], rows, status_col=2))
        return page

    def _tab_closed_loop(self, closed_loop: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        if not closed_loop.get("enabled"):
            layout.addWidget(QLabel(closed_loop.get("note", "闭环验证不可用")))
            layout.addStretch(1)
            return page
        rows = [
            ["校正前最差 RI", closed_loop.get("before_ri_min")],
            ["校正后最差 RI", closed_loop.get("after_ri_min")],
            ["校正前 ri_diff", closed_loop.get("before_ri_diff")],
            ["校正后 ri_diff", closed_loop.get("after_ri_diff")],
            ["校正前 G/R 偏移", closed_loop.get("before_green_red_shift")],
            ["校正后 G/R 偏移", closed_loop.get("after_green_red_shift")],
            ["校正前 G/B 偏移", closed_loop.get("before_green_blue_shift")],
            ["校正后 G/B 偏移", closed_loop.get("after_green_blue_shift")],
            ["残余判定", "PASS" if closed_loop.get("residual_pass") else "FAIL"],
        ]
        layout.addWidget(_make_table(["项", "值"], rows))
        layout.addStretch(1)
        return page

    def _tab_multi(self, details: dict) -> QWidget:
        lights = details.get("lights") or {}
        comparison = details.get("comparison") or {}
        rows = []
        for light_name, res in lights.items():
            metrics = res.get("metrics", {})
            rows.append([
                light_name,
                self._ri_min(metrics),
                self._shift(metrics, "green_red_shift"),
                self._shift(metrics, "green_blue_shift"),
                "PASS" if res.get("pass") else "FAIL",
            ])
        spread = comparison.get("color_shift_spread")
        summary = [
            ["ri_spread", comparison.get("ri_spread")],
            ["color_shift_spread (G/R)", (spread or {}).get("green_red")],
            ["color_shift_spread (G/B)", (spread or {}).get("green_blue")],
        ]
        page = QWidget()
        layout = QVBoxLayout(page)
        label = QLabel("各光源对比")
        label.setObjectName("panelDesc")
        layout.addWidget(label)
        layout.addWidget(_make_table(
            ["光源", "最差 RI", "G/R 偏移", "G/B 偏移", "判定"],
            rows, status_col=4,
        ))
        label2 = QLabel("跨光源一致性")
        label2.setObjectName("panelDesc")
        layout.addWidget(label2)
        layout.addWidget(_make_table(["指标", "值"], summary))
        layout.addStretch(1)
        return page

    def _tab_judgment_multi(self, details: dict) -> QWidget:
        lights = details.get("lights") or {}
        rows = []
        for light_name, res in lights.items():
            for key, m in (res.get("metrics") or {}).items():
                rows.append([light_name, key, m.get("value"),
                             m.get("status", "INFO")])
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_make_table(
            ["光源", "指标", "值", "判定"], rows, status_col=3
        ))
        return page

    # ------------------------------------------------------------ 工具

    @staticmethod
    def _ri_min(metrics: dict) -> float:
        vals = []
        for key in ("ri_tl", "ri_tr", "ri_bl", "ri_br"):
            value = (metrics.get(key) or {}).get("value", [])
            vals.extend(np.atleast_1d(value))
        return float(np.nanmin(vals)) if vals else float("nan")

    @staticmethod
    def _shift(metrics: dict, key: str) -> float | None:
        metric = metrics.get(key)
        return float(metric["value"]) if metric is not None else None

    # ------------------------------------------------------------ 导出

    def _export_profile(self) -> None:
        from iqtest.analysis.shading_export import (
            save_shading_profile_image,
            write_shading_profile_csv,
            write_shading_profile_npy,
        )

        details = self._result.get("details") or {}
        profile = details.get("shading_profile")
        report = details.get("report") or {}
        if profile is None and report.get("shading_map") is None:
            QMessageBox.information(self, "导出 shading_profile", "当前结果无可导出的 profile")
            return
        images = list((details.get("image_sizes") or {}).keys())
        default = f"{Path(images[0]).stem}_shading_profile.npy" if images else "shading_profile.npy"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出 shading_profile", default,
            "shading profile (*.npy *.csv *.png);;npy (*.npy);;CSV (*.csv);;PNG (*.png)",
        )
        if not path:
            return
        try:
            suffix = Path(path).suffix.lower()
            if suffix == ".csv":
                write_shading_profile_csv(self._result, path)
            elif suffix == ".png":
                if report.get("shading_map") is None:
                    raise ValueError("当前结果没有报告通道 shading 网格，无法导出 PNG")
                save_shading_profile_image(report["shading_map"], path)
            else:
                if profile is None:
                    raise ValueError("当前结果没有全分辨率 shading_profile，无法导出 npy")
                write_shading_profile_npy(profile, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"shading_profile 已保存：\n{path}")

    def _export_result_csv(self) -> None:
        from iqtest.analysis.shading_export import _sanitize, write_result_csv

        details = self._result.get("details") or {}
        images = list((details.get("image_sizes") or {}).keys())
        default_label = Path(images[0]).stem if images else "Shading"
        label, ok = QInputDialog.getText(
            self, "导出结果 CSV", "模组标签（label）：", text=default_label
        )
        if not ok:
            return
        default_name = f"{_sanitize(label) or 'shading_result'}_shading.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 Shading 结果 CSV", default_name, "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            write_result_csv(self._result, path, label=label)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"Shading 结果已保存：\n{path}")
