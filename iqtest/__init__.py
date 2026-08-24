"""LeopardIQTS — LeopardIQ IQ 测试软件 UI 包。

分层（见 doc/LeopardIQ-IQ测试软件规划.md §4.1）：
    UI 层    iqtest/main_window.py、iqtest/panels/、iqtest/figures/、iqtest/widgets/
    应用层   iqtest/session.py、iqtest/runner.py（M2）、iqtest/report/（M4）
    算法层   leopardiq/（不改动，仅通过 analyze_* 统一接口调用）
"""

__version__ = "0.1.0"  # 初步实现 MTF/SFR 配套功能
