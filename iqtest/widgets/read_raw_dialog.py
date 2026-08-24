"""Generalized Read Raw（简化版）设置对话框。

仿照 Imatest 的 Generalized Read Raw（https://www.imatest.com/docs/raw/）收敛而来：
二进制 RAW 的读取参数（分辨率 / 位深 / CFA / 去马赛克）在此统一配置，
全局生效并持久化（见 iqtest.config.read_raw_settings）；各分析模块（MTF/SFR 等）
读取 .raw 时使用这里的设置。

「读取测试…」可按当前表单值试读一个 .raw 文件并预览灰度图，
用于验证 宽/高/位深 是否正确（对应 Imatest Read Raw 的辅助 plot）。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from leopardiq.utils.raw_reader import DEMOSAIC_CODES, RawReadConfig, read_raw
from iqtest.config.lf_config import load_lf_read_raw_params
from iqtest.config.read_raw_settings import (
    READ_RAW_FIELDS,
    default_read_raw_params,
    get_read_raw_params,
    save_read_raw_params,
)
from iqtest.widgets.config_form import ConfigForm
from iqtest.widgets.image_view import RoiImageView, float_image_to_qimage


def config_from_form(values: dict) -> RawReadConfig:
    """表单值 → RawReadConfig（字节序/黑电平固定默认：little / 0）。"""
    return RawReadConfig(
        width=int(values.get("width", 0)),
        height=int(values.get("height", 0)),
        bit_depth=int(values.get("bit_depth", 16)),
        channels=1,
        cfa=str(values.get("cfa", "Y")),
        demosaic=bool(values.get("demosaic", True)),
        gray_method=str(values.get("gray_method", "BT709")),
    )


def preview_qimage(img: np.ndarray, cfa: str, bit_depth: int) -> QImage:
    """读取测试预览图：Bayer → 去马赛克彩色（RGB888，0.5%~99.5% 分位拉伸）；
    mono → 灰度。彩色预览可直接验证 CFA pattern 是否选对。"""
    mosaic = np.squeeze(np.asarray(img, dtype=np.float64))
    if cfa not in DEMOSAIC_CODES:
        return float_image_to_qimage(mosaic)
    base_dtype = np.uint8 if bit_depth == 8 else np.uint16
    clipped = np.clip(mosaic, 0, np.iinfo(base_dtype).max).astype(base_dtype)
    bgr = cv2.demosaicing(clipped, DEMOSAIC_CODES[cfa]).astype(np.float64)
    lo, hi = np.percentile(bgr, (0.5, 99.5))
    if hi <= lo:
        lo, hi = float(bgr.min()), float(bgr.max())
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((bgr - lo) / (hi - lo), 0.0, 1.0)
    rgb = np.ascontiguousarray((norm * 255.0).round().astype(np.uint8)[:, :, ::-1])
    h, w, _ = rgb.shape
    qimg = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return qimg.copy()  # 脱离 numpy 缓冲生命周期


class ReadRawDialog(QDialog):
    """Generalized Read Raw（简化版）设置对话框（Utilities 入口）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generalized Read Raw（简化版）")
        self.resize(760, 720)

        desc = QLabel(
            "二进制 RAW 文件的读取参数，全局生效（MTF/SFR 等模块读取 .raw 时使用）。\n"
            "宽度/高度填 0 时按文件大小自动识别常见分辨率；"
            "「读取测试…」可验证参数（Bayer 显示彩色去马赛克图，可核对 CFA pattern）。"
        )
        desc.setObjectName("panelDesc")
        desc.setWordWrap(True)

        self.form = ConfigForm(READ_RAW_FIELDS, values=get_read_raw_params())

        form_group = QGroupBox("读取参数")
        form_layout = QVBoxLayout(form_group)
        form_layout.addWidget(self.form)

        # ---- 读取测试（预览）----
        preview_group = QGroupBox("读取测试（验证参数）")
        preview_layout = QVBoxLayout(preview_group)
        row = QHBoxLayout()
        self._btn_test = QPushButton("读取测试…")
        self._btn_test.setToolTip("按当前表单参数试读一个 .raw 文件并预览")
        self._test_info = QLabel("未测试")
        self._test_info.setObjectName("panelDesc")
        row.addWidget(self._btn_test)
        row.addWidget(self._test_info, stretch=1)
        preview_layout.addLayout(row)
        self._preview = RoiImageView()
        self._preview.setMinimumHeight(280)
        preview_layout.addWidget(self._preview, stretch=1)

        # ---- 按钮 ----
        self._btn_defaults = QPushButton("恢复默认")
        self._btn_lf_config = QPushButton("Add LF Config…")
        self._btn_lf_config.setToolTip(
            "读取 LenFocus 调焦软件保存的 config.json，"
            "自动将其 \"Camera\" 段参数（分辨率/位深/Bayer）填入表单"
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Close
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_defaults)
        btn_row.addWidget(self._btn_lf_config)
        btn_row.addStretch(1)
        btn_row.addWidget(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(desc)
        layout.addWidget(form_group)
        layout.addWidget(preview_group, stretch=1)
        layout.addLayout(btn_row)

        # ---- 信号 ----
        self._btn_defaults.clicked.connect(
            lambda: self.form.set_values(default_read_raw_params())
        )
        self._btn_test.clicked.connect(self._on_test_read)
        self._btn_lf_config.clicked.connect(self._on_add_lf_config)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)

    # ------------------------------------------------------------ 动作

    def _on_add_lf_config(self) -> None:
        """读取 LenFocus config.json，将 "Camera" 段参数填入表单。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 LenFocus 配置文件", "", "JSON 配置 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            params, summary = load_lf_read_raw_params(path)
        except ValueError as e:
            QMessageBox.warning(self, "Add LF Config", str(e))
            return
        self.form.set_values(params)
        QMessageBox.information(
            self,
            "Add LF Config",
            "已从 LenFocus 配置导入以下参数：\n\n" + "\n".join(summary)
            + "\n\n确认无误后点击「保存」生效。",
        )

    def _on_save(self) -> None:
        path = save_read_raw_params(self.form.values())
        QMessageBox.information(
            self,
            "Generalized Read Raw",
            f"设置已保存并对所有分析模块生效：\n{path}",
        )
        self.accept()

    def _on_test_read(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 RAW 文件", "", "RAW 文件 (*.raw);;所有文件 (*)"
        )
        if not path:
            return
        values = self.form.values()
        cfa = str(values.get("cfa", "Y"))
        try:
            # 预览始终读原始 mosaic，Bayer 时单独做彩色去马赛克显示
            # （分析链路 read_raw 的 demosaic 输出是给算法用的灰度 Y 图）
            cfg = config_from_form(values)
            cfg.demosaic = False
            img, info = read_raw(path, cfg)
        except (ValueError, OSError) as e:
            QMessageBox.warning(self, "读取失败", str(e))
            return
        self._preview.set_image(
            preview_qimage(img, cfa, int(values.get("bit_depth", 16)))
        )
        self._preview.fit()
        guessed = "（分辨率自动识别）" if info.resolution_guessed else ""
        kind = "彩色去马赛克预览" if cfa in DEMOSAIC_CODES else "灰度预览"
        self._test_info.setText(
            f"{Path(info.path).name}：{info.width}×{info.height}{guessed}，"
            f"{kind}，min={img.min():.0f} max={img.max():.0f}"
        )
