"""iqtest.config — criteria / 参数 JSON 持久化。

JSON 结构（version 1）：
    {
      "version": 1,
      "modules": {
        "mtf": {"params": {...}, "criteria": {...}},
        ...
      }
    }
"""

from iqtest.config.store import (
    default_modules_config,
    export_default_criteria,
    load_json,
    merge_modules_config,
    save_json,
)

__all__ = [
    "default_modules_config",
    "export_default_criteria",
    "load_json",
    "merge_modules_config",
    "save_json",
]
