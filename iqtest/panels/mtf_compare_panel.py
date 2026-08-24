"""MTF 模组比较面板：N 款镜头 MTF 结果 CSV 的加载、校验、配对与比较。

入口：主窗口品牌栏 🛠 Utilities →「MTF 模组比较…」（非模态对话框）。
设计文档：doc/LeopardIQ-IQ测试软件-模组性能比较MTF.md §5/§6.2。

**基准金样模式（2026-08-17，N ≥ 2）**：第一款（或用户单选）为基准
（金样），其余各款分别与基准跑 pairwise `compare()`；图表为 N 条折线
+ 每位置分组 Δ 条形（相对基准）；结论区按「vs 基准」逐款输出。

面板布局（左窄右宽、图表为主）：
    左栏：1 比较数据（动态槽位列表 + 基准单选）/ 2 ROI 配对预览
    右栏：3 比较测试项 + 4 打平阈值与评分权重（并排）
          5 比较图表（含执行比较按钮）/ 6 比较结论
    底部：保存比较结果 CSV… / 关闭
"""

from __future__ import annotations

from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iqtest.analysis import mtf_compare
from iqtest.panels.mtf_compare_charts import _ZONE_ORDER, render_compare_charts

#: 槽位数量限制
_MIN_SLOTS = 2
_MAX_SLOTS = 6
_SLOT_LETTERS = "abcdef"


