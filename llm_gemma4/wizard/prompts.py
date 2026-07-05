"""Wizard phase prompt snippets (token-minimal)."""

from __future__ import annotations

from llm_gemma4.wizard import toml_io


WIZARD_SYSTEM = (
    "You configure Excel template TOML. Reply with ONE JSON object only, no markdown. "
    "Allowed actions: set_top_level, patch_field, test_paste_split, test_regex, "
    "test_source_row, ask_user."
)

TOP_LEVEL_HINT = (
    "Set top-level keys: work_sheet, print_sheet, determiner, db_id, input_section. "
    "Use action set_top_level with patch object. If unsure, use ask_user."
)

FIELD_MAP_HINT = (
    "Map paste columns for each Input_label. index is 0-based tab-split column. "
    "Validate with test_paste_split or test_regex, then patch_field with "
    "updates {index, field, regex}."
)

FIELD_BATCH_SIZE = 5
MAX_FIELD_RETRIES = 3
MAX_LLM_CALLS = 15


def phase_user_prefix(phase: str, digest: str) -> str:
    return f"[phase={phase}]\n{digest}"


def top_level_user_prompt(digest: str, *, skip_google: bool) -> str:
    google_note = "skip_google=true; leave source_file empty." if skip_google else ""
    return phase_user_prefix("TOP_LEVEL_QA", digest) + f"\n{TOP_LEVEL_HINT}\n{google_note}"


def field_map_user_prompt(
    digest: str,
    batch_labels: list[str],
    *,
    cfg,
    paste_sample: str,
    form_snapshot: dict,
    determiner: str,
    retry_note: str = "",
) -> str:
    batch_text = toml_io.field_batch_summary(cfg, batch_labels)
    snap_preview = "; ".join(
        f"{k}={v!r}" for k, v in list(form_snapshot.items())[:8]
    )
    paste_preview = paste_sample[:400] if paste_sample else "(empty)"
    lines = [
        phase_user_prefix("FIELD_MAP_LOOP", digest),
        FIELD_MAP_HINT,
        f"determiner={determiner!r}",
        f"paste_sample={paste_preview!r}",
        f"form_snapshot={snap_preview}",
        f"batch ({len(batch_labels)}):",
        batch_text,
    ]
    if retry_note:
        lines.append(f"retry: {retry_note}")
    return "\n".join(lines)


def tool_retry_prompt(observation: dict) -> str:
    err = observation.get("error") or observation.get("errors") or observation
    return f"Tool failed: {err}. Try another action or fix parameters."
