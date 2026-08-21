"""Phase A 线性 stub 决策（仅 WORKFLOW_DECIDE_STUB=1 调试时使用）。"""

from __future__ import annotations

from llm_toml_wizard.toml_config.intake_plan import already_captured, intake_key_for_action
from llm_toml_wizard.workflow.state import Decision, WorkflowState

_STUB_ORDER = [
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
]

_ASK_USER_ACTIONS = frozenset({
    "capture_sources",
    "capture_layout",
    "capture_sample",
    "finalize_toml",
})


def _has_google_source(state: WorkflowState) -> bool:
    return any(
        ds.get("type") == "google_sheet" or ds.get("source1")
        for ds in (state.data_sources or [])
    )


def _stub_next_action(action_id: str, state: WorkflowState) -> str:
    """
    函数名: _stub_next_action
    作用: 将 stub 动作映射到正确的 next_action
    输入:
        action_id (str): 动作标识
        state (WorkflowState): 当前状态
    输出:
        str: ask_user / compute / finalize
    """
    if action_id == "finalize_toml" and already_captured(state, "db_id"):
        return "finalize"
    if action_id in _ASK_USER_ACTIONS:
        return "ask_user"
    return "compute"


def decide_stub(state: WorkflowState, stub_index: int) -> tuple[Decision | None, int]:
    """
    函数名: decide_stub
    作用: 按固定顺序返回下一动作（Phase A 兼容）
    输入:
        state (WorkflowState): 当前状态
        stub_index (int): 当前 stub 索引
    输出:
        tuple[Decision | None, int]: 决策与更新后的索引
    """
    index = stub_index
    while index < len(_STUB_ORDER):
        action_id = _STUB_ORDER[index]
        intake_key = intake_key_for_action(action_id)
        if intake_key and already_captured(state, intake_key):
            index += 1
            continue
        if action_id == "record_sources" and already_captured(state, "data_sources"):
            index += 1
            continue
        if action_id == "match_sheet_columns":
            if not _has_google_source(state) or not state.google_sheet_headers:
                index += 1
                continue
        return (
            Decision(
                next_action=_stub_next_action(action_id, state),
                action_id=action_id,
                reason=f"stub: {action_id}",
                route_key=action_id,
            ),
            index,
        )
    return None, index
