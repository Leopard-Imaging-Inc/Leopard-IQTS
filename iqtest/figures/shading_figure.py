"""Lens Shading 结果 Figure：RI 热力图 + 四象限数值表 + 逐项判定 + 导出。

作为 content 嵌入 FigureWindow（FigureManager.register_view("shading", ShadingResultView)）。
消费 shading_adapter.analyze_shading 的返回 dict：
    result["metrics"] / ["pass"]        判定指标与总判定（单光源）
    result["details"]["mode"]           single | multi
    result["details"]["report"]         报告通道 shading 网格 + 四象限 RI
    result["details"]["per_channel_ri"] 逐通道四象限 RI（Bayer）
    result["details"]["closed_loop"]    闭环自检（apply_lsc 校正前/后残余 + 校正后数据）
    result["details"]["comparison"]     多光源对比（ri_spread / color_shift_spread）

界面保持全局浅色主题；三个 tab 页内容（标题/文字）使用深色字体以提升可读性。
单光源时提供「亮度通道 / 使用 LSC / RBF 外插」组件，任一变化即通过
shading_adapter.recompute_single 即时重算并刷新内容区（不改主判定）。
勾选 LSC 后额外出现「LSC 验证」Tab（校正前/后对比 + 校正后相对照度热力图），
左侧图区下拉列表按「原始 RAW 图示 → Imatest Luma 等高线 → Imatest Color Shading
等值线 → 相对照度热力图 → LSC 校正后图片」排列（原始/校正后图像为原始 RAW 全分辨率
图，Bayer 输入经 demosaic 显示为彩色、mono 为灰度，可逐像素对照），各图标题第二行
显示测试图片文件名（原始 RAW 图示直接用文件名）。Imatest Luma 等高线以同一份
demosaic 后的原始 RAW 图作底图；Imatest Color Shading 等值线以该图的 BT.709 亮度为
Y0、按 R/G、B/G 归一化比值逐像素调制（Imatest "exaggerated color"，整体偏绿为预期
效果，不做白平衡/去绿）。两张 matplotlib 图均支持滚轮缩放 / 拖拽平移 / 双击复位；
热力图/等高线/等值线叠加 9 个 ROI 采样红框，工具栏可导出其 PNG。
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGraphicsRectItem,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

#: PASS/FAIL 状态色（浅色背景下的醒目色）
_PASS_COLOR = "#1e8a57"
_FAIL_COLOR = "#c0504d"

#: 三个 tab 页标题/文字的深色字体色（与全局 QSS 浅色底对比更醒目）
_HEADING_COLOR = "#1a1d20"

#: 软件主题色（青）
_THEME_COLOR = "#1b9aaa"
_THEME_COLOR_DARK = "#17808e"
_TEXT_DARK = "#2b2f33"

#: 亮度通道选项（与 _report_channel 支持一致；仅单光源展示相关）
REPORT_CHANNELS = ["Y", "G", "Gr"]

#: 三个 tab 页签文字用主题青色
_TABS_QSS = (
    f"QTabBar::tab{{color:{_THEME_COLOR}; padding:5px 12px; font-weight:600;}}"
    f"QTabBar::tab:selected{{color:{_THEME_COLOR_DARK}; font-weight:700;}}"
)

#: 结果界面后处理复选框：文字深色、勾选框青色边框、勾选后青色填充
_CHECK_QSS = (
    f"QCheckBox{{color:{_TEXT_DARK}; spacing:6px; background:transparent;}}"
    f"QCheckBox::indicator{{width:15px; height:15px;"
    f"border:2px solid {_THEME_COLOR}; border-radius:3px; background:#ffffff;}}"
    f"QCheckBox::indicator:checked{{background:{_THEME_COLOR};}}"
    f"QCheckBox::indicator:disabled{{border-color:#c9d1d7; background:#f0f2f4;}}"
)


def _status_color(text: str) -> str:
    if text == "PASS":
        return _PASS_COLOR
    if text == "FAIL":
        return _FAIL_COLOR
    return "#2b2f33"


def _fmt_value(value, decimals: int = 4) -> str:
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.atleast_1d(value)
        parts = []
        for v in arr:
            try:
                parts.append(f"{float(v):.{decimals}f}")
            except (TypeError, ValueError):
                parts.append(str(v))
        return ", ".join(parts)
    if value is None:
        return "—"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _heading(text: str) -> QLabel:
    """tab 页标题：深色字体，浅色底上更醒目。"""
    label = QLabel(text)
    label.setStyleSheet(f"color:{_HEADING_COLOR}; font-weight:700;")
    return label


def _pg_title(name: str, file_label) -> str:
    """pyqtgraph 图标题：第一行说明 + 第二行测试图片文件名（无文件名时只显示说明）。

    pyqtgraph 标题走 HTML（``QGraphicsTextItem.setHtml``），换行须用 ``<br>``。
    """
    label = str(file_label or "")
    if not label:
        return name
    return f"{escape(name)}<br>{escape(label)}"


def _mpl_title(name: str, file_label) -> str:
    """matplotlib 图标题：第一行说明 + 第二行测试图片文件名（无文件名时只显示说明）。"""
    label = str(file_label or "")
    return f"{name}\n{label}" if label else name


def _add_roi_boxes_pg(plot, boxes: dict | None) -> None:
    """在 pyqtgraph 视图上叠加 9 个 ROI 采样红框（与热力图同一网格坐标系）。"""
    for x0, x1, y0, y1 in (boxes or {}).values():
        rect = QGraphicsRectItem(x0, y0, x1 - x0, y1 - y0)
        rect.setPen(pg.mkPen("red", width=1))
        plot.addItem(rect)


def _make_zoomable_canvas(fig, ax, home_lims):
    """把 matplotlib 画布包装为可缩放画布，手感与 pyqtgraph 图表一致。

    滚轮以光标位置为锚点缩放（上滚放大 / 下滚缩小）、左键拖拽平移、双击复位到
    ``home_lims``；``home_lims`` 为 ``(x0, x1, y0, y1)``，为 None 时不启用交互。
    """
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    class _ZoomableCanvas(FigureCanvasQTAgg):
        def __init__(self) -> None:
            super().__init__(fig)
            self._ax = ax
            self._home = tuple(float(v) for v in home_lims) if home_lims else None
            self._drag_origin = None
            self._drag_lims = None

        def _lims(self):
            x0, x1 = self._ax.get_xlim()
            y0, y1 = self._ax.get_ylim()
            return x0, x1, y0, y1

        def _apply(self, x0, x1, y0, y1) -> None:
            self._ax.set_xlim(x0, x1)
            self._ax.set_ylim(y0, y1)
            self.draw_idle()

        def _data_at(self, x: float, y: float):
            """Qt 控件坐标（y 轴向下）→ matplotlib 数据坐标。"""
            return self._ax.transData.inverted().transform((x, self.height() - y))

        def wheelEvent(self, event) -> None:
            if self._home is None or not event.angleDelta().y():
                super().wheelEvent(event)
                return
            factor = 0.8 if event.angleDelta().y() > 0 else 1.25
            point = event.position()
            xdata, ydata = self._data_at(point.x(), point.y())
            x0, x1, y0, y1 = self._lims()
            nx0, nx1 = xdata + (x0 - xdata) * factor, xdata + (x1 - xdata) * factor
            ny0, ny1 = ydata + (y0 - ydata) * factor, ydata + (y1 - ydata) * factor
            # 缩到极限即停止，避免跨度退化为 0 后视图空白
            if abs(nx1 - nx0) < 1e-3 or abs(ny1 - ny0) < 1e-3:
                return
            self._apply(nx0, nx1, ny0, ny1)
            event.accept()

        def mousePressEvent(self, event) -> None:
            if self._home is None or event.button() != Qt.MouseButton.LeftButton:
                super().mousePressEvent(event)
                return
            self._drag_origin = (event.position().x(), event.position().y())
            self._drag_lims = self._lims()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

        def mouseMoveEvent(self, event) -> None:
            if self._drag_origin is None:
                super().mouseMoveEvent(event)
                return
            x0, x1, y0, y1 = self._drag_lims
            dx = event.position().x() - self._drag_origin[0]
            dy = event.position().y() - self._drag_origin[1]
            # 图像跟随光标：横向反向、纵向同向（y 轴方向不影响该结论）
            sx = -(x1 - x0) * dx / max(1, self.width())
            sy = (y1 - y0) * dy / max(1, self.height())
            self._apply(x0 + sx, x1 + sx, y0 + sy, y1 + sy)

        def mouseReleaseEvent(self, event) -> None:
            if self._drag_origin is not None:
                self._drag_origin = None
                self._drag_lims = None
                self.unsetCursor()
                return
            super().mouseReleaseEvent(event)

        def mouseDoubleClickEvent(self, event) -> None:
            if self._home is not None:
                self._apply(*self._home)
            super().mouseDoubleClickEvent(event)

    return _ZoomableCanvas()


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
            item = QTableWidgetItem(_fmt_value(value))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status_col is not None and c == status_col and str(value) in ("PASS", "FAIL"):
                item.setForeground(pg.mkColor(_status_color(str(value))))
            table.setItem(r, c, item)
    return table


class ShadingResultView(QWidget):
    """Lens Shading 模块结果视图。

    单光源（有 avg/alg_config）时启用「亮度通道 / 使用 LSC / RBF 外插」组件，
    变化即时重算内容区。multi 分支无重算能力，组件禁用。
    """

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result = result
        self._content: QWidget | None = None
        self._content_layout: QVBoxLayout | None = None
        self._channel_combo: QComboBox | None = None
        self._lsc_check: QCheckBox | None = None
        self._rbf_check: QCheckBox | None = None
        self._export_profile_btn: QPushButton | None = None
        self._save_corrected_btn: QPushButton | None = None
        self._left_combo: QComboBox | None = None

        # ---- 固定外层布局（组件 + 工具栏不变，仅内容区重建）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        ctrl = QHBoxLayout()
        ctrl.setContentsMargins(0, 0, 0, 4)
        self._build_controls(ctrl)
        outer.addLayout(ctrl)

        self._toolbar = QHBoxLayout()
        self._build_toolbar()
        outer.addLayout(self._toolbar)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)
        outer.addWidget(self._content, stretch=1)

        self._build_content()

    # ------------------------------------------------------------ 控制行

    def _build_controls(self, bar: QHBoxLayout) -> None:
        details = self._result.get("details", {})
        can_recalc = details.get("avg") is not None and details.get("alg_config") is not None

        bar.addWidget(QLabel("亮度通道"))
        self._channel_combo = QComboBox()
        self._channel_combo.addItems(REPORT_CHANNELS)
        cur = str(details.get("luminance_channel", "Y"))
        idx = self._channel_combo.findText(cur)
        self._channel_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._channel_combo.setEnabled(can_recalc)
        self._channel_combo.currentTextChanged.connect(self._on_recalc_triggered)
        bar.addWidget(self._channel_combo)

        # LSC 闭环验证默认关闭
        self._lsc_check = QCheckBox("LSC")
        self._lsc_check.setChecked(False)
        self._lsc_check.setEnabled(can_recalc)
        self._lsc_check.setStyleSheet(_CHECK_QSS)
        self._lsc_check.toggled.connect(self._on_recalc_triggered)
        bar.addWidget(self._lsc_check)

        self._rbf_check = QCheckBox("RBF 外插")
        self._rbf_check.setChecked(bool(details.get("alg_config", {}).get("support_extrapolation", False)))
        self._rbf_check.setEnabled(can_recalc)
        self._rbf_check.setStyleSheet(_CHECK_QSS)
        self._rbf_check.toggled.connect(self._on_recalc_triggered)
        bar.addWidget(self._rbf_check)

        bar.addStretch(1)

    def _build_toolbar(self) -> None:
        details = self._result.get("details", {})
        mode = details.get("mode", "single")
        self._export_profile_btn = QPushButton("导出 shading_profile…")
        self._export_profile_btn.setToolTip(
            "导出当前（按结果界面选择）的 shading_profile（通用参考数据：npy / CSV / PNG，"
            "非可烧录 OTP 表）"
        )
        self._export_profile_btn.setEnabled(mode == "single")
        self._export_profile_btn.clicked.connect(self._export_profile)
        export_csv_btn = QPushButton("导出结果 CSV…")
        export_csv_btn.clicked.connect(self._export_result_csv)
        # 校正后图片：仅在勾选「使用 LSC」且已生成校正图后可用（查看请用左下角下拉列表）
        self._save_corrected_btn = QPushButton("保存校正后图片…")
        self._save_corrected_btn.setToolTip(
            "将 LSC 校正后图像保存为 PNG（需勾选「LSC」，按数据范围归一化）"
        )
        self._save_corrected_btn.clicked.connect(self._save_corrected_image)
        self._toolbar.addWidget(self._export_profile_btn)
        self._toolbar.addWidget(export_csv_btn)
        self._toolbar.addWidget(self._save_corrected_btn)
        self._toolbar.addStretch(1)

    def _on_recalc_triggered(self, *_args) -> None:
        """组件变化 → recompute_single → 刷新内容区。"""
        from iqtest.analysis.shading_adapter import recompute_single

        prev = {
            "channel": self._channel_combo.currentText(),
            "lsc": self._lsc_check.isChecked(),
            "rbf": self._rbf_check.isChecked(),
        }
        try:
            self._result = recompute_single(
                self._result,
                support_extrapolation=prev["rbf"],
                enable_lsc_verify=prev["lsc"],
                luminance_channel=prev["channel"],
            )
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "重算失败", str(exc))
            self._channel_combo.blockSignals(True)
            self._lsc_check.blockSignals(True)
            self._rbf_check.blockSignals(True)
            self._channel_combo.setCurrentText(prev["channel"])
            self._lsc_check.setChecked(prev["lsc"])
            self._rbf_check.setChecked(prev["rbf"])
            self._channel_combo.blockSignals(False)
            self._lsc_check.blockSignals(False)
            self._rbf_check.blockSignals(False)
            return
        self._build_content()

    # ------------------------------------------------------------ 内容区构建

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)  # 立即脱离父级，避免 findChild 命中旧控件
                w.deleteLater()
            else:
                sub = item.layout()
                if sub is not None:
                    ShadingResultView._clear_layout(sub)

    def _build_content(self) -> None:
        """重建内容区（verdict + subtitle + plot + tabs），不触碰组件/工具栏。"""
        self._clear_layout(self._content_layout)

        result = self._result
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

        plot = self._build_left_panel(details) if mode == "single" else None
        tabs = self._build_tabs(details)

        self._content_layout.addWidget(verdict)
        self._content_layout.addWidget(subtitle)
        if plot is not None:
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.addWidget(plot)
            splitter.addWidget(tabs)
            splitter.setStretchFactor(0, 3)
            splitter.setStretchFactor(1, 2)
            self._content_layout.addWidget(splitter, stretch=1)
        else:
            self._content_layout.addWidget(tabs, stretch=1)
        self._update_corrected_buttons(details)

    # ------------------------------------------------------------ 副标题

    @staticmethod
    def _subtitle(details: dict) -> str:
        mode = details.get("mode", "single")
        cfa = "、".join(details.get("channels") or ["Y"])
        bin_size = details.get("bin_size")
        criteria = details.get("criteria") or {}
        chan = details.get("luminance_channel", "Y")
        rbf = bool((details.get("alg_config") or {}).get("support_extrapolation", False))
        parts = [
            f"光源：{details.get('light_source', '—')}",
            f"CFA：{cfa}",
            f"bin_size：{bin_size}",
            f"亮度通道：{chan}",
            f"RBF 外插：{'开' if rbf else '关'}",
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

    @staticmethod
    def _make_shading_heatmap(shading_map, title: str, boxes: dict | None = None):
        """归一化 shading 网格 → viridis 热力图（含四象限分界线 + 9 个 ROI 红框）。"""
        plot = pg.PlotWidget(background="w")
        plot.setAspectLocked(True)
        plot.showGrid(x=True, y=True, alpha=0.2)
        plot.setLabel("bottom", "网格 x")
        plot.setLabel("left", "网格 y")
        plot.setTitle(title)

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
        _add_roi_boxes_pg(plot, boxes)
        plot.setXRange(0, w, padding=0.01)
        plot.setYRange(0, h, padding=0.01)
        return plot

    def _build_heatmap(self, details: dict):
        report = details.get("report") or {}
        shading_map = report.get("shading_map")
        if shading_map is None:
            return None
        title = _pg_title(
            f"Contrastive Illuminance Heat Map ({report.get('channel', 'Y')})",
            details.get("file_label"),
        )
        return self._make_shading_heatmap(shading_map, title, report.get("boxes"))

    @staticmethod
    def _make_raw_image_plot(image, title: str) -> QWidget:
        """原始 RAW 展示图（校正前 / 校正后）。

        Bayer 输入为 demosaic 后彩色图 (H, W, 3)；mono 为灰度图。
        彩色图按 0.5%~99.5% 分位拉伸显示（与 Generalized Read Raw 预览口径一致）。
        """
        plot = pg.PlotWidget(background="w")
        plot.setAspectLocked(True)
        plot.setTitle(title)
        data = np.asarray(image, dtype=np.float64)
        img_item = pg.ImageItem()
        if data.ndim == 3 and data.shape[-1] == 3:
            finite = data[np.isfinite(data)]
            lo = float(np.percentile(finite, 0.5)) if finite.size else 0.0
            hi = float(np.percentile(finite, 99.5)) if finite.size else 1.0
            if hi <= lo:
                hi = lo + 1e-6
            norm = np.clip((data - lo) / (hi - lo), 0.0, 1.0)
            norm = np.where(np.isfinite(data), norm, 0.0)
            # ImageItem 默认 axisOrder='col-major'（第一维为 x），故 (H,W,3) → (W,H,3)
            rgb = norm.transpose(1, 0, 2)
            img_item.setImage((rgb * 255.0).round().astype(np.uint8))
        else:
            finite = data[np.isfinite(data)]
            lo = float(finite.min()) if finite.size else 0.0
            hi = float(finite.max()) if finite.size else 1.0
            if hi <= lo:
                hi = lo + 1e-6
            safe = np.where(np.isfinite(data), data, lo)
            img_item.setLookupTable(
                pg.colormap.getFromMatplotlib("gray").getLookupTable(0.0, 1.0, 256)
            )
            img_item.setImage(safe.T, levels=(lo, hi))
        plot.addItem(img_item)
        return plot

    def _build_left_panel(self, details: dict) -> QWidget:
        """左侧结果图切换面板：原始 RAW/校正后图像 + Imatest 结果图 + 相对照度热力图。"""
        imatest = details.get("imatest") or {}
        has_color = imatest.get("color") is not None
        closed_loop = details.get("closed_loop") or {}
        source_image = details.get("source_image")
        file_label = str(details.get("file_label") or "")
        corrected_image = (
            closed_loop.get("corrected_image") if closed_loop.get("enabled") else None
        )

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 选项文本与 stack 页顺序严格一一对应
        options: list[str] = []
        stack = QStackedWidget()

        if source_image is not None:
            options.append("原始 RAW 图示")
            # 标题直接显示测试图片文件名（用于与 LSC 校正后图片对照）
            stack.addWidget(self._make_raw_image_plot(
                source_image, escape(file_label) if file_label else "原始 RAW 图示"
            ))
        if imatest.get("luma"):
            options.append("Imatest Luma 等高线")
            # 底图用「原始 RAW 图示」同一份 demosaic 图，便于与等值线逐像素对照
            stack.addWidget(self._make_luma_contour(imatest["luma"], source_image))
        if has_color:
            options.append("Imatest Color Shading 等值线")
            # 底色用「原始 RAW 图示」同一份 demosaic 图求亮度 Y0，再按 R/G、B/G 比值调制
            stack.addWidget(self._make_color_contour_widget(imatest["color"], source_image))
        heatmap = self._build_heatmap(details)
        if heatmap is not None:
            options.append("相对照度热力图")
            stack.addWidget(heatmap)
        if corrected_image is not None:
            options.append("LSC 校正后图片")
            stack.addWidget(self._make_raw_image_plot(
                corrected_image, _pg_title("After LSC", file_label)
            ))

        combo = QComboBox()
        combo.addItems(options)
        combo.currentIndexChanged.connect(stack.setCurrentIndex)
        self._left_combo = combo

        layout.addWidget(combo)
        layout.addWidget(stack, stretch=1)
        return panel

    # ------------------------------------------------------------ Tabs

    def _build_tabs(self, details: dict) -> QTabWidget:
        tabs = QTabWidget()
        tabs.setStyleSheet(_TABS_QSS)
        mode = details.get("mode", "single")
        if mode == "single":
            tabs.addTab(self._tab_quadrant_widget(details), "四象限 RI")
            if (self._result.get("metrics") or {}).get("green_red_shift") is not None \
               or (self._result.get("metrics") or {}).get("green_blue_shift") is not None:
                tabs.addTab(self._tab_color_shift(), "Color shift")
            if details.get("imatest"):
                tabs.addTab(self._tab_imatest_widget(details), "Imatest 对标")
            if details.get("closed_loop"):
                tabs.addTab(
                    self._tab_closed_loop(
                        details["closed_loop"], details.get("file_label")
                    ),
                    "LSC 验证",
                )
        else:
            tabs.addTab(self._tab_multi_widget(details), "多光源对比")
            tabs.addTab(self._tab_judgment_multi(details), "逐项判定")
        return tabs

    def _tab_quadrant_widget(self, details: dict) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        report = details.get("report") or {}
        ri = report.get("ri") or {}

        layout.addWidget(_heading(f"Luma Shading（{report.get('channel', 'Y')} 通道）"))
        layout.addWidget(_make_table(
            ["象限", "RI"],
            [["TL", ri.get("tl")], ["TR", ri.get("tr")],
             ["BL", ri.get("bl")], ["BR", ri.get("br")],
             ["ri_diff", report.get("ri_diff")]],
        ))

        per_channel = details.get("per_channel_ri")
        if per_channel:
            layout.addWidget(_heading("Channel Luma Shading（逐通道判定）"))
            layout.addWidget(self._make_per_channel_table(per_channel))

        metrics = self._result.get("metrics") or {}
        ri_diff_metric = metrics.get("ri_diff")
        if ri_diff_metric is not None:
            layout.addWidget(_heading("整体判定"))
            layout.addWidget(_make_table(
                ["指标", "值", "判定"],
                [["ri_diff（四象限离散度）", ri_diff_metric.get("value"),
                  ri_diff_metric.get("status", "INFO")]],
                status_col=2,
            ))
        layout.addStretch(1)
        return page

    @staticmethod
    def _make_per_channel_table(per_channel: dict) -> QTableWidget:
        """Channel Luma 表：行=通道，列=象限，单元格按逐通道判定着色。"""
        channels = per_channel.get("channels") or []
        status = per_channel.get("status") or {}
        quadrants = ("tl", "tr", "bl", "br")
        headers = ["通道", "TL", "TR", "BL", "BR"]
        table = QTableWidget(len(channels), len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, ch in enumerate(channels):
            head = QTableWidgetItem(str(ch))
            head.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            table.setItem(i, 0, head)
            for j, q in enumerate(quadrants):
                vals = per_channel.get(q) or []
                stats = status.get(q) or []
                value = vals[i] if i < len(vals) else None
                st = stats[i] if i < len(stats) else "INFO"
                cell = QTableWidgetItem(_fmt_value(value))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if st in ("PASS", "FAIL"):
                    cell.setForeground(pg.mkColor(_status_color(st)))
                table.setItem(i, j + 1, cell)
        return table

    def _tab_color_shift(self) -> QWidget:
        metrics = self._result.get("metrics") or {}
        gr = metrics.get("green_red_shift")
        gb = metrics.get("green_blue_shift")
        rows = [
            ["green_red_shift", gr.get("value") if gr else None,
             gr.get("status", "INFO") if gr else "N/A"],
            ["green_blue_shift", gb.get("value") if gb else None,
             gb.get("status", "INFO") if gb else "N/A"],
        ]
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(_heading("Color Shading（色度随位置的偏移）"))
        layout.addWidget(_make_table(["指标", "值", "判定"], rows, status_col=2))
        layout.addWidget(QLabel(
            "G/R、G/B 比值在全画面的离散程度，越小表示色度越均匀；仅 Bayer 彩色输入计算。"))
        layout.addStretch(1)
        return page

    def _tab_imatest_widget(self, details: dict) -> QWidget:
        imatest = details.get("imatest") or {}
        luma = imatest.get("luma")
        color = imatest.get("color")

        page = QWidget()
        layout = QVBoxLayout(page)

        if luma:
            layout.addWidget(_heading("Luma 指标（Imatest 口径）"))
            layout.addWidget(self._make_imatest_text(luma["text_block"]))

        if color:
            layout.addWidget(_heading("Color Shading 指标（R/G、B/G、R/B 归一化比值）"))
            layout.addWidget(self._make_imatest_text(color["text_block"]))

        layout.addStretch(1)
        return page

    @staticmethod
    def _make_imatest_text(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(
            f"color:{_TEXT_DARK}; font-family:'Consolas','Courier New',monospace;"
            " font-size:12px; background:#fafbfc; padding:8px;"
            " border:1px solid #e2e6ea;"
        )
        return label

    def _make_color_contour_widget(self, color: dict, source_image=None) -> QWidget:
        """Imatest「Color shading: R/G Pixel ratio Normalized; exaggerated color」对标图。

        四个图层（自下而上）：exaggerated color 底色、白色等值线、9 个 ROI 红框、两行标题。
        底色按 Imatest 口径逐像素调制 ``R'=Y0·rg^α`` / ``G'=Y0`` / ``B'=Y0·bg^α``
        （clip 到 [0,1]）：``Y0`` 取「原始 RAW 图示」同一份 demosaic 全分辨率图的
        BT.709 亮度（同一 0.5%~99.5% 分位拉伸口径，亮度结构与 Imatest Luma 等高线
        底图一致）；``rg``/``bg`` 为比值图，**显示口径与 Imatest 一致：÷全图最大值**
        （与 Luma 等高线 ``norm_map`` 同口径，故等值线标签为 0.70~0.95 一档，与
        Imatest 截图一致；指标层 ``rg_map``/``bg_map`` 仍是"均值=1"，见
        ``compute_imatest_color_metrics``，两者只差一个常数因子、不影响任何指标）。
        比值图先双线性上采样到全分辨率再逐像素调制（不做逐 block 填色，避免马赛克色块）。

        整体偏绿是**预期效果**：本模组中心 R/G≈0.85、B/G≈0.69（÷max 口径）均 < 1，
        R、B 通道被压暗后 G 通道主导（中心饱和橄榄绿、四角更暗）；此处不做白平衡、
        不做通道归一化、不做任何"去绿"处理；γ 与 α 只影响显示，不改变任何数值。

        比值下拉 / 夸大因子 α 变化即时重绘；显示 gamma 取 Lens Shading 面板的 Gamma
        （``color["gamma"]``）。画布支持滚轮缩放 / 左键拖拽平移 / 双击复位。
        数值结果统一在「Imatest 对标」Tab 的 Color Shading 指标中查看；
        本函数只消费 ``compute_imatest_color_metrics`` 的返回 dict，不做任何指标重算。
        """
        from matplotlib.figure import Figure
        from matplotlib.patches import Rectangle

        import cv2

        axisx = np.asarray(color.get("axisx", []), dtype=np.float64)
        axisy = np.asarray(color.get("axisy", []), dtype=np.float64)
        y_norm = np.asarray(color.get("y_norm"), dtype=np.float64)
        #: 比值下拉 → 归一化比值图（指标层：全图均值=1）
        ratio_maps: dict[str, np.ndarray] = {
            "R/G": color.get("rg_map"),
            "B/G": color.get("bg_map"),
            "R/B": color.get("rb_map"),
        }
        #: 显示用比值图：÷全图最大值（Imatest "Normalized" 口径，与 Luma norm_map 一致）
        display_maps: dict[str, np.ndarray | None] = {}
        for key, value in ratio_maps.items():
            if value is None:
                display_maps[key] = None
                continue
            arr = np.asarray(value, dtype=np.float64)
            peak = float(np.nanmax(arr)) if np.isfinite(arr).any() else 0.0
            display_maps[key] = arr / peak if peak else arr
        boxes = color.get("boxes") or {}
        step = float(color.get("contour_step") or 0.05)
        #: 显示 gamma = 面板 Gamma（编码 gamma），仅用于 Y0 的显示重新编码
        gamma = float(color.get("gamma") or 1.0)
        file_label = str(color.get("file_label") or "")

        def y0_base_map() -> np.ndarray:
            """底色的 Y0：demosaic 全分辨率图的 BT.709 亮度（0.5%~99.5% 分位拉伸）。

            与「Imatest Luma 等高线」底图同源同口径，保证两张图亮度结构一致；
            无原图时回退为 block 网格归一化亮度（上采样后同样平滑）。
            """
            if source_image is None:
                return np.clip(np.nan_to_num(y_norm, nan=0.0), 0.0, 1.0)
            rgb = np.asarray(source_image, dtype=np.float64)
            if rgb.ndim == 3 and rgb.shape[-1] >= 3:
                lum = (0.2125 * rgb[:, :, 0] + 0.7154 * rgb[:, :, 1]
                       + 0.0721 * rgb[:, :, 2])
            else:
                lum = np.squeeze(rgb)
            finite = lum[np.isfinite(lum)]
            lo = float(np.percentile(finite, 0.5)) if finite.size else 0.0
            hi = float(np.percentile(finite, 99.5)) if finite.size else 1.0
            if hi <= lo:
                hi = lo + 1e-6
            out = np.clip((lum - lo) / (hi - lo), 0.0, 1.0)
            return np.where(np.isfinite(lum), out, 0.0)

        y0_base = y0_base_map()

        def upsample(data: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
            """双线性上采样到目标尺寸（已是目标尺寸时原样返回）。"""
            if data.shape[0] == target_h and data.shape[1] == target_w:
                return data
            return cv2.resize(
                data.astype(np.float32), (target_w, target_h),
                interpolation=cv2.INTER_LINEAR,
            ).astype(np.float64)

        def exaggerated_color(alpha: float) -> np.ndarray | None:
            """R'=Y0·rg^α, G'=Y0, B'=Y0·bg^α，clip 到 [0,1] 的逐像素渲染图。"""
            rg_raw, bg_raw = display_maps["R/G"], display_maps["B/G"]
            if not y0_base.size or rg_raw is None or bg_raw is None:
                return None
            if source_image is not None:
                target_h, target_w = y0_base.shape[:2]
            else:
                # 无原图：以 block 网格 ×8 为目标，仅保底平滑，正常 Bayer 输入不会走到
                target_h, target_w = y0_base.shape[0] * 8, y0_base.shape[1] * 8
            rg = np.asarray(rg_raw, dtype=np.float64)
            bg = np.asarray(bg_raw, dtype=np.float64)
            # 先上采样到全分辨率再调制；无效比值（掩膜外/非正值）按中性 1.0 填充
            rg_full = upsample(np.where(np.isfinite(rg) & (rg > 0), rg, 1.0),
                               target_h, target_w)
            bg_full = upsample(np.where(np.isfinite(bg) & (bg > 0), bg, 1.0),
                               target_h, target_w)
            y0 = upsample(y0_base, target_h, target_w) ** gamma
            rgb = np.dstack([
                y0 * np.power(rg_full, alpha),
                y0,
                y0 * np.power(bg_full, alpha),
            ])
            return np.clip(rgb, 0.0, 1.0)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        fig = Figure(figsize=(6.0, 3.8), dpi=100)
        fig.patch.set_facecolor("#ffffff")
        ax = fig.add_subplot(111)

        home = None
        if axisx.size and axisy.size:
            dx = axisx[1] - axisx[0] if axisx.size > 1 else 1.0
            dy = axisy[1] - axisy[0] if axisy.size > 1 else 1.0
            # origin="upper" + 反转 extent：row 0 在图像顶部（与采样网格一致）
            home = (axisx[0] - dx / 2, axisx[-1] + dx / 2,
                    axisy[-1] + dy / 2, axisy[0] - dy / 2)

        canvas = _make_zoomable_canvas(fig, ax, home)
        canvas.setMinimumHeight(240)

        ratio_combo = QComboBox()
        ratio_combo.addItems(list(ratio_maps))
        alpha_slider = QSlider(Qt.Orientation.Horizontal)
        alpha_slider.setRange(1, 16)
        alpha_slider.setValue(int(color.get("alpha") or 4))
        alpha_slider.setMinimumWidth(90)
        alpha_value = QLabel(str(alpha_slider.value()))
        alpha_value.setMinimumWidth(20)

        state = {"drawn": False}

        def redraw() -> None:
            key = ratio_combo.currentText()
            ratio_map = display_maps[key]
            alpha = float(alpha_slider.value())

            # 切换比值/夸大因子时保留当前缩放视图（双击仍复位到 home）
            keep = (ax.get_xlim(), ax.get_ylim()) if state["drawn"] else None
            ax.clear()
            ax.set_facecolor("#ffffff")

            if home is not None:
                # 图层 1：exaggerated color 底色（先上采样比值图，再逐像素调制）
                rgb = exaggerated_color(alpha)
                if rgb is not None:
                    ax.imshow(rgb, origin="upper", extent=home,
                              interpolation="bilinear")

                # 图层 2：白色等值线（block 网格，NaN block 由 contour 跳过）
                if ratio_map is not None:
                    data = np.asarray(ratio_map, dtype=np.float64)
                    finite = data[np.isfinite(data)]
                    levels = np.arange(0.70, 1.05, step)
                    if finite.size:
                        levels = levels[(levels >= np.floor(finite.min()))
                                        & (levels <= np.ceil(finite.max()))]
                    if levels.size:
                        gx, gy = np.meshgrid(axisx, axisy)
                        cs = ax.contour(gx, gy, np.ma.masked_invalid(data),
                                        levels=levels, colors="white",
                                        linewidths=0.8)
                        ax.clabel(cs, inline=True, fmt="%.2g", fontsize=8,
                                  colors="white")

                # 图层 3：9 个 ROI 红框（4 角 + 4 边中点 + 1 中心，与采样区域一致）
                for x0, x1, y0b, y1b in boxes.values():
                    ax.add_patch(Rectangle((x0, y0b), x1 - x0, y1b - y0b,
                                           fill=False, edgecolor="red",
                                           linewidth=1))

                lims = keep if keep is not None else ((home[0], home[1]),
                                                     (home[2], home[3]))
                ax.set_xlim(*lims[0])
                ax.set_ylim(*lims[1])

            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_aspect("equal", adjustable="box")
            for spine in ax.spines.values():
                spine.set_color("#e2e6ea")

            # 图层 4：标题两行（指标名 + 原始文件名）
            ax.set_title(
                f"Color shading: {key} Pixel ratio Normalized; exaggerated color\n"
                f"{file_label}",
                fontsize=9, color=_HEADING_COLOR,
            )
            fig.tight_layout()
            canvas.draw_idle()
            state["drawn"] = True

        def on_alpha_changed(_value: int) -> None:
            alpha_value.setText(str(alpha_slider.value()))
            redraw()

        ratio_combo.currentIndexChanged.connect(lambda *_: redraw())
        alpha_slider.valueChanged.connect(on_alpha_changed)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("比值"))
        controls.addWidget(ratio_combo)
        controls.addSpacing(12)
        controls.addWidget(QLabel("夸大因子 α"))
        controls.addWidget(alpha_slider, stretch=1)
        controls.addWidget(alpha_value)

        hint = QLabel("滚轮缩放 · 左键拖拽平移 · 双击复位")
        hint.setStyleSheet(f"color:{_TEXT_DARK}; font-size:11px;")

        layout.addWidget(canvas, stretch=1)
        layout.addLayout(controls)
        layout.addWidget(hint)

        redraw()
        return page

    def _make_luma_contour(self, luma: dict, source_image=None) -> QWidget:
        """Imatest「Y (luminance) contours Normalized」对标图。

        底图为 demosaic 后的原始 RAW 图（``source_image``，与「原始 RAW 图示」同一
        份数据、同一 0.5%~99.5% 分位拉伸口径），坐标与 block 网格对齐；缺省回退为
        灰度归一化 luma 网格。其上叠加白色等值线（带数值标签）与 9 个 ROI 红框，
        标题两行（指标名 + 测试图片文件名），与 Color Shading 等值线图保持一致。
        画布支持滚轮缩放 / 左键拖拽平移 / 双击复位。
        """
        from matplotlib.figure import Figure
        from matplotlib.patches import Rectangle

        norm_map = np.asarray(luma.get("norm_map"), dtype=np.float64)
        axisx = np.asarray(luma.get("axisx"), dtype=np.float64)
        axisy = np.asarray(luma.get("axisy"), dtype=np.float64)

        fig = Figure(figsize=(6.0, 3.8), dpi=100)
        fig.patch.set_facecolor("#ffffff")
        ax = fig.add_subplot(111)
        home = None
        if norm_map.size and axisx.size and axisy.size:
            # 外扩半个 block：使图像边界与 block 像素边界对齐（等值线/红框坐标一致）
            dx = axisx[1] - axisx[0] if axisx.size > 1 else 1.0
            dy = axisy[1] - axisy[0] if axisy.size > 1 else 1.0
            extent = [axisx[0] - dx / 2, axisx[-1] + dx / 2,
                      axisy[0] - dy / 2, axisy[-1] + dy / 2]
            home = (extent[0], extent[1], extent[2], extent[3])

            # 图层 1：底图 = 原始 RAW 展示图（0.5%~99.5% 分位拉伸，与预览一致）
            background = None
            if source_image is not None:
                raw = np.asarray(source_image, dtype=np.float64)
                finite = raw[np.isfinite(raw)]
                lo = float(np.percentile(finite, 0.5)) if finite.size else 0.0
                hi = float(np.percentile(finite, 99.5)) if finite.size else 1.0
                if hi <= lo:
                    hi = lo + 1e-6
                background = np.clip((raw - lo) / (hi - lo), 0.0, 1.0)
                background = np.where(np.isfinite(raw), background, 0.0)
            if background is not None:
                ax.imshow(background, origin="lower", extent=extent,
                          interpolation="bilinear")
            else:
                ax.imshow(norm_map, origin="lower", cmap="gray", extent=extent)

            # 图层 2：白色等值线（block 网格坐标，与底图/红框同一坐标系）
            X, Y = np.meshgrid(axisx, axisy)
            peak = float(np.nanmax(norm_map)) if np.isfinite(np.nanmax(norm_map)) else 1.0
            # 等间距覆盖 [0.125, 0.995] × 峰值：最高一级必须严格低于峰值，否则该级
            # 恰好落在数据上界、matplotlib 会跳过它（表现为中心区域少一条高线）。
            # 0.995 与 Imatest 的最高级 0.99513 一致，中心峰值块周围即出现闭合高线。
            levels = np.linspace(0.125, 0.995, int(luma.get("contour_levels", 10))) \
                * (peak if peak else 1.0)
            contour_map = np.where(np.isfinite(norm_map), norm_map, np.nan)
            cs = ax.contour(X, Y, contour_map, levels=levels, colors="white",
                            linewidths=0.8)
            ax.clabel(cs, inline=True, fontsize=6, colors="white")

            # 图层 3：9 个 ROI 采样红框（与 Luma 九点采样逐像素一致）
            for x0, x1, y0, y1 in (luma.get("boxes") or {}).values():
                ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                                       edgecolor="red", linewidth=1))

            ax.set_xlim(extent[0], extent[1])
            ax.set_ylim(extent[2], extent[3])
            ax.set_xticks([])
            ax.set_yticks([])
        ax.set_title(
            _mpl_title("Y (luminance) contours Normalized", luma.get("file_label")),
            fontsize=9, color=_HEADING_COLOR,
        )
        ax.set_aspect("equal", adjustable="box")
        canvas = _make_zoomable_canvas(fig, ax, home)
        canvas.setMinimumHeight(240)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(canvas, stretch=1)
        hint = QLabel("滚轮缩放 · 左键拖拽平移 · 双击复位")
        hint.setStyleSheet(f"color:{_TEXT_DARK}; font-size:11px;")
        layout.addWidget(hint)
        return page

    def _tab_closed_loop(self, closed_loop: dict,
                         file_label: str | None = None) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        if not closed_loop.get("enabled"):
            note = QLabel(closed_loop.get("note", "LSC 验证不可用"))
            note.setStyleSheet("color:#2b2f33;")
            layout.addWidget(note)
            layout.addStretch(1)
            return page

        layout.addWidget(_heading("校正前后残余对比"))
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

        # 校正后测试数据（用 profile 自检得到的残余结果）
        after_report = closed_loop.get("after_report") or {}
        channel = after_report.get("channel") or closed_loop.get("luminance_channel", "Y")
        ri = after_report.get("ri") or {}
        if ri:
            layout.addWidget(_heading(f"校正后四象限 RI（{channel} 通道）"))
            layout.addWidget(_make_table(
                ["象限", "RI"],
                [["TL", ri.get("tl")], ["TR", ri.get("tr")],
                 ["BL", ri.get("bl")], ["BR", ri.get("br")],
                 ["ri_diff", after_report.get("ri_diff")]],
            ))
        shading_map = after_report.get("shading_map")
        if shading_map is not None:
            layout.addWidget(_heading("校正后相对照度热力图"))
            heatmap = self._make_shading_heatmap(
                shading_map,
                _pg_title(f"After LSC Contrastive Illuminance ({channel})", file_label),
                after_report.get("boxes"),
            )
            heatmap.setMinimumHeight(320)
            layout.addWidget(heatmap)
        layout.addStretch(1)
        return page

    def _tab_multi_widget(self, details: dict) -> QWidget:
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
        layout.addWidget(_heading("各光源对比"))
        layout.addWidget(_make_table(
            ["光源", "最差 RI", "G/R 偏移", "G/B 偏移", "判定"],
            rows, status_col=4,
        ))
        layout.addWidget(_heading("跨光源一致性"))
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

    def _corrected_image(self):
        """当前结果中 LSC 校正后图像（未勾选 LSC 时为 None）。"""
        closed_loop = (self._result.get("details") or {}).get("closed_loop") or {}
        if not closed_loop.get("enabled"):
            return None
        return closed_loop.get("corrected_image")

    def _update_corrected_buttons(self, details: dict) -> None:
        """按当前结果是否含校正后图像，同步校正后图片保存按钮可用状态。"""
        if self._save_corrected_btn is None:
            return
        self._save_corrected_btn.setEnabled(self._corrected_image() is not None)

    def _save_corrected_image(self) -> None:
        from iqtest.analysis.shading_export import save_corrected_image

        image = self._corrected_image()
        if image is None:
            QMessageBox.information(self, "保存校正后图片", "请先勾选「LSC」再保存校正后图片")
            return
        details = self._result.get("details") or {}
        images = list((details.get("image_sizes") or {}).keys())
        default = f"{Path(images[0]).stem}_corrected.png" if images else "lsc_corrected.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存校正后图片", default, "PNG 图片 (*.png)"
        )
        if not path:
            return
        try:
            save_corrected_image(image, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(self, "保存完成", f"校正后图片已保存：\n{path}")

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
        # 标签默认取首张图文件名，不再单独弹窗询问（直接进保存对话框）
        label = Path(images[0]).stem if images else "Shading"
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
