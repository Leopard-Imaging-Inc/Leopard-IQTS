"""MTF 模组比较核心（兼容门面）。

原 iqtest/analysis/mtf_compare.py 拆分为包：
- _csv_io：结果 CSV 解析 / 比较结果 CSV 导出
- _model：视场位置 / 指标模型 / 口径校验 / ROI 配对 / 多款辅助
- _core：compare() 差异计算与胜负判定

本模块 re-export 全部公开符号，保持
`from iqtest.analysis.mtf_compare import xxx` 与 `mtf_compare.xxx` 调用不变。
"""

from ._csv_io import (
    COMPARE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    compare_result_to_csv,
    load_result_csv,
    parse_result_csv,
    write_compare_csv,
)
from ._core import compare
from ._model import (
    DEFAULT_SCORE_TIE,
    DEFAULT_TIE_FREQ,
    DEFAULT_TIE_SFR,
    DEFAULT_ZONE_WEIGHTS,
    ZONE_GROUP,
    ZONE_GROUP_CN,
    available_metrics,
    available_metrics_multi,
    check_compatibility,
    check_compatibility_multi,
    field_zone,
    match_rois,
    match_zones_multi,
    metric_kind,
    metric_label,
    normalized_metric,
    pair_outcome,
    zone_group,
)

__all__ = [
    # 常量
    "SCHEMA_VERSION",
    "COMPARE_SCHEMA_VERSION",
    "DEFAULT_TIE_FREQ",
    "DEFAULT_TIE_SFR",
    "DEFAULT_SCORE_TIE",
    "DEFAULT_ZONE_WEIGHTS",
    "ZONE_GROUP",
    "ZONE_GROUP_CN",
    # CSV 进出
    "parse_result_csv",
    "load_result_csv",
    "compare_result_to_csv",
    "write_compare_csv",
    # 模型 / 校验 / 配对
    "field_zone",
    "zone_group",
    "metric_kind",
    "metric_label",
    "available_metrics",
    "check_compatibility",
    "match_rois",
    "normalized_metric",
    "pair_outcome",
    "available_metrics_multi",
    "check_compatibility_multi",
    "match_zones_multi",
    # 比较计算
    "compare",
]
