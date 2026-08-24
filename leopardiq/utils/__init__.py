"""
LeopardIQ core utilities package.

图像 I/O、预处理、结果持久化、PASS/FAIL 判定等通用工具。

**推荐导入方式：优先从子模块导入**（更明确、避免拉入无关名字）：

    from leopardiq.utils.raw_reader import read_raw, RawReadConfig
    from leopardiq.utils.pass_fail import evaluate_pass_fail

顶层 `leopardiq.utils` 仅作便捷重导出，`__all__` 只含规范 API。

⚠️ 遗留兼容接口（`read_raw_image` / `read_raw_image_from_config` /
`load_image_stack` / `load_image_stack_with_validation`）已从 `__all__`
移除：`from leopardiq.utils import *` 不再带出。如需使用请显式
`from leopardiq.utils.image_io import read_raw_image`，或改用
`leopardiq.utils.raw_reader.read_raw`（含位深左移 / 黑电平处理）。
"""

from .image_io import (
    read_mtf_image,                      # 规范 API：算法库仍在使用
    read_raw_image,                      # 遗留兼容（不在 __all__）
    read_raw_image_from_config,          # 遗留兼容（不在 __all__）
    load_image_stack,                    # 遗留兼容（不在 __all__）
    load_image_stack_with_validation,    # 遗留兼容（不在 __all__）
)

from .raw_reader import (
    CFA_PATTERNS,
    COMMON_RESOLUTIONS,
    DEMOSAIC_CODES,
    GRAY_METHODS,
    RawReadConfig,
    RawReadInfo,
    demosaic_gray,
    guess_raw_resolution,
    read_raw,
)

from .image_preprocess import (
    get_black_level,
    apply_black_level_correction,
    split_bayer_channels,
    get_bayer_index,
    bayer_to_luminance,
    create_average_filter,
    prepare_bayer_images,
)

from .result_saver import (
    pad_channel_data,
    save_results_csv,
    save_results_json,
)

from .pass_fail import (
    evaluate_pass_fail,
    validate_metrics,
    validate_metrics_ordered,
)

from .binning import bin_image

from .common import (
    create_disk_structuring_element,
    extract_largest_region,
    round_half_up,
    filter_centroid,
)

#: 规范 API —— `from leopardiq.utils import *` 仅带出这些名字
__all__ = [
    # image_io
    "read_mtf_image",
    # raw_reader（简化版 Generalized Read Raw）
    "CFA_PATTERNS",
    "COMMON_RESOLUTIONS",
    "DEMOSAIC_CODES",
    "GRAY_METHODS",
    "RawReadConfig",
    "RawReadInfo",
    "demosaic_gray",
    "guess_raw_resolution",
    "read_raw",
    # image_preprocess
    "get_black_level",
    "apply_black_level_correction",
    "split_bayer_channels",
    "get_bayer_index",
    "bayer_to_luminance",
    "create_average_filter",
    "prepare_bayer_images",
    # result_saver
    "pad_channel_data",
    "save_results_csv",
    "save_results_json",
    # pass_fail
    "evaluate_pass_fail",
    "validate_metrics",
    "validate_metrics_ordered",
    # binning
    "bin_image",
    # common
    "create_disk_structuring_element",
    "extract_largest_region",
    "round_half_up",
    "filter_centroid",
]
