"""FreeStackedWidget — 忽略页面内容的最小尺寸，允许窗口自由缩放。

QStackedWidget 默认的 minimumSizeHint()/sizeHint() 会取所有页面尺寸的并集
（最宽 x 最高），导致即使只显示一页，主窗口最小尺寸也被所有页面拖到很大、
出现"缩放卡住"。本控件忽略内容尺寸，配合主窗口显式的最小尺寸使用。
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QStackedWidget


class FreeStackedWidget(QStackedWidget):
    """最小尺寸始终为 0，不因页面内容撑大主窗口。"""

    def sizeHint(self) -> QSize:
        return QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, 0)
