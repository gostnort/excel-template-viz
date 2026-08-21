"""JSON 三态判定：parse + normalize + run_judgment（无 LiteRT 约束解码）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from llm_lmstudio.backend import LlmBackend
from llm_lmstudio.json_extract import extract_json_object


DEFAULT_AFFIRMATIVE = frozenset({"true", "yes", "是", "有", "problem", "1", "affirmative"})
DEFAULT_NEGATIVE = frozenset({"false", "no", "否", "无", "ok", "0", "negative"})



@dataclass(frozen=True)
class JudgmentSpec:
    """调用方提供的判定请求。"""

    system: str
    user: str
    verdict_key: str = "has_problem"
    reason_key: str = "reason"
    max_tokens: int = 256
    use_constrained_decoding: bool = False



@dataclass(frozen=True)
class JudgmentDraft:
    """解析但尚未归一化的草稿。"""

    raw_text: str
    payload: dict | None
    parse_error: str | None



@dataclass(frozen=True)
class JudgmentResult:
    """稳定三态结果。"""

    verdict: Literal["affirmative", "negative", "unknown"]
    reason: str
    raw_text: str
    normalized_from: Literal["json", "keyword", "default"]



def parse_judgment(text: str, *, verdict_key: str) -> JudgmentDraft:
    """
    函数名: parse_judgment
    作用: 从模型文本抽取含 verdict_key 的 JSON
    输入:
        text (str): 模型原文
        verdict_key (str): 判定字段名
    输出:
        JudgmentDraft
    """
    payload, err = extract_json_object(text)
    if err is not None:
        return JudgmentDraft(raw_text=text, payload=None, parse_error=err)
    if verdict_key not in payload:
        return JudgmentDraft(raw_text=text, payload=payload, parse_error=f"missing key {verdict_key!r}")
    return JudgmentDraft(raw_text=text, payload=payload, parse_error=None)



def normalize_judgment(
    draft: JudgmentDraft,
    *,
    verdict_key: str,
    reason_key: str = "reason",
    affirmative: frozenset[str] = DEFAULT_AFFIRMATIVE,
    negative: frozenset[str] = DEFAULT_NEGATIVE,
    default_on_ambiguous: Literal["affirmative", "negative", "unknown"] = "unknown",
) -> JudgmentResult:
    """
    函数名: normalize_judgment
    作用: 把布尔 / 同义词映射为 affirmative / negative / unknown
    输入:
        draft (JudgmentDraft): 解析草稿
        verdict_key (str): 判定键
        reason_key (str): 原因键
        affirmative / negative: 同义词表
        default_on_ambiguous: 歧义回退
    输出:
        JudgmentResult
    """
    if draft.payload is None or verdict_key not in draft.payload:
        return JudgmentResult(verdict="unknown", reason="", raw_text=draft.raw_text, normalized_from="default")
    reason = str(draft.payload.get(reason_key, ""))
    raw_value = draft.payload[verdict_key]
    token = str(raw_value).strip().lower()
    is_affirmative = raw_value is True or token in affirmative
    is_negative = raw_value is False or token in negative
    if is_affirmative and not is_negative:
        return JudgmentResult(verdict="affirmative", reason=reason, raw_text=draft.raw_text, normalized_from="json")
    if is_negative and not is_affirmative:
        return JudgmentResult(verdict="negative", reason=reason, raw_text=draft.raw_text, normalized_from="json")
    return JudgmentResult(verdict=default_on_ambiguous, reason=reason, raw_text=draft.raw_text, normalized_from="default")



def run_judgment(backend: LlmBackend, spec: JudgmentSpec) -> JudgmentResult:
    """
    函数名: run_judgment
    作用: 无状态 generate + JSON 抽取 + 三态归一
    输入:
        backend (LlmBackend): 推理后端
        spec (JudgmentSpec): 系统/用户提示与键名
    输出:
        JudgmentResult
    """
    user = spec.user
    if "json" not in spec.system.lower() and "json" not in user.lower():
        user = (
            user
            + f'\n\nReply with JSON only: {{"{spec.verdict_key}": true or false, "{spec.reason_key}": "one sentence"}}.'
        )
    messages = [{"role": "system", "content": spec.system}, {"role": "user", "content": user}]
    result = backend.generate(messages, thinking=False, max_tokens=spec.max_tokens, temperature=0.0)
    draft = parse_judgment(result.text, verdict_key=spec.verdict_key)
    return normalize_judgment(
        draft,
        verdict_key=spec.verdict_key,
        reason_key=spec.reason_key,
        affirmative=DEFAULT_AFFIRMATIVE,
        negative=DEFAULT_NEGATIVE,
        default_on_ambiguous="unknown",
    )
