"""IntakePlan：根据 WorkflowState 判断仍需采集的数据项。"""

from __future__ import annotations

from dataclasses import dataclass

from llm_gemma4.workflow.state import WorkflowState


INTAKE_KEYS = [
    "data_sources",
    "input_section",
    "ghost_sample",
    "field_drafts",
    "ghost_preprocess",
    "field_match",
    "sheet_match",
    "regex_infer",
    "db_id",
]

# intake key → 关联 state 字段名（文档/调试）
_INTAKE_STATE_FIELDS: dict[str, list[str]] = {
    "data_sources": ["data_sources", "template_id", "template_path"],
    "input_section": ["input_area", "move_to", "offset"],
    "ghost_sample": ["ghost_text_sample"],
    "field_drafts": ["user_draft"],
    "ghost_preprocess": ["indexed_segments", "preprocess_done", "determiner"],
    "field_match": ["planned_labels", "fields"],
    "sheet_match": ["google_sheet_headers", "data_sources"],
    "regex_infer": ["fields"],
    "db_id": ["db_id", "is_finished"],
}

# intake key → 中断 kind
_INTAKE_INTERRUPT_KIND: dict[str, str | None] = {
    "data_sources": "ask_sources",
    "input_section": "ask_layout",
    "ghost_sample": "ask_sample",
    "field_drafts": "ask_sample",
    "ghost_preprocess": None,
    "field_match": None,
    "sheet_match": None,
    "regex_infer": None,
    "db_id": "ask_db_id",
}

# action_id → intake key（用于 executor 防重复 ask）
_ACTION_INTAKE_KEY: dict[str, str | None] = {
    "capture_sources": "data_sources",
    "record_sources": None,
    "capture_layout": "input_section",
    "capture_sample": "ghost_sample",
    "preprocess_sample": "ghost_preprocess",
    "plan_ghost_tasks": None,
    "match_ghost_fields": "field_match",
    "match_sheet_columns": "sheet_match",
    "infer_regex": "regex_infer",
    "finalize_toml": "db_id",
}


@dataclass
class IntakeItem:
    """单项 intake 计划条目。"""

    key: str
    status: str  # pending | done | skip
    interrupt_kind: str | None
    state_fields: list[str]


def init_progress(labels: list[str]) -> dict[str, str]:
    """
    函数名: init_progress
    作用: 初始化 workflow progress 字典
    输入:
        labels (list[str]): 模板字段标签
    输出:
        dict[str, str]: progress 初始状态（均为 pending）
    """
    progress: dict[str, str] = {
        "data_sources": "pending",
        "input_section": "pending",
        "ghost_sample": "pending",
        "field_drafts": "pending",
        "ghost_preprocess": "pending",
        "field_match": "pending",
        "sheet_match": "pending",
        "regex_infer": "pending",
        "db_id": "pending",
    }
    for label in labels:
        progress[f"field:{label}"] = "pending"
    return progress


def _has_google_source(state: WorkflowState) -> bool:
    return any(
        ds.get("type") == "google_sheet" or ds.get("source1")
        for ds in (state.data_sources or [])
    )


def _input_area_set(state: WorkflowState) -> bool:
    area = state.input_area
    if isinstance(area, list):
        return any(str(item or "").strip() for item in area)
    return bool(str(area or "").strip())


def already_captured(state: WorkflowState, key: str) -> bool:
    """
    函数名: already_captured
    作用: 判断某 intake key 对应的数据是否已满足
    输入:
        state (WorkflowState): 当前状态
        key (str): intake key
    输出:
        bool: 已满足时为 True
    """
    progress = state.progress or {}
    if progress.get(key) == "done":
        return True
    if progress.get(key) == "skip":
        return True
    if key == "data_sources":
        if state.data_sources:
            return True
        # 用户显式跳过 Google 源
        return bool(state.user_inputs.get("data_sources_skipped"))
    if key == "input_section":
        return state.offset >= 1 and _input_area_set(state)
    if key == "ghost_sample":
        return bool(str(state.ghost_text_sample or "").strip())
    if key == "field_drafts":
        # capture_sample 成功即视为已采集（含全空 draft）
        if progress.get("ghost_sample") == "done":
            return True
        if state.user_inputs.get("field_drafts_captured"):
            return True
        return bool(state.user_draft) or bool(state.user_inputs.get("field_drafts_ok_empty"))
    if key == "ghost_preprocess":
        return bool(state.preprocess_done)
    if key == "field_match":
        labels = list(state.planned_labels or [])
        if not labels:
            return bool(state.field_tasks_planned)
        for label in labels:
            fs = state.fields.get(label)
            if fs is None:
                return False
            if fs.match_type == "unknown" and not fs.error:
                return False
        return True
    if key == "sheet_match":
        if not _has_google_source(state):
            return True
        for label in state.template_labels or []:
            fs = state.fields.get(label)
            if fs is None:
                continue
            if fs.column_name:
                continue
            if fs.match_type == "unknown" and not fs.error:
                return False
        return True
    if key == "regex_infer":
        needs = [
            label for label, fs in (state.fields or {}).items()
            if fs.needs_regex and not str(fs.regex or "").strip() and not fs.error
        ]
        return not needs
    if key == "db_id":
        if state.is_finished:
            return True
        return bool(state.user_inputs.get("db_id_confirmed"))
    return False


def _item_status(state: WorkflowState, key: str) -> str:
    if key == "sheet_match" and not _has_google_source(state):
        return "skip"
    if key == "regex_infer":
        needs = [
            label for label, fs in (state.fields or {}).items()
            if fs.needs_regex and not str(fs.regex or "").strip()
        ]
        if not needs and state.field_tasks_planned:
            return "skip"
    progress = state.progress or {}
    if progress.get(key) == "skip":
        return "skip"
    if already_captured(state, key):
        return "done"
    return "pending"


def build_intake_plan(state: WorkflowState) -> list[IntakeItem]:
    """
    函数名: build_intake_plan
    作用: 根据当前状态构建仍需采集/处理的数据项清单
    输入:
        state (WorkflowState): 当前工作流状态
    输出:
        list[IntakeItem]: intake 计划列表
    """
    items: list[IntakeItem] = []
    for key in INTAKE_KEYS:
        items.append(
            IntakeItem(
                key=key,
                status=_item_status(state, key),
                interrupt_kind=_INTAKE_INTERRUPT_KIND.get(key),
                state_fields=list(_INTAKE_STATE_FIELDS.get(key, [])),
            )
        )
    return items


def intake_key_for_action(action_id: str) -> str | None:
    """
    函数名: intake_key_for_action
    作用: 将 action_id 映射到 intake key，供 executor 防重复 ask
    输入:
        action_id (str): 动作标识
    输出:
        str | None: 对应 intake key
    """
    return _ACTION_INTAKE_KEY.get(action_id)


def format_intake_plan(intake: list[IntakeItem]) -> str:
    """
    函数名: format_intake_plan
    作用: 将 IntakePlan 格式化为 decide 提示词片段
    输入:
        intake (list[IntakeItem]): intake 列表
    输出:
        str: 多行文本
    """
    lines: list[str] = []
    for item in intake:
        kind = item.interrupt_kind or "-"
        fields = ", ".join(item.state_fields) if item.state_fields else "-"
        lines.append(f"- {item.key}: {item.status} (interrupt={kind}; fields={fields})")
    return "\n".join(lines)
