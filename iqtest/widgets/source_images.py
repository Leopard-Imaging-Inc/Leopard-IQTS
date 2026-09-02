"""Source images 工作区：拖拽加载 + 列表/网格双模式 + 批量管理。

头部工具栏（右上角）：
  - 批量组（有图时显示）：
      ⊟ 选定/取消选定所有图片（随勾选状态切换图标与提示）
      ⊗ 移除所有图片（清空图像集，文件保留在磁盘）
      ⊕/⊖ 图片选择功能开关（添加面板显隐）
  - 模式组：☷ 列表显示模式 / ▦ 网格显示模式（互斥高亮，默认网格）

添加面板（虚线 drop zone）：
  - 无图时：大虚线框整区显示；
  - 有图且面板开启：收缩为顶部小条（右上角 X 可关闭，等同 ⊖）；
  - 有图且面板关闭：完全隐藏。

勾选状态存于 Session（ImageEntry.selected），ANALYZE 只处理勾选的图像。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QImageReader,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from iqtest.session import IMAGE_EXTENSIONS, Session, scan_folder
from iqtest.widgets.free_stack import FreeStackedWidget

THUMB_SIZE = 240
LIST_THUMB_SIZE = 64

#: 缩略图解码缓存：{str(path): 160px QPixmap}（RAW 等不可解码格式不入缓存）
_THUMB_CACHE: dict[str, QPixmap] = {}

_ACCENT = "#1b9aaa"
_GRAY = "#8a939b"


# ---------------------------------------------------------------------- 图标


def _paint_icon(kind: str, color: str, size: int = 32) -> QIcon:
    """绘制工具栏图标（QPainter 矢量，随状态换色）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c, max(2.0, size / 14.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    m = size * 0.18
    w = size - 2 * m
    cx = cy = size / 2.0

    if kind in ("select_all", "select_all_checked"):
        p.drawRoundedRect(QRectF(m, m, w, w), 3, 3)
        if kind == "select_all":
            p.drawLine(QPointF(m + w * 0.25, cy), QPointF(m + w * 0.75, cy))
        else:
            path = QPainterPath()
            path.moveTo(m + w * 0.20, cy)
            path.lineTo(m + w * 0.42, m + w * 0.72)
            path.lineTo(m + w * 0.82, m + w * 0.28)
            p.drawPath(path)
    elif kind == "remove_all":
        p.drawEllipse(QRectF(m, m, w, w))
        d = w * 0.24
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    elif kind in ("plus_circle", "minus_circle"):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(m * 0.6, m * 0.6, size - 1.2 * m, size - 1.2 * m))
        white = QPen(QColor("#ffffff"), max(2.5, size / 11.0))
        white.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(white)
        d = size * 0.20
        p.drawLine(QPointF(cx - d, cy), QPointF(cx + d, cy))
        if kind == "plus_circle":
            p.drawLine(QPointF(cx, cy - d), QPointF(cx, cy + d))
    elif kind == "list":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        rh = w / 4.6
        gap = (w - 3 * rh) / 2.0
        sq = rh
        for i in range(3):
            y = m + i * (rh + gap)
            p.drawRoundedRect(QRectF(m, y, sq, rh), 1.5, 1.5)
            p.drawRoundedRect(
                QRectF(m + sq + w * 0.14, y, w - sq - w * 0.14, rh), 1.5, 1.5
            )
    elif kind == "grid":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        cell = w / 3.0 * 0.74
        gap = (w - 3 * cell) / 2.0
        for r in range(3):
            for cidx in range(3):
                p.drawRoundedRect(
                    QRectF(m + cidx * (cell + gap), m + r * (cell + gap), cell, cell),
                    1.5,
                    1.5,
                )
    elif kind == "eye":
        p.drawEllipse(QRectF(m, cy - w * 0.28, w, w * 0.56))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        d = w * 0.16
        p.drawEllipse(QPointF(cx, cy), d, d)
    elif kind == "close":
        d = size * 0.22
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))
    p.end()
    return QIcon(pixmap)


def _file_dialog_filter() -> str:
    exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
    return f"图像文件 ({exts});;所有文件 (*)"


def _format_size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "—"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.2f} MB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f} KB"
    return f"{n} B"


