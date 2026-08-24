"""ROI 框选 + 精调弹框（Imatest SFR ROI selection 风格，参考 imatest.com/docs/sfr_instructions2/#roi）。

功能（对应 Imatest ROI fine adjustment 对话框）：
  - draw_new=True（框选入口）：先在弹框图像上拖拽画出粗 ROI（虚线预览），
    画出后自动进入精调状态；取消则不产生任何改动；
  - 整体移动 ROI（↑↓←→，步长可选）；
  - 单边缘调整（T/B/L/R 双边按钮）；
  - 步长：1 / 5 / 15 pixel 单选（默认 1px）；
  - L/R/T/B 数值框直接输入（回车生效，自图像左上角计）；
  - 视图：滚轮缩放、拖拽平移、「显示全图 / 适应 ROI」切换；
  - 多 ROI 时「上一个 / 下一个」切换编辑。

用法：
    dlg = RoiFineTuneDialog(image_2d, rois, current=0, parent=...)          # 精调已有 ROI
    dlg = RoiFineTuneDialog(image_2d, rois, parent=..., draw_new=True)      # 框选新 ROI
    if dlg.exec() == QDialog.Accepted:
        new_rois = dlg.rois()
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from iqtest.widgets.image_view import MIN_ROI_SIZE, float_image_to_qimage

#: 步长选项（radio 顺序：1 / 5 / 15 pixel）
_STEPS = [1, 5, 15]

_ROI_PEN = QPen(QColor("#e8912d"), 2)
_ROI_PEN.setCosmetic(True)
_ROI_DRAW_PEN = QPen(QColor("#e8912d"), 2, Qt.PenStyle.DashLine)
_ROI_DRAW_PEN.setCosmetic(True)


class _ZoomView(QGraphicsView):
    """弹框内的图像视图：滚轮缩放 + 拖拽平移；可切换为框选模式（画粗 ROI）。"""

    roi_drawn = Signal(list)  # 框选完成：[x, y, w, h]（图像像素坐标）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor("#4a5259"))
        self._draw_enabled = False
        self._draft: QGraphicsRectItem | None = None
        self._draft_start: QRectF | None = None

    def enable_draw(self, on: bool) -> None:
        """切换框选模式：开 → 左键拖拽画矩形（十字光标）；关 → 恢复拖拽平移。"""
        self._draw_enabled = on
        self.setDragMode(
            QGraphicsView.DragMode.NoDrag if on
            else QGraphicsView.DragMode.ScrollHandDrag
        )
        if on:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.unsetCursor()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._draw_enabled and event.button() == Qt.MouseButton.LeftButton:
            pos = self.mapToScene(event.position().toPoint())
            self._draft_start = QRectF(pos, pos)
            self._draft = self._scene.addRect(self._draft_start, QPen(_ROI_DRAW_PEN))
            self._draft.setZValue(10)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._draft is not None and self._draft_start is not None:
            pos = self.mapToScene(event.position().toPoint())
            rect = QRectF(self._draft_start.topLeft(), pos).normalized()
            rect = rect.intersected(self._scene.sceneRect())
            self._draft.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._draft is not None:
            rect = self._draft.rect()
            self._scene.removeItem(self._draft)
            self._draft = None
            self._draft_start = None
            if rect.width() >= MIN_ROI_SIZE and rect.height() >= MIN_ROI_SIZE:
                self.roi_drawn.emit([
                    int(round(rect.x())), int(round(rect.y())),
                    int(round(rect.width())), int(round(rect.height())),
                ])
            event.accept()
            return
        super().mouseReleaseEvent(event)


class RoiFineTuneDialog(QDialog):
    """ROI 框选/精调弹框。image 为 2D float 灰度图（全分辨率）。

    draw_new=True 时为框选入口：先在视图中拖拽画出新 ROI（此前精调控件禁用），
    画出后进入精调状态；此时 rois 可为空列表。
    """

    def __init__(
        self,
        image: np.ndarray,
        rois: list,
        current: int = 0,
        parent: QWidget | None = None,
        draw_new: bool = False,
    ) -> None:
        super().__init__(parent)
        if not rois and not draw_new:
            raise ValueError("rois 不能为空")
        self._draw_new = draw_new
        self._new_drawn = False      # 框选模式下是否已画出新 ROI
        self.setWindowTitle("ROI 框选 / 精调")
        self.resize(960, 640)

        self._rois = [list(map(int, r[:4])) for r in rois]
        self._idx = max(0, min(int(current), len(self._rois) - 1)) if self._rois else 0
        gray = np.squeeze(np.asarray(image))
        if gray.ndim != 2:
            raise ValueError(f"image 需为 2D 灰度图，got shape={gray.shape}")
        self._img_h, self._img_w = gray.shape

        # ---- 视图
        self._view = _ZoomView(self)
        self._pixmap_item: QGraphicsPixmapItem = self._view._scene.addPixmap(
            QPixmap.fromImage(float_image_to_qimage(gray))
        )
        self._pixmap_item.setZValue(-1)
        self._view._scene.setSceneRect(QRectF(0, 0, self._img_w, self._img_h))
        self._rect_item = QGraphicsRectItem()
        self._rect_item.setPen(QPen(_ROI_PEN))
        self._rect_item.setZValue(5)
        self._view._scene.addItem(self._rect_item)

        # ---- 左：控制面板
        self._controls = self._build_controls()

        # ---- 顶：ROI 切换 + 框选提示
        self._btn_prev = QPushButton("◀ 上一个 ROI")
        self._btn_next = QPushButton("下一个 ROI ▶")
        self._roi_label = QLabel()
        self._roi_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._roi_label.setStyleSheet("font-weight: 700;")
        nav = QHBoxLayout()
        nav.addWidget(self._btn_prev)
        nav.addWidget(self._roi_label, stretch=1)
        nav.addWidget(self._btn_next)

        self._hint = QLabel("在图像上按住左键拖拽，框选包含一条黑白斜边的 ROI")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setStyleSheet("color: #e8912d; font-weight: 700;")

        # ---- 底：L/R/T/B 数值 + 尺寸 + 确认按钮
        bottom = self._build_bottom()

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.addLayout(nav)
        center.addWidget(self._hint)
        center.addWidget(self._view, stretch=1)
        center.addLayout(bottom)

        body = QHBoxLayout(self)
        body.setContentsMargins(12, 12, 12, 12)
        body.setSpacing(12)
        body.addWidget(self._controls)
        body.addLayout(center, stretch=1)

        # ---- 信号
        self._btn_prev.clicked.connect(lambda: self._switch_roi(-1))
        self._btn_next.clicked.connect(lambda: self._switch_roi(+1))
        self._view.roi_drawn.connect(self._on_view_roi_drawn)

        # ---- 框选入口初始状态：禁用精调控件，等待画框
        multi = len(self._rois) > 1
        self._btn_prev.setVisible(multi)
        self._btn_next.setVisible(multi)
        self._hint.setVisible(draw_new)
        if draw_new:
            self._view.enable_draw(True)
            self._rect_item.hide()
            self._set_editing_enabled(False)

        self._refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 视图在 show 之后才有真实尺寸，此时 fit 才准确
        if self._draw_new and not self._new_drawn:
            self._view.fitInView(
                self._view._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        else:
            self._fit_roi()

    # ------------------------------------------------------------ UI 构建

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(250)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 整体移动
        move_group = QGroupBox("整体移动")
        grid = QGridLayout(move_group)
        grid.addWidget(self._arrow("↑", 0, -1), 0, 1)
        grid.addWidget(self._arrow("←", -1, 0), 1, 0)
        grid.addWidget(self._arrow("→", +1, 0), 1, 2)
        grid.addWidget(self._arrow("↓", 0, +1), 2, 1)
        layout.addWidget(move_group)

        # 边缘调整（T/B/L/R 环绕，步长单选居中 —— Imatest 风格）
        edge_group = QGroupBox("边缘调整")
        egrid = QGridLayout(edge_group)
        egrid.setSpacing(4)
        # (text, 边, 方向, row, col, col_span)  方向=该边向外(+)/向内(-)的单位位移
        for text, edge, d, row, col, span in (
            ("T ^", "t", -1, 0, 1, 2), ("T v", "t", +1, 1, 1, 2),
            ("L <", "l", -1, 2, 0, 1), ("L >", "l", +1, 3, 0, 1),
            ("R <", "r", -1, 2, 3, 1), ("R >", "r", +1, 3, 3, 1),
            ("B ^", "b", -1, 4, 1, 2), ("B v", "b", +1, 5, 1, 2),
        ):
            egrid.addWidget(self._edge_button(text, edge, d), row, col, 1, span)
        # 中间：步长单选（1 / 5 / 15 pixel）
        step_box = QWidget()
        step_box.setObjectName("thumbCard")
        step_layout = QVBoxLayout(step_box)
        step_layout.setContentsMargins(8, 4, 8, 4)
        step_layout.setSpacing(2)
        self._step_group = QButtonGroup(self)
        for i, step in enumerate(_STEPS):
            radio = QRadioButton(f"{step} pixel")
            if i == 0:
                radio.setChecked(True)
            self._step_group.addButton(radio, i)
            step_layout.addWidget(radio)
        egrid.addWidget(step_box, 2, 1, 2, 2,
                        Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(edge_group)

        # 视图切换
        self._btn_full = QPushButton("显示全图")
        self._btn_full.setCheckable(True)
        self._btn_fit = QPushButton("适应 ROI")
        layout.addWidget(self._btn_full)
        layout.addWidget(self._btn_fit)
        layout.addStretch(1)

        self._btn_full.toggled.connect(self._on_full_toggled)
        self._btn_fit.clicked.connect(self._fit_roi)
        return panel

    def _sizable(self, btn: QPushButton) -> QPushButton:
        """按钮自适应文字宽度（最小 46×30），避免不同字体/DPI 下文字截断。"""
        btn.setMinimumSize(46, 30)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return btn

    def _arrow(self, text: str, dx: int, dy: int) -> QPushButton:
        btn = self._sizable(QPushButton(text))
        btn.clicked.connect(lambda: self._move(dx, dy))
        return btn

    def _edge_button(self, text: str, edge: str, d: int) -> QPushButton:
        btn = self._sizable(QPushButton(text))
        btn.clicked.connect(lambda: self._adjust_edge(edge, d))
        return btn

    def _build_bottom(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self._spins: dict[str, QSpinBox] = {}
        for key, label in (("l", "L"), ("r", "R"), ("t", "T"), ("b", "B")):
            spin = QSpinBox()
            spin.setRange(0, max(self._img_w, self._img_h))
            spin.setToolTip("像素坐标（自图像左上角），回车生效")
            spin.setKeyboardTracking(False)  # 回车/失焦才提交
            spin.valueChanged.connect(self._on_spin_changed)
            self._spins[key] = spin
            layout.addWidget(QLabel(label))
            layout.addWidget(spin)
        self._size_label = QLabel()
        self._size_label.setObjectName("panelDesc")
        layout.addSpacing(12)
        layout.addWidget(self._size_label)
        layout.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._btn_ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._btn_ok.setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        return layout

    def _set_editing_enabled(self, on: bool) -> None:
        """框选模式画出 ROI 前，禁用全部精调控件。"""
        self._controls.setEnabled(on)
        for spin in self._spins.values():
            spin.setEnabled(on)
        self._btn_ok.setEnabled(on)
        self._btn_prev.setEnabled(on)
        self._btn_next.setEnabled(on)

    # ------------------------------------------------------------ 状态刷新

    def _current(self) -> list[int]:
        return self._rois[self._idx]

    def _refresh(self) -> None:
        if not self._rois:
            self._roi_label.setText("等待框选…")
            self._size_label.setText(f"(共 {self._img_w}×{self._img_h} px)")
            return
        x, y, w, h = self._current()
        self._rect_item.setRect(QRectF(x, y, w, h))
        for spin in self._spins.values():
            spin.blockSignals(True)
        self._spins["l"].setValue(x)
        self._spins["r"].setValue(x + w)
        self._spins["t"].setValue(y)
        self._spins["b"].setValue(y + h)
        for spin in self._spins.values():
            spin.blockSignals(False)
        self._roi_label.setText(f"ROI {self._idx + 1} / {len(self._rois)}")
        self._size_label.setText(f"({w}×{h}，共 {self._img_w}×{self._img_h} px)")

    def _set_current(self, rect: list[int], refit: bool = False) -> None:
        x, y, w, h = rect
        w = max(MIN_ROI_SIZE, min(w, self._img_w))
        h = max(MIN_ROI_SIZE, min(h, self._img_h))
        x = max(0, min(x, self._img_w - w))
        y = max(0, min(y, self._img_h - h))
        self._rois[self._idx] = [x, y, w, h]
        self._refresh()
        if refit:
            self._fit_roi()

    # ------------------------------------------------------------ 交互

    def _step(self) -> int:
        return _STEPS[max(0, self._step_group.checkedId())]

    def _move(self, dx: int, dy: int) -> None:
        x, y, w, h = self._current()
        step = self._step()
        self._set_current([x + dx * step, y + dy * step, w, h])

    def _adjust_edge(self, edge: str, d: int) -> None:
        x, y, w, h = self._current()
        step = self._step() * d
        if edge == "l":
            new_x = x + step
            w -= new_x - x
            x = new_x
        elif edge == "r":
            w += step
        elif edge == "t":
            new_y = y + step
            h -= new_y - y
            y = new_y
        else:  # "b"
            h += step
        self._set_current([x, y, w, h])

    def _on_spin_changed(self) -> None:
        l, r = self._spins["l"].value(), self._spins["r"].value()
        t, b = self._spins["t"].value(), self._spins["b"].value()
        if r - l < MIN_ROI_SIZE or b - t < MIN_ROI_SIZE:
            self._refresh()  # 非法输入回滚显示
            return
        self._set_current([l, t, r - l, b - t])

    def _switch_roi(self, delta: int) -> None:
        self._idx = (self._idx + delta) % len(self._rois)
        self._refresh()
        self._fit_roi()

    def _on_view_roi_drawn(self, rect: list) -> None:
        """框选模式：画出粗 ROI → 加入列表并进入精调状态。"""
        self._rois.append(list(rect))
        self._idx = len(self._rois) - 1
        self._new_drawn = True
        self._view.enable_draw(False)
        self._hint.hide()
        self._rect_item.show()
        self._set_editing_enabled(True)
        multi = len(self._rois) > 1
        self._btn_prev.setVisible(multi)
        self._btn_next.setVisible(multi)
        self._refresh()
        self._fit_roi()

    def _on_full_toggled(self, checked: bool) -> None:
        self._btn_full.setText("适应 ROI" if checked else "显示全图")
        if checked:
            self._view.fitInView(
                self._view._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio
            )
        else:
            self._fit_roi()

    def _fit_roi(self) -> None:
        if not self._rois:
            return
        if self._btn_full.isChecked():
            self._btn_full.setChecked(False)
            return
        x, y, w, h = self._current()
        margin_x, margin_y = w * 0.6, h * 0.6
        target = QRectF(x - margin_x, y - margin_y,
                        w + 2 * margin_x, h + 2 * margin_y)
        self._view.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)

    # ------------------------------------------------------------ 结果

    def rois(self) -> list[list[int]]:
        """精调后的 ROI 列表（[x, y, w, h]）。"""
        return [list(r) for r in self._rois]
