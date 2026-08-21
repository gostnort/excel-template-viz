"""Gemma 驱动的工作流路由决策层。"""

from __future__ import annotations

import os
import uuid
from typing import Any

from llm_lmstudio.backend import LlmBackend, SessionOptions
from llm_toml_wizard.toml_config.context import build_main_turn_prefix
from llm_toml_wizard.toml_config.decide_stub import decide_stub
from llm_toml_wizard.toml_config.design_doc import build_design_doc
from llm_toml_wizard.toml_config.intake_plan import (
    IntakeItem,
    already_captured,
    format_intake_plan,
)
from llm_toml_wizard.toml_config.parse_decision_json import ParseDecisionError, parse_decision_json
from llm_toml_wizard.workflow.state import Decision, WorkflowState

ALLOWED_ACTION_IDS = frozenset({
    "capture_sources",
    "record_sources",
    "capture_layout",
    "capture_sample",
    "preprocess_sample",
    "plan_ghost_tasks",
    "match_ghost_fields",
    "match_sheet_columns",
    "infer_regex",
    "finalize_toml",
})

ALLOWED_NEXT_ACTIONS = frozenset({
    "ask_user",
    "compute",
    "validate",
    "finalize",
    "error",
})

_ASK_USER_ACTION_IDS = frozenset({
    "capture_sources",
    "capture_layout",
    "capture_sample",
    "finalize_toml",
})

_COMPUTE_ACTION_IDS = frozenset({
    "record_sources",
    "preprocess_sample",
    "plan_ghost_tasks",
    "match_ghost_fields",
    "match_sheet_columns",
    "infer_regex",
})

DECISION_SYSTEM_PROMPT = """You are the TOML wizard workflow router.
Output ONLY a single JSON object (no markdown fences, no prose).

Required keys: next_action, action_id
Optional keys: reason, expected_input, context_update, route_key

next_action must be one of: ask_user, compute, validate, finalize, error
action_id must be one of the ACTION_CATALOG ids.

Rules:
- ask_user only for intake keys still pending; never re-ask already_captured keys
- ask_user action_id must be capture_sources, capture_layout, capture_sample, or finalize_toml
- compute action_id must be record_sources, preprocess_sample, plan_ghost_tasks,
  match_ghost_fields, match_sheet_columns, or infer_regex
- When no Google Sheet source, use route_key=skip_sheet for match_sheet_columns
- Do not request ghost_sample if ghost_sample is already captured
"""

ACTION_CATALOG = """
| action_id | next_action | Preconditions | Effect |
|-----------|-------------|---------------|--------|
| capture_sources | ask_user | template_id set | Interrupt ask_sources; user configures Google or skips |
| record_sources | compute | data_sources captured/skipped | Store data_sources; persist TOML |
| capture_layout | ask_user | sources recorded | Interrupt ask_layout; set input_area/move_to/offset |
| capture_sample | ask_user | layout done | Interrupt ask_sample; ghost + field drafts |
| preprocess_sample | compute | sample captured | build indexed_segments + determiner |
| plan_ghost_tasks | compute | preprocess done | wizard_main plans FieldTasks |
| match_ghost_fields | compute | plan done | Parallel ghost field agents (max 2) |
| match_sheet_columns | compute | ghost match done | Sheet column match; skip if no google |
| infer_regex | compute | sheet done/skipped | Regex for needs_regex fields |
| finalize_toml | ask_user/finalize | matching done | Interrupt ask_db_id; persist and finish |
"""


def _stub_mode() -> bool:
    return os.environ.get("WORKFLOW_DECIDE_STUB", "").strip() in ("1", "true", "yes")


def _format_captured(state: WorkflowState) -> str:
    captured = [key for key in (
        "data_sources", "input_section", "ghost_sample", "field_drafts",
        "ghost_preprocess", "field_match", "sheet_match", "regex_infer", "db_id",
    ) if already_captured(state, key)]
    if not captured:
        return "(none)"
    return ", ".join(captured)


def _format_user_input(user_input: dict[str, Any] | None) -> str:
    if not user_input:
        return "(none)"
    keys = ", ".join(sorted(str(k) for k in user_input.keys()))
    return f"keys: {keys}"


