"""② Select Analysis 对应的 Analysis options 页面（主窗口右侧第二页）。

与 Source images 页通过 Workflow 的 NEXT / PREVIOUS（或点击步骤标题）切换；
内容 = 模块单选列表 + 对应模块的配置 panel（参数 + 判定 criteria）。

单选约束：每个测试项的拍摄环境 / 靶标不同，一批图像只能对应一个测试，
因此勾选是互斥的（radio 行为）；清空则回到 "Not selected"。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from iqtest.panels import MODULE_PANELS
from iqtest.widgets.free_stack import FreeStackedWidget


class AnalysisOptionsWidget(QWidget):
    """Analysis options 页面（② Select Analysis 的工作区，单选）。"""

    selection_changed = Signal()

    def __init__(self, session=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ---- 左：模块单选列表（checkbox 外观，互斥行为）
        self._list = QListWidget()
        self._list.setObjectName("moduleList")
        self._list.setFixedWidth(200)

        btn_none = QPushButton("清空选择")
        btn_none.clicked.connect(self.clear_selection)
        sel_row = QHBoxLayout()
        sel_row.addWidget(btn_none)
        sel_row.addStretch(1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._list, stretch=1)
        left_layout.addLayout(sel_row)

        # ---- 右：panel 堆叠（session 供需要访问图像集的面板使用，如 MTF 的 ROI 框选）
        self._stack = FreeStackedWidget()
        self._panels: dict[str, QWidget] = {}
        for panel_cls in MODULE_PANELS:
            panel = panel_cls(session=session)
            self._panels[panel.MODULE_KEY] = panel
            self._stack.addWidget(panel)
            item = QListWidgetItem(panel.TITLE)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, panel.MODULE_KEY)
            self._list.addItem(item)

        self._list.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._list.itemChanged.connect(self._on_item_changed)
        self._list.setCurrentRow(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)

        hint = QLabel(
            "选择一个分析项（各测试项拍摄环境 / 靶标不同，一批图像仅对应一个测试），"
            "并在右侧配置参数与判定 criteria。"
        )
        hint.setObjectName("panelDesc")
        hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(hint)
        layout.addWidget(splitter, stretch=1)

    # ------------------------------------------------------------- 单选行为

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if item.checkState() == Qt.CheckState.Checked:
            # 互斥：勾中一项即取消其余
            self._list.blockSignals(True)
            for i in range(self._list.count()):
                other = self._list.item(i)
                if other is not item:
                    other.setCheckState(Qt.CheckState.Unchecked)
            self._list.blockSignals(False)
            # 勾中即展示对应配置 panel
            self._list.setCurrentItem(item)
        self.selection_changed.emit()

    def clear_selection(self) -> None:
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        self.selection_changed.emit()

    # ------------------------------------------------------------- 读写

    def set_selected(self, configs: dict) -> None:
        """按 {key: config} 回填（单选：仅勾选注册表顺序中的第一个匹配项）。"""
        checked_key: str | None = None
        self._list.blockSignals(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            key = item.data(Qt.ItemDataRole.UserRole)
            if checked_key is None and key in configs:
                checked_key = key
                item.setCheckState(Qt.CheckState.Checked)
                self._list.setCurrentItem(item)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._list.blockSignals(False)
        for key, cfg in configs.items():
            if key in self._panels:
                self._panels[key].set_config(cfg)
        self.selection_changed.emit()

    def selected_keys(self) -> list[str]:
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                return [item.data(Qt.ItemDataRole.UserRole)]
        return []

    def selected_configs(self) -> dict:
        """当前勾选模块的配置（0 或 1 项）。"""
        return {key: self._panels[key].config() for key in self.selected_keys()}