class MtfCompareDialog(QDialog):
    """MTF 模组比较对话框（Utilities → MTF 模组比较…），基准金样模式。"""

    #: 比较完成信号：携带首组（基准 vs 第 1 款非基准）compare 结果 dict
    compared = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MTF 模组比较")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1180, 800)

        self._slots: list[dict] = []        # 槽位列表（key/data/error/widgets）
        self._ref_group = QButtonGroup(self)  # 基准（金样）单选
        self._metric_rows: list[dict] = []
        self._main_group = QButtonGroup(self)
        self._last_result: dict | None = None   # 首组 pairwise 结果（兼容/图表）
        self._last_results: list[dict] = []     # 全部 vs 基准 pairwise 结果
        self._chart_ctx: dict | None = None     # 图表上下文（多款公共匹配）

        layout = QVBoxLayout(self)
        body = QHBoxLayout()

        # ================ 左栏（窄）：1 比较数据 + 2 ROI 配对预览
        left_col = QVBoxLayout()

        # ---- 1 比较数据槽位（动态列表，基准单选）
        slots_box = QGroupBox("1 比较数据（MTF 结果 CSV，单选基准/金样）")
        self._slots_area = QVBoxLayout(slots_box)
        for letter in _SLOT_LETTERS[:_MIN_SLOTS]:
            self._add_slot(letter)
        add_row = QHBoxLayout()
        self._add_btn = QPushButton("＋ 添加模组 CSV 槽位")
        self._add_btn.setObjectName("addSlotBtn")
        self._add_btn.clicked.connect(self._on_add_slot)
        add_row.addWidget(self._add_btn)
        add_row.addStretch(1)
        self._slots_area.addLayout(add_row)
        self._status = QLabel("请载入至少两款模组的 MTF 结果 CSV")
        self._status.setObjectName("compareStatus")
        self._status.setWordWrap(True)
        self._slots_area.addWidget(self._status)
        left_col.addWidget(slots_box)

        # ---- 2 配对预览（3×3 视场位置）
        pair_box = QGroupBox("2 ROI 配对预览（按视场位置）")
        pair_layout = QVBoxLayout(pair_box)
        self._pair_table = QTableWidget(len(_ZONE_ORDER), 4)
        self._pair_table.setObjectName("pairTable")
        self._pair_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._pair_table.verticalHeader().setVisible(False)
        self._pair_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (_, name) in enumerate(_ZONE_ORDER):
            item = QTableWidgetItem(name)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pair_table.setItem(row, 0, item)
        self._rebuild_pair_header()
        pair_layout.addWidget(self._pair_table)
        left_col.addWidget(pair_box, stretch=1)  # 左栏下方无其他模块，占满

        left_holder = QWidget()
        left_holder.setLayout(left_col)
        left_holder.setFixedWidth(400)
        body.addWidget(left_holder)

        # ================ 右栏（宽）：3 测试项 + 4 阈值并排在上，
        # 5 比较图表（含执行比较按钮）居中，6 比较结论在图表下方
        right_col = QVBoxLayout()
        config_row = QHBoxLayout()

        # ---- 3 比较测试项（各 CSV 指标列交集）
        metric_box = QGroupBox("3 比较测试项（勾选参与比较的指标，单选主判定项）")
        self._metric_area = QVBoxLayout(metric_box)
        self._metric_hint = QLabel("载入 CSV 后显示可比较的测试项")
        self._metric_hint.setObjectName("panelDesc")
        self._metric_area.addWidget(self._metric_hint)
        self._metric_area.addStretch(1)
        config_row.addWidget(metric_box, stretch=1)

        # ---- 4 打平阈值与评分权重（无上下箭头，直接键入）
        tuning = QGroupBox("4 打平阈值与评分权重")
        form = QFormLayout(tuning)
        self._tie_freq = self._spin(0.001, 0.5, 0.01, 3, "tieFreqSpin")
        self._tie_sfr = self._spin(0.001, 0.5, 0.01, 3, "tieSfrSpin")
        self._score_tie = self._spin(0.001, 1.0, 0.01, 3, "scoreTieSpin")
        self._w_center = self._spin(0.0, 1.0, 0.6, 2, "wCenterSpin")
        self._w_edge = self._spin(0.0, 1.0, 0.0, 2, "wEdgeSpin")
        self._w_corner = self._spin(0.0, 1.0, 0.4, 2, "wCornerSpin")
        self._tie_freq.setToolTip(
            "同一视场位置两款之差 ≤ 此值记为平手：MTF 重复测量本身有\n"
            "±0.003 量级的不确定度，阈值内的差异是噪声而非真实优劣。\n"
            "用于频率类指标（MTF50 / MTFnn / MTFnnP），单位 cy/px。"
        )
        self._tie_sfr.setToolTip(
            "同上，用于 SFR 类指标（MTF@评估频率、MTFa），0~1 无单位。"
        )
        self._score_tie.setToolTip(
            "总体评分差 ≤ 此值时，总体结论为「两者相当」。"
        )
        form.addRow("频率类打平阈值 (cy/px)", self._tie_freq)
        form.addRow("SFR 类打平阈值 (0~1)", self._tie_sfr)
        form.addRow("评分打平阈值", self._score_tie)
        weights_row = QHBoxLayout()
        for name, spin in (("中心", self._w_center), ("边缘", self._w_edge),
                           ("四角", self._w_corner)):
            weights_row.addWidget(QLabel(name))
            weights_row.addWidget(spin)
        weights_row.addStretch(1)
        weights_holder = QWidget()
        weights_holder.setLayout(weights_row)
        weights_holder.setToolTip(
            "总体评分 = 中心/边缘/四角分区均值的加权和（默认 0.6/0/0.4）"
        )
        form.addRow("评分权重", weights_holder)
        config_row.addWidget(tuning, stretch=1)
        right_col.addLayout(config_row)

        # ---- 5 比较图表（嵌入面板，比较后直接可见）：
        # 左 = 逐视场位置 N 条折线对比（横轴 ROI 位置，纵轴所选测试项）；
        # 右 = Δ（各款 − 基准）每位置分组条形 + ±打平阈值参考线
        chart_box = QGroupBox("5 比较图表")
        chart_layout = QVBoxLayout(chart_box)
        chart_head = QHBoxLayout()
        chart_head.addWidget(QLabel("图表测试项："))
        self._chart_metric = QComboBox()
        self._chart_metric.setObjectName("chartMetricCombo")
        self._chart_metric.currentIndexChanged.connect(self._render_charts)
        chart_head.addWidget(self._chart_metric, stretch=1)
        self._compare_btn = QPushButton("执 行 比 较")
        self._compare_btn.setObjectName("compareBtn")
        self._compare_btn.setEnabled(False)
        self._compare_btn.setMinimumHeight(32)
        self._compare_btn.setStyleSheet("font-weight: 700;")
        self._compare_btn.clicked.connect(self._run_compare)
        chart_head.addWidget(self._compare_btn)
        chart_layout.addLayout(chart_head)

        charts_row = QHBoxLayout()
        self._plot_compare = pg.PlotWidget(background="w")
        self._plot_compare.setObjectName("plotCompare")
        self._plot_compare.showGrid(x=False, y=True, alpha=0.25)
        self._plot_compare.addLegend(
            offset=(10, 10), pen=pg.mkPen("#d5dbe0"),
            brush=pg.mkBrush(255, 255, 255, 220))
        self._plot_delta = pg.PlotWidget(background="w")
        self._plot_delta.setObjectName("plotDelta")
        self._plot_delta.showGrid(x=False, y=True, alpha=0.25)
        charts_row.addWidget(self._plot_compare)
        charts_row.addWidget(self._plot_delta)
        chart_layout.addLayout(charts_row)
        right_col.addWidget(chart_box, stretch=1)

        # ---- 6 比较结论（图表下方）
        summary_box = QGroupBox("6 比较结论")
        summary_layout = QVBoxLayout(summary_box)
        self._summary = QPlainTextEdit()
        self._summary.setObjectName("compareSummary")
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("比较结论将显示在这里")
        self._summary.setMaximumHeight(120)
        summary_layout.addWidget(self._summary)
        right_col.addWidget(summary_box)

        right_holder = QWidget()
        right_holder.setLayout(right_col)
        body.addWidget(right_holder, stretch=1)
        layout.addLayout(body, stretch=1)

        # ---- 7 操作按钮
        bottom = QHBoxLayout()
        self._save_btn = QPushButton("保存比较结果 CSV…")
        self._save_btn.setObjectName("saveCompareBtn")
        self._save_btn.setEnabled(False)
        self._save_btn.setToolTip(
            "比较结果不会自动保存；点击后自行选择路径保存。\n"
            "两款比较保存单个 CSV；多款比较按「基准 vs 各款」\n"
            "分别保存多个 CSV 到所选目录。"
        )
        self._save_btn.clicked.connect(self._save_compare_result)
        close_btn = QPushButton("关  闭")
        close_btn.clicked.connect(self.close)
        bottom.addWidget(self._save_btn)
        bottom.addStretch(1)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

    # ------------------------------------------------------------ 控件工具

    @staticmethod
    def _spin(mn: float, mx: float, value: float, decimals: int,
              name: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        # 无上下箭头：用户直接键入数值
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setRange(mn, mx)
        spin.setDecimals(decimals)
        spin.setSingleStep(0.01 if decimals == 3 else 0.05)
        spin.setValue(value)
        spin.setObjectName(name)
        return spin

    # ------------------------------------------------------------ 槽位管理

    def _add_slot(self, letter: str) -> dict:
        """新增一个 CSV 槽位（构建期/「添加槽位」按钮共用）。"""
        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        row = QHBoxLayout()
        ref_radio = QRadioButton("基准")
        ref_radio.setObjectName(f"ref_{letter}")
        ref_radio.setToolTip("设为基准（金样）：其余各款与它比较")
        ref_radio.toggled.connect(lambda _=False: self._refresh())
        self._ref_group.addButton(ref_radio)
        if letter == "a":
            ref_radio.setChecked(True)
        row.addWidget(ref_radio)
        row.addWidget(QLabel(f"模组 {letter.upper()}："))
        path_edit = QLineEdit()
        path_edit.setReadOnly(True)
        path_edit.setPlaceholderText("尚未载入 MTF 结果 CSV…")
        path_edit.setObjectName(f"path_{letter}")
        browse = QPushButton("浏览…")
        browse.setObjectName(f"browse_{letter}")
        browse.clicked.connect(lambda _=False, k=letter: self._browse(k))
        remove = QPushButton("✕")
        remove.setObjectName(f"remove_{letter}")
        remove.setFixedWidth(30)
        remove.setToolTip("移除此槽位")
        remove.clicked.connect(lambda _=False, k=letter: self._remove_slot(k))
        row.addWidget(path_edit, stretch=1)
        row.addWidget(browse)
        row.addWidget(remove)
        col.addLayout(row)
        info = QLabel("")
        info.setObjectName(f"info_{letter}")
        info.setStyleSheet("color: #5a6a75;")
        col.addWidget(info)
        slot = {
            "key": letter, "widget": container, "path_edit": path_edit,
            "info": info, "ref_radio": ref_radio, "remove_btn": remove,
            "data": None, "error": "",
        }
        self._slots.append(slot)
        # 插入到「添加槽位」按钮行之前
        self._slots_area.insertWidget(len(self._slots) - 1, container)
        self._sync_slot_buttons()
        return slot

    def _on_add_slot(self) -> None:
        if len(self._slots) >= _MAX_SLOTS:
            return
        letter = _SLOT_LETTERS[len(self._slots)]
        self._add_slot(letter)
        self._refresh()

    def _remove_slot(self, key: str) -> None:
        if len(self._slots) <= _MIN_SLOTS:
            return
        slot = next(s for s in self._slots if s["key"] == key)
        was_ref = slot["ref_radio"].isChecked()
        self._ref_group.removeButton(slot["ref_radio"])
        self._slots.remove(slot)
        slot["widget"].setParent(None)
        slot["widget"].deleteLater()
        if was_ref:
            self._slots[0]["ref_radio"].setChecked(True)
        self._sync_slot_buttons()
        self._rebuild_pair_header()
        self._refresh()

    def _sync_slot_buttons(self) -> None:
        n = len(self._slots)
        add_btn = getattr(self, "_add_btn", None)  # 构建期尚未创建
        if add_btn is not None:
            add_btn.setEnabled(n < _MAX_SLOTS)
        for slot in self._slots:
            slot["remove_btn"].setEnabled(n > _MIN_SLOTS)

    def _slot(self, key: str) -> dict:
        return next(s for s in self._slots if s["key"] == key)

    # ------------------------------------------------------------ 数据载入

    def _browse(self, slot: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"选择模组 {slot.upper()} 的 MTF 结果 CSV", "",
            "MTF 结果 CSV (*.csv);;所有文件 (*)",
        )
        if path:
            self.load_csv(slot, path)

    def load_csv(self, slot: str, path) -> None:
        """载入一份 MTF 结果 CSV（slot = 槽位字母），供浏览按钮与测试调用。"""
        entry = self._slot(slot)
        try:
            data = mtf_compare.load_result_csv(path)
        except ValueError as exc:
            entry["data"] = None
            entry["error"] = f"模组 {slot.upper()} 载入失败：{exc}"
            entry["path_edit"].setText(str(path))
            entry["info"].setText("")
            self._status.setText(entry["error"])
            self._status.setStyleSheet("color: #c0504d;")
            self._refresh()
            return
        entry["data"] = data
        entry["error"] = ""
        entry["path_edit"].setText(str(path))
        meta = data["meta"]
        entry["info"].setText(
            f"{meta['label'] or Path(str(path)).stem}"
            f"（{len(data['rows'])} 行）"
        )
        self._refresh()

    # ------------------------------------------------------------ 状态刷新

    def _loaded_slots(self) -> list[dict]:
        return [s for s in self._slots if s["data"] is not None]

    def _ref_slot(self) -> dict:
        for s in self._slots:
            if s["ref_radio"].isChecked():
                return s
        return self._slots[0]

    def _refresh(self) -> None:
        """数据/基准变化后：口径校验 → 配对预览 → 测试项清单。"""
        if getattr(self, "_save_btn", None) is None:
            return  # 构建期基准单选触发 toggled，控件尚未就绪
        self._clear_metrics()
        self._clear_pair_table()
        self._compare_btn.setEnabled(False)
        self._summary.clear()
        # 数据变化后旧比较结果失效：清空图表并禁用保存
        self._last_result = None
        self._last_results = []
        self._chart_ctx = None
        self._save_btn.setEnabled(False)
        self._chart_metric.clear()
        self._plot_compare.clear()
        self._plot_delta.clear()

        loaded = self._loaded_slots()
        if len(loaded) < 2:
            failed = next((s for s in self._slots
                           if s["data"] is None and s["error"]), None)
            if failed is not None:
                self._status.setText(failed["error"])
                self._status.setStyleSheet("color: #c0504d;")
            elif loaded:
                self._status.setText("请再载入另一份 MTF 结果 CSV")
                self._status.setStyleSheet("color: #5a6a75;")
            return

        # 基准排首位，其余按槽位顺序
        ref = self._ref_slot()
        if ref["data"] is None:  # 基准槽位未载入 → 回退到首个已载入
            ref = loaded[0]
            ref["ref_radio"].setChecked(True)
        ordered = [ref] + [s for s in loaded if s is not ref]
        datasets = [s["data"] for s in ordered]

        try:
            mtf_compare.check_compatibility_multi(datasets)
            metrics = mtf_compare.available_metrics_multi(datasets)
            matched = mtf_compare.match_zones_multi(
                [ds["rows"] for ds in datasets]
            )
        except ValueError as exc:
            self._status.setText(f"口径校验失败：{exc}")
            self._status.setStyleSheet("color: #c0504d;")
            return

        n_pairs = sum(len(v) for v in matched["groups"].values())
        if not n_pairs:
            self._status.setText("没有全部镜头共有的视场位置，无法比较")
            self._status.setStyleSheet("color: #c0504d;")
            return

        first_meta = datasets[0]["meta"]
        self._status.setText(
            f"口径一致（{first_meta['freq_unit']}，评估频率 "
            f"{first_meta['freq1']:g} cy/px，Gamma {first_meta['gamma']:g}）；"
            f"基准（金样）= "
            f"{first_meta.get('label') or '模组 ' + ref['key'].upper()}；"
            f"配对 {n_pairs} 对"
        )
        self._status.setStyleSheet("color: #1e8a57;")
        self._fill_pair_table(ordered, matched)
        self._fill_metrics(metrics)
        self._compare_btn.setEnabled(True)

    # ------------------------------------------------------------ 配对预览

    def _rebuild_pair_header(self) -> None:
        """配对表列 = 视场位置 + 各槽位 + 共同。"""
        headers = ["视场位置"]
        for s in self._slots:
            label = ""
            if s["data"] is not None:
                label = s["data"]["meta"].get("label", "")
            headers.append(label or f"模组{s['key'].upper()}")
        headers.append("共同")
        self._pair_table.setColumnCount(len(headers))
        self._pair_table.setHorizontalHeaderLabels(headers)
        self._clear_pair_table()

    def _clear_pair_table(self) -> None:
        for col in range(1, self._pair_table.columnCount()):
            for r in range(self._pair_table.rowCount()):
                self._pair_table.setItem(r, col, QTableWidgetItem(""))

    def _fill_pair_table(self, ordered: list[dict], matched: dict) -> None:
        self._rebuild_pair_header()
        counts = matched["counts"]  # zone → [每槽位数量]（按载入顺序）
        # match_zones_multi 的 counts 顺序 = datasets 顺序 = ordered 顺序
        common: dict[str, int] = {}
        for (zone, _ch), groups in matched["groups"].items():
            common[zone] = common.get(zone, 0) + len(groups)
        for row, (zone, _) in enumerate(_ZONE_ORDER):
            texts = [
                str(c) if c else "—"
                for c in counts.get(zone, [0] * len(ordered))
            ]
            texts.append(str(common.get(zone, 0)) if common.get(zone) else "—")
            for col, text in enumerate(texts, start=1):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == len(texts) and text != "—":
                    item.setForeground(Qt.GlobalColor.darkCyan)
                self._pair_table.setItem(row, col, item)

    # ------------------------------------------------------------ 测试项

    def _clear_metrics(self) -> None:
        for entry in self._metric_rows:
            entry["widget"].setParent(None)
            entry["widget"].deleteLater()
        self._metric_rows = []
        self._metric_hint.setVisible(True)
        for btn in self._main_group.buttons():
            self._main_group.removeButton(btn)

    def _fill_metrics(self, metrics: list[dict]) -> None:
        self._metric_hint.setVisible(False)
        for i, m in enumerate(metrics):
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            checkbox = QCheckBox(m["label"])
            checkbox.setObjectName(f"metricCheck_{m['key']}")
            checkbox.setChecked(True)
            radio = QRadioButton("主判定")
            radio.setObjectName(f"metricMain_{m['key']}")
            self._main_group.addButton(radio)
            if i == 0:
                radio.setChecked(True)
            row.addWidget(checkbox, stretch=1)
            row.addWidget(radio)
            self._metric_area.insertWidget(self._metric_area.count() - 1,
                                           row_widget)
            self._metric_rows.append({
                "key": m["key"], "widget": row_widget,
                "checkbox": checkbox, "radio": radio,
            })

    def _selected_metrics(self) -> tuple[list[str], str | None]:
        keys = [e["key"] for e in self._metric_rows
                if e["checkbox"].isChecked()]
        main = next((e["key"] for e in self._metric_rows
                     if e["radio"].isChecked()), None)
        return keys, main

    # ------------------------------------------------------------ 比较

    def _run_compare(self) -> None:
        loaded = self._loaded_slots()
        if len(loaded) < 2:
            return
        keys, main = self._selected_metrics()
        if not keys:
            QMessageBox.warning(self, "无法比较", "请至少勾选一个比较测试项")
            return
        if main not in keys:
            main = keys[0]  # 主判定项未勾选时回退到第一个勾选项

        ref = self._ref_slot()
        if ref["data"] is None:
            ref = loaded[0]
        ordered = [ref] + [s for s in loaded if s is not ref]
        ref_ds = ref["data"]
        ref_label = ref_ds["meta"].get("label") or f"模组 {ref['key'].upper()}"
        weights = {
            "center": self._w_center.value(),
            "edge": self._w_edge.value(),
            "corner": self._w_corner.value(),
        }
        ties = {"tie_freq": self._tie_freq.value(),
                "tie_sfr": self._tie_sfr.value(),
                "score_tie": self._score_tie.value()}

        results = []
        try:
            for slot in ordered[1:]:
                results.append(mtf_compare.compare(
                    ref_ds, slot["data"], metric_keys=keys, main_metric=main,
                    zone_weights=weights, **ties,
                ))
        except ValueError as exc:
            QMessageBox.critical(self, "比较失败", str(exc))
            return

        self._last_results = results
        self._last_result = results[0]
        self._save_btn.setEnabled(True)
        self._summary.setPlainText(self._format_summary(
            ref_label, results, keys, main
        ))
        # 图表上下文：多款公共位置匹配 + 数据集（基准排首位）
        self._chart_ctx = {
            "ordered": ordered,
            "matched": mtf_compare.match_zones_multi(
                [s["data"]["rows"] for s in ordered]
            ),
        }
        # 填充图表测试项下拉并渲染（默认显示主判定项）
        self._chart_metric.blockSignals(True)
        self._chart_metric.clear()
        for m in results[0]["metrics"]:
            self._chart_metric.addItem(m["label"], m["key"])
        main_index = next(
            (i for i, m in enumerate(results[0]["metrics"])
             if m["key"] == main), 0
        )
        self._chart_metric.setCurrentIndex(main_index)
        self._chart_metric.blockSignals(False)
        self._render_charts()
        self.compared.emit(results[0])

    def _format_summary(self, ref_label: str, results: list[dict],
                        keys: list[str], main: str) -> str:
        """结论文本：两款保持原格式；多款按「vs 基准」逐款输出。"""
        if len(results) == 1:
            result = results[0]
            la, lb = result["labels"]["a"], result["labels"]["b"]
            lines = [
                f"总体结论（主判定项 "
                f"{result['stats'][main]['label']}）：{result['main_summary']}",
                "",
            ]
            for key in keys:
                st = result["stats"][key]
                lines.append(f"· {st['label']}：{st['summary']}")
            if result["only_a"] or result["only_b"]:
                lines.append("")
                if result["only_a"]:
                    lines.append(
                        f"注：{len(result['only_a'])} 个 ROI 仅存在于 {la}，"
                        "未参与比较"
                    )
                if result["only_b"]:
                    lines.append(
                        f"注：{len(result['only_b'])} 个 ROI 仅存在于 {lb}，"
                        "未参与比较"
                    )
            if result["cross_pixel"]:
                lines.append("")
                lines.append(
                    "注意：两模组像元尺寸不同，频率类指标已统一按 LP/mm "
                    "展示，结论仅供参考"
                )
            return "\n".join(lines)

        lines = [f"基准（金样）：{ref_label}", ""]
        for result in results:
            lb = result["labels"]["b"]
            lines.append(
                f"【{lb} vs 基准】总体结论（主判定项 "
                f"{result['stats'][main]['label']}）：{result['main_summary']}"
            )
            for key in keys:
                st = result["stats"][key]
                lines.append(f"  · {st['label']}：{st['summary']}")
            if result["only_a"] or result["only_b"]:
                na, nb = len(result["only_a"]), len(result["only_b"])
                notes = []
                if na:
                    notes.append(f"{na} 个仅基准")
                if nb:
                    notes.append(f"{nb} 个仅 {lb}")
                lines.append(f"  注：{'，'.join(notes)} 的 ROI 未参与比较")
            if result["cross_pixel"]:
                lines.append(
                    "  注意：该款与基准像元尺寸不同，频率类指标按 LP/mm "
                    "展示，结论仅供参考"
                )
            lines.append("")
        return "\n".join(lines).rstrip()

    # ------------------------------------------------------------ 图表

    def _render_charts(self, *_args) -> None:
        """按当前所选测试项渲染 N 折线对比图与 Δ（vs 基准）分组条形图。"""
        result = self._last_result
        ctx = self._chart_ctx
        if result is None or ctx is None:
            return
        key = self._chart_metric.currentData()
        if not key:
            return
        kind = next(m["kind"] for m in result["metrics"] if m["key"] == key)
        label = next(m["label"] for m in result["metrics"] if m["key"] == key)
        factor = float(result["display_scale"]) if kind == "freq" else 1.0
        unit = result["display_unit"] if kind == "freq" else ""
        tie = (result["config_echo"]["tie_freq"] if kind == "freq"
               else result["config_echo"]["tie_sfr"])

        # 图表渲染已抽到 mtf_compare_charts.render_compare_charts；
        # 此处仅从对话框状态取数据并写回横轴标签。
        self._chart_tick_labels = render_compare_charts(
            self._plot_compare, self._plot_delta,
            ctx["ordered"], ctx["matched"],
            key, label, factor, unit, tie,
        )

    # ------------------------------------------------------------ 保存

    def _save_compare_result(self) -> None:
        """保存比较结果 CSV（用户主动触发，默认不自动保存）。

        两款：保存单个 CSV；多款：按「基准 vs 各款」分别保存到所选目录。
        """
        if not self._last_results:
            return

        def _clean(text: str) -> str:
            return "".join(
                ch if ch not in r'\/:*?"<>|' else "_" for ch in text
            ).strip() or "MTF"

        try:
            if len(self._last_results) == 1:
                labels = self._last_results[0]["labels"]
                default_name = (
                    f"MTF比较_{_clean(labels['a'])}_vs_"
                    f"{_clean(labels['b'])}.csv"
                )
                path, _ = QFileDialog.getSaveFileName(
                    self, "保存比较结果 CSV", default_name, "CSV 文件 (*.csv)"
                )
                if not path:
                    return
                mtf_compare.write_compare_csv(self._last_results[0], path)
                saved = [path]
            else:
                directory = QFileDialog.getExistingDirectory(
                    self, "选择保存目录（按「基准 vs 各款」分别保存 CSV）"
                )
                if not directory:
                    return
                saved = []
                for result in self._last_results:
                    labels = result["labels"]
                    path = Path(directory) / (
                        f"MTF比较_{_clean(labels['a'])}_vs_"
                        f"{_clean(labels['b'])}.csv"
                    )
                    mtf_compare.write_compare_csv(result, path)
                    saved.append(str(path))
        except Exception as exc:  # noqa: BLE001 — 任何写出错误弹窗而非崩溃
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        QMessageBox.information(
            self, "保存完成", "比较结果已保存：\n" + "\n".join(saved)
        )
