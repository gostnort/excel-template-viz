"""通用 decide()：Gemma 选出下一步 action_id；与 toml_config.decision 解耦。"""

from __future__ import annotations

import os
import uuid
from typing import Any

from llm_lmstudio.backend import LlmBackend, SessionOptions
from llm_toml_wizard.dialog.spec import DialogSpec
from llm_toml_wizard.dialog.state import DialogState, pending_needs
from llm_lmstudio.json_extract import extract_json_object
from llm_toml_wizard.workflow.state import Decision

ALLOWED_ACTION_IDS = frozenset({
    "plan_intake",
    "ask_user",
    "dispatch_subagents",
    "synthesize",
    "finish",
})

ALLOWED_NEXT_ACTIONS = frozenset({"ask_user", "compute", "finalize", "error"})

ACTION_CATALOG = """
| action_id | next_action | When |
|-----------|-------------|------|
| plan_intake | compute | Intake list missing or should be refined from the goal |
| ask_user | ask_user | A required fact is still pending; never re-ask a captured key |
| dispatch_subagents | compute | Required facts are captured; spawn focused sub-agent sessions |
| synthesize | compute | Sub-agent artifacts are ready; main session writes the answer |
| finish | finalize | Synthesis done (or nothing left to do) |
"""

DEFAULT_DECISION_SYSTEM = """You are a dialog router, not the domain expert.
Output ONLY one JSON object (no markdown fences).
Required keys: next_action, action_id
Optional: reason, expected_input, route_key
next_action: ask_user | compute | finalize | error
Never ask for an already captured fact. thinking is forbidden on this session.
"""


def _stub_env() -> bool:
    """
    函数名: _stub_env
    作用: 是否由环境变量强制 stub 路由
    输入: 无
    输出:
        bool: DIALOG_DECIDE_STUB 开启时为 True
    """
    return os.environ.get("DIALOG_DECIDE_STUB", "").strip().lower() in ("1", "true", "yes")


def decide_stub(state: DialogState) -> Decision:
    """
    函数名: decide_stub
    作用: 按固定顺序选下一步（离线 / 测试）
    输入:
        state (DialogState): 当前状态
    输出:
        Decision: 下一步动作
    """
    if not state.intake_planned:
        return Decision(next_action="compute", action_id="plan_intake", reason="stub: plan_intake", route_key="plan_intake")
    if pending_needs(state):
        return Decision(next_action="ask_user", action_id="ask_user", reason="stub: ask_user", route_key="ask_user")
    if not state.artifacts:
        return Decision(next_action="compute", action_id="dispatch_subagents", reason="stub: dispatch", route_key="dispatch_subagents")
    if not str(state.last_summary or "").strip():
        return Decision(next_action="compute", action_id="synthesize", reason="stub: synthesize", route_key="synthesize")
    return Decision(next_action="finalize", action_id="finish", reason="stub: finish", route_key="finish")


def _format_intake(state: DialogState) -> str:
    lines: list[str] = []
    for item in state.intake:
        status = state.progress.get(item.key, "pending")
        if str(state.facts.get(item.key) or "").strip():
            status = "done"
        lines.append(f"- {item.key}: {status} required={item.required} q={item.question}")
    return "\n".join(lines) if lines else "(none)"


