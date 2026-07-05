"""Narrow wizard tools + dispatch (embed_gemma4.md §6.2.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from llm_gemma4.tools.browser_playwright import NiceGuiBrowser
from llm_gemma4.tools.browser_state import format_page_state
from llm_gemma4.wizard import toml_io


def _compact_observation(payload: dict[str, Any], max_chars: int = 2000) -> dict[str, Any]:
    """Ensure dispatch return fits context limits."""
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) <= max_chars:
        return payload
    clipped = dict(payload)
    clipped["_truncated"] = True
    return clipped


def dispatch(
    action: dict[str, Any],
    *,
    template_id: str,
    template_xlsx: Path | None = None,
    state_paste: str = "",
    determiner: str = "\t",
    browser: NiceGuiBrowser | None = None,
    observation_max_chars: int = 2000,
) -> dict[str, Any]:
    """Route one action dict to Python implementation."""
    name = str(action.get("action", "")).strip()
    if name == "read_toml":
        out = toml_io.read_toml_digest(template_id, template_xlsx)
        return _compact_observation(out, observation_max_chars)
    if name == "set_top_level":
        patch = action.get("patch") or {}
        if not isinstance(patch, dict):
            return {"ok": False, "error": "patch must be object"}
        out = toml_io.apply_patch(
            template_id,
            top_level=patch,
            template_xlsx=template_xlsx,
        )
        return _compact_observation(out, observation_max_chars)
    if name == "patch_field":
        label = action.get("input_label")
        updates = action.get("updates") or {}
        if not label or not isinstance(updates, dict):
            return {"ok": False, "error": "input_label and updates required"}
        out = toml_io.apply_patch(
            template_id,
            field_label=str(label),
            field_updates=updates,
            template_xlsx=template_xlsx,
        )
        return _compact_observation(out, observation_max_chars)
    if name == "test_regex":
        out = toml_io.test_regex(
            str(action.get("pattern", "")),
            str(action.get("sample", "")),
            action.get("group"),
        )
        return _compact_observation(out, observation_max_chars)
    if name == "test_paste_split":
        out = toml_io.test_paste_split(
            str(action.get("paste_text", state_paste)),
            int(action.get("index", 0)),
            str(action.get("determiner", determiner)),
        )
        return _compact_observation(out, observation_max_chars)
    if name == "test_source_row":
        keys = action.get("keys")
        key_list = list(keys) if isinstance(keys, list) else None
        out = toml_io.test_source_row(
            template_id,
            str(action.get("source_file", "")),
            str(action.get("source_sheet", "")),
            key_list,
            row_index=int(action.get("row_index", 0)),
            template_xlsx=template_xlsx,
        )
        return _compact_observation(out, observation_max_chars)
    if name == "ask_user":
        kind = str(action.get("kind", "confirm"))
        options = action.get("options")
        option_list: list[str] | None = None
        if isinstance(options, list):
            option_list = [str(item) for item in options]
        return {
            "ok": True,
            "wait": True,
            "kind": kind,
            "question": str(action.get("question", "")),
            "options": option_list,
        }
    if name == "browser_snapshot":
        if browser is None:
            return {"ok": False, "error": "browser_snapshot requires active WizardRunner browser"}
        page_state = browser.snapshot(template_id=template_id)
        text = format_page_state(page_state)
        return {"ok": True, "page_state": text[:observation_max_chars]}
    if name == "browser_click":
        if browser is None:
            return {"ok": False, "error": "browser_click requires active WizardRunner browser"}
        text = action.get("text") or action.get("ref") or ""
        if not text:
            return {"ok": False, "error": "text or ref required"}
        clicked = browser.click_text(str(text))
        if not clicked:
            return {"ok": False, "error": f"click failed: {text!r}"}
        page_state = browser.snapshot(template_id=template_id)
        return {"ok": True, "clicked": str(text), "page_state": format_page_state(page_state)[:800]}
    return {"ok": False, "error": f"unknown action: {name}"}
