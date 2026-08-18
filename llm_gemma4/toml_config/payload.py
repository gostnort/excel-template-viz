"""向导 start/resume 载荷与 executor patch 合并进 WorkflowState。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_gemma4.workflow.state import WorkflowState, ensure_field_states


def sanitize_template_labels(raw: list[Any]) -> list[str]:
    """
    函数名: sanitize_template_labels
    作用: 去重并过滤空白的 template_labels
    输入:
        raw (list): UI 传入的标签列表
    输出:
        list[str]: 清洗后的标签
    """
    seen: set[str] = set()
    labels: list[str] = []
    for item in raw:
        label = str(item or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def merge_payload_into_state(state: WorkflowState, payload: dict[str, Any]) -> None:
    """
    函数名: merge_payload_into_state
    作用: 将 UI/CLI tick payload 合并进 WorkflowState
    输入:
        state (WorkflowState): 当前状态
        payload (dict): start/resume 字段
    输出: 无
    """
    if not payload:
        return
    if payload.get("template_id"):
        state.template_id = str(payload.get("template_id") or state.template_id)
    tpath = payload.get("template_path")
    if tpath:
        state.template_path = Path(str(tpath))
    if "data_sources" in payload:
        incoming = list(payload.get("data_sources") or [])
        # 中文注释: 空列表不覆盖 init_workflow / sidecar 已预填的 [[sources]]
        if incoming or not state.data_sources:
            state.data_sources = incoming
    if "input_area" in payload:
        state.input_area = payload.get("input_area") or ""
    if "move_to" in payload:
        state.move_to = payload.get("move_to") or ""
    if "offset" in payload:
        try:
            state.offset = int(payload.get("offset") or 1)
        except (TypeError, ValueError):
            state.offset = 1
    if "user_draft" in payload:
        draft = payload.get("user_draft") or {}
        state.user_draft = {str(k): str(v) for k, v in draft.items() if str(v or "").strip()}
        state.user_inputs["field_drafts_captured"] = True
        ensure_field_states(state)
    if "ghost_text_sample" in payload:
        state.ghost_text_sample = str(payload.get("ghost_text_sample") or "")
        ensure_field_states(state)
    if "template_labels" in payload:
        labels = sanitize_template_labels(list(payload.get("template_labels") or []))
        state.template_labels = labels
        ensure_field_states(state, labels)
    if "google_sheet_headers" in payload:
        state.google_sheet_headers = list(payload.get("google_sheet_headers") or [])
    if "google_sheet_sample" in payload:
        state.google_sheet_sample = list(payload.get("google_sheet_sample") or [])
    if "db_id" in payload:
        raw_id = str(payload.get("db_id") or "").strip()
        state.db_id = "" if raw_id in ("", "None") else raw_id
        state.user_inputs["db_id_confirmed"] = True
    if payload.get("data_sources_skipped"):
        state.user_inputs["data_sources_skipped"] = True


def merge_state_patch(state: WorkflowState, patch: dict[str, Any]) -> None:
    """
    函数名: merge_state_patch
    作用: 将 executor state_patch 写回 dataclass（fields 原地变更不覆盖）
    输入:
        state (WorkflowState): 当前状态
        patch (dict): executor 返回补丁
    输出: 无
    """
    if not patch:
        return
    for key, value in patch.items():
        if key == "fields":
            continue
        if hasattr(state, key):
            setattr(state, key, value)
