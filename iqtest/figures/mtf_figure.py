"""MTF/SFR 结果 Figure：MTF 曲线（pyqtgraph）+ 逐通道指标表 + PASS/FAIL 横幅。

作为 content 嵌入 FigureWindow（FigureManager.register_view("mtf", MtfResultView)）。
消费 mtf_adapter.analyze_mtf 的返回 dict：
    result["details"]["curves"]    逐 (ROI, 通道) 的 MTF 曲线与指标
    result["metrics"]              判定指标（PASS / FAIL / INFO）
    result["pass"]                 总判定
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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
    QVBoxLayout,
    QWidget,
)

from leopardiq.mtf import compute_mtf_metrics, unit_label

#: 曲线配色（按 ROI 轮换；同一 ROI 多通道用线型区分）
_CURVE_COLORS = [
    "#1b9aaa", "#e8912d", "#2bb673", "#c0504d",
    "#8064a2", "#4bacc6", "#f79646", "#9bbb59",
]
_CHANNEL_STYLES = [Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine,
                   Qt.PenStyle.DotLine, Qt.PenStyle.DashDotLine]


class MtfResultView(QWidget):
    """MTF/SFR 模块结果视图。"""

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result = result
        details = result.get("details", {})
        curves = details.get("curves", [])
        frequency = details.get("frequency", [0.125])  # cy/px（规范单位）
        criteria = details.get("criteria", {})
        readouts = details.get("readouts", [])

        # 显示单位（仿 Imatest Secondary Readout）：cy/px → 所选单位
        unit = details.get("freq_unit", "Cycles/pixel")
        scale = float(details.get("unit_scale", 1.0))
        unit_str = unit_label(unit)

        # ---- 顶部判定横幅
        overall = bool(result.get("pass"))
        verdict = QLabel("判定：PASS" if overall else "判定：FAIL")
        verdict.setAlignment(Qt.AlignmentFlag.AlignCenter)
        verdict.setStyleSheet(
            "font-size: 16px; font-weight: 700; padding: 6px; border-radius: 4px;"
            + ("color: #ffffff; background: #2bb673;" if overall
               else "color: #ffffff; background: #c0504d;")
        )
        freq1 = frequency[0]
        subtitle = QLabel(
            f"评估频率 MTF @ {freq1 * scale:g} {unit_str}　|　"
            f"criteria：Readout1 ≥ {criteria.get('readout1_min', 0) * scale:g} {unit_str}，"
            f"MTF@{freq1 * scale:g} ≥ {criteria.get('sfr_main_min', 0):g}"
        )
        subtitle.setObjectName("panelDesc")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ---- 左：MTF 曲线
        plot = pg.PlotWidget(background="w")
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setLabel("bottom", f"Spatial frequency ({unit_str})")
        plot.setLabel("left", "MTF")
        plot.addLegend(offset=(10, 10), pen=pg.mkPen("#d5dbe0"),
                       brush=pg.mkBrush(255, 255, 255, 220))
        plot.setXRange(0, 1.0 * scale, padding=0.02)
        plot.setYRange(0, 1.05, padding=0)

        # 参考线：Nyquist（0.5 cy/px 换算）、评估频率
        for x, style, name in ((0.5 * scale, Qt.PenStyle.DotLine, "Nyquist"),
                               (freq1 * scale, Qt.PenStyle.DashLine, "MTF @")):
            line = pg.InfiniteLine(
                pos=x, angle=90, movable=False,
                pen=pg.mkPen("#8a939b", width=1, style=style),
                label=name, labelOpts={"color": "#8a939b"},
            )
            plot.addItem(line)

        # ---- 交互状态（供 ROI 选中高亮 / 标注开关 / 复位视图使用）
        self._plot = plot
        self._scale = scale
        self._curves = curves
        self._unit_str = unit_str
        self._readout1_key = details.get("readout1_key")
        self._init_x = (0.0, 1.0 * scale)
        self._init_y = (0.0, 1.05)
        self._curve_items: dict[int, object] = {}
        self._curve_colors: dict[int, str] = {}
        self._curve_styles: dict[int, object] = {}
        # 标注按 ROI 存储（roi -> (x, y, color) / [垂线, 水平线]），
        # 共享散点承载落点（图例各一条），可见性由 _refresh_markers 统一控制
        self._mtf50_points: dict[int, tuple] = {}
        self._mtf30_points: dict[int, tuple] = {}
        self._mtf50_lines: dict[int, list] = {}
        self._mtf30_lines: dict[int, list] = {}
        self._mtf50_scatter: object | None = None
        self._mtf30_scatter: object | None = None
        self._selected_roi: int | None = None
        self._curve_click_guard = False

        # ---- 右：指标表
        table = self._build_table(result, curves, frequency, scale, unit_str,
                                  readouts)
        self._table = table
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.cellClicked.connect(self._on_table_cell_clicked)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(plot)
        splitter.addWidget(table)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # ---- 工具行：标注开关 + 复位视图 + 导出结果 CSV
        self._btn_mtf50 = QPushButton("MTF50")
        self._btn_mtf50.setObjectName("mtf50Btn")
        self._btn_mtf50.setCheckable(True)
        self._btn_mtf50.setToolTip(
            "标出 MTF50 落点：垂线连 x 轴、水平线连 y 轴（选中 ROI 时仅标该 ROI）"
        )
        self._btn_mtf30 = QPushButton("MTF30")
        self._btn_mtf30.setObjectName("mtf30Btn")
        self._btn_mtf30.setCheckable(True)
        self._btn_mtf30.setToolTip(
            "标出 MTF30 落点：垂线连 x 轴、水平线连 y 轴（选中 ROI 时仅标该 ROI）"
        )
        self._btn_reset = QPushButton("复位视图")
        self._btn_reset.setObjectName("resetViewBtn")
        self._btn_reset.setToolTip("将曲线图还原到初始坐标范围")

        export_btn = QPushButton("导出结果 CSV…")
        export_btn.setObjectName("exportCsvBtn")
        export_btn.setToolTip(
            "导出为模组比较用的 MTF 结果 CSV（含口径元数据与逐 ROI 指标）"
        )
        export_btn.clicked.connect(self._export_csv)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._btn_mtf50)
        toolbar.addWidget(self._btn_mtf30)
        toolbar.addWidget(self._btn_reset)
        toolbar.addStretch(1)
        toolbar.addWidget(export_btn)
        layout.addLayout(toolbar)

        layout.addWidget(verdict)
        layout.addWidget(subtitle)
        layout.addWidget(splitter, stretch=1)

        self._plot_curves(plot, curves, scale)
        self._build_markers(plot, curves, scale)
        self._btn_mtf50.toggled.connect(self._on_marker_toggled)
        self._btn_mtf30.toggled.connect(self._on_marker_toggled)
        self._btn_reset.clicked.connect(self._reset_view)
        plot.scene().sigMouseClicked.connect(self._on_plot_clicked)
        self._refresh_markers()
        self._refresh_table_columns()

    # ------------------------------------------------------------ 绘图

    def _plot_curves(self, plot: pg.PlotWidget, curves: list[dict],
                     scale: float = 1.0) -> None:
        """绘制 MTF 曲线，并记录曲线 item 与配色（供 ROI 选中高亮）。"""
        for curve in curves:
            roi = curve["roi"]
            color = _CURVE_COLORS[(roi - 1) % len(_CURVE_COLORS)]
            style = _CHANNEL_STYLES[
                hash(curve["channel"]) % len(_CHANNEL_STYLES)
            ]
            name = f"ROI{roi} {curve['channel']}"
            if not curve.get("valid") or not curve.get("freq"):
                continue
            item = plot.plot(
                [f * scale for f in curve["freq"]], curve["mtf"],
                pen=pg.mkPen(color, width=2, style=style), name=name,
            )
            item.setCurveClickable(True, width=8)
            item.sigClicked.connect(lambda *args, r=roi: self._on_curve_clicked(r))
            self._curve_items[roi] = item
            self._curve_colors[roi] = color
            self._curve_styles[roi] = style

    def _build_markers(self, plot: pg.PlotWidget, curves: list[dict],
                       scale: float = 1.0) -> None:
        """预建 MTF50 / MTF30 落点数据与垂线/水平线（可见性由 _refresh_markers 控制）。"""
        for curve in curves:
            color = _CURVE_COLORS[(curve["roi"] - 1) % len(_CURVE_COLORS)]
            if not curve.get("valid") or not curve.get("freq"):
                continue
            roi = curve["roi"]
            mtf50 = curve.get("mtf50", 0.0)
            if mtf50 > 0:
                x = mtf50 * scale
                self._mtf50_points[roi] = (x, 0.5, color)
                self._mtf50_lines[roi] = self._drop_lines(plot, x, 0.5, color)
            mtf30 = self._curve_mtf30(curve)
            if mtf30 > 0:
                x = mtf30 * scale
                self._mtf30_points[roi] = (x, 0.3, color)
                self._mtf30_lines[roi] = self._drop_lines(plot, x, 0.3, color)
        # 共享散点：图例各一条（MTF50 / MTF30），初始无点、隐藏
        self._mtf50_scatter = pg.ScatterPlotItem(
            symbol="o", size=9, pen=pg.mkPen("w", width=1), name="MTF50",
        )
        plot.addItem(self._mtf50_scatter)
        self._mtf30_scatter = pg.ScatterPlotItem(
            symbol="o", size=9, pen=pg.mkPen("w", width=1), name="MTF30",
        )
        plot.addItem(self._mtf30_scatter)

    @staticmethod
    def _drop_lines(plot: pg.PlotWidget, x: float, y: float,
                    color: str) -> list:
        """落点 → x 轴的垂线 + → y 轴的水平线（虚线、曲线同色，不进图例）。"""
        vline = plot.plot([x, x], [0.0, y],
                          pen=pg.mkPen(color, width=1,
                                       style=Qt.PenStyle.DashLine))
        hline = plot.plot([0.0, x], [y, y],
                          pen=pg.mkPen(color, width=1,
                                       style=Qt.PenStyle.DashLine))
        return [vline, hline]

    @staticmethod
    def _curve_mtf30(curve: dict) -> float:
        """由曲线 freq/mtf 现算 MTF30（MTF=0.3 处的频率，cy/px，配置无关）。"""
        freq = curve.get("freq") or []
        mtf = curve.get("mtf") or []
        if len(freq) < 2 or len(mtf) < 2:
            return 0.0
        try:
            arr = np.column_stack([np.asarray(freq, dtype=float),
                                   np.asarray(mtf, dtype=float)])
            return float(compute_mtf_metrics(arr, ("mtf30",))["mtf30"])
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------ 交互

    def _on_curve_clicked(self, roi: int) -> None:
        """点击曲线：置守卫标志（避免随后 scene 点击误判为空白）并选中。"""
        self._curve_click_guard = True
        self._select_roi(roi)

    def _on_plot_clicked(self, event) -> None:
        """点击图中空白处 → 取消选中（曲线点击已由 sigClicked 处理）。"""
        if self._curve_click_guard:
            self._curve_click_guard = False
            return
        self._select_roi(None)

    def _on_table_cell_clicked(self, row: int, column: int) -> None:  # noqa: ARG002
        curves = self._curves
        if 0 <= row < len(curves):
            self._select_roi(curves[row]["roi"])

    def _select_roi(self, roi: int | None) -> None:
        """选中某 ROI（None 或再次点击同一 ROI → 取消）；高亮其曲线、淡化其余。"""
        if roi == self._selected_roi:
            roi = None
        self._selected_roi = roi
        self._apply_selection()
        self._sync_table_selection(roi)
        self._refresh_markers()

    def _apply_selection(self) -> None:
        for r, item in self._curve_items.items():
            color = self._curve_colors[r]
            style = self._curve_styles[r]
            if self._selected_roi is None:
                item.setPen(pg.mkPen(color, width=2, style=style))
                item.setZValue(0)
            elif r == self._selected_roi:
                item.setPen(pg.mkPen(color, width=3, style=style))
                item.setZValue(10)
            else:
                dim = QColor(color)
                dim.setAlpha(80)
                item.setPen(pg.mkPen(dim, width=1, style=style))
                item.setZValue(0)

    def _sync_table_selection(self, roi: int | None) -> None:
        """联动右侧指标表：高亮选中 ROI 的行（阻断信号，避免递归触发）。"""
        table = getattr(self, "_table", None)
        if table is None:
            return
        table.blockSignals(True)
        try:
            if roi is None:
                table.clearSelection()
                return
            for row in range(table.rowCount()):
                item = table.item(row, 0)
                if item is not None and item.text() == f"ROI{roi}":
                    table.selectRow(row)
                    return
        finally:
            table.blockSignals(False)

    def _on_marker_toggled(self, *args) -> None:  # noqa: ARG002
        """MTF50/MTF30 按钮切换：同步刷新曲线标注与表格列显隐。"""
        self._refresh_markers()
        self._refresh_table_columns()

    def _refresh_markers(self, *args) -> None:  # noqa: ARG002
        """按按钮开关 + 当前 ROI 选中，刷新 MTF50/MTF30 落点与连线可见性。

        无选中 ROI 时标注全部曲线；选中某 ROI 时仅标注该 ROI 的落点。
        """
        self._apply_marker_type(
            self._btn_mtf50.isChecked(), self._mtf50_points,
            self._mtf50_lines, self._mtf50_scatter,
        )
        self._apply_marker_type(
            self._btn_mtf30.isChecked(), self._mtf30_points,
            self._mtf30_lines, self._mtf30_scatter,
        )

    def _apply_marker_type(self, checked: bool, points: dict, lines: dict,
                           scatter) -> None:
        if not checked:
            scatter.setVisible(False)
            for items in lines.values():
                for item in items:
                    item.setVisible(False)
            return
        visible = [r for r in points
                   if self._selected_roi is None or r == self._selected_roi]
        if visible:
            xs, ys, brushes = [], [], []
            for r in sorted(visible):
                x, y, color = points[r]
                xs.append(x)
                ys.append(y)
                brushes.append(pg.mkBrush(color))
            scatter.setData(x=xs, y=ys, brush=brushes, symbol="o", size=9,
                            pen=pg.mkPen("w", width=1))
            scatter.setVisible(True)
        else:
            scatter.setVisible(False)
        visible_set = set(visible)
        for r, items in lines.items():
            for item in items:
                item.setVisible(r in visible_set)

    def _reset_view(self) -> None:
        """复位视图：曲线图回到初始坐标范围（不影响选中与标注开关）。"""
        self._plot.setXRange(self._init_x[0], self._init_x[1], padding=0.02)
        self._plot.setYRange(self._init_y[0], self._init_y[1], padding=0)

    def _refresh_table_columns(self) -> None:
        """让指标表的 MTF50 / MTF30 列跟随标注开关显隐。

        规则：MTF50 列由「MTF50」按钮控制，MTF30 列由「MTF30」按钮控制；
        但当 Readout1 = 50 / 30 时，该列即 Readout1 判定列，始终显示（开关不隐藏）。
        """
        table = self._table
        headers = {
            table.horizontalHeaderItem(i).text(): i
            for i in range(table.columnCount())
        }
        mtf50_col = headers.get(f"MTF50 ({self._unit_str})")
        mtf30_col = headers.get(f"MTF30 ({self._unit_str})")
        if mtf50_col is not None:
            show = self._btn_mtf50.isChecked() or self._readout1_key == "mtf50"
            table.setColumnHidden(mtf50_col, not show)
        if mtf30_col is not None:
            show = self._btn_mtf30.isChecked() or self._readout1_key == "mtf30"
            table.setColumnHidden(mtf30_col, not show)

    # ------------------------------------------------------------ 表格

    @staticmethod
    def _build_table(result: dict, curves: list[dict], frequency,
                     scale: float = 1.0, unit_str: str = "cy/px",
                     readouts: list[dict] | None = None) -> QTableWidget:
        metrics = result.get("metrics", {})
        readouts = readouts or []
        freq1 = frequency[0]

        headers = ["ROI", "通道", f"MTF @ {freq1 * scale:g}",
                   f"MTF50 ({unit_str})"]
        headers += [f"{r['label']} ({unit_str})" for r in readouts]
        headers.append("判定")
        table = QTableWidget(len(curves), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # 逐 ROI 判定 = 该 ROI 全部判据的与（无效 ROI 记 FAIL）
        roi_status: dict[int, str] = {}
        for key, m in metrics.items():
            label, _, metric = key.partition("_")
            if not label.startswith("ROI") or m["status"] not in ("PASS", "FAIL"):
                continue
            idx = int(label[3:])
            prev = roi_status.get(idx, "PASS")
            roi_status[idx] = "FAIL" if m["status"] == "FAIL" else prev

        fail_color = QColor("#c0504d")
        pass_color = QColor("#1e8a57")
        for row, curve in enumerate(curves):
            idx = curve["roi"]
            sfr = curve.get("sfr", [float("nan")])
            readout_vals = curve.get("readouts", [])
            values = [
                f"ROI{idx}",
                curve["channel"],
                f"{sfr[0]:.4f}" if sfr else "—",
                f"{curve.get('mtf50', 0.0) * scale:.4g}" if curve.get("valid") else "—",
            ]
            values += [
                f"{readout_vals[i] * scale:.4g}"
                if curve.get("valid") and i < len(readout_vals) else "—"
                for i in range(len(readouts))
            ]
            values.append(
                ("PASS" if roi_status.get(idx) == "PASS" else "FAIL")
                if curve.get("valid") else "无效"
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == len(values) - 1:
                    if text == "PASS":
                        item.setForeground(pass_color)
                    else:
                        item.setForeground(fail_color)
                table.setItem(row, col, item)
        return table

    # ------------------------------------------------------------ 导出 CSV

    def _export_csv(self) -> None:
        """导出模组比较用 MTF 结果 CSV（mtf_export.write_result_csv）。"""
        from iqtest.analysis.mtf_export import _sanitize, write_result_csv

        details = self._result.get("details", {})
        images = [
            str(r.get("image") or "") for r in details.get("rois", [])
            if r.get("image")
        ]
        default_label = Path(images[0]).stem if images else "MTF"

        label, ok = QInputDialog.getText(
            self, "导出结果 CSV",
            "模组标签（label，显示在模组比较结果的 A/B 表头中）：",
            text=default_label,
        )
        if not ok:
            return
        default_name = f"{_sanitize(label) or 'mtf_result'}_mtf.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 MTF 结果 CSV", default_name, "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            write_result_csv(self._result, path, label=label)
        except Exception as exc:  # noqa: BLE001 — 任何导出错误都应弹窗而非崩溃
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"MTF 结果已保存：\n{path}")