def _build_decision_prompt(
    state: WorkflowState,
    user_input: dict[str, Any] | None,
    intake: list[IntakeItem],
) -> str:
    doc = state.design_doc or build_design_doc(
        state.template_id,
        state.template_path,
        list(state.template_labels or []),
    )
    summary = build_main_turn_prefix(state)
    return (
        f"{ACTION_CATALOG}\n\n"
        f"## design_doc\n{doc[:4000]}\n\n"
        f"## IntakePlan\n{format_intake_plan(intake)}\n\n"
        f"## already_captured\n{_format_captured(state)}\n\n"
        f"## State summary\n{summary or '(empty)'}\n\n"
        f"## Last user_input\n{_format_user_input(user_input)}\n\n"
        "Choose the single best next action. Output JSON only."
    )


def _validate_action_next_action_pair(next_action: str, action_id: str) -> None:
    """
    函数名: _validate_action_next_action_pair
    作用: 校验 next_action 与 action_id 的确定性映射，防止 Gemma 返回矛盾组合
    输入:
        next_action (str): 决策动作类型
        action_id (str): 执行器动作标识
    输出: 无；不合法时抛出 ParseDecisionError
    """
    if next_action == "error":
        return
    if next_action == "ask_user" and action_id not in _ASK_USER_ACTION_IDS:
        raise ParseDecisionError(
            f"ask_user requires capture_* or finalize_toml, got {action_id!r}"
        )
    if next_action == "compute" and action_id not in _COMPUTE_ACTION_IDS:
        raise ParseDecisionError(
            f"compute requires record/preprocess/match action, got {action_id!r}"
        )
    if next_action == "finalize" and action_id != "finalize_toml":
        raise ParseDecisionError(
            f"finalize requires finalize_toml, got {action_id!r}"
        )
    if next_action == "validate" and action_id not in ALLOWED_ACTION_IDS:
        raise ParseDecisionError(f"validate has invalid action_id: {action_id!r}")


def _decision_from_parsed(data: dict[str, Any]) -> Decision:
    next_action = str(data.get("next_action") or "").strip()
    action_id = str(data.get("action_id") or "").strip()
    if next_action not in ALLOWED_NEXT_ACTIONS:
        raise ParseDecisionError(f"invalid next_action: {next_action!r}")
    if action_id not in ALLOWED_ACTION_IDS:
        raise ParseDecisionError(f"invalid action_id: {action_id!r}")
    _validate_action_next_action_pair(next_action, action_id)
    context_update = data.get("context_update")
    if context_update is not None and not isinstance(context_update, dict):
        context_update = {}
    return Decision(
        next_action=next_action,
        action_id=action_id,
        reason=str(data.get("reason") or ""),
        expected_input=str(data.get("expected_input") or ""),
        context_update=dict(context_update or {}),
        route_key=str(data.get("route_key") or ""),
    )


def _call_decision_session(backend: LlmBackend, prompt: str, retry_hint: str = "") -> str:
    """
    函数名: _call_decision_session
    作用: 打开一次性 wizard_decision 会话并发送决策提示
    输入:
        backend (LlmBackend): LLM 后端
        prompt (str): 用户提示
        retry_hint (str): 解析失败时的重试附加说明
    输出:
        str: 模型回复文本
    """
    sid = f"wizard_decision_{uuid.uuid4().hex[:8]}"
    opts = SessionOptions(
        system_message=DECISION_SYSTEM_PROMPT,
        thinking=False,
        max_tokens=512,
    )
    content = prompt
    if retry_hint:
        content = f"{prompt}\n\n{retry_hint}"
    session = backend.open_session(sid, options=opts)
    try:
        result = session.send_turn({"role": "user", "content": content})
        return result.text
    finally:
        session.close()


