"""
Image preprocessing utilities for LeopardIQ testing software.

Handles Bayer pattern decomposition, black level correction, luminance conversion,
and filter generation.

Extracted and refactored from leopardiq.utils.utils.
"""

import warnings
from typing import Tuple, Optional
import numpy as np


def get_black_level(img: np.ndarray) -> Tuple[float, list]:
    """
    Calculate the black level from the averaged image.

    Computes per-channel black level as the mean of each channel,
    plus an overall average black level.

    Args:
        img: Averaged image array of shape (height, width, channels).

    Returns:
        Tuple of (black_level_overall, black_level_per_channel).
            - black_level_overall: Average black level across all channels.
            - black_level_per_channel: List of black levels per channel.
    """
    height, width = img.shape[:2]
    num_channels = img.shape[2] if img.ndim >= 3 else 1

    black_level_per_channel = []
    black_level_overall = 0.0

    for ch in range(num_channels):
        if img.ndim >= 3:
            bl_by_chan = np.sum(img[:, :, ch]) / width / height
        else:
            bl_by_chan = np.sum(img) / width / height
        black_level_per_channel.append(float(bl_by_chan))
        black_level_overall += bl_by_chan

    black_level_overall /= num_channels
    return black_level_overall, black_level_per_channel


def apply_black_level_correction(
    img: np.ndarray, black_level: float
) -> np.ndarray:
    """
    Apply black level correction to an image.

    Subtracts black level and clamps negative values to 0.

    Args:
        img: Input image array.
        black_level: Black level value to subtract.

    Returns:
        np.ndarray: Black-level-corrected image.
    """
    img_blc = img - black_level
    img_blc[img_blc < 0] = 0
    return img_blc


def split_bayer_channels(img: np.ndarray) -> np.ndarray:
    """
    Split a Bayer RAW image into 4 color channels.

    Decomposes a single-channel Bayer pattern image into:
        Channel 0: R  (top-left)
        Channel 1: Gr (top-right)
        Channel 2: Gb (bottom-left)
        Channel 3: B  (bottom-right)

    Args:
        img: Bayer image of shape (height, width) or (N, height, width).

    Returns:
        np.ndarray: Decomposed image of shape:
            - (height/2, width/2, 4) for single image
            - (N, height/2, width/2, 4) for image stack
    """
    if len(img.shape) == 2:
        img_height, img_width = img.shape
        img_number = 1
    elif len(img.shape) == 3:
        img_number, img_height, img_width = img.shape
    else:
        raise ValueError(f"Unsupported image shape: {img.shape}")

    # Handle odd dimensions by cropping
    if img_height % 2 != 0:
        warnings.warn("Odd image height, cropping the last line")
        if len(img.shape) == 2:
            img = img[:-1, :]
        else:
            img = img[:, :-1, :]
        img_height -= 1

    if img_width % 2 != 0:
        warnings.warn("Odd image width, cropping the last column")
        if len(img.shape) == 2:
            img = img[:, :-1]
        else:
            img = img[:, :, :-1]
        img_width -= 1

    out_h = img_height // 2
    out_w = img_width // 2

    if img_number == 1:
        bayer = np.zeros((out_h, out_w, 4), dtype=img.dtype)
        bayer[:, :, 0] = img[0::2, 0::2]  # R
        bayer[:, :, 1] = img[0::2, 1::2]  # Gr
        bayer[:, :, 2] = img[1::2, 0::2]  # Gb
        bayer[:, :, 3] = img[1::2, 1::2]  # B
    else:
        bayer = np.zeros((img_number, out_h, out_w, 4), dtype=img.dtype)
        for idx in range(img_number):
            bayer[idx, :, :, 0] = img[idx, 0::2, 0::2]
            bayer[idx, :, :, 1] = img[idx, 0::2, 1::2]
            bayer[idx, :, :, 2] = img[idx, 1::2, 0::2]
            bayer[idx, :, :, 3] = img[idx, 1::2, 1::2]

    return bayer


def get_bayer_index(cfa: list) -> Tuple[int, int, int, int]:
    """
    Get the channel indices for a given Bayer CFA order.

    Args:
        cfa: List of color names, e.g., ["R", "Gr", "Gb", "B"] or ["Gr", "R", "B", "Gb"].

    Returns:
        Tuple of (gr_index, red_index, blue_index, gb_index).
    """
    gr_index = cfa.index("Gr")
    red_index = cfa.index("R")
    blue_index = cfa.index("B")
    gb_index = cfa.index("Gb")
    return gr_index, red_index, blue_index, gb_index


def bayer_to_luminance(img: np.ndarray, cfa: list) -> np.ndarray:
    """
    Convert a Bayer-channel image to luminance using standard weights.

    Uses ITU-R BT.709 luminance weights:
        Y = 0.2126*R + 0.7152*G + 0.0722*B
    where G = (Gr + Gb) / 2

    （注：0.2126/0.7152/0.0722 为 BT.709 系数；BT.601 为 0.299/0.587/0.114，
    与 demosaic 后灰度所用的 BT.709 加权 0.2125/0.7154/0.0721 属同一标准族。）

    Args:
        img: Image array of shape (..., 4) with Bayer channels.
        cfa: Bayer CFA order list.

    Returns:
        np.ndarray: Luminance image of shape (...).
    """
    gr_idx, r_idx, b_idx, gb_idx = get_bayer_index(cfa)
    green = (img[..., gr_idx] + img[..., gb_idx]) / 2.0
    luminance = (
        img[..., r_idx] * 0.2126
        + green * 0.7152
        + img[..., b_idx] * 0.0722
    )
    return luminance


def create_average_filter(size: int = 9) -> np.ndarray:
    """
    Create a 2D averaging filter (box filter).

    Equivalent to MATLAB's fspecial('average', size).

    Args:
        size: Filter kernel size (default: 9 for 9x9, matching NVIDIA spec).

    Returns:
        np.ndarray: (size x size) averaging filter with sum = 1.
    """
    cell_value = 1.0 / (size ** 2)
    return np.ones((size, size), dtype=np.float64) * cell_value


def prepare_bayer_images(
    avg_img: np.ndarray,
    img_stack: np.ndarray,
    cfa: list,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Prepare Bayer images for analysis by decomposing into 4 channels.

    If the CFA has 4 channels, both avg_img and img_stack are decomposed.
    If monochrome (1 channel), they are returned as-is.

    Args:
        avg_img: Averaged image.
        img_stack: Stack of raw images.
        cfa: Bayer CFA order list.

    Returns:
        Tuple of (decomposed_avg, decomposed_stack).
    """
    if len(cfa) == 4:
        # For image stacks, first squeeze the trailing singleton dims if any
        if img_stack.ndim == 4 and img_stack.shape[-1] == 1:
            img_stack = np.squeeze(img_stack, axis=-1)
        if avg_img.ndim == 3 and avg_img.shape[-1] == 1:
            avg_img = np.squeeze(avg_img, axis=-1)

        decomposed_avg = split_bayer_channels(avg_img)
        decomposed_stack = split_bayer_channels(img_stack)
        return decomposed_avg, decomposed_stack
    else:
        # Monochrome: return as-is
        return avg_img, img_stack
