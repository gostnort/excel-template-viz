"""规则还原：数字化通道与文本测地线，输出 TOML 可消费的映射。"""

from geodesic_align.digit_processor import (
    ColumnRoute,
    DigitEnd,
    cell_to_z,
    route_columns,
    run_digit_align,
    z_eq,
)
from geodesic_align.emit_mapping import MappingDecision, recover_mapping


__all__ = [
    "ColumnRoute",
    "DigitEnd",
    "MappingDecision",
    "cell_to_z",
    "recover_mapping",
    "route_columns",
    "run_digit_align",
    "z_eq",
]
