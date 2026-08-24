"""分析项模块面板基类：参数表单 + 判定 criteria 表单。

每个模块一个子类（mtf_panel.py 等），只声明 schema：
    MODULE_KEY / TITLE / DESCRIPTION / PARAMS / CRITERIA
"""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from iqtest.widgets.config_form import ConfigForm, default_values


class ModulePanel(QWidget):
    """单个分析项的配置面板（② Select Analysis 对话框右侧页）。"""

    MODULE_KEY: str = ""
    TITLE: str = ""
    DESCRIPTION: str = ""
    PARAMS: list[dict] = []
    CRITERIA: list[dict] = []

    def __init__(self, session=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session

        title = QLabel(self.TITLE)
        title.setObjectName("panelTitle")
        desc = QLabel(self.DESCRIPTION)
        desc.setObjectName("panelDesc")
        desc.setWordWrap(True)

        self.params_form = ConfigForm(self.PARAMS)
        params_group = QGroupBox("参数")
        params_layout = QVBoxLayout(params_group)
        params_layout.addWidget(self.params_form)

        self.criteria_form = ConfigForm(self.CRITERIA)
        criteria_group = QGroupBox("判定 Criteria（PASS/FAIL 阈值）")
        criteria_layout = QVBoxLayout(criteria_group)
        criteria_layout.addWidget(self.criteria_form)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(desc)
        self._add_custom(layout)
        layout.addWidget(params_group)
        layout.addWidget(criteria_group)
        layout.addStretch(1)

    def _add_custom(self, layout: QVBoxLayout) -> None:
        """子类钩子：在参数表单之前插入模块专属控件（如 MTF 的 ROI 编辑器）。"""

    # ------------------------------------------------------------- 读写

    def config(self) -> dict:
        return {
            "params": self.params_form.values(),
            "criteria": self.criteria_form.values(),
        }

    def set_config(self, config: dict) -> None:
        self.params_form.set_values(config.get("params", {}))
        self.criteria_form.set_values(config.get("criteria", {}))

    @classmethod
    def default_config(cls) -> dict:
        return {
            "params": default_values(cls.PARAMS),
            "criteria": default_values(cls.CRITERIA),
        }