def load_thumbnail(entry, size: int = THUMB_SIZE) -> QPixmap | None:
    """解码缩略图（带缓存，按 160px 基准缓存再缩放）。"""
    if not entry.thumbnailable:
        return None
    key = str(entry.path)
    base = _THUMB_CACHE.get(key)
    if base is None:
        reader = QImageReader(key)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return None
        base = QPixmap.fromImage(image).scaled(
            THUMB_SIZE,
            THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        _THUMB_CACHE[key] = base
    if size == THUMB_SIZE:
        return base
    return base.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _thumb_label(entry, size: int) -> QLabel:
    thumb = QLabel()
    thumb.setObjectName("thumbImage")
    thumb.setFixedSize(size, size)
    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
    pixmap = load_thumbnail(entry, size)
    if pixmap is not None:
        thumb.setPixmap(pixmap)
    else:
        thumb.setText(f"image: {entry.path.suffix.upper()[1:] or '?'}")
    return thumb


def _make_check(entry) -> QCheckBox:
    check = QCheckBox()
    check.setObjectName("selCheck")
    check.setChecked(entry.selected)
    check.setToolTip("勾选后该图像参与 ANALYZE")
    return check


# ---------------------------------------------------------------- 网格模式


class ThumbnailCard(QFrame):
    """网格模式卡片：勾选框 + 缩略图 + 文件名 + 大小；右键菜单移除。"""

    remove_requested = Signal(Path)
    selection_toggled = Signal(Path, bool)

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("thumbCard")
        self.setFixedWidth(THUMB_SIZE + 12)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.check = _make_check(entry)
        self.check.toggled.connect(
            lambda on: self.selection_toggled.emit(self.entry.path, on)
        )

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self.check)
        top_row.addStretch(1)

        name = QLabel(entry.name)
        name.setObjectName("thumbName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setToolTip(str(entry.path))

        size_label = QLabel(_format_size(entry.path))
        size_label.setObjectName("thumbSize")
        size_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addLayout(top_row)
        layout.addWidget(
            _thumb_label(entry, THUMB_SIZE), alignment=Qt.AlignmentFlag.AlignHCenter
        )
        layout.addWidget(name)
        layout.addWidget(size_label)

        self.setToolTip(str(entry.path))
        self.set_selected(entry.selected)

    def set_selected(self, selected: bool) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(selected)
        self.check.blockSignals(False)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        menu = QMenu(self)
        action = QAction("移除该图像", self)
        action.triggered.connect(
            lambda: self.remove_requested.emit(self.entry.path)
        )
        menu.addAction(action)
        menu.exec(event.globalPos())


class ImageGridView(QScrollArea):
    """网格模式：缩略图流式卡片。"""

    remove_requested = Signal(Path)
    selection_toggled = Signal(Path, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setSpacing(8)
        self._grid.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.setWidget(self._container)
        self.cards: list[ThumbnailCard] = []
        self._cols = 0

    def show_entries(self, entries) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.cards = []
        self._cols = 0
        for entry in entries:
            card = ThumbnailCard(entry)
            card.remove_requested.connect(self.remove_requested)
            card.selection_toggled.connect(self.selection_toggled)
            self.cards.append(card)
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """按当前可用宽度重排列数（窗口缩小 → 列数减少、卡片下移换行）。"""
        if not self.cards:
            return
        cols = max(1, (self.viewport().width() - 16) // (THUMB_SIZE + 20))
        if cols == self._cols:
            return
        self._cols = cols
        for card in self.cards:
            self._grid.removeWidget(card)
        for i, card in enumerate(self.cards):
            self._grid.addWidget(card, i // cols, i % cols)


# ---------------------------------------------------------------- 列表模式


class ListRowWidget(QFrame):
    """列表模式行：勾选框 + 缩略图 + 文件名 + 大小 + 预览 + 移除。"""

    remove_requested = Signal(Path)
    preview_requested = Signal(Path)
    selection_toggled = Signal(Path, bool)

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("listRow")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        self.check = _make_check(entry)
        self.check.toggled.connect(
            lambda on: self.selection_toggled.emit(self.entry.path, on)
        )

        name = QLabel(entry.name)
        name.setObjectName("listRowName")
        name.setToolTip(str(entry.path))

        size_label = QLabel(_format_size(entry.path))
        size_label.setObjectName("listRowSize")

        self.btn_preview = QToolButton()
        self.btn_preview.setObjectName("rowToolBtn")
        self.btn_preview.setIcon(_paint_icon("eye", _GRAY, 26))
        self.btn_preview.setToolTip("预览图像")
        self.btn_preview.setEnabled(entry.thumbnailable)
        if not entry.thumbnailable:
            self.btn_preview.setToolTip("该格式暂不支持界面预览")
        self.btn_preview.clicked.connect(
            lambda: self.preview_requested.emit(self.entry.path)
        )

        self.btn_remove = QToolButton()
        self.btn_remove.setObjectName("rowToolBtn")
        self.btn_remove.setIcon(_paint_icon("close", _GRAY, 26))
        self.btn_remove.setToolTip("移除该图像")
        self.btn_remove.clicked.connect(
            lambda: self.remove_requested.emit(self.entry.path)
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(12)
        layout.addWidget(self.check)
        layout.addWidget(_thumb_label(entry, LIST_THUMB_SIZE))
        layout.addWidget(name, stretch=1)
        layout.addWidget(size_label)
        layout.addWidget(self.btn_preview)
        layout.addWidget(self.btn_remove)

        self.setToolTip(str(entry.path))
        self.set_selected(entry.selected)

    def set_selected(self, selected: bool) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(selected)
        self.check.blockSignals(False)
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


class ImageListView(QScrollArea):
    """列表模式：逐行显示。"""

    remove_requested = Signal(Path)
    preview_requested = Signal(Path)
    selection_toggled = Signal(Path, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget()
        self._rows = QVBoxLayout(self._container)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        self.setWidget(self._container)
        self.rows: list[ListRowWidget] = []

    def show_entries(self, entries) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.rows = []
        for entry in entries:
            row = ListRowWidget(entry)
            row.remove_requested.connect(self.remove_requested)
            row.preview_requested.connect(self.preview_requested)
            row.selection_toggled.connect(self.selection_toggled)
            self._rows.addWidget(row)
            self.rows.append(row)
        self._rows.addStretch(1)


# ---------------------------------------------------------------- 预览弹框


class ImagePreviewDialog(QDialog):
    """单张图像预览（仅 QImageReader 可解码格式）。"""

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(entry.name)
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reader = QImageReader(str(entry.path))
        reader.setAutoTransform(True)
        image = reader.read()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image).scaled(
                960,
                720,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(pixmap)
        else:
            label.setText("该图像无法解码预览")
            label.setMinimumSize(QSize(320, 200))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(label)


# ---------------------------------------------------------------- 主工作区


class SourceImagesWidget(QWidget):
    """Source images 工作区（拖拽、加载入口、列表/网格模式、批量管理）。"""

    status_message = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setAcceptDrops(True)
        self._mode = "grid"  # "grid" | "list"
        self._panel_open = True  # 图片选择功能（添加面板）开关

        # ---- 头部：IMAGES 标签 + 工具栏
        self._tab_button = QToolButton()
        self._tab_button.setObjectName("imagesTab")
        self._tab_button.setText("🖼  IMAGES")
        self._tab_button.setEnabled(False)

        self.btn_select_all = QToolButton()
        self.btn_select_all.setObjectName("imgToolBtn")
        self.btn_select_all.clicked.connect(self._on_toggle_select_all)

        self.btn_remove_all = QToolButton()
        self.btn_remove_all.setObjectName("imgToolBtn")
        self.btn_remove_all.setIcon(_paint_icon("remove_all", _GRAY))
        self.btn_remove_all.setToolTip("移除所有图片（不删除磁盘文件）")
        self.btn_remove_all.clicked.connect(self._on_remove_all)

        self.btn_panel_toggle = QToolButton()
        self.btn_panel_toggle.setObjectName("imgToolBtn")
        self.btn_panel_toggle.clicked.connect(self._on_toggle_panel)

        self.btn_list_mode = QToolButton()
        self.btn_list_mode.setObjectName("modeBtn")
        self.btn_list_mode.setCheckable(True)
        self.btn_list_mode.setToolTip("列表显示模式")
        self.btn_list_mode.clicked.connect(lambda: self._set_mode("list"))

        self.btn_grid_mode = QToolButton()
        self.btn_grid_mode.setObjectName("modeBtn")
        self.btn_grid_mode.setCheckable(True)
        self.btn_grid_mode.setToolTip("网格显示模式")
        self.btn_grid_mode.clicked.connect(lambda: self._set_mode("grid"))

        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_list_mode)
        self._mode_group.addButton(self.btn_grid_mode)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        header.addWidget(self._tab_button)
        header.addStretch(1)
        header.addWidget(self.btn_select_all)
        header.addWidget(self.btn_remove_all)
        header.addWidget(self.btn_panel_toggle)
        header.addSpacing(12)
        header.addWidget(self.btn_list_mode)
        header.addWidget(self.btn_grid_mode)

        # ---- 添加面板（drop zone，无图时整区 / 有图时收缩为顶部小条）
        self._drop_frame = QFrame()
        self._drop_frame.setObjectName("dropZone")
        self._drop_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._btn_close_panel = QToolButton()
        self._btn_close_panel.setObjectName("imgToolBtn")
        self._btn_close_panel.setIcon(_paint_icon("close", _GRAY, 26))
        self._btn_close_panel.setToolTip("关闭图片选择面板（可通过右上角 ⊕ 重新打开）")
        self._btn_close_panel.clicked.connect(self._on_toggle_panel)

        hint = QLabel("Drop image files here")
        hint.setObjectName("dropHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        or_label = QLabel("or")
        or_label.setObjectName("dropOr")
        or_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_select_images = QPushButton("🖼  SELECT IMAGES")
        self.btn_select_images.setObjectName("primaryButton")
        self.btn_select_folders = QPushButton("☰  SELECT FOLDERS")
        self.btn_select_camera = QPushButton("▸  SELECT CAMERA")
        self.btn_select_camera.setToolTip("相机采集为后续迭代功能（M1 暂不可用）")
        self.btn_select_camera.setEnabled(False)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_select_images)
        btn_row.addWidget(self.btn_select_folders)
        btn_row.addWidget(self.btn_select_camera)
        btn_row.addStretch(1)

        self.radio_files = QRadioButton("Use selected images")
        self.radio_device = QRadioButton("Acquire from device")
        self.radio_files.setChecked(True)
        self.radio_device.setEnabled(False)
        self.radio_device.setToolTip("相机采集为后续迭代功能（M1 暂不可用）")
        self._source_group = QButtonGroup(self)
        self._source_group.addButton(self.radio_files)
        self._source_group.addButton(self.radio_device)

        radio_row = QHBoxLayout()
        radio_row.addStretch(1)
        radio_row.addWidget(self.radio_files)
        radio_row.addWidget(self.radio_device)
        radio_row.addStretch(1)

        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch(1)
        close_row.addWidget(self._btn_close_panel)

        drop_layout = QVBoxLayout(self._drop_frame)
        drop_layout.setContentsMargins(24, 8, 8, 24)
        drop_layout.addLayout(close_row)
        drop_layout.addStretch(2)
        drop_layout.addWidget(hint)
        drop_layout.addWidget(or_label)
        drop_layout.addSpacing(12)
        drop_layout.addLayout(btn_row)
        drop_layout.addSpacing(12)
        drop_layout.addLayout(radio_row)
        drop_layout.addStretch(3)

        # ---- 有图态：列表 / 网格双视图
        self._list_view = ImageListView()
        self._list_view.remove_requested.connect(self._on_remove)
        self._list_view.preview_requested.connect(self._on_preview)
        self._list_view.selection_toggled.connect(self._on_item_toggled)

        self._grid_view = ImageGridView()
        self._grid_view.remove_requested.connect(self._on_remove)
        self._grid_view.selection_toggled.connect(self._on_item_toggled)

        self._view_stack = FreeStackedWidget()
        self._view_stack.addWidget(self._list_view)   # index 0
        self._view_stack.addWidget(self._grid_view)   # index 1

        # ---- 组装
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self._drop_frame)
        layout.addWidget(self._view_stack, stretch=1)

        # ---- 信号
        self.btn_select_images.clicked.connect(self._on_select_images)
        self.btn_select_folders.clicked.connect(self._on_select_folders)
        session.images_changed.connect(self._refresh)
        session.selection_changed.connect(self._sync_selection_ui)
        self._set_mode("grid")
        self._refresh()

    # ------------------------------------------------------------- 状态刷新

    def _refresh(self) -> None:
        has_images = self.session.count > 0

        # 添加面板：无图 → 整区显示；有图 → 依开关收缩为顶部小条或隐藏
        self._drop_frame.setVisible(not has_images or self._panel_open)
        self._drop_frame.setProperty("compact", has_images)
        self._drop_frame.setMaximumHeight(210 if has_images else 16777215)
        self._drop_frame.style().unpolish(self._drop_frame)
        self._drop_frame.style().polish(self._drop_frame)
        self._btn_close_panel.setVisible(has_images)

        # 批量按钮只在有图时可用
        for btn in (self.btn_select_all, self.btn_remove_all, self.btn_panel_toggle):
            btn.setVisible(has_images)
        self._sync_panel_toggle_icon()

        self._view_stack.setVisible(has_images)
        if has_images:
            self._list_view.show_entries(self.session.images)
            self._grid_view.show_entries(self.session.images)
        self._sync_select_all_icon()

    def _sync_selection_ui(self) -> None:
        """勾选状态变化：同步两个视图中的勾选框（不重建缩略图）。"""
        states = {e.path: e.selected for e in self.session.images}
        for card in self._grid_view.cards:
            card.set_selected(states.get(card.entry.path, True))
        for row in self._list_view.rows:
            row.set_selected(states.get(row.entry.path, True))
        self._sync_select_all_icon()

    def _sync_select_all_icon(self) -> None:
        all_selected = (
            self.session.count > 0
            and self.session.selected_count == self.session.count
        )
        kind = "select_all_checked" if all_selected else "select_all"
        self.btn_select_all.setIcon(_paint_icon(kind, _GRAY))
        self.btn_select_all.setToolTip(
            "取消选定所有图片" if all_selected else "选定所有图片"
        )

    def _sync_panel_toggle_icon(self) -> None:
        if self._panel_open:
            self.btn_panel_toggle.setIcon(_paint_icon("minus_circle", _GRAY))
            self.btn_panel_toggle.setToolTip("关闭图片选择功能（隐藏添加面板）")
        else:
            self.btn_panel_toggle.setIcon(_paint_icon("plus_circle", _ACCENT))
            self.btn_panel_toggle.setToolTip("开启图片选择功能（显示添加面板）")

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        is_list = mode == "list"
        self.btn_list_mode.setChecked(is_list)
        self.btn_grid_mode.setChecked(not is_list)
        for btn, active in (
            (self.btn_list_mode, is_list),
            (self.btn_grid_mode, not is_list),
        ):
            kind = "list" if btn is self.btn_list_mode else "grid"
            btn.setIcon(_paint_icon(kind, _ACCENT if active else _GRAY))
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._view_stack.setCurrentIndex(0 if is_list else 1)

    # ------------------------------------------------------------- 工具栏动作

    def _on_toggle_select_all(self) -> None:
        select = self.session.selected_count < self.session.count
        self.session.set_all_selected(select)
        self.status_message.emit(
            "已选定全部图像" if select else "已取消选定全部图像"
        )

    def _on_remove_all(self) -> None:
        n = self.session.count
        self.session.clear_images()
        self.status_message.emit(f"已移除全部 {n} 张图像（文件保留在磁盘中）")

    def _on_toggle_panel(self) -> None:
        self._panel_open = not self._panel_open
        self._refresh()

    def _on_item_toggled(self, path: Path, selected: bool) -> None:
        self.session.set_selected(path, selected)

    def _on_preview(self, path: Path) -> None:
        entry = next((e for e in self.session.images if e.path == path), None)
        if entry is not None:
            ImagePreviewDialog(entry, self).exec()

    # ------------------------------------------------------------- 加载入口

    def _on_select_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图像文件", "", _file_dialog_filter()
        )
        if paths:
            self.add_paths([Path(p) for p in paths])

    def _on_select_folders(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择图像文件夹")
        if folder:
            found = scan_folder(Path(folder))
            if not found:
                self.status_message.emit(f"文件夹中未找到支持的图像：{folder}")
                return
            self.add_paths(found)

    def add_paths(self, paths: list[Path]) -> None:
        added = self.session.add_images(paths)
        skipped = len(paths) - added
        msg = f"已加载 {added} 张图像（共 {self.session.count} 张）"
        if skipped > 0:
            msg += f"，跳过 {skipped} 个（重复或不支持的格式）"
        self.status_message.emit(msg)

    def _on_remove(self, path: Path) -> None:
        self.session.remove_image(path)
        self.status_message.emit(
            f"已移除 {path.name}（剩余 {self.session.count} 张）"
        )

    # ------------------------------------------------------------- 拖拽

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths.extend(scan_folder(p))
            else:
                paths.append(p)
        if paths:
            self.add_paths(paths)
        event.acceptProposedAction()
