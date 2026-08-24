"""Read Raw 对话框 GUI 冒烟验证（离屏，不入库）。"""
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["LEOPARDIQTS_CONFIG_DIR"] = tempfile.mkdtemp(prefix="lqiq_")
sys.path.insert(0, r"F:\project\python\LeopardIQTest_Software")

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication([])

# 1. 主窗口可构建，Utilities 菜单含 Read Raw 入口
from iqtest.main_window import MainWindow
window = MainWindow()
menu = window.btn_utilities_menu.menu()
texts = [a.text() for a in menu.actions()]
assert "Generalized Read Raw…" in texts, texts
assert menu.actions()[0].isEnabled()
print("✅ Utilities 菜单含 Generalized Read Raw…（可用）")

# 2. 对话框：默认值 → 修改 → 保存 → 重开读取一致
from iqtest.widgets.read_raw_dialog import ReadRawDialog, config_from_form
from iqtest.config.read_raw_settings import get_read_raw_params

dlg = ReadRawDialog()
values = dlg.form.values()
assert values["width"] == 0 and values["bit_depth"] == "16", values
assert "header_bytes" not in values and "black_level" not in values, values
dlg.form.set_values({"width": 800, "height": 600, "cfa": "RGGB"})
saved = dlg.form.values()
cfg = config_from_form(saved)
assert cfg.width == 800 and cfg.cfa == "RGGB"
from iqtest.config.read_raw_settings import save_read_raw_params
path = save_read_raw_params(saved)
loaded = get_read_raw_params()
assert loaded["width"] == 800 and loaded["cfa"] == "RGGB", loaded
print(f"✅ 设置保存/读取一致（header/black_level 已移除）：{path}")

# 3. 用全局设置（无模块参数）读取 .raw → 走 Read Raw 设置 + 自动识别
raw_path = os.path.join(os.environ["LEOPARDIQTS_CONFIG_DIR"], "t.raw")
np.zeros((1200, 1920), dtype=np.uint16).tofile(raw_path)
from pathlib import Path
from iqtest.analysis.mtf_adapter import load_raw_image
img = load_raw_image(Path(raw_path), {"cfa": "Y"})
assert img.shape == (1200, 1920, 1), img.shape
# 模块参数覆盖全局设置（800×600 与文件不符 → 自动识别）
img2 = load_raw_image(Path(raw_path), {"cfa": "Y", "raw_width": 800, "raw_height": 600})
assert img2.shape == (1200, 1920, 1), img2.shape
print("✅ 全局设置回落 + 模块参数覆盖均正常")

# 4. MTF 面板默认配置不再含 RAW 参数
from iqtest.panels.mtf_panel import MtfPanel
keys = set(MtfPanel.default_config()["params"])
assert "raw_width" not in keys and "cfa" not in keys, keys
print("✅ MTF 面板参数已收敛（无 RAW 读取参数）")

# 5. 真实 GRBG 文件：彩色去马赛克预览（RGB888，且通道间有差异）
from PySide6.QtGui import QImage
from iqtest.widgets.read_raw_dialog import preview_qimage

real_raw = (r"F:\project\python\LeopardIQTest_Software\assets\data\MTF"
            r"\camera_0\1\2-0.6\SN_2-0.6_D_07_28_2026_T_16_37_32.raw")
if os.path.isfile(real_raw):
    from leopardiq.utils.raw_reader import RawReadConfig, read_raw
    cfg = RawReadConfig(cfa="GRBG", demosaic=False)
    mosaic, info = read_raw(real_raw, cfg)
    assert (info.width, info.height) == (1920, 1200)
    qimg = preview_qimage(mosaic, "GRBG", 16)
    assert qimg.format() == QImage.Format.Format_RGB888, qimg.format()
    # 彩色图三个通道不应完全相同（否则就是灰色）
    buf = qimg.bits()[: qimg.sizeInBytes()]
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(qimg.height(), qimg.width(), 3)
    ch_std = [float(arr[:, :, c].std()) for c in range(3)]
    diff = float(np.abs(arr[:, :, 0].astype(int) - arr[:, :, 2].astype(int)).mean())
    assert diff > 1.0, f"R/B 通道几乎相同（仍为灰色？）mean|R-B|={diff:.3f}"
    print(f"✅ GRBG 彩色预览 RGB888，mean|R-B|={diff:.1f}（非灰色）")
else:
    print("⚠️ 真实 RAW 不存在，跳过彩色预览检查")

window.close()
print("\nGUI 冒烟验证全部通过")
