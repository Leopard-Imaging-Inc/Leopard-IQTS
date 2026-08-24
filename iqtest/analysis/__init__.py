"""iqtest.analysis — M3 真实算法适配器注册表。

runner 约定 fn(images, config) -> dict；此处把各模块适配器注册进
runner.MODULE_ANALYZERS，导入本包即生效（main_window 负责导入）。
"""

from iqtest.analysis.mtf_adapter import analyze_mtf
from iqtest.runner import MODULE_ANALYZERS

MODULE_ANALYZERS["mtf"] = analyze_mtf

__all__ = ["analyze_mtf"]
