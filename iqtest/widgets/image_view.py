"""图像查看 + 矩形 ROI 展示控件（QGraphicsView）。

对应规划 §4.2 widgets/image_view.py + roi_editor.py（首版只做矩形 ROI）：
  - 左键拖拽空白处：平移；滚轮：以光标为中心缩放；
  - 单击 ROI：选中（橙色高亮）；双击 ROI：请求精调（roi_edit_requested）；
  - 右键点击 ROI / Delete 键：删除该 ROI；
  - set_image 接受 2D float ndarray（自动归一化显示）或 QImage。

框选（画粗 ROI）不在本控件内进行 —— 由 ROI 精调弹框（roi_dialog.py）内置的
框选视图完成，避免主界面误触。

ROI 以 [x, y, w, h]（图像像素坐标，int）存取，供 config JSON 序列化。
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QMenu,
    QWidget,
)

#: 最小 ROI 边长（算法层对 min(shape) < 8 的退化 ROI 判无效，此处同步拦截）
MIN_ROI_SIZE = 8

_ROI_PEN = QPen(QColor("#1b9aaa"), 2)
_ROI_PEN.setCosmetic(True)
_ROI_SELECTED_PEN = QPen(QColor("#e8912d"), 3)
_ROI_SELECTED_PEN.setCosmetic(True)
_ROI_LABEL_COLOR = QColor("#12616c")


def float_image_to_qimage(img: np.ndarray) -> QImage:
    """2D float 图像 → 8-bit 灰度 QImage（0.5%~99.5% 分位拉伸，抗离群像素）。"""
    gray = np.squeeze(np.asarray(img, dtype=np.float64))
    if gray.ndim != 2:
        raise ValueError(f"仅支持 2D 灰度图显示，got shape={gray.shape}")
    lo, hi = np.percentile(gray, (0.5, 99.5))
    if hi <= lo:
        lo, hi = float(gray.min()), float(gray.max())
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((gray - lo) / (hi - lo), 0.0, 1.0)
    data = np.ascontiguousarray((norm * 255.0).round().astype(np.uint8))
    h, w = data.shape
    qimg = QImage(data.data, w, h, w, QImage.Format.Format_Grayscale8)
    return qimg.copy()  # 脱离 numpy 缓冲生命周期


class RoiImageView(QGraphicsView):
    """ROI 展示/查看视图（单一查看模式，防误触，不提供框选）。

    交互：左键拖拽空白处平移；单击 ROI 选中；双击 ROI 请求精调；
    右键 ROI 删除菜单；Delete 键删除选中 ROI；滚轮缩放。
    """

    rois_changed = Signal()
    roi_selected = Signal(int)          # 单击选中 ROI（-1 = 取消选择）
    roi_edit_requested = Signal(int)    # 双击 ROI 请求精调

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#ffffff"))
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._pixmap_item: QGraphicsPixmapItem | None = None
        self._roi_items: list[QGraphicsRectItem] = []
        self._selected: int = -1
        self._press_roi: int = -1
        self._pan_start = None           # (鼠标点, hscroll, vscroll)

    # ------------------------------------------------------------ 图像

    def set_image(self, image) -> None:
        """设置底图（2D float ndarray / QImage / QPixmap），并清空已有 ROI。"""
        self.clear_rois()
        if self._pixmap_item is not None:
            self._scene.removeItem(self._pixmap_item)
            self._pixmap_item = None
        if isinstance(image, np.ndarray):
            image = float_image_to_qimage(image)
        if isinstance(image, QImage):
            image = QPixmap.fromImage(image)
        if not isinstance(image, QPixmap):
            raise TypeError(f"不支持的图像类型: {type(image)!r}")
        self._pixmap_item = self._scene.addPixmap(image)
        self._pixmap_item.setZValue(-1)
        self._scene.setSceneRect(QRectF(image.rect()))

    def has_image(self) -> bool:
        return self._pixmap_item is not None

    def fit(self) -> None:
        """适应窗口显示整幅图像。"""
        if self._pixmap_item is not None:
            self.fitInView(self._pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------ ROI 存取

    def rois(self) -> list[list[int]]:
        """全部 ROI，按创建顺序：[x, y, w, h]（图像像素坐标）。"""
        out = []
        for item in self._roi_items:
            r = item.rect()
            out.append([int(round(r.x())), int(round(r.y())),
                        int(round(r.width())), int(round(r.height()))])
        return out

    def set_rois(self, rois: list) -> None:
        """以 [x, y, w, h] 列表重建 ROI（供 config 回填 / 精调结果写回）。"""
        selected = self._selected
        self.clear_rois()
        for rect in rois or []:
            x, y, w, h = [float(v) for v in rect[:4]]
            self._add_roi_item(QRectF(x, y, w, h))
        if self._roi_items:
            self.select_roi(min(selected, len(self._roi_items) - 1)
                            if selected >= 0 else len(self._roi_items) - 1)
        self.rois_changed.emit()

    def clear_rois(self) -> None:
        for item in self._roi_items:
            self._scene.removeItem(item)
        self._roi_items.clear()
        self._selected = -1
        self._press_roi = -1
        self.rois_changed.emit()

    # ------------------------------------------------------------ 交互

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pixmap_item is None:
            super().mousePressEvent(event)
            return
        pos = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton:
            # 命中 ROI → 候选选中；空白处 → 手动平移
            hit = self._roi_index_at(pos)
            if hit >= 0:
                self._press_roi = hit
            else:
                self._pan_start = (
                    event.position(),
                    self.horizontalScrollBar().value(),
                    self.verticalScrollBar().value(),
                )
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            if self._delete_roi_at(pos, event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_roi >= 0:
            # 命中 ROI 后拖动：取消本次选中候选
            self._press_roi = -1
        if self._pan_start is not None:
            start, h0, v0 = self._pan_start
            delta = event.position() - start
            self.horizontalScrollBar().setValue(int(h0 - delta.x()))
            self.verticalScrollBar().setValue(int(v0 - delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_roi >= 0:
            self.select_roi(self._press_roi)
            self._press_roi = -1
            event.accept()
            return
        if self._pan_start is not None:
            self._pan_start = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pixmap_item is not None:
            pos = self.mapToScene(event.position().toPoint())
            hit = self._roi_index_at(pos)
            if hit >= 0:
                self.select_roi(hit)
                self.roi_edit_requested.emit(hit)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) \
                and 0 <= self._selected < len(self._roi_items):
            self._remove_roi(self._roi_items[self._selected])
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 选中

    @property
    def selected_index(self) -> int:
        return self._selected

    def select_roi(self, index: int) -> None:
        """选中指定 ROI（橙色高亮）；-1 取消选择。"""
        self._selected = index if 0 <= index < len(self._roi_items) else -1
        self._apply_pens()
        self.roi_selected.emit(self._selected)

    def _apply_pens(self) -> None:
        for i, item in enumerate(self._roi_items):
            pen = QPen(_ROI_SELECTED_PEN if i == self._selected else _ROI_PEN)
            item.setPen(pen)

    # ------------------------------------------------------------ 内部

    def _roi_index_at(self, scene_pos) -> int:
        for i in range(len(self._roi_items) - 1, -1, -1):
            if self._roi_items[i].rect().contains(scene_pos):
                return i
        return -1

    def _add_roi_item(self, rect: QRectF) -> None:
        pen = QPen(_ROI_PEN)
        item = self._scene.addRect(rect, pen)
        item.setZValue(5)
        label = QGraphicsSimpleTextItem(f"ROI{len(self._roi_items) + 1}", item)
        label.setBrush(_ROI_LABEL_COLOR)
        label.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIgnoresTransformations)
        label.setPos(rect.topLeft())
        self._roi_items.append(item)

    def _delete_roi_at(self, scene_pos, global_pos) -> bool:
        """右键命中 ROI 时弹出删除菜单；命中（无论是否选择删除）即消费事件。"""
        for item in reversed(self._roi_items):
            if item.rect().contains(scene_pos):
                menu = QMenu(self)
                action = menu.addAction(f"删除 {item.childItems()[0].text()}")
                if menu.exec(global_pos) == action:
                    self._remove_roi(item)
                return True
        return False

    def _remove_roi(self, item: QGraphicsRectItem) -> bool:
        if item not in self._roi_items:
            return False
        removed = self._roi_items.index(item)
        self._scene.removeItem(item)
        self._roi_items.remove(item)
        # 重编号
        for i, it in enumerate(self._roi_items):
            for child in it.childItems():
                if isinstance(child, QGraphicsSimpleTextItem):
                    child.setText(f"ROI{i + 1}")
        # 修正选中下标
        if self._selected == removed:
            self._selected = -1
        elif self._selected > removed:
            self._selected -= 1
        self._apply_pens()
        self.rois_changed.emit()
        return True
