"""BOOT + TABLE / NO_TABLE 事件表数据（runner 只读表，callee 不互调）。"""

from __future__ import annotations

from paddle_ocr.job.events import (
    DAEMON_OCR_ENSURE,
    DAEMON_STRUCTURE_ENSURE,
    DAEMON_STRUCTURE_RELEASE,
    INFER_OCR,
    INFER_STRUCTURE,
    JOB_DECODE,
    JOB_DETECT_LM,
    JOB_DETECT_TABLE,
    JOB_PICK_TEMPLATE,
    SCORE_LM_SIMILARITY,
    WHEN_ALWAYS,
    WHEN_FINALLY,
    WHEN_LM_LOADED,
)

TEMPLATE_TABLE = "TABLE"
TEMPLATE_NO_TABLE = "NO_TABLE"

# (has_table, lm_loaded, template)；None 表示该维通配。引擎只看有无表；图表 v1 视同有表。
TEMPLATE_ROUTES = (
    (True, None, TEMPLATE_TABLE),
    (False, None, TEMPLATE_NO_TABLE),
)

BOOT = [
    {"kind": JOB_DECODE, "when": WHEN_ALWAYS},
    {"kind": JOB_DETECT_TABLE, "when": WHEN_ALWAYS},
    {"kind": JOB_DETECT_LM, "when": WHEN_ALWAYS},
    {"kind": JOB_PICK_TEMPLATE, "when": WHEN_ALWAYS},
]

TABLE = [
    {"kind": DAEMON_STRUCTURE_ENSURE, "when": WHEN_ALWAYS},
    {"kind": INFER_STRUCTURE, "when": WHEN_ALWAYS},
    {"kind": SCORE_LM_SIMILARITY, "when": WHEN_LM_LOADED},
    {"kind": DAEMON_STRUCTURE_RELEASE, "when": WHEN_FINALLY},
]

NO_TABLE = [
    {"kind": DAEMON_OCR_ENSURE, "when": WHEN_ALWAYS},
    {"kind": INFER_OCR, "when": WHEN_ALWAYS},
    {"kind": SCORE_LM_SIMILARITY, "when": WHEN_LM_LOADED},
]

TEMPLATES = {
    TEMPLATE_TABLE: TABLE,
    TEMPLATE_NO_TABLE: NO_TABLE,
}


def pick_template_name(has_table: bool, lm_loaded: bool = False) -> str:
    """
    函数名: pick_template_name
    作用: 只按 BOOT 的 has_table 选模板；lm_loaded 不决定引擎，只给 when=lm_loaded。
    输入:
        has_table (bool): HasTableGrid 结果；True 时走 TABLE。
        lm_loaded (bool): 保留 BOOT 签名；选模板时忽略。
    输出:
        str: TABLE 或 NO_TABLE。
    """
    _ = lm_loaded
    for want_table, _want_lm, name in TEMPLATE_ROUTES:
        if want_table is not None and bool(want_table) != bool(has_table):
            continue
        return name
    return TEMPLATE_NO_TABLE
