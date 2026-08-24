"""Figure 窗口框架：FigureWindow（独立结果窗）+ FigureManager（统一管理）。

- 每个分析模块结果弹一个 FigureWindow（Imatest 风格，可并排对比）；
- FigureManager 跟踪全部打开的窗口，CLOSE FIGURES 一键关闭；
- M3 各模块图表控件作为 content 嵌入，窗口框架不变。
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class ResultSummaryView(QWidget):
    """结果 dict 的键值摘要表（M2 stub / M3 数值结果的通用展示）。"""

    def __init__(self, result: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        table = QTableWidget(len(result), 2)
        table.setHorizontalHeaderLabels(["项目", "值"])
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for row, (key, value) in enumerate(result.items()):
            table.setItem(row, 0, QTableWidgetItem(str(key)))
            if isinstance(value, (dict, list)):
                text = json.dumps(value, ensure_ascii=False)
            else:
                text = str(value)
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            table.setItem(row, 1, item)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(table)


class FigureWindow(QWidget):
    """独立结果 Figure 窗口。"""

    closed = Signal(str)  # figure_id

    def __init__(
        self,
        figure_id: str,
        title: str,
        content: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.figure_id = figure_id
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(560, 440)

        close_btn = QPushButton("CLOSE")
        close_btn.clicked.connect(self.close)
        hint = QLabel("主窗口 CLOSE FIGURES 可一键关闭全部结果窗")
        hint.setObjectName("panelDesc")

        bottom = QHBoxLayout()
        bottom.addWidget(hint, stretch=1)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(content, stretch=1)
        layout.addLayout(bottom)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.closed.emit(self.figure_id)
        super().closeEvent(event)


class FigureManager(QObject):
    """跟踪并管理全部打开的 Figure 窗口。

    register_view(figure_id, factory) 可为模块注册专属结果视图
    （如 MTF 曲线图）；未注册的模块回退到 ResultSummaryView 键值表。
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._figures: dict[str, FigureWindow] = {}
        self._view_factories: dict = {}
        self._cascade = 0

    @property
    def count(self) -> int:
        return len(self._figures)

    def register_view(self, figure_id: str, factory) -> None:
        """注册模块专属结果视图：factory(result: dict) -> QWidget。"""
        self._view_factories[figure_id] = factory

    def show_result(self, figure_id: str, title: str, result: dict) -> FigureWindow:
        """打开（或替换）某模块的结果 Figure。"""
        self.close(figure_id)
        factory = self._view_factories.get(figure_id)
        content = factory(result) if factory is not None else ResultSummaryView(result)
        fig = FigureWindow(figure_id, f"{title} — 分析结果", content)
        fig.closed.connect(self._on_closed)
        self._cascade = (self._cascade + 1) % 8
        offset = 32 * self._cascade
        fig.move(160 + offset, 120 + offset)
        fig.show()
        self._figures[figure_id] = fig
        return fig

    def close(self, figure_id: str) -> None:
        fig = self._figures.pop(figure_id, None)
        if fig is not None:
            fig.blockSignals(True)  # 主动关闭不再回发 closed
            fig.close()

    def close_all(self) -> int:
        """关闭全部 Figure，返回关闭数量。"""
        n = len(self._figures)
        for figure_id in list(self._figures):
            self.close(figure_id)
        return n

    def _on_closed(self, figure_id: str) -> None:
        self._figures.pop(figure_id, None)
