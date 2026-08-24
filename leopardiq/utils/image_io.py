"""
Image I/O utilities for LeopardIQ testing software.

Handles RAW image file reading and multi-frame image stack loading.
Extracted from leopardiq.utils.read_image and leopardiq.utils.utils (load_imgs).

RAW 读取已收敛到 leopardiq.utils.raw_reader（简化版 Generalized Read Raw）；
本模块的 read_raw_image 等接口保留为兼容 wrapper。

⚠️ 遗留兼容层说明：`read_raw_image` / `read_raw_image_from_config` /
`load_image_stack` / `load_image_stack_with_validation` 为历史接口，仅
`read_mtf_image` 仍被算法库（sfr_analyzer / peak_focus）使用；新代码请
直接使用 leopardiq.utils.raw_reader.read_raw（含位深左移与黑电平处理），
以避免两套 RAW 读取口径不一致。
"""

import os
from typing import Tuple, Optional, List
import numpy as np

from .raw_reader import RawReadConfig, read_raw


def read_raw_image(
    img_path: str,
    width: int,
    height: int,
    dtype: type = np.uint16,
    channels: int = 1,
) -> np.ndarray:
    """
    Read a RAW image file into a numpy array.

    Args:
        img_path: Path to the RAW image file.
        width: Image width in pixels.
        height: Image height in pixels.
        dtype: Data type of the raw pixel values (default: np.uint16).
        channels: Number of channels (default: 1 for monochrome RAW).

    Returns:
        np.ndarray: Image array of shape (height, width, channels) as float32.
    """
    img_data = np.fromfile(img_path, dtype=dtype)
    img = np.reshape(img_data, (height, width, channels))
    img = img.astype(np.float32)
    return img


def read_raw_image_from_config(
    img_path: str, config_data: dict, dtype: type = np.uint16, channels: int = 1
) -> np.ndarray:
    """
    Read a RAW image using dimensions from config_data.

    Args:
        img_path: Path to the RAW image file.
        config_data: Dictionary containing 'width' and 'height' keys.
        dtype: Data type of the raw pixel values.
        channels: Number of channels.

    Returns:
        np.ndarray: Image array of shape (height, width, channels) as float32.
    """
    return read_raw_image(
        img_path,
        width=config_data["width"],
        height=config_data["height"],
        dtype=dtype,
        channels=channels,
    )


def read_mtf_image(
    img_path: str, config_data: dict, channels: int = 3
) -> np.ndarray:
    """
    Read a RAW image for MTF/SFR analysis.
    Applies black level correction from config_data.

    兼容 wrapper：内部走 raw_reader.read_raw（黑电平逻辑已收敛到该模块）。

    Args:
        img_path: Path to the RAW image file.
        config_data: Dictionary containing 'width', 'height', and 'black_level' keys.
        channels: Number of channels.

    Returns:
        np.ndarray: Black-level-corrected image as float32.
    """
    img, _ = read_raw(
        img_path,
        RawReadConfig(
            width=int(config_data["width"]),
            height=int(config_data["height"]),
            channels=channels,
            black_level=float(config_data.get("black_level", 0)),
            cfa="Y",
            demosaic=False,
        ),
    )
    return img


def load_image_stack(
    img_dir: str,
    config_data: dict,
    image_names: Optional[List[str]] = None,
    dtype: type = np.uint16,
    channels: int = 1,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Load multiple RAW images from a directory and compute their average.

    This replaces the original load_imgs() function with a cleaner interface.

    Args:
        img_dir: Directory containing the RAW image files.
        config_data: Dictionary containing 'width' and 'height' keys.
        image_names: Optional list of specific image filenames to load.
                     If None, all files in img_dir are loaded.
        dtype: Data type of the raw pixel values.
        channels: Number of channels per image.

    Returns:
        Tuple of (avg_img, img_stack):
            - avg_img: Mean image of shape (height, width, channels) as float32.
            - img_stack: Stack of all images of shape (N, height, width, channels).
    """
    if image_names is None:
        image_names = sorted(os.listdir(img_dir))

    img_list = []
    for img_name in image_names:
        img_path = os.path.join(img_dir, img_name)
        if os.path.isfile(img_path):
            img = read_raw_image_from_config(
                img_path, config_data, dtype=dtype, channels=channels
            )
            img_list.append(img)

    if not img_list:
        raise ValueError(f"No valid image files found in {img_dir}")

    img_stack = np.array(img_list)
    avg_img = np.mean(img_stack, axis=0)
    return avg_img, img_stack


def load_image_stack_with_validation(
    img_dir: str,
    config_data: dict,
    frame_qty: int,
    dtype: type = np.uint16,
    channels: int = 1,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Load image stack with frame quantity validation.

    Replaces the frame-count check logic from the original get_img_avg().

    Args:
        img_dir: Directory containing the RAW image files.
        config_data: Dictionary with 'width' and 'height'.
        frame_qty: Expected number of frames. Returns None if fewer files exist.
        dtype: Data type of raw pixels.
        channels: Number of channels.

    Returns:
        Tuple of (avg_img, img_stack) or None if insufficient frames.
    """
    image_names = sorted(os.listdir(img_dir))
    if len(image_names) < frame_qty:
        return None

    # Use only the first frame_qty images
    return load_image_stack(
        img_dir, config_data, image_names[:frame_qty], dtype=dtype, channels=channels
    )
