"""向导内存状态结构（不落盘）。"""

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
class WizardState:
    current_step: int = 1
    template_id: str = ""
    template_path: Path | None = None
    data_sources: list[dict[str, str]] = field(default_factory=list)
    ghost_text_sample: str = ""
    ghost_json_sample: dict | None = None
    sample_kind: str = ""
    determiner: str | list[str] = ""
    indexed_segments: dict[int, str] = field(default_factory=dict)
    preprocess_done: bool = False
    field_tasks_planned: bool = False
    planned_labels: list[str] = field(default_factory=list)
    normalized_sample: str = ""
    flat_kv: dict[str, str] = field(default_factory=dict)
    user_draft: dict[str, str] = field(default_factory=dict)
    google_sheet_headers: list[str] = field(default_factory=list)
    google_sheet_sample: list[list[Any]] = field(default_factory=list)
    template_labels: list[str] = field(default_factory=list)
    fields: dict[str, FieldState] = field(default_factory=dict)
    # input_section：空 / offset<=0 表示尚未由用户步骤写入，落盘时保留模板底稿
    input_area: str | list[str] = ""
    move_to: str | list[str] = ""
    offset: int = 0
    db_id: str = ""
    is_finished: bool = False
    trial_ok: bool = False
    trial_mismatches: list[dict[str, str]] = field(default_factory=list)
    written_toml_path: str = ""
