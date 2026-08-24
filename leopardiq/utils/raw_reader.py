"""
Simplified Generalized Read Raw for LeopardIQ testing software.

A converged single entry point for reading binary RAW files from sensor
development systems, inspired by (and deliberately much simpler than)
Imatest's "Generalized Read Raw" (https://www.imatest.com/docs/raw/).

Pipeline（与 Cal_MTF/scripts/mtf_single.py 的 load_image 对齐）:
    np.fromfile (skip header, byte order, bit depth)
        → reshape to (H, W, C)
        → 位深左移（10/12/14-bit 按 uint16 存储读取后左移到 16bit）
        → subtract black level (clip negatives)
        → optional CFA demosaic → grayscale（默认 BT.709 浮点系数）
        → float32 image + RawReadInfo metadata

Deliberately out of scope (fields reserved for future extension):
    packed 10/12-bit MIPI data, gamma / white balance / color matrix,
    RCCC / RGBIR sensors.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

#: CFA pattern → OpenCV demosaic code.
#: （OpenCV 命名与习惯命名错位的实测映射：
#:   RGGB 数据用 COLOR_BayerBG2BGR 解码才能得到正确 R/B 通道）
DEMOSAIC_CODES: dict[str, int] = {
    "RGGB": cv2.COLOR_BayerBG2BGR,
    "BGGR": cv2.COLOR_BayerRG2BGR,
    "GRBG": cv2.COLOR_BayerGB2BGR,
    "GBRG": cv2.COLOR_BayerGR2BGR,
}

#: 支持的 CFA 取值（"Y" = mono / 不做去马赛克）
CFA_PATTERNS: Tuple[str, ...] = ("Y", "RGGB", "BGGR", "GRBG", "GBRG")

#: bit_depth → numpy dtype（10/12/14-bit 按 uint16 存储读取，读取后左移到 16bit）
BIT_DEPTH_DTYPES: dict[int, type] = {
    8: np.uint8,
    10: np.uint16,
    12: np.uint16,
    14: np.uint16,
    16: np.uint16,
}

#: 去马赛克后转灰度的方法（与 mtf_single.py 一致）
GRAY_METHODS: Tuple[str, ...] = ("BT709", "BGR2GRAY")

#: 常见 sensor 分辨率 (width, height)，用于按 RAW 文件大小自动识别
COMMON_RESOLUTIONS: list[tuple[int, int]] = [
    (1920, 1200), (1920, 1080), (1920, 1536), (1600, 1200), (1600, 1300),
    (2048, 1536), (2592, 1944), (2592, 1536), (1280, 720), (1280, 960),
    (1280, 1024), (1280, 800), (1440, 1080), (640, 480), (752, 480),
    (3840, 2160), (4096, 3072), (4208, 3120), (3264, 2448), (5472, 3648),
]


@dataclass
class RawReadConfig:
    """Generalized Read Raw 参数集。"""

    width: int = 0              # 像素宽；与文件大小不符时按常见分辨率自动识别
    height: int = 0             # 像素高；同上
    bit_depth: int = 16         # 8 / 10 / 12 / 14 / 16；10/12/14 按 uint16 存储读取并左移到 16bit
    byte_order: str = "little"  # "little" / "big"
    header_bytes: int = 0       # 跳过的文件头字节数
    channels: int = 1           # 每像素通道数（单通道 Bayer / mono 为 1）
    black_level: float = 0.0    # 读取后减去的黑电平（截负值）
    cfa: str = "Y"              # Y / RGGB / BGGR / GRBG / GBRG
    demosaic: bool = True       # Bayer 数据是否去马赛克并转灰度
    gray_method: str = "BT709"  # 去马赛克后灰度转换方法：BT709 / BGR2GRAY


@dataclass
class RawReadInfo:
    """read_raw 返回的元数据（实际生效的读取参数）。"""

    path: str
    width: int
    height: int
    bit_depth: int
    byte_order: str
    header_bytes: int
    channels: int
    black_level: float
    cfa: str
    demosaiced: bool
    gray_method: str = "BT709"
    resolution_guessed: bool = False  # 分辨率是否由文件大小自动识别


def guess_raw_resolution(
    nbytes: int, bytes_per_pixel: int = 2, channels: int = 1
) -> Optional[tuple[int, int]]:
    """按文件字节数猜测 RAW 分辨率；无匹配返回 None。"""
    unit = bytes_per_pixel * channels
    if unit <= 0 or nbytes % unit != 0:
        return None
    pixels = nbytes // unit
    for width, height in COMMON_RESOLUTIONS:
        if width * height == pixels:
            return width, height
    return None


def _make_dtype(bit_depth: int, byte_order: str) -> np.dtype:
    if bit_depth not in BIT_DEPTH_DTYPES:
        raise ValueError(
            f"暂不支持的位深：{bit_depth}（支持 {sorted(BIT_DEPTH_DTYPES)}；"
            f"packed 10/12-bit 需先解包）"
        )
    dtype = np.dtype(BIT_DEPTH_DTYPES[bit_depth])
    if byte_order == "big":
        dtype = dtype.newbyteorder(">")
    elif byte_order != "little":
        raise ValueError(f"未知字节序：{byte_order!r}（应为 'little' 或 'big'）")
    return dtype


def demosaic_gray(mosaic: np.ndarray, cfa: str,
                  gray_method: str = "BT709") -> np.ndarray:
    """Bayer 去马赛克并转灰度（与 mtf_single.py 的 demosaic_gray 一致）。

    Args:
        mosaic: 单通道 Bayer mosaic 整型图像（uint8 / uint16）。
        cfa: Bayer 排布（RGGB / BGGR / GRBG / GBRG）。
        gray_method: 灰度转换方法，BT709（默认，浮点系数保留精度）/
                     BGR2GRAY（OpenCV BT.601）。
    """
    if cfa not in DEMOSAIC_CODES:
        raise ValueError(f"未知 CFA pattern：{cfa!r}")
    bgr = cv2.demosaicing(mosaic, DEMOSAIC_CODES[cfa])
    if gray_method == "BT709":
        # BT.709 灰度转换: Gray = 0.2125*R + 0.7154*G + 0.0721*B
        # bgr 为 BGR 通道顺序: 通道2=R, 通道1=G, 通道0=B
        gray = (bgr[:, :, 2].astype(np.float64) * 0.2125
                + bgr[:, :, 1].astype(np.float64) * 0.7154
                + bgr[:, :, 0].astype(np.float64) * 0.0721)
    elif gray_method == "BGR2GRAY":
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        raise ValueError(
            f"不支持的灰度转换方法: {gray_method!r}，可选: {list(GRAY_METHODS)}"
        )
    return gray


def read_raw(
    img_path: str | os.PathLike,
    config: Optional[RawReadConfig] = None,
) -> Tuple[np.ndarray, RawReadInfo]:
    """
    Generalized Read Raw 入口：按 config 读取二进制 RAW 文件。

    Args:
        img_path: RAW 文件路径。
        config: 读取参数；None 时使用默认 RawReadConfig()。

    Returns:
        Tuple of (img, info):
            - img: (H, W, C) float32。Bayer + demosaic=True 时为 (H, W, 1) 灰度；
                   否则为原始 mosaic / mono 数据。
            - info: 实际生效的读取参数（含分辨率是否自动识别）。

    Raises:
        ValueError: 分辨率与文件大小不符且无法自动识别、未知 CFA、
                    不支持的位深 / 字节序。
    """
    if config is None:
        config = RawReadConfig()
    path = Path(img_path)

    dtype = _make_dtype(config.bit_depth, config.byte_order)
    bytes_per_pixel = dtype.itemsize

    # ── 分辨率：校验 + 自动识别 ───────────────────────────────
    width, height = int(config.width), int(config.height)
    nbytes = path.stat().st_size - config.header_bytes
    if nbytes <= 0:
        raise ValueError(
            f"RAW 数据区为空：{path.name}（文件 {path.stat().st_size} 字节，"
            f"header {config.header_bytes} 字节）"
        )
    guessed = False
    if (width < 8 or height < 8
            or width * height * bytes_per_pixel * config.channels != nbytes):
        auto = guess_raw_resolution(nbytes, bytes_per_pixel, config.channels)
        if auto is not None:
            width, height = auto
            guessed = True
        elif width < 8 or height < 8:
            raise ValueError(
                f"读取 .raw 需先填写有效分辨率：{path.name} "
                f"数据区共 {nbytes} 字节（{config.bit_depth}-bit = "
                f"{nbytes // bytes_per_pixel} px），未匹配到常见分辨率"
            )
        else:
            raise ValueError(
                f"RAW 分辨率与文件大小不符：{path.name} 数据区共 {nbytes} 字节"
                f"（{config.bit_depth}-bit = {nbytes // bytes_per_pixel} px），"
                f"参数为 {width}×{height}（{width * height} px）。"
                f"请修改 RAW 宽度/高度参数。"
            )

    # ── 读取 ────────────────────────────────────────────────
    count = width * height * config.channels
    raw = np.fromfile(
        str(path), dtype=dtype, count=count, offset=config.header_bytes
    )
    if raw.size != count:
        raise ValueError(
            f"RAW 数据长度不足：{path.name} 期望 {count} 像素，"
            f"实际读到 {raw.size}"
        )
    raw_img = raw.reshape(height, width, config.channels)

    # ── 位深左移（与 mtf_single.py 一致：10/12/14-bit → 16bit）──
    storage_bits = 8 if BIT_DEPTH_DTYPES[config.bit_depth] is np.uint8 else 16
    if config.bit_depth < storage_bits:
        raw_img = np.left_shift(raw_img, storage_bits - config.bit_depth)
    img = raw_img.astype(np.float32)

    # ── 黑电平（位深左移之后扣除，与 mtf_single.py 顺序一致）──
    if config.black_level:
        img = img - float(config.black_level)
        img[img < 0] = 0

    # ── CFA 去马赛克 ────────────────────────────────────────
    cfa_key = config.cfa
    if cfa_key not in CFA_PATTERNS:
        raise ValueError(f"未知 CFA pattern：{cfa_key!r}")
    if config.gray_method not in GRAY_METHODS:
        raise ValueError(
            f"不支持的灰度转换方法: {config.gray_method!r}，可选: {list(GRAY_METHODS)}"
        )
    demosaiced = False
    if cfa_key in DEMOSAIC_CODES and config.demosaic:
        mosaic = np.squeeze(img)
        if mosaic.ndim != 2:
            raise ValueError(
                f"去马赛克要求单通道数据（channels=1），当前 shape={img.shape}"
            )
        # 转回原始整型做去马赛克（OpenCV demosaicing 要求 8/16-bit 整型；
        # 10/12/14-bit 已左移到 16bit，统一按 uint16 处理）
        base_dtype = BIT_DEPTH_DTYPES[config.bit_depth]
        mosaic = np.clip(mosaic, 0, np.iinfo(base_dtype).max).astype(base_dtype)
        gray = demosaic_gray(mosaic, cfa_key, config.gray_method)
        img = gray.astype(np.float32)[:, :, np.newaxis]
        demosaiced = True

    info = RawReadInfo(
        path=str(path),
        width=width,
        height=height,
        bit_depth=config.bit_depth,
        byte_order=config.byte_order,
        header_bytes=config.header_bytes,
        channels=config.channels,
        black_level=float(config.black_level),
        cfa=cfa_key,
        demosaiced=demosaiced,
        gray_method=config.gray_method,
        resolution_guessed=guessed,
    )
    return img, info
