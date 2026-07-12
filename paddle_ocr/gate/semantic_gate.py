"""Gemma 4 语义门禁：逐单元判定 fast 草稿是否有语义问题，短路转 PaddleVL。"""

from __future__ import annotations

from typing import Any

from paddle_ocr import config
from paddle_ocr.gate.hardware_probe import AcceleratorAvailable
from paddle_ocr.gate.memory_guard import RefinePathEnabled



# 严格 OCR 质检系统提示：约束解码路径下模型调 report_verdict(has_problem, reason)。
_OCR_SEMANTIC_SYSTEM = (
    "You are an extremely strict OCR Quality Assurance Inspector. "
    "You audit Chinese text extracted from forms or table cells and decide if it contains "
    "any recognition error, flaw, or semantic anomaly. "
    "Call report_verdict with has_problem=true if ANY of the following holds: "
    "(1) a single misrecognized character (shape/phonetic similarity or broken radicals); "
    "(2) a standard phrase/idiom/professional term with even one wrong character; "
    "(3) characters are valid individually but their combination violates natural grammar "
    "or reads like mechanically scrambled text; "
    "(4) misaligned key-value pairs, broken/dangling punctuation, or unreadable garbled text. "
    "Call report_verdict with has_problem=false only when the text is 100% flawless, perfectly "
    "coherent, entirely natural, and free of any typo or formatting artifact. "
    "Keep the reason short (one sentence)."
)



def iter_string_units(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(key, text)] for every non-empty string1..stringN, key-sorted."""
    units: list[tuple[str, str]] = []
    for key in sorted(result):
        if not key.startswith("string"):
            continue
        value = result.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            units.append((key, text))
    return units



def iter_table_row_units(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(label, joined_cells)] for every non-empty table row, key-sorted."""
    units: list[tuple[str, str]] = []
    for key in sorted(result):
        if not key.startswith("table"):
            continue
        table = result.get(key)
        if not isinstance(table, list):
            continue
        for row in table:
            if not isinstance(row, dict):
                continue
            row_no = row.get("row", "?")
            cells = row.get("cells") or []
            parts = [str(c).strip() for c in cells if str(c).strip()]
            if not parts:
                continue
            label = f"{key}:row{row_no}"
            units.append((label, " | ".join(parts)))
    return units



def iter_all_judge_units(result: dict[str, Any]) -> list[tuple[str, str]]:
    """string* units first, then table row units (per doc §3.2 逐单元 + 短路)."""
    return iter_string_units(result) + iter_table_row_units(result)



def _ocr_semantic_to_bool(verdict: str) -> bool:
    """affirmative → True (调 VL)；negative/unknown → False（保守不误触发）。"""
    return verdict == "affirmative"



def _build_ocr_judgment_spec(unit_text: str) -> Any:
    """组 OCR 专用 JudgmentSpec；verdict_key 字母序排在 reason_key 之前（约束解码）。"""
    from llm_gemma4.runtime.judgment import JudgmentSpec
    return JudgmentSpec(
        system=_OCR_SEMANTIC_SYSTEM,
        user=unit_text,
        verdict_key="has_problem",
        reason_key="reason",
        max_tokens=256,
        use_constrained_decoding=True,
    )



def HasOcrSemanticProblem(fast_result: dict[str, Any]) -> bool:
    """
    函数名: HasOcrSemanticProblem
    作用: 把 fast 草稿拆成单元（string* / table* 每行），逐单元调 run_judgment。首个
        affirmative（有问题）即短路返回 True，直接转入 PaddleVL；全部 negative/unknown
        返回 False。Gemma 不可用/导入失败时返回 False（不调 VL）。禁止用 HasContent 代替。
    输入:
        fast_result (dict): §3.3 fast JSON（含 string*/table*/ok/message）。
    输出:
        bool: True=存在语义问题，应调 PaddleVL；False=无问题或 Gemma 不可用。
    """
    try:
        import llm_gemma4.__main__ as gemma_main
        from llm_gemma4.runtime.judge import run_judgment
    except Exception:
        return False
    try:
        backend = gemma_main._get_backend()
    except Exception:
        return False
    for _unit_id, text in iter_all_judge_units(fast_result):
        spec = _build_ocr_judgment_spec(text)
        try:
            result = run_judgment(backend, spec)
        except Exception:
            # 单单元判定异常：保守跳过该单元，继续判下一个（不因一次异常误触发 VL）。
            continue
        if _ocr_semantic_to_bool(result.verdict):
            return True
    return False



def ShouldTryVl(fast: dict[str, Any]) -> bool:
    """
    函数名: ShouldTryVl
    作用: RefinePathEnabled 且 有加速器（GPU+paddlepaddle-gpu）且 fast 存在语义问题时
        才调 PaddleOCRVL。坏图/坏选区/引擎未就绪/模型缺失等 fast 已失败的状态直接返回
        False。无加速器时返回 False（gemma_only 档暂无纠错动作，见 main.PaddleOcr）。
    输入:
        fast (dict): fast 路径返回的 §3.3 JSON。
    输出:
        bool: True=应尝试 PaddleOCRVL（GPU）精修；False=直接返回 fast。
    """
    if not RefinePathEnabled():
        return False
    if not AcceleratorAvailable():
        return False
    msg = str(fast.get("message") or "")
    if msg in (config.MSG_BAD_IMAGE, config.MSG_BAD_CROP, config.MSG_NOT_READY, config.MSG_MODEL_MISSING):
        return False
    if not fast.get("ok"):
        return False
    return HasOcrSemanticProblem(fast)
