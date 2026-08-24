"""Source images 工作区：拖拽加载 + 缩略图网格。

对应规划 §4.3 右侧区域：
  - 空态：虚线框 "Drop image files here" + SELECT IMAGES / SELECT FOLDERS / SELECT CAMERA
  - 有图态：缩略图卡片网格（右键可移除），整区持续接受拖拽
  - 底部：Use selected images / Acquire from device 切换（采集为后续迭代）
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
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

THUMB_SIZE = 160


def _file_dialog_filter() -> str:
    exts = " ".join(f"*{e}" for e in sorted(IMAGE_EXTENSIONS))
    return f"图像文件 ({exts});;所有文件 (*)"


class ThumbnailCard(QFrame):
    """单张图像缩略图卡片；右键菜单移除。"""

    remove_requested = Signal(Path)

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("thumbCard")
        self.setFixedWidth(THUMB_SIZE + 16)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        thumb = QLabel()
        thumb.setObjectName("thumbImage")
        thumb.setFixedSize(THUMB_SIZE, THUMB_SIZE)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = self._load_thumbnail(entry)
        if pixmap is not None:
            thumb.setPixmap(pixmap)
        else:
            thumb.setText(f"{entry.path.suffix.upper()[1:]}\n无预览")

        name = QLabel(entry.name)
        name.setObjectName("thumbName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setToolTip(str(entry.path))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(thumb, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name)

        self.setToolTip(str(entry.path))

    @staticmethod
    def _load_thumbnail(entry) -> QPixmap | None:
        if not entry.thumbnailable:
            return None
        reader = QImageReader(str(entry.path))
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            return None
        return QPixmap.fromImage(image).scaled(
            THUMB_SIZE,
            THUMB_SIZE,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        menu = QMenu(self)
        action = QAction("移除该图像", self)
        action.triggered.connect(
            lambda: self.remove_requested.emit(self.entry.path)
        )
        menu.addAction(action)
        menu.exec(event.globalPos())


class ImageGrid(QScrollArea):
    """缩略图流式网格。"""

    remove_requested = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setSpacing(12)
        self.setWidget(self._container)

    def show_entries(self, entries) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not entries:
            return
        cols = max(1, (self.viewport().width() - 24) // (THUMB_SIZE + 28))
        for i, entry in enumerate(entries):
            card = ThumbnailCard(entry)
            card.remove_requested.connect(self.remove_requested)
            self._grid.addWidget(card, i // cols, i % cols)
        self._grid.setRowStretch(len(entries) // cols + 1, 1)


class SourceImagesWidget(QWidget):
    """Source images 工作区（含拖拽、三种加载入口、来源切换）。"""

    status_message = Signal(str)

    def __init__(self, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.setAcceptDrops(True)

        # ---- 顶部 IMAGES 标签页位（M1 单页，为后续多页预留）
        self._tab_button = QToolButton()
        self._tab_button.setObjectName("imagesTab")
        self._tab_button.setText("🖼  IMAGES")
        self._tab_button.setEnabled(False)

        # ---- 空态：虚线拖拽区
        self._empty_frame = QFrame()
        self._empty_frame.setObjectName("dropZone")
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

        empty_layout = QVBoxLayout(self._empty_frame)
        empty_layout.setContentsMargins(24, 24, 24, 24)
        empty_layout.addStretch(2)
        empty_layout.addWidget(hint)
        empty_layout.addWidget(or_label)
        empty_layout.addSpacing(12)
        empty_layout.addLayout(btn_row)
        empty_layout.addSpacing(12)
        empty_layout.addLayout(radio_row)
        empty_layout.addStretch(3)

        # ---- 有图态：缩略图网格
        self._grid = ImageGrid()
        self._grid.remove_requested.connect(self._on_remove)

        # ---- 组装
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._tab_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._empty_frame, stretch=1)
        layout.addWidget(self._grid, stretch=1)
        self._grid.hide()

        # ---- 信号
        self.btn_select_images.clicked.connect(self._on_select_images)
        self.btn_select_folders.clicked.connect(self._on_select_folders)
        session.images_changed.connect(self._refresh)
        self._refresh()

    # ------------------------------------------------------------- 状态刷新

    def _refresh(self) -> None:
        has_images = self.session.count > 0
        self._empty_frame.setVisible(not has_images)
        self._grid.setVisible(has_images)
        if has_images:
            self._grid.show_entries(self.session.images)

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