def _decision_from_payload(data: dict[str, Any], spec: DialogSpec | None = None) -> Decision:
    """
    函数名: _decision_from_payload
    作用: 将模型 JSON 校验为 Decision；域 spec 可放宽 action_id 白名单
    输入:
        data (dict): 解析后的决策对象
        spec (DialogSpec | None): 域插件；None 则用通用五动作规则
    输出:
        Decision: 合法决策；不合法抛 ValueError
    """
    allowed_next = (spec.get_allowed_next_actions() if spec is not None else None) or ALLOWED_NEXT_ACTIONS
    allowed_ids = (spec.get_allowed_action_ids() if spec is not None else None) or ALLOWED_ACTION_IDS
    next_action = str(data.get("next_action") or "").strip()
    action_id = str(data.get("action_id") or "").strip()
    if next_action not in allowed_next:
        raise ValueError(f"invalid next_action: {next_action!r}")
    if action_id not in allowed_ids:
        raise ValueError(f"invalid action_id: {action_id!r}")
    # 中文注释: 仅通用五动作强制 next_action↔action_id 配对；域 catalog 自管
    if spec is None or spec.get_allowed_action_ids() is None:
        if next_action == "ask_user" and action_id != "ask_user":
            raise ValueError("ask_user next_action requires action_id=ask_user")
        if next_action == "finalize" and action_id != "finish":
            raise ValueError("finalize requires action_id=finish")
        if next_action == "compute" and action_id not in ("plan_intake", "dispatch_subagents", "synthesize"):
            raise ValueError(f"compute cannot use {action_id!r}")
    return Decision(
        next_action=next_action,
        action_id=action_id,
        reason=str(data.get("reason") or ""),
        expected_input=str(data.get("expected_input") or ""),
        route_key=str(data.get("route_key") or action_id),
    )


def _call_decision(backend: LlmBackend, spec: DialogSpec, prompt: str, retry_hint: str = "") -> str:
    sid = f"dialog_decision_{uuid.uuid4().hex[:8]}"
    opts = SessionOptions(
        system_message=spec.decision_system or DEFAULT_DECISION_SYSTEM,
        thinking=False,
        max_tokens=512,
    )
    content = prompt if not retry_hint else f"{prompt}\n\n{retry_hint}"
    session = backend.open_session(sid, options=opts)
    try:
        result = session.send_turn({"role": "user", "content": content})
        return result.text or ""
    finally:
        session.close()


def decide(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    user_input: dict[str, Any] | None,
    *,
    stub: bool = False,
) -> Decision:
    """
    函数名: decide
    作用: 一次性决策会话选出下一步；失败则再问一轮，再失败则 error
    输入:
        state (DialogState): 当前状态
        spec (DialogSpec): 域插件（decision_system）
        backend (LlmBackend): 推理后端
        user_input (dict | None): 本轮用户恢复数据
        stub (bool): True 时走 decide_stub
    输出:
        Decision: 下一步
    """
    if stub or _stub_env():
        custom_stub = spec.stub_decide(state)
        if custom_stub is not None:
            return custom_stub
        return decide_stub(state)
    captured = [k for k, v in state.facts.items() if str(v or "").strip()]
    catalog = spec.get_decision_catalog() or ACTION_CATALOG
    prompt = (
        f"{catalog}\n\n"
        f"## Intake\n{_format_intake(state)}\n\n"
        f"## captured keys\n{', '.join(captured) if captured else '(none)'}\n\n"
        f"## goal\n{state.goal or '(none)'}\n\n"
        f"## artifacts\n{', '.join(state.artifacts.keys()) or '(none)'}\n\n"
        f"## summary_ready\n{bool(str(state.last_summary or '').strip())}\n\n"
        f"## last user_input keys\n{', '.join(sorted((user_input or {}).keys())) or '(none)'}\n\n"
        "Choose the single best next action. JSON only."
    )
    try:
        reply = _call_decision(backend, spec, prompt)
        payload, err = extract_json_object(reply)
        if err or payload is None:
            raise ValueError(err or "empty decision json")
        return _decision_from_payload(payload, spec)
    except (ValueError, TypeError) as first_err:
        retry = "Previous reply was invalid. Output ONLY one JSON object with next_action and action_id."
        try:
            reply2 = _call_decision(backend, spec, prompt, retry_hint=retry)
            payload2, err2 = extract_json_object(reply2)
            if err2 or payload2 is None:
                raise ValueError(err2 or "empty decision json")
            return _decision_from_payload(payload2, spec)
        except (ValueError, TypeError):
            return Decision(
                next_action="error",
                action_id="finish",
                reason=f"decision parse failed: {first_err}",
                route_key="decision_error",
            )
