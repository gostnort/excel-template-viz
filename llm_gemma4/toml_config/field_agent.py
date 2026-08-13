"""字段子代理：pass1 普通推理，pass2 thinking 重试。

Phase A: 从 wizard/field_agent.py 迁移，更新导入路径（wizard → toml_config）。
thinking=True 仅允许 field_{label}_pass2 使用。
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from llm_gemma4.backends.base import LlmBackend, SessionOptions
from llm_gemma4.toml_config.parse_field_json import ParseFieldError, parse_field_json
from llm_gemma4.toml_config.prompts import (
    STEP3_SYSTEM_PROMPT,
    STEP4_SYSTEM_PROMPT,
    STEP5_SYSTEM_PROMPT,
)


FieldTask = Literal["ghost", "sheet", "regex"]


@dataclass
class FieldAgentResult:
    ok: bool
    payload: dict[str, Any] | None = None
    error: str = ""
    used_thinking: bool = False


def _session_send(
    backend: LlmBackend,
    session_id: str,
    *,
    system_message: str,
    user_content: str,
    thinking: bool,
    max_tokens: int,
    on_chat: Callable[[str, str], None] | None = None,
    chat_tag: str = "",
) -> str:
    """
    函数名: _session_send
    作用: 发送单轮对话并记录日志，支持 thinking 模式
    输入:
        backend (LlmBackend): LLM 后端实例
        session_id (str): 会话标识（唯一）
        system_message (str): 系统提示词
        user_content (str): 用户消息正文
        thinking (bool): 是否启用 thinking
        max_tokens (int): 最大输出 token 数
        on_chat (Callable | None): 对话日志回调 (role, text)
        chat_tag (str): 聊天标签（用于前缀）
    输出:
        str: 模型回复文本
    """
    opts = SessionOptions(
        system_message=system_message,
        thinking=thinking,
        max_tokens=max_tokens,
    )
    prefix = f"[{chat_tag}] " if chat_tag else ""
    if on_chat is not None:
        on_chat("user", f"{prefix}{user_content}")
    session = backend.open_session(session_id, options=opts)
    try:
        result = session.send_turn({"role": "user", "content": user_content})
        if on_chat is not None:
            on_chat("assistant", f"{prefix}{result.text}")
        return result.text
    finally:
        session.close()


def _normalize_key(text: str) -> str:
    """
    函数名: _normalize_key
    作用: 去除空白与全角空格，便于标签比较
    输入:
        text (str): 原始文本
    输出:
        str: 规范化后的文本
    """
    return (text or "").replace(" ", "").replace("\u3000", "")


def _segment_matches_draft(segment: str, draft: str) -> bool:
    """
    函数名: _segment_matches_draft
    作用: 判断段文本是否与用户 draft 值匹配（全等或包含）
    输入:
        segment (str): indexed 段文本
        draft (str): 用户草稿值
    输出:
        bool: 匹配时为 True
    """
    seg_s = (segment or "").strip()
    draft_s = (draft or "").strip()
    if not draft_s:
        return False
    if seg_s == draft_s:
        return True
    return draft_s in seg_s or seg_s in draft_s


def _segment_matches_label(segment: str, label: str) -> bool:
    """
    函数名: _segment_matches_label
    作用: 判断段文本是否像字段标签（非数据值）
    输入:
        segment (str): indexed 段文本
        label (str): Input_label
    输出:
        bool: 像标签时为 True
    """
    seg_s = (segment or "").strip()
    label_s = (label or "").strip()
    if not label_s or not seg_s:
        return False
    if _normalize_key(seg_s) == _normalize_key(label_s):
        return True
    return label_s in seg_s or seg_s in label_s


def _resolve_ghost_index(
    raw_index: int,
    *,
    label: str,
    draft: str,
    indexed_segments: dict[int, str],
) -> int:
    """
    函数名: _resolve_ghost_index
    作用: 将模型误选的 label 索引纠正为 brace-JSON 邻接 value 索引
    输入:
        raw_index (int): 模型返回的 index
        label (str): Input_label
        draft (str): 用户草稿值
        indexed_segments (dict[int, str]): 预处理段字典
    输出:
        int: 纠正后的 index
    """
    if raw_index < 0 or not (draft or "").strip() or not indexed_segments:
        return raw_index
    segment = str(indexed_segments.get(raw_index, "") or "")
    draft_s = (draft or "").strip()
    # 已指向数据值则保留
    if _segment_matches_draft(segment, draft_s):
        return raw_index
    # brace-JSON KV：常见误选为标签，真实值在下一 token
    if _segment_matches_label(segment, label):
        next_seg = str(indexed_segments.get(raw_index + 1, "") or "")
        if _segment_matches_draft(next_seg, draft_s):
            return raw_index + 1
    # 回退：在 indexed 中搜索唯一 draft 命中
    exact_hits: list[int] = []
    fuzzy_hits: list[int] = []
    for idx in sorted(indexed_segments.keys()):
        seg = str(indexed_segments.get(idx, "") or "")
        seg_s = seg.strip()
        if not seg_s:
            continue
        if seg_s == draft_s:
            exact_hits.append(idx)
        elif _segment_matches_draft(seg, draft_s):
            fuzzy_hits.append(idx)
    if len(exact_hits) == 1:
        return exact_hits[0]
    if exact_hits:
        return exact_hits[0]
    if len(fuzzy_hits) == 1:
        return fuzzy_hits[0]
    return raw_index


def _normalize_ghost_match_type(match_type: str, draft: str, segment: str) -> str:
    """
    函数名: _normalize_ghost_match_type
    作用: 按 draft 与 segment 的字符串关系强制纠正 exact/fuzzy（不信任模型）
    输入:
        match_type (str): 模型给出的匹配类型
        draft (str): 用户草稿值（已可未 strip）
        segment (str): indexed 段文本（已可未 strip）
    输出:
        str: 纠正后的 exact|fuzzy|none
    """
    mt = (match_type or "none").strip().lower()
    draft_s = (draft or "").strip()
    seg_s = (segment or "").strip()
    # 无草稿时无法做相等性硬校验，保留模型类型（空草稿路径通常不调用本函数）
    if not draft_s:
        return mt if mt in ("exact", "fuzzy", "none") else "none"
    # 全量相等才允许 exact；部分包含必须 fuzzy；其它非相等不得保留 exact
    if seg_s == draft_s:
        return "exact"
    if seg_s and (draft_s in seg_s or seg_s in draft_s):
        return "fuzzy"
    if mt == "exact":
        return "fuzzy"
    return mt if mt in ("exact", "fuzzy", "none") else "fuzzy"


def _apply_ghost_payload(
    field_payload: dict[str, Any],
    *,
    draft: str = "",
    segment: str = "",
) -> tuple[str, int, bool]:
    """
    函数名: _apply_ghost_payload
    作用: 从子代理 JSON 提取 ghost 匹配结果，并用 draft/segment 硬校验 match_type
    输入:
        field_payload (dict): 模型 JSON（含 match_type / index）
        draft (str): 用户草稿值
        segment (str): 命中索引对应的段文本
    输出:
        tuple[str, int, bool]: (match_type, index, needs_regex)
    """
    index = int(field_payload.get("index", -1))
    raw_mt = str(field_payload.get("match_type", "none")).lower()
    # 无有效 index 时统一 none；有 index 时用字符串关系纠正 exact/fuzzy
    if index < 0:
        match_type = "none"
    else:
        match_type = _normalize_ghost_match_type(raw_mt, draft, segment)
    needs_regex = match_type == "fuzzy"
    return match_type, index, needs_regex


def _apply_sheet_payload(
    field_payload: dict[str, Any],
    *,
    label: str = "",
) -> tuple[str, str, bool]:
    """
    函数名: _apply_sheet_payload
    作用: 从子代理 JSON 提取 Sheet 列匹配，并用 label/列名硬校验 exact/fuzzy
    输入:
        field_payload (dict): 模型 JSON（含 match_type / column_name|field）
        label (str): 模板 Input_label
    输出:
        tuple[str, str, bool]: (match_type, column_name, needs_regex)
    """
    match_type = str(field_payload.get("match_type", "none")).lower()
    column = str(field_payload.get("column_name") or field_payload.get("field") or "")
    label_s = (label or "").strip()
    col_s = column.strip()
    # 列名与标签全等才 exact；部分包含强制 fuzzy；非相等不得保留 exact
    if col_s and label_s:
        if col_s == label_s:
            match_type = "exact"
        elif label_s in col_s or col_s in label_s:
            match_type = "fuzzy"
        elif match_type == "exact":
            match_type = "fuzzy"
    elif not col_s:
        match_type = "none"
    needs_regex = match_type == "fuzzy"
    return match_type, column, needs_regex


def run_field_agent(
    backend: LlmBackend,
    task: FieldTask,
    label: str,
    *,
    ghost_sample: str = "",
    google_headers: list[str] | None = None,
    google_rows: list[list[Any]] | None = None,
    raw_text_for_regex: str = "",
    thinking_budget: int = 512,
    pass1_tokens: int = 256,
    segments: list[str] | None = None,
    indexed_segments: dict[int, str] | None = None,
    determiner: str | list[str] = "",
    draft_value: str = "",
    on_chat: Callable[[str, str], None] | None = None,
) -> FieldAgentResult:
    """
    函数名: run_field_agent
    作用: 对单字段执行子代理推理；JSON 或 regex 回验失败时 pass2 thinking 重试
    输入:
        backend (LlmBackend): 底座实例
        task (FieldTask): ghost / sheet / regex
        label (str): Input_label
        ghost_sample (str): Ghost 粘贴样本
        google_headers (list[str] | None): Sheet 表头
        google_rows (list[list[Any]] | None): Sheet 样例行
        raw_text_for_regex (str): regex 回验用的原文
        thinking_budget (int): pass2 max_tokens
        pass1_tokens (int): pass1 max_tokens
        segments (list[str] | None): determiner 拆分后的段（兼容保留）
        indexed_segments (dict[int, str] | None): index 字典（ghost 必需）
        determiner (str | list[str]): 已推断的分隔符
        draft_value (str): 用户对该字段的输入值（匹配主信号）
        on_chat (Callable | None): 对话日志回调 (role, text)
    输出:
        FieldAgentResult: 推理与解析结果
    """
    chat_tag = f"字段 {label}"
    if task == "ghost":
        system = STEP3_SYSTEM_PROMPT
        if not indexed_segments:
            return FieldAgentResult(ok=False, error="indexed_segments required for ghost match")
        draft = (draft_value or "").strip()
        # 空 draft：不调用 Gemma
        if not draft:
            return FieldAgentResult(
                ok=True,
                payload={
                    "match_type": "none",
                    "index": -1,
                    "reason": "empty draft; skipped Gemma",
                },
            )
        seg_lines = "\n".join(
            f"{idx}: {value}" for idx, value in sorted(indexed_segments.items())
        )
        user_pass1 = (
            f"Input_label (hint only): {label}\n"
            f"User-provided value (primary signal): {draft}\n"
            f"Indexed segments:\n{seg_lines}\n"
            "Find the index of the DATA VALUE for this field."
        )
    elif task == "sheet":
        system = STEP4_SYSTEM_PROMPT
        headers = google_headers or []
        rows = google_rows or []
        user_pass1 = f"Target Field: {label}\nHeaders: {headers}\nSample rows: {rows[:5]}"
    else:
        system = STEP5_SYSTEM_PROMPT
        # Step 6：haystack = 命中 index 的段文本；draft = 用户假定输入（捕获目标）
        draft = (draft_value or "").strip()
        haystack = (raw_text_for_regex or ghost_sample or "").strip()
        user_pass1 = (
            f"Input_label: {label}\n"
            f"User-provided value (must be captured by group 1): {draft or '(none)'}\n"
            f"Indexed segment text (haystack):\n{haystack}\n"
            "Write a Python regex with one capture group that extracts the user-provided "
            "value from this segment. Output exactly one JSON object."
        )
    sid_base = f"field_{label}_{uuid.uuid4().hex[:8]}"
    text1 = _session_send(
        backend, f"{sid_base}_pass1",
        system_message=system, user_content=user_pass1,
        thinking=False, max_tokens=pass1_tokens,
        on_chat=on_chat, chat_tag=chat_tag,
    )
    parsed = parse_field_json(text1)
    if isinstance(parsed, ParseFieldError):
        text2 = _session_send(
            backend, f"{sid_base}_pass2",
            system_message=system,
            user_content=f"{user_pass1}\n\nPrevious parse error: {parsed.message}\nPrevious output: {parsed.raw_text[:500]}",
            thinking=True, max_tokens=thinking_budget,
            on_chat=on_chat, chat_tag=f"{chat_tag} thinking",
        )
        parsed2 = parse_field_json(text2)
        if isinstance(parsed2, ParseFieldError):
            return FieldAgentResult(ok=False, error=parsed2.message, used_thinking=True)
        parsed = parsed2
        used_thinking = True
    else:
        used_thinking = False
    if task == "regex":
        regex = str(parsed.get("regex", "")).strip()
        if not regex:
            return FieldAgentResult(ok=False, error="missing regex in JSON", used_thinking=used_thinking)
        try:
            re.compile(regex)
        except re.error as exc:
            return FieldAgentResult(ok=False, error=f"invalid regex: {exc}", payload=parsed, used_thinking=used_thinking)
        # 回验只针对该字段命中的段文本（或回退样本），不是整份 index 字典
        haystack = (raw_text_for_regex or ghost_sample or "").strip()
        draft = (draft_value or "").strip()
        if not haystack:
            return FieldAgentResult(
                ok=False,
                error="no segment/sample text for regex validation",
                used_thinking=used_thinking,
            )
        def _regex_ok(pat: str) -> bool:
            m = re.search(pat, haystack)
            if m is None:
                return False
            # 有捕获组且用户给了 draft 时，要求 group(1) 能对上 draft
            if draft and m.lastindex:
                captured = str(m.group(1) or "").strip()
                if captured == draft or draft in captured or captured in draft:
                    return True
                return False
            return True
        if not _regex_ok(regex):
            text2 = _session_send(
                backend, f"{sid_base}_pass2_re",
                system_message=system,
                user_content=(
                    f"{user_pass1}\n\n"
                    f"Regex {regex!r} failed validation against the segment "
                    f"(need re.search to match"
                    + (f" and group(1) to capture {draft!r}" if draft else "")
                    + "). Fix the regex."
                ),
                thinking=True, max_tokens=thinking_budget,
                on_chat=on_chat, chat_tag=f"{chat_tag} regex",
            )
            parsed2 = parse_field_json(text2)
            if isinstance(parsed2, ParseFieldError):
                return FieldAgentResult(ok=False, error="regex retry parse failed", used_thinking=True)
            regex2 = str(parsed2.get("regex", "")).strip()
            try:
                re.compile(regex2)
            except re.error as exc:
                return FieldAgentResult(ok=False, error=f"invalid regex after retry: {exc}", used_thinking=True)
            if not _regex_ok(regex2):
                return FieldAgentResult(
                    ok=False,
                    error="regex did not extract draft from segment after retry",
                    payload=parsed2,
                    used_thinking=True,
                )
            return FieldAgentResult(ok=True, payload=parsed2, used_thinking=True)
        return FieldAgentResult(ok=True, payload=parsed, used_thinking=used_thinking)
    return FieldAgentResult(ok=True, payload=parsed, used_thinking=used_thinking)
