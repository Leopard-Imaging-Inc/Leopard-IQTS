"""MTF / SFR 模块面板（M3 接入）：ROI 框选 + 参数/criteria 表单。

交互（规划 §2 MTF/SFR 行 + §5 M3 标准步骤 2）：
  1. 从会话图像中选择一张并「载入图像」（.raw 按 Utilities →
     Generalized Read Raw 的全局设置读取）；
  2. 主视图固定为「查看」模式：拖拽平移、滚轮缩放、单击选中 ROI、
     双击 ROI 弹出框选/精调窗口、右键或 Delete 删除单个 ROI；
     点「框选…」弹出框选/精调窗口：拖拽画出粗 ROI 后直接精调，确认加入；
     「查看 / 框选…」为互斥单选按钮，激活的模式以颜色高亮；
  3. config() 将 ROI 列表注入 params["rois"]，随 ANALYZE 交给 mtf_adapter。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from iqtest.analysis.mtf_adapter import load_analysis_image
from iqtest.config.lf_csv import centers_to_rects, parse_lf_edge_centers
from iqtest.panels.base_panel import ModulePanel
from iqtest.widgets.image_view import RoiImageView
from leopardiq.mtf import FREQ_UNITS, unit_label, unit_scale


class MtfPanel(ModulePanel):
    MODULE_KEY = "mtf"
    TITLE = "MTF / SFR"
    DESCRIPTION = (
        "斜边 SFR 分析：载入图像后框选斜边 ROI（每个 ROI 包含一条黑白斜边），"
        "算法计算 MTF @ 评估频率（参与判定）、MTF50 与两个可配置的 "
        "Secondary Readout（MTFnn/MTFnnP），并绘制 MTF 曲线。"
        "Gamma (input) 用于 SFR 前线性化（仿 Imatest）：RAW 线性数据 = 1.0，"
        "BMP 等 sRGB 编码图像 ≈ 0.5。"
        "RAW 读取参数（分辨率/位深/黑电平/CFA）在 Utilities → "
        "Generalized Read Raw 中统一配置。"
    )

    PARAMS = [
        {
            "key": "pixel_size_um",
            "label": "像元尺寸 (µm/px)",
            "type": "float",
            "default": 2.0,
            "min": 0.1,
            "max": 100.0,
            "step": 0.05,
            "decimals": 3,
            "tooltip": "像元尺寸（µm/px），Cycles/mm、LP/mm、L/mm 单位换算所需",
        },
        {
            "key": "picture_height",
            "label": "像高 Picture Height (px)",
            "type": "int",
            "default": 1080,
            "min": 1,
            "max": 100000,
            "tooltip": "像高（px），LP/PH、LW/PH 单位换算所需；"
            "载入图像后自动填入图像高度，裁剪图应手动改为原始全幅像高",
        },
        {
            "key": "freq_unit",
            "label": "频率单位（Secondary Readout）",
            "type": "choice",
            "choices": FREQ_UNITS,
            "default": "Cycles/pixel",
            "tooltip": (
                "空间频率单位（仿 Imatest Secondary Readout）：评估频率与 "
                "Readout1 下限按所选单位输入，切换单位时数值自动换算。"
                "Cycles/mm、LP/mm、L/mm 需像元尺寸；LP/PH、LW/PH 需像高"
            ),
        },
        {
            "key": "freq1",
            "label": "评估频率 MTF @ (cy/px)",
            "type": "float",
            "default": 0.125,
            "min": 0.005,
            "max": 1.0,
            "step": 0.005,
            "decimals": 3,
            "tooltip": "MTF @ nn：读取该空间频率处的 SFR 值并参与 criteria 判定"
            "（默认 Nyquist/4 = 0.125 cy/px），按所选单位输入",
        },
        {
            "key": "mtfnn1_type",
            "label": "Secondary Readout 1 类型",
            "type": "choice",
            "choices": ["MTFnn", "MTFnnP"],
            "default": "MTFnn",
            "tooltip": "MTFnn：MTF 降至低频值 nn% 处的空间频率；"
            "MTFnnP：MTF 降至峰值 nn% 处的空间频率（适合强锐化图像）",
        },
        {
            "key": "mtfnn1_value",
            "label": "Readout 1 百分比 nn (%)",
            "type": "float",
            "default": 30.0,
            "min": 1.0,
            "max": 99.0,
            "step": 1.0,
            "decimals": 1,
            "tooltip": "如 30 → MTF30 / MTF30P（Readout1，其频率下限即"
            "Readout1 下限判据，参与判定）",
        },
        {
            "key": "mtfnn2_type",
            "label": "Secondary Readout 2 类型",
            "type": "choice",
            "choices": ["MTFnn", "MTFnnP"],
            "default": "MTFnnP",
            "tooltip": "MTFnn：MTF 降至低频值 nn% 处的空间频率；"
            "MTFnnP：MTF 降至峰值 nn% 处的空间频率（适合强锐化图像）",
        },
        {
            "key": "mtfnn2_value",
            "label": "Readout 2 百分比 nn (%)",
            "type": "float",
            "default": 30.0,
            "min": 1.0,
            "max": 99.0,
            "step": 1.0,
            "decimals": 1,
            "tooltip": "如 30 → MTF30P（INFO 展示，不参与判定）",
        },
        {
            "key": "gamma",
            "label": "Gamma (input)",
            "type": "float",
            "default": 1.0,
            "min": 0.1,
            "max": 2.0,
            "step": 0.01,
            "decimals": 3,
            "tooltip": (
                "编码（前向）Gamma，SFR 计算前按其倒数线性化：pixel^(1/Gamma)"
                "（仿 Imatest「Input gamma value」）。"
                "RAW 线性数据 = 1.0（不线性化，默认）；"
                "BMP/JPEG 等 sRGB 编码图像 ≈ 0.45~0.5（Imatest 默认 0.5）。"
                "设置错误会使 MTF 失真；超出 0.3~0.8 视为异常选择"
                "（分析时给出警告）"
            ),
        },
    ]

    CRITERIA = [
        {
            "key": "readout1_min",
            "label": "Readout1 下限 (cy/px)",
            "type": "float",
            "default": 0.10,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "Readout1（Secondary Readout 1，MTF@nn，默认 MTF30）频率下限，"
            "按所选频率单位输入",
        },
        {
            "key": "sfr_main_min",
            "label": "MTF@评估频率 SFR 下限",
            "type": "float",
            "default": 0.20,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "评估频率（MTF @ nn）处的 SFR 下限（0~1，无单位）",
        },
    ]

    #: 频率类 SpinBox 在不同单位下的量程/精度
    _SPIN_CY_PX = {"min": 0.0, "max": 1.0, "step": 0.005, "decimals": 3}
    _SPIN_OTHER = {"min": 0.0, "max": 1e7, "step": 1.0, "decimals": 2}

    def __init__(self, session=None, parent=None) -> None:
        self._loaded_name: str | None = None
        self._loaded_image = None  # 2D float 灰度图（框选/精调弹框用）
        self._pending_rois: list | None = None
        super().__init__(session=session, parent=parent)
        # 频率单位联动（仿 Imatest Secondary Readout：切换单位时数值自动换算）
        self._current_unit: str = "Cycles/pixel"
        unit_combo = self.params_form.widget("freq_unit")
        unit_combo.currentTextChanged.connect(self._on_freq_unit_changed)
        self._apply_unit_display(self._current_unit)

    # -------------------------------------------- 频率单位（Secondary Readout）

    def _on_freq_unit_changed(self, new_unit: str) -> None:
        """切换频率单位：按旧单位读出数值 → 换算 → 以新单位回填。"""
        old_unit = self._current_unit
        if new_unit == old_unit:
            return
        vals = self.params_form.values()
        pixel = vals.get("pixel_size_um")
        height = vals.get("picture_height")
        # 先按旧单位取出当前值：调整量程/精度会取整或截断显示值，必须先读
        freq_vals = self.params_form.values()
        crit_vals = self.criteria_form.values()
        try:
            factor = unit_scale(new_unit, pixel, height) / unit_scale(
                old_unit, pixel, height
            )
        except ValueError as e:
            QMessageBox.warning(self, "频率单位换算", str(e))
            self._apply_unit_display(new_unit)
            return
        # 先扩量程再回填，避免大数值（如 LW/PH）被旧量程截断
        self._apply_unit_display(new_unit)
        self.params_form.set_values({
            "freq1": round(freq_vals["freq1"] * factor, 6),
        })
        self.criteria_form.set_values({
            "readout1_min": round(crit_vals["readout1_min"] * factor, 6),
        })

    def _apply_unit_display(self, unit: str) -> None:
        """按单位调整频率类 SpinBox 量程/精度与行标签。"""
        self._current_unit = unit
        label = unit_label(unit)
        spin = self._SPIN_CY_PX if unit == "Cycles/pixel" else self._SPIN_OTHER
        for form, keys in (
            (self.params_form, ("freq1",)),
            (self.criteria_form, ("readout1_min",)),
        ):
            for key in keys:
                w = form.widget(key)
                w.setRange(spin["min"], spin["max"])
                w.setSingleStep(spin["step"])
                w.setDecimals(spin["decimals"])
        self.params_form.set_label("freq1", f"评估频率 MTF @ ({label})")
        self.criteria_form.set_label("readout1_min", f"Readout1 下限 ({label})")

    # ------------------------------------------------------------ ROI 编辑器

    def _add_custom(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("ROI 框选（斜边）")
        v = QVBoxLayout(group)

        # 图像选择行
        self._image_combo = QComboBox()
        self._btn_load = QPushButton("载入图像")
        self._btn_load.setObjectName("primaryButton")
        row = QHBoxLayout()
        row.addWidget(QLabel("源图像："))
        row.addWidget(self._image_combo, stretch=1)
        row.addWidget(self._btn_load)
        v.addLayout(row)

        # 工具行（查看/框选互斥单选：哪个模式激活哪个有颜色）
        self._btn_view = QPushButton("查看")
        self._btn_view.setCheckable(True)
        self._btn_view.setChecked(True)
        self._btn_view.setToolTip(
            "查看模式（主视图默认）：拖拽平移、滚轮缩放、单击选中 ROI、"
            "双击 ROI 弹出框选/精调窗口、右键或 Delete 删除单个 ROI"
        )
        self._btn_draw = QPushButton("框选…")
        self._btn_draw.setCheckable(True)
        self._btn_draw.setToolTip("框选模式：弹出框选窗口，拖拽画出粗 ROI 后可直接精调，确定后加入")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)  # 互斥单选
        self._mode_group.addButton(self._btn_view)
        self._mode_group.addButton(self._btn_draw)
        self._btn_fit = QPushButton("适应窗口")
        self._btn_clear = QPushButton("清空 ROI")
        # Add LF CSV：读取 LenFocus 结果 CSV 的 edge's center（ROI 中心点），
        # 配合边长自动生成正方形 ROI
        self._lf_side_spin = QSpinBox()
        self._lf_side_spin.setRange(8, 512)
        self._lf_side_spin.setValue(40)
        self._lf_side_spin.setButtonSymbols(
            QAbstractSpinBox.ButtonSymbols.NoButtons
        )
        self._lf_side_spin.setToolTip("LF CSV 导入的 ROI 边长（px，正方形）")
        self._btn_lf_csv = QPushButton("Add LF CSV…")
        self._btn_lf_csv.setToolTip(
            "读取 LenFocus 结果 CSV 的 edge's center 列（ROI 中心点），"
            "按左侧边长在图中自动画出全部 ROI（替换现有 ROI）"
        )
        self._roi_count = QLabel("ROI：0")
        self._roi_count.setObjectName("panelDesc")
        tool = QHBoxLayout()
        tool.addWidget(self._btn_view)
        tool.addWidget(self._btn_draw)
        tool.addWidget(self._btn_fit)
        tool.addWidget(self._btn_clear)
        tool.addStretch(1)
        tool.addWidget(QLabel("LF 边长:"))
        tool.addWidget(self._lf_side_spin)
        tool.addWidget(self._btn_lf_csv)
        tool.addWidget(self._roi_count)
        v.addLayout(tool)

        self.roi_view = RoiImageView()
        self.roi_view.setMinimumHeight(320)
        v.addWidget(self.roi_view, stretch=1)

        hint = QLabel(
            "「查看」模式下（默认）：拖拽平移、滚轮缩放、单击选中 ROI、"
            "双击 ROI 弹出框选/精调窗口、右键或 Delete 删除单个 ROI。\n"
            "点「框选…」在弹出的窗口中画框并精调；「Add LF CSV…」读取 LenFocus "
            "结果 CSV 的 edge's center（ROI 中心点），按「LF 边长」自动画出全部 ROI。\n"
            "RAW 读取参数（分辨率/黑电平/CFA）在 Utilities → Generalized Read Raw 配置。"
        )
        hint.setObjectName("panelDesc")
        hint.setWordWrap(True)
        v.addWidget(hint)

        layout.addWidget(group, stretch=1)

        # ---- 信号
        self._btn_load.clicked.connect(self._on_load_image)
        self._btn_fit.clicked.connect(self.roi_view.fit)
        self._btn_clear.clicked.connect(self.roi_view.clear_rois)
        self._btn_draw.clicked.connect(self._on_draw_roi)
        self._btn_lf_csv.clicked.connect(self._on_add_lf_csv)
        self.roi_view.roi_edit_requested.connect(self._on_tune_roi)
        self.roi_view.rois_changed.connect(self._on_rois_changed)
        if self.session is not None:
            self.session.images_changed.connect(self._refresh_images)
        self._refresh_images()

    def _on_rois_changed(self) -> None:
        self._roi_count.setText(f"ROI：{len(self.roi_view.rois())}")

    def _refresh_images(self) -> None:
        current = self._image_combo.currentText()
        self._image_combo.blockSignals(True)
        self._image_combo.clear()
        if self.session is not None:
            for entry in self.session.images:
                self._image_combo.addItem(entry.name)
        idx = self._image_combo.findText(current)
        if idx >= 0:
            self._image_combo.setCurrentIndex(idx)
        self._image_combo.blockSignals(False)
        if self._loaded_name and self._image_combo.findText(self._loaded_name) < 0:
            # 已载入的图像被移出会话 → 清空视图与 ROI
            self._loaded_name = None
            self._loaded_image = None
            self.roi_view.clear_rois()

    def _on_load_image(self) -> None:
        name = self._image_combo.currentText()
        if not name or self.session is None:
            return
        path = next((e.path for e in self.session.images if e.name == name), None)
        if path is None:
            return
        try:
            image = load_analysis_image(path, self.params_form.values())
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "载入图像失败", str(e))
            return
        self._loaded_image = image[:, :, 0]
        self.roi_view.set_image(self._loaded_image)
        self.roi_view.fit()
        self._loaded_name = name
        # 像高默认取输入图像高度（Imatest 行为；裁剪图可由用户改为原始像高）
        self.params_form.set_values(
            {"picture_height": int(self._loaded_image.shape[0])}
        )
        if self._pending_rois:
            rois = [r for r in self._pending_rois if r.get("image") == name]
            self._pending_rois = None
            if rois:
                self.roi_view.set_rois([r["rect"] for r in rois])

    def _on_add_lf_csv(self) -> None:
        """Add LF CSV：读取 LenFocus 结果 CSV 的 edge's center（ROI 中心点），
        按「LF 边长」生成正方形 ROI 并在图中画出（替换现有 ROI）。"""
        if self._loaded_image is None:
            QMessageBox.information(self, "Add LF CSV", "请先「载入图像」再导入 LF CSV。")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 LenFocus 结果 CSV", "", "CSV 文件 (*.csv);;所有文件 (*)"
        )
        if not path:
            return
        try:
            centers = parse_lf_edge_centers(path)
            height, width = self._loaded_image.shape[:2]
            rects = centers_to_rects(
                centers, self._lf_side_spin.value(), width, height
            )
        except ValueError as e:
            QMessageBox.warning(self, "Add LF CSV", str(e))
            return
        self.roi_view.set_rois(rects)
        QMessageBox.information(
            self,
            "Add LF CSV",
            f"已从 {len(centers)} 个 edge's center 生成 {len(rects)} 个 ROI"
            f"（边长 {rects[0][2]}px，已替换现有 ROI）。",
        )

    def _on_draw_roi(self) -> None:
        """框选入口：弹出框选/精调窗口（在弹框内画粗 ROI 并直接精调）。

        弹框期间「框选…」保持选中高亮；弹框关闭后恢复「查看」选中。
        """
        try:
            if self._loaded_image is None:
                QMessageBox.information(self, "框选 ROI", "请先「载入图像」再框选 ROI。")
                return
            rois = self.roi_view.rois()
            self._exec_tune_dialog(rois, max(0, len(rois) - 1), draw_new=True)
        finally:
            self._btn_view.setChecked(True)

    def _on_tune_roi(self, *args) -> None:
        """双击 ROI：弹出同一个框选/精调窗口，定位到被双击的 ROI。"""
        rois = self.roi_view.rois()
        if not rois or self._loaded_image is None:
            return
        current = self.roi_view.selected_index
        if current < 0:
            current = len(rois) - 1
        self._exec_tune_dialog(rois, current)

    def _exec_tune_dialog(self, rois: list, current: int,
                          draw_new: bool = False) -> None:
        from iqtest.widgets.roi_dialog import RoiFineTuneDialog

        dialog = RoiFineTuneDialog(self._loaded_image, rois, current=current,
                                   parent=self, draw_new=draw_new)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.roi_view.set_rois(dialog.rois())
        # 取消：视图中 ROI 保持原样

    # ------------------------------------------------------------ 读写

    def config(self) -> dict:
        cfg = super().config()
        rois = []
        if self._loaded_name is not None:
            rois = [
                {"image": self._loaded_name, "rect": rect}
                for rect in self.roi_view.rois()
            ]
        cfg["params"]["rois"] = rois
        return cfg

    def set_config(self, config: dict) -> None:
        # 存储值按 config 中的 freq_unit 解释：先按该单位扩量程/同步显示状态，
        # 再阻断联动回填（避免大数值被 cy/px 量程截断、避免二次换算）
        unit = (config.get("params") or {}).get("freq_unit") or "Cycles/pixel"
        self._apply_unit_display(unit)
        unit_combo = self.params_form.widget("freq_unit")
        unit_combo.blockSignals(True)
        super().set_config(config)
        unit_combo.blockSignals(False)
        rois = (config.get("params") or {}).get("rois") or []
        self._pending_rois = rois or None
        if rois and self._loaded_name is not None:
            rects = [r["rect"] for r in rois if r.get("image") == self._loaded_name]
            self.roi_view.set_rois(rects)
            self._pending_rois = None
