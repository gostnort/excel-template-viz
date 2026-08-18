"""工作流运行时原语 + TOML 域状态袋。

Decision / InterruptPayload / ExecutorResult 是 Graph 运行时原语，不含业务字段。
WorkflowState / FieldState 是 toml_config 向导的域状态；通用对话请用 llm_gemma4.dialog。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class FieldState:
    input_label: str
    match_type: str = "unknown"
    index: int = -1
    column_name: str = ""
    needs_regex: bool = False
    regex: str = ""
    source_file: str = ""
    source_sheet: str = ""
    id: bool = False
    error: str = ""
    used_thinking: bool = False


@dataclass
class WorkflowState:
    # --- 从 wizard/state.py WizardState 复制的字段 ---
    current_step: int = 1
    template_id: str = ""
    template_path: Path | None = None
    data_sources: list[dict[str, str]] = field(default_factory=list)
    ghost_text_sample: str = ""
    sample_kind: str = ""
    determiner: str | list[str] = ""
    indexed_segments: dict[int, str] = field(default_factory=dict)
    preprocess_done: bool = False
    field_tasks_planned: bool = False
    planned_labels: list[str] = field(default_factory=list)
    user_draft: dict[str, str] = field(default_factory=dict)
    google_sheet_headers: list[str] = field(default_factory=list)
    google_sheet_sample: list[list[Any]] = field(default_factory=list)
    template_labels: list[str] = field(default_factory=list)
    fields: dict[str, FieldState] = field(default_factory=dict)
    input_area: str | list[str] = ""
    move_to: str | list[str] = ""
    offset: int = 0
    db_id: str = ""
    is_finished: bool = False
    written_toml_path: str = ""
    # --- workflow 新增字段（Phase B 使用）---
    design_doc: str = ""
    user_inputs: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    route_key: str = ""
    pending_interrupt: dict[str, Any] | None = None


def ensure_field_states(state: WorkflowState, labels: list[str] | None = None) -> None:
    """
    函数名: ensure_field_states
    作用: 按标签补齐 FieldState，避免 resume 跳过 capture_sample 后缺字段
    输入:
        state (WorkflowState): 当前工作流状态
        labels (list[str] | None): 指定标签；默认用 template_labels
    输出: 无
    """
    for label in labels if labels is not None else list(state.template_labels or []):
        name = str(label or "").strip()
        if not name or name in state.fields:
            continue
        state.fields[name] = FieldState(input_label=name)




@dataclass
class InterruptPayload:
    kind: str  # ask_sources | ask_layout | ask_sample | ask_db_id
    expected_input: str
    auto_chain: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutorResult:
    ok: bool
    messages: list[str]
    state_patch: dict[str, Any]
    interrupt: InterruptPayload | None = None
    route_key: str = ""


@dataclass
class Decision:
    next_action: str
    action_id: str
    reason: str = ""
    expected_input: str = ""
    context_update: dict[str, Any] = field(default_factory=dict)
    route_key: str = ""
