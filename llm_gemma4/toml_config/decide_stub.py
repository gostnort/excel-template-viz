"""Phase A 线性 stub 决策（仅 WORKFLOW_DECIDE_STUB=1 调试时使用）。"""

from __future__ import annotations

from llm_gemma4.toml_config.intake_plan import already_captured
from llm_gemma4.workflow.state import Decision, WorkflowState

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


def _has_google_source(state: WorkflowState) -> bool:
    return any(
        ds.get("type") == "google_sheet" or ds.get("source1")
        for ds in (state.data_sources or [])
    )


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
        if action_id == "capture_sources":
            if already_captured(state, "data_sources"):
                index += 1
                continue
            return (
                Decision(
                    next_action="ask_user",
                    action_id="capture_sources",
                    reason="stub: capture_sources",
                    route_key="capture_sources",
                ),
                index,
            )
        if action_id == "match_sheet_columns":
            if not _has_google_source(state) or not state.google_sheet_headers:
                index += 1
                continue
        return (
            Decision(
                next_action="compute",
                action_id=action_id,
                reason=f"stub: {action_id}",
                route_key=action_id,
            ),
            index,
        )
    return None, index
