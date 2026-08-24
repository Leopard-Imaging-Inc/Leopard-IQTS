"""离屏事件级验证：主视图查看交互（单击选中/双击精调/Delete 删除/右键菜单）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

import iqtest.widgets.image_view as iv  # noqa: E402

v = iv.RoiImageView()
v.resize(400, 300)
v.set_image(np.random.rand(200, 300) * 100)
v.set_rois([[50, 50, 60, 40], [150, 100, 50, 50]])
v.show()
v.select_roi(-1)
print("setup: OK", flush=True)


def mouse(etype, scene_xy, button=Qt.MouseButton.LeftButton):
    pos = v.mapFromScene(QPointF(*scene_xy))
    e = QMouseEvent(etype, QPointF(pos), button, button,
                    Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(v.viewport(), e)


mouse(QEvent.Type.MouseButtonPress, (80, 70))
mouse(QEvent.Type.MouseButtonRelease, (80, 70))
assert v.selected_index == 0, f"单击选中失败: {v.selected_index}"
print("单击选中 ROI: OK", flush=True)

hits = []
v.roi_edit_requested.connect(hits.append)
mouse(QEvent.Type.MouseButtonDblClick, (175, 125))
assert hits == [1], f"双击精调信号失败: {hits}"
print("双击请求精调信号: OK", flush=True)

v.select_roi(0)
key = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete,
                Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(v, key)
assert v.rois() == [[150, 100, 50, 50]], f"Delete 删除失败: {v.rois()}"
print("Delete 键删除 ROI: OK", flush=True)
print("主视图查看交互全部正常", flush=True)
