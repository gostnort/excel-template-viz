"""LM Studio 语义门禁：semantic_judge 只判定草稿通顺与否；不启动 MCP、不调 OCR/Structure。"""

from __future__ import annotations

from typing import Any



# 严格 OCR 质检系统提示：要求输出 JSON has_problem / reason。
_OCR_SEMANTIC_SYSTEM = (
    "You are an extremely strict OCR Quality Assurance Inspector. "
    "You audit Chinese text extracted from forms or table cells and decide if it contains "
    "any recognition error, flaw, or semantic anomaly. "
    "Reply with JSON only: {\"has_problem\": true} if ANY of the following holds: "
    "(1) a single misrecognized character (shape/phonetic similarity or broken radicals); "
    "(2) a standard phrase/idiom/professional term with even one wrong character; "
    "(3) characters are valid individually but their combination violates natural grammar "
    "or reads like mechanically scrambled text; "
    "(4) misaligned key-value pairs, broken/dangling punctuation, or unreadable garbled text. "
    "Use {\"has_problem\": false} only when the text is 100% flawless, perfectly "
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
    """affirmative → True（进入精修）；negative/unknown → False（保守不误触发）。"""
    return verdict == "affirmative"



def _build_ocr_judgment_spec(unit_text: str) -> Any:
    """组 OCR 专用 JudgmentSpec；输出 JSON has_problem / reason。"""
    from llm_lmstudio.judgment import JudgmentSpec
    return JudgmentSpec(
        system=_OCR_SEMANTIC_SYSTEM,
        user=unit_text,
        verdict_key="has_problem",
        reason_key="reason",
        max_tokens=256,
        use_constrained_decoding=False,
    )



def HasOcrSemanticProblem(fast_result: dict[str, Any]) -> bool:
    """
    函数名: HasOcrSemanticProblem
        作用: 把 fast 草稿拆成单元（string* / table* 每行），逐单元调 run_judgment。首个
        affirmative（有问题）即短路返回 True；全部 negative/unknown 返回 False。
        LM Studio 不可用/导入失败时返回 False。禁止用 HasContent 代替。
    输入:
        fast_result (dict): §3.3 fast JSON（含 string*/table*/ok/message）。
    输出:
        bool: True=存在语义问题，应精修；False=无问题或 LM Studio 不可用。
    """
    try:
        from llm_lmstudio.backend import get_backend
        from llm_lmstudio.judgment import run_judgment
    except Exception:
        return False
    try:
        backend = get_backend()
    except Exception:
        return False
    for _unit_id, text in iter_all_judge_units(fast_result):
        spec = _build_ocr_judgment_spec(text)
        try:
            result = run_judgment(backend, spec)
        except Exception:
            # 单单元判定异常：保守跳过该单元，继续判下一个。
            continue
        if _ocr_semantic_to_bool(result.verdict):
            return True
    return False



def semantic_judge(draft: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: semantic_judge
    作用: 只判断 OCR 草稿是否通顺；不通顺才由事件表决定是否 Structure。不启动 MCP、不调 PaddleOcr/PpStructure、不 load_model。
    输入:
        draft (dict): OCR 草稿 JSON（含 string*/table*）。
    输出:
        dict: fluent (bool)、keep_draft (bool)、has_problem (bool)、可选 reason。LM 未加载、导入失败或判定异常时 keep_draft（fluent=True，不视为有问题）。
    """
    keep_draft = {"fluent": True, "keep_draft": True, "has_problem": False}
    # 中文注释: 只查询是否已加载；失败或未加载则 keep_draft，禁止 load_model
    try:
        from llm_lmstudio.models import is_model_loaded
        if not is_model_loaded():
            keep_draft["reason"] = "lm_not_loaded"
            return keep_draft
    except Exception:
        keep_draft["reason"] = "lm_unavailable"
        return keep_draft
    # 中文注释: 逐单元 run_judgment；导入失败或任一判定异常视为通顺（keep_draft）
    try:
        from llm_lmstudio.backend import get_backend
        from llm_lmstudio.judgment import run_judgment
        backend = get_backend()
        for _unit_id, text in iter_all_judge_units(draft):
            spec = _build_ocr_judgment_spec(text)
            result = run_judgment(backend, spec)
            if _ocr_semantic_to_bool(result.verdict):
                return {
                    "fluent": False,
                    "keep_draft": False,
                    "has_problem": True,
                    "reason": str(getattr(result, "reason", "") or ""),
                }
    except Exception:
        keep_draft["reason"] = "judge_error"
        return keep_draft
    return {"fluent": True, "keep_draft": True, "has_problem": False}
