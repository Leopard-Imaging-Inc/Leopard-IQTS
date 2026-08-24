"""config 驱动的表单生成器。

字段以 dict 描述（见 iqtest/panels/*_panel.py 中的 PARAMS / CRITERIA）：
    {"key": "readout1_min", "label": "Readout1 下限", "type": "float",
     "default": 0.10, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "..."}

支持类型：bool / int / float / choice / text。
新增模块只需提供 schema，表单自动生成（规划 §4.1「config 驱动」）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

#: 字段 schema 中允许携带的说明键（不生成控件）
_META_KEYS = {"key", "label", "type", "default", "tooltip"}


def default_values(fields: list[dict]) -> dict:
    """提取一组字段的默认值。"""
    return {f["key"]: f.get("default") for f in fields}


class ConfigForm(QWidget):
    """按字段 schema 自动生成的表单。"""

    def __init__(
        self,
        fields: list[dict],
        values: dict | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._widgets: dict[str, tuple[dict, QWidget]] = {}
        self._labels: dict[str, QLabel] = {}
        layout = QFormLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(16)
        for field in fields:
            widget = self._make_widget(field)
            tooltip = field.get("tooltip")
            if tooltip:
                widget.setToolTip(tooltip)
            self._widgets[field["key"]] = (field, widget)
            label = QLabel(field.get("label", field["key"]))
            self._labels[field["key"]] = label
            layout.addRow(label, widget)
        self.set_values(values or default_values(fields))

    # ------------------------------------------------------------- 控件构造

    @staticmethod
    def _make_widget(field: dict) -> QWidget:
        ftype = field["type"]
        if ftype == "bool":
            return QCheckBox()
        if ftype == "int":
            w = QSpinBox()
            w.setRange(int(field.get("min", 0)), int(field.get("max", 999_999)))
            w.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            return w
        if ftype == "float":
            w = QDoubleSpinBox()
            w.setDecimals(int(field.get("decimals", 4)))
            w.setRange(float(field.get("min", -1e9)), float(field.get("max", 1e9)))
            w.setSingleStep(float(field.get("step", 0.01)))
            w.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            return w
        if ftype == "choice":
            w = QComboBox()
            w.addItems([str(c) for c in field["choices"]])
            return w
        if ftype == "text":
            return QLineEdit()
        raise ValueError(f"未知字段类型: {ftype!r}（字段 {field.get('key')!r}）")

    # ------------------------------------------------------------- 读写

    def widget(self, key: str) -> QWidget:
        """按字段 key 取控件（供面板做联动，如单位切换时调整 SpinBox 范围）。"""
        return self._widgets[key][1]

    def set_label(self, key: str, text: str) -> None:
        """更新字段行标签（如单位切换后在标签中显示当前单位）。"""
        if key in self._labels:
            self._labels[key].setText(text)

    def values(self) -> dict:
        out: dict = {}
        for key, (field, w) in self._widgets.items():
            ftype = field["type"]
            if ftype == "bool":
                out[key] = w.isChecked()
            elif ftype in ("int", "float"):
                out[key] = w.value()
            elif ftype == "choice":
                out[key] = w.currentText()
            elif ftype == "text":
                out[key] = w.text()
        return out

    def set_values(self, values: dict) -> None:
        for key, (field, w) in self._widgets.items():
            if key not in values or values[key] is None:
                continue
            value = values[key]
            ftype = field["type"]
            try:
                if ftype == "bool":
                    w.setChecked(bool(value))
                elif ftype == "int":
                    w.setValue(int(value))
                elif ftype == "float":
                    w.setValue(float(value))
                elif ftype == "choice":
                    idx = w.findText(str(value))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif ftype == "text":
                    w.setText(str(value))
            except (TypeError, ValueError):
                continue  # 非法值保留默认，不中断整个表单