def _fallback_compute_decision(state: WorkflowState) -> Decision | None:
    """
    函数名: _fallback_compute_decision
    作用: Gemma 路由失准时按 intake 顺序强制下一 compute 步（尤其 field_match 链）
    输入:
        state (WorkflowState): 当前状态
    输出:
        Decision | None: 可执行的 compute 决策；无需 fallback 时为 None
    """
    if (
        already_captured(state, "ghost_sample")
        and already_captured(state, "field_drafts")
        and not already_captured(state, "ghost_preprocess")
    ):
        return Decision(
            next_action="compute",
            action_id="preprocess_sample",
            reason="fallback: ghost preprocess pending",
            route_key="preprocess_sample",
        )
    if state.preprocess_done and not state.field_tasks_planned:
        return Decision(
            next_action="compute",
            action_id="plan_ghost_tasks",
            reason="fallback: plan ghost tasks pending",
            route_key="plan_ghost_tasks",
        )
    if state.field_tasks_planned and not already_captured(state, "field_match"):
        return Decision(
            next_action="compute",
            action_id="match_ghost_fields",
            reason="fallback: ghost field match pending",
            route_key="match_ghost_fields",
        )
    if (
        already_captured(state, "field_match")
        and not already_captured(state, "sheet_match")
    ):
        return Decision(
            next_action="compute",
            action_id="match_sheet_columns",
            reason="fallback: sheet match pending",
            route_key="match_sheet_columns",
        )
    if (
        already_captured(state, "sheet_match")
        and not already_captured(state, "regex_infer")
    ):
        return Decision(
            next_action="compute",
            action_id="infer_regex",
            reason="fallback: regex infer pending",
            route_key="infer_regex",
        )
    return None


def _fallback_finalize_decision(state: WorkflowState) -> Decision | None:
    """
    函数名: _fallback_finalize_decision
    作用: compute 链结束后强制 finalize_toml，避免 Gemma 重复 ask 早期 intake
    输入:
        state (WorkflowState): 当前状态
    输出:
        Decision | None: finalize 决策；尚未到 finalize 阶段时为 None
    """
    if already_captured(state, "db_id"):
        return Decision(
            next_action="finalize",
            action_id="finalize_toml",
            reason="fallback: db_id confirmed, finalize",
            route_key="finalize_toml",
        )
    if not already_captured(state, "regex_infer"):
        return None
    if not already_captured(state, "field_match"):
        return None
    if not already_captured(state, "ghost_preprocess"):
        return None
    return Decision(
        next_action="ask_user",
        action_id="finalize_toml",
        reason="fallback: compute chain complete, db_id pending",
        route_key="finalize_toml",
    )


def decide(
    state: WorkflowState,
    user_input: dict[str, Any] | None,
    intake: list[IntakeItem],
    backend: LlmBackend,
    *,
    stub_index: int = 0,
) -> tuple[Decision, int]:
    """
    函数名: decide
    作用: 调用 Gemma 一次性会话，返回下一步决策 JSON
    输入:
        state (WorkflowState): 当前状态
        user_input (dict | None): 最近一次 UI 输入
        intake (list[IntakeItem]): intake 计划
        backend (LlmBackend): LLM 后端
        stub_index (int): stub 模式下的动作索引
    输出:
        tuple[Decision, int]: 决策与更新后的 stub_index
    """
    if _stub_mode():
        decision, index = decide_stub(state, stub_index)
        if decision is None:
            return (
                Decision(
                    next_action="finalize",
                    action_id="finalize_toml",
                    reason="stub sequence complete",
                    route_key="stub_done",
                ),
                index,
            )
        return decision, index
    # compute / finalize 链 fallback：避免 Gemma 重复 ask 或跳过 match_ghost_fields
    forced = _fallback_compute_decision(state)
    if forced is not None:
        return forced, stub_index
    forced_finalize = _fallback_finalize_decision(state)
    if forced_finalize is not None:
        return forced_finalize, stub_index
    # Gemma 路由
    prompt = _build_decision_prompt(state, user_input, intake)
    try:
        reply = _call_decision_session(backend, prompt)
        parsed = parse_decision_json(reply)
        return _decision_from_parsed(parsed), stub_index
    except (ParseDecisionError, ValueError) as first_err:
        retry = (
            "Your previous reply was not valid JSON with next_action and action_id. "
            "Output ONLY one JSON object."
        )
        try:
            reply2 = _call_decision_session(backend, prompt, retry_hint=retry)
            parsed2 = parse_decision_json(reply2)
            return _decision_from_parsed(parsed2), stub_index
        except (ParseDecisionError, ValueError):
            return (
                Decision(
                    next_action="error",
                    action_id="finalize_toml",
                    reason=f"decision parse failed: {first_err}",
                    route_key="decision_error",
                ),
                stub_index,
            )
