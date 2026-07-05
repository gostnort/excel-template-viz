"""Wizard persisted state (temp/wizard/{template_id}.json)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from llm_gemma4.models_catalog import repo_root


class WizardPhase(str, Enum):
    INIT = "INIT"
    PRECHECK = "PRECHECK"
    GOOGLE_PROBE = "GOOGLE_PROBE"
    READ_TOML = "READ_TOML"
    COLLECT_PASTE = "COLLECT_PASTE"
    TOP_LEVEL_QA = "TOP_LEVEL_QA"
    FIELD_MAP_LOOP = "FIELD_MAP_LOOP"
    FINAL_VERIFY = "FINAL_VERIFY"
    DONE = "DONE"


@dataclass
class WizardState:
    template_id: str
    phase: str = WizardPhase.INIT.value
    skip_google: bool = False
    paste_sample: str = ""
    form_snapshot: dict = field(default_factory=dict)
    regex_attempts: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    field_map_cursor: int = 0
    user_notes: dict = field(default_factory=dict)


def state_dir() -> Path:
    path = repo_root() / "temp" / "wizard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(template_id: str) -> Path:
    return state_dir() / f"{template_id}.json"


def load_state(template_id: str) -> WizardState:
    path = state_path(template_id)
    if not path.is_file():
        return WizardState(template_id=template_id)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return WizardState(
        template_id=template_id,
        phase=str(raw.get("phase", WizardPhase.INIT.value)),
        skip_google=bool(raw.get("skip_google", False)),
        paste_sample=str(raw.get("paste_sample", "")),
        form_snapshot=dict(raw.get("form_snapshot") or {}),
        regex_attempts=list(raw.get("regex_attempts") or []),
        llm_calls=int(raw.get("llm_calls", 0)),
        field_map_cursor=int(raw.get("field_map_cursor", 0)),
        user_notes=dict(raw.get("user_notes") or {}),
    )


def save_state(state: WizardState) -> None:
    path = state_path(state.template_id)
    payload = asdict(state)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
