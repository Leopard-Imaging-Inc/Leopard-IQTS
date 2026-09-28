"""Lens Shading 模块面板（M3 接入）。

提供「测试项」选择器切换两个子功能：
  - 单光源 Shading：RI + Color Shading + LSC 闭环验证；
  - 多光源对比：跨光源一致性（ri_spread / color_shift_spread）。

参数/criteria schema 之外，多光源子功能提供「图像 → 光源」分配表：逐图像指定
光源（默认取 `DEFAULT_LIGHT_SOURCE`），要求 ≥2 个不同光源。单光源子功能不绑定
光源类型，所有图像合并做多帧平均。

面板参数 → 算法 config 的映射由 `iqtest.analysis.shading_adapter` 完成：
  - test_item      → 子功能分发（single / multi_light）
  - grid_size      → bin_size
  - thresh         → 平场掩膜 DN 阈值（0 = 全图有效）
  - ri_corner_min  → criteria.ri（四象限 RI 下限）
  - lum_uniformity_min   → criteria.ri_diff = 1 - 均匀性（四象限离散上限）
  - green_red_shift_max / green_blue_shift_max → Color Shading 判定（仅 Bayer）

RBF 外插、LSC 闭环验证、亮度通道（Y/G/Gr）为结果后处理/展示项，已移至分析结果界面：
  - support_extrapolation / enable_lsc_verify / luminance_channel → 结果界面的复选/下拉组件，
    通过 `recompute_single` 即时重算（不改主判定）。
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

#: 多光源「图像 → 光源」表的默认光源（未单独指定时使用）
DEFAULT_LIGHT_SOURCE = "D65"

#: 子功能选项（test_item）
TEST_ITEMS = ["single", "multi_light"]


class ShadingPanel(ModulePanel):
    MODULE_KEY = "shading"
    TITLE = "Lens Shading"
    DESCRIPTION = (
        "镜头阴影测试，含两个子功能：\n"
        "· 单光源 Shading：相对照度（RI）、亮度均匀性、四象限 RI、Color Shading、"
        "LSC 校正表导出与闭环验证；\n"
        "· 多光源对比：同镜头在不同光源下的表现一致性（ri_spread / color_shift_spread）。\n"
        "算法接口：analyze_relative_illumination / analyze_multi_light / apply_lsc。"
    )

    PARAMS = [
        {
            "key": "test_item",
            "label": "测试项",
            "type": "choice",
            "choices": TEST_ITEMS,
            "default": "single",
            "tooltip": "Lens Shading 子功能：single=单光源 Shading（RI/Color/LSC闭环），"
            "multi_light=多光源对比（跨光源一致性）",
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
            "decimals": 3,
            "tooltip": "平场有效区域 DN 阈值：取 Gr 通道 > thresh 的区域并排除边缘/污染；"
            "0 = 全图有效",
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
                "编码（前向）Gamma，非 Raw 图（PNG/JPEG 等）计算前按其倒数线性化："
                "pixel^(1/Gamma)（仿 Imatest「Input gamma value」）。"
                "RAW 线性数据 = 1.0（不线性化，默认）；"
                "BMP/JPEG 等 sRGB 编码图像 ≈ 0.45~0.5。"
            ),
        },
        {
            "key": "imatest_report",
            "label": "Imatest 对标",
            "type": "bool",
            "default": True,
            "tooltip": "是否生成 Imatest Uniformity 口径的结果集（Luma 文本块 / Pixel contours / Color Shading）",
        },
        {
            "key": "imatest_block_size",
            "label": "Imatest block 尺寸",
            "type": "int",
            "default": 32,
            "min": 8,
            "max": 64,
            "tooltip": "Imatest 对标的 block 尺寸（原始像素，[32x32 pxls areas]）；Bayer 拆分后按 1/2 换算",
        },
        {
            "key": "corner_region_pct",
            "label": "角区比例",
            "type": "float",
            "default": 0.0,
            "min": 0.0,
            "max": 0.5,
            "step": 0.01,
            "decimals": 3,
            "tooltip": "角区/边区边长 s = max(32, 该比例 × min(原始H,W))；设为 0 即固定 32×32（Imatest 默认）",
        },
        {
            "key": "contour_levels",
            "label": "等值线级数",
            "type": "int",
            "default": 10,
            "min": 2,
            "max": 30,
            "tooltip": "Pixel contours 等值线级数（默认 10 级，覆盖 [0.125, 1.0]×max）",
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
            "decimals": 3,
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
            "decimals": 3,
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
            "decimals": 3,
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
            "decimals": 3,
            "tooltip": "Color Shading：green_blue_shift 上限（仅 Bayer 输入生效）",
        },
    ]

    def __init__(self, session=None, parent=None) -> None:
        #: 图像名 → 光源（仅显式覆盖；缺省取 DEFAULT_LIGHT_SOURCE）
        self._image_lights: dict[str, str] = {}
        #: 「图像 → 光源」分组框（多光源子功能下显示）
        self._light_group: QGroupBox | None = None
        super().__init__(session=session, parent=parent)
        # 测试项切换：动态显隐相关参数与「图像 → 光源」表
        test_combo = self.params_form.widget("test_item")
        test_combo.currentTextChanged.connect(self._on_test_item_changed)
        self._apply_test_item_visibility()

    # ------------------------------------------------------------ 图像 → 光源表

    def _add_custom(self, layout: QVBoxLayout) -> None:
        self._light_group = QGroupBox("图像 → 光源（多光源对比）")
        v = QVBoxLayout(self._light_group)

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

        layout.addWidget(self._light_group)

        if self.session is not None:
            self.session.images_changed.connect(self._refresh_images)
        self._refresh_images()

    # ------------------------------------------------------------ 子功能显隐

    def _test_item(self) -> str:
        return str(self.params_form.values().get("test_item", "single"))

    def _on_test_item_changed(self, _value: str) -> None:
        self._apply_test_item_visibility()

    def _apply_test_item_visibility(self) -> None:
        """根据 test_item 显隐「图像 → 光源」表（仅多光源子功能显示）。"""
        is_multi = self._test_item() == "multi_light"
        if self._light_group is not None:
            self._light_group.setVisible(is_multi)

    def _image_names(self) -> list[str]:
        if self.session is None:
            return []
        return [e.name for e in self.session.images]

    def _refresh_images(self) -> None:
        names = self._image_names()
        default = DEFAULT_LIGHT_SOURCE
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
        return {
            name: self._image_lights.get(name, DEFAULT_LIGHT_SOURCE)
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
        self._apply_test_item_visibility()
