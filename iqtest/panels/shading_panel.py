"""Lens Shading 模块面板（M3 接入）。

参数/criteria schema 之外，提供「图像 → 光源」分配表：多光源对比时逐图像指定
光源（默认取 `light_source` 参数），单光源时全部图像归入同一光源做多帧平均。

面板参数 → 算法 config 的映射由 `iqtest.analysis.shading_adapter` 完成：
  - grid_size      → bin_size
  - thresh         → 平场掩膜 DN 阈值（0 = 全图有效）
  - support_extrapolation → shading profile 是否 RBF 外插
  - luminance_channel     → 报告/展示通道（Y/G/Gr），不改判定口径
  - ri_corner_min  → criteria.ri（四象限 RI 下限）
  - lum_uniformity_min   → criteria.ri_diff = 1 - 均匀性（四象限离散上限）
  - green_red_shift_max / green_blue_shift_max → Color Shading 判定（仅 Bayer）
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from iqtest.panels.base_panel import ModulePanel

#: 可选光源（与算法 analyze_multi_light 的光源名一致）
LIGHT_SOURCES = ["D65", "TL84", "A", "CWF"]


class ShadingPanel(ModulePanel):
    MODULE_KEY = "shading"
    TITLE = "Lens Shading"
    DESCRIPTION = (
        "相对照度（RI）、亮度均匀性、四象限 RI、Color Shading、多光源对比、"
        "LSC 校正表导出与闭环验证。\n"
        "算法接口：analyze_relative_illumination / analyze_multi_light / apply_lsc。"
    )

    PARAMS = [
        {
            "key": "light_source",
            "label": "光源类型",
            "type": "choice",
            "choices": LIGHT_SOURCES,
            "default": "D65",
            "tooltip": "默认光源；「图像 → 光源」表中可为每张图像单独覆盖（多光源对比）",
        },
        {
            "key": "luminance_channel",
            "label": "亮度通道",
            "type": "choice",
            "choices": ["Y", "G", "Gr"],
            "default": "Y",
            "tooltip": "RI 热力图与四象限数值表的报告通道：Y=亮度(G 加权)、G=(Gr+Gb)/2、"
            "Gr=Gr 通道（mono 输入仅 Y 有效）",
        },
        {
            "key": "grid_size",
            "label": "网格尺寸",
            "type": "int",
            "default": 16,
            "min": 4,
            "max": 64,
            "tooltip": "RI 热力图分块粒度（bin_size，像素）",
        },
        {
            "key": "thresh",
            "label": "平场掩膜阈值",
            "type": "float",
            "default": 0.0,
            "min": 0.0,
            "max": 1e9,
            "step": 1.0,
            "tooltip": "平场有效区域 DN 阈值：取 Gr 通道 > thresh 的区域并排除边缘/污染；"
            "0 = 全图有效",
        },
        {
            "key": "support_extrapolation",
            "label": "RBF 外插",
            "type": "bool",
            "default": False,
            "tooltip": "shading profile 是否用 RBF 填补 griddata 外插区（更准但更慢、更耗内存）",
        },
        {
            "key": "enable_lsc_verify",
            "label": "闭环验证（LSC）",
            "type": "bool",
            "default": True,
            "tooltip": "单光源时对校正后图像再测残余 shading（apply_lsc 闭环自检）",
        },
    ]

    CRITERIA = [
        {
            "key": "ri_corner_min",
            "label": "四象限 RI 下限",
            "type": "float",
            "default": 0.70,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "四角相对照度不得低于该比例（min(RI) ≥ 该值）",
        },
        {
            "key": "lum_uniformity_min",
            "label": "亮度均匀性下限",
            "type": "float",
            "default": 0.80,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "四象限离散度上限 ri_diff = 1 - 均匀性（如 0.80 → ri_diff ≤ 0.20）",
        },
        {
            "key": "green_red_shift_max",
            "label": "G/R 偏移上限",
            "type": "float",
            "default": 0.20,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "Color Shading：green_red_shift 上限（仅 Bayer 输入生效）",
        },
        {
            "key": "green_blue_shift_max",
            "label": "G/B 偏移上限",
            "type": "float",
            "default": 0.20,
            "min": 0.0,
            "max": 1.0,
            "step": 0.01,
            "tooltip": "Color Shading：green_blue_shift 上限（仅 Bayer 输入生效）",
        },
    ]

    def __init__(self, session=None, parent=None) -> None:
        #: 图像名 → 光源（仅显式覆盖；缺省跟随 light_source 参数）
        self._image_lights: dict[str, str] = {}
        super().__init__(session=session, parent=parent)
        # 光源默认值变化时，未显式覆盖的图像跟随新默认
        light_combo = self.params_form.widget("light_source")
        light_combo.currentTextChanged.connect(self._on_light_source_changed)

    # ------------------------------------------------------------ 图像 → 光源表

    def _add_custom(self, layout: QVBoxLayout) -> None:
        group = QGroupBox("图像 → 光源（多光源对比）")
        v = QVBoxLayout(group)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["图像", "光源"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setMinimumHeight(140)
        v.addWidget(self._table)

        layout.addWidget(group)

        if self.session is not None:
            self.session.images_changed.connect(self._refresh_images)
        self._refresh_images()

    def _light_source(self) -> str:
        values = self.params_form.values()
        return str(values.get("light_source", "D65"))

    def _on_light_source_changed(self, new_source: str) -> None:
        # 未显式覆盖的图像跟随新默认；已覆盖的保持不变
        for name in list(self._image_lights):
            if name not in self._image_names():
                self._image_lights.pop(name, None)
        self._refresh_images()

    def _image_names(self) -> list[str]:
        if self.session is None:
            return []
        return [e.name for e in self.session.images]

    def _refresh_images(self) -> None:
        names = self._image_names()
        default = self._light_source()
        # 清理已移出会话的显式覆盖
        for name in list(self._image_lights):
            if name not in names:
                self._image_lights.pop(name, None)
        self._table.blockSignals(True)
        try:
            self._table.setRowCount(len(names))
            for row, name in enumerate(names):
                item = QTableWidgetItem(name)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, 0, item)
                combo = QComboBox()
                combo.addItems(LIGHT_SOURCES)
                current = self._image_lights.get(name, default)
                idx = combo.findText(current)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                combo.currentTextChanged.connect(
                    lambda value, n=name: self._on_image_light(n, value)
                )
                self._table.setCellWidget(row, 1, combo)
        finally:
            self._table.blockSignals(False)

    def _on_image_light(self, name: str, value: str) -> None:
        self._image_lights[name] = value

    # ------------------------------------------------------------ 读写

    def _effective_image_lights(self) -> dict[str, str]:
        default = self._light_source()
        return {
            name: self._image_lights.get(name, default)
            for name in self._image_names()
        }

    def config(self) -> dict:
        cfg = super().config()
        cfg["params"]["image_lights"] = self._effective_image_lights()
        return cfg

    def set_config(self, config: dict) -> None:
        super().set_config(config)
        saved = (config.get("params") or {}).get("image_lights")
        if isinstance(saved, dict):
            self._image_lights = {str(k): str(v) for k, v in saved.items()}
        self._refresh_images()
