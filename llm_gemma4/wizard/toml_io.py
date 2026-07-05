"""TOML digest, patch, backup (app.core_toml integration)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core_registry import SortTemplates, TEMPLATES_DIR
from app.core_toml import (
    GetTomlValues,
    TomlDefault,
    TomlGenerator,
    _core_toml_path,
    load_toml,
    verify_toml,
)
from app.core_transform import Template2DB, _load_sheet_rows


class TomlIOError(Exception):
    """User-facing TOML wizard error."""


def resolve_template_xlsx(template_id: str) -> Path | None:
    """Map template_id to xlsx via sort_templates.json."""
    registry = SortTemplates()
    mapped = registry.TemplateIDs.get(template_id)
    if mapped and mapped.is_file():
        return mapped.resolve()
    stem = template_id.lower().replace("-", "_")
    for path in TEMPLATES_DIR.glob("*.xlsx"):
        if path.stem.lower().replace("-", "_").replace(" ", "_") == stem:
            return path.resolve()
    return None


def toml_path(template_id: str) -> Path:
    return _core_toml_path(template_id)


def compact_verify_errors(report: dict[str, Any], limit: int = 12) -> list[str]:
    """Short error list for LLM context."""
    errors = list(report.get("errors") or [])
    if report.get("missing_labels"):
        errors.append(f"missing_labels: {report['missing_labels'][:5]}")
    if report.get("duplicate_labels"):
        errors.append(f"duplicate_labels: {report['duplicate_labels'][:5]}")
    if report.get("out_of_area_labels"):
        errors.append(f"out_of_area_labels: {report['out_of_area_labels'][:5]}")
    if report.get("invalid_db_id"):
        errors.append(f"invalid_db_id: {report['invalid_db_id']}")
    return errors[:limit]


def build_toml_digest(
    cfg: GetTomlValues,
    report: dict[str, Any] | None = None,
    *,
    pending_labels: list[str] | None = None,
) -> str:
    """Structured summary for wizard / LLM (not full TOML)."""
    field_count = len(cfg.field_rules)
    unmapped = sum(1 for row in cfg.field_rules if row.index < 0)
    lines = [
        f"work_sheet={cfg.work_sheet!r} print_sheet={cfg.print_sheet!r} fields={field_count}",
        f"determiner={cfg.determiner!r} db_id={cfg.db_id!r} unmapped_index={unmapped}",
        f"input_area={cfg.input_section.input_area!r}",
    ]
    if report is not None:
        ok = report.get("ok", False)
        lines.append(f"verify_ok={ok}")
        err_lines = compact_verify_errors(report)
        if err_lines:
            lines.append("errors: " + "; ".join(err_lines))
    if pending_labels:
        preview = pending_labels[:8]
        lines.append(f"pending_batch: {preview}")
    return "\n".join(lines)


def backup_toml(template_id: str) -> Path:
    """Copy current toml to .bak.{timestamp}."""
    src = toml_path(template_id)
    if not src.is_file():
        raise TomlIOError(f"TOML missing: {src}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = src.with_name(f"{src.stem}.toml.bak.{stamp}")
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def restore_backup(template_id: str, backup: Path) -> None:
    dest = toml_path(template_id)
    dest.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")


def _merge_top_level(cfg: GetTomlValues, patch: dict[str, Any]) -> None:
    allowed = {"work_sheet", "print_sheet", "determiner", "db_id"}
    for key, value in patch.items():
        if key in allowed:
            setattr(cfg, key, value)
        elif key == "input_section" and isinstance(value, dict):
            if "input_area" in value:
                cfg.input_section.input_area = str(value["input_area"])
            if "move_to" in value:
                cfg.input_section.move_to = str(value["move_to"])
            if "offset" in value:
                cfg.input_section.offset = int(value["offset"])


def _merge_field(cfg: GetTomlValues, input_label: str, updates: dict[str, Any]) -> bool:
    for row in cfg.field_rules:
        if row.Input_label != input_label:
            continue
        for key, value in updates.items():
            if key == "index":
                row.index = int(value)
            elif key == "field":
                row.field = None if value in ("", None) else str(value)
            elif key == "regex":
                row.regex = None if value in ("", None) else str(value)
            elif key == "source_file":
                row.source_file = None if value in ("", None) else str(value)
            elif key == "source_sheet":
                row.source_sheet = None if value in ("", None) else str(value)
            elif key == "id":
                row.id = bool(value)
        return True
    return False


def apply_patch(
    template_id: str,
    *,
    top_level: dict[str, Any] | None = None,
    field_label: str | None = None,
    field_updates: dict[str, Any] | None = None,
    template_xlsx: Path | None = None,
) -> dict[str, Any]:
    """
    Patch cfg in memory, write TOML, verify; rollback on failure.

    Returns observation dict for tools.dispatch.
    """
    cfg = load_toml(template_id)
    if cfg is None:
        raise TomlIOError(f"Cannot load TOML for {template_id}")
    xlsx = template_xlsx or resolve_template_xlsx(template_id)
    if xlsx is None or not xlsx.is_file():
        raise TomlIOError(f"Template xlsx not found for {template_id}")
    backup = backup_toml(template_id)
    if top_level:
        _merge_top_level(cfg, top_level)
    if field_label and field_updates:
        if not _merge_field(cfg, field_label, field_updates):
            restore_backup(template_id, backup)
            raise TomlIOError(f"Unknown Input_label: {field_label}")
    text = TomlGenerator().ConfigToToml(cfg.ToDict())
    path = toml_path(template_id)
    path.write_text(text, encoding="utf-8")
    report = verify_toml(xlsx, cfg)
    if not report.get("ok", False):
        restore_backup(template_id, backup)
        return {
            "ok": False,
            "rolled_back": True,
            "errors": compact_verify_errors(report),
        }
    return {
        "ok": True,
        "errors": [],
        "digest": build_toml_digest(cfg, report),
    }


def read_toml_digest(template_id: str, template_xlsx: Path | None = None) -> dict[str, Any]:
    """Load cfg + verify report + digest."""
    cfg = load_toml(template_id)
    if cfg is None:
        raise TomlIOError(f"Cannot load TOML for {template_id}")
    xlsx = template_xlsx or resolve_template_xlsx(template_id)
    report: dict[str, Any] | None = None
    if xlsx and xlsx.is_file():
        report = verify_toml(xlsx, cfg)
    digest = build_toml_digest(cfg, report)
    return {
        "digest": digest,
        "verify_ok": bool(report.get("ok")) if report else None,
        "errors": compact_verify_errors(report) if report else [],
    }


def test_regex(pattern: str, sample: str, group: int | None = None) -> dict[str, Any]:
    try:
        match = re.search(pattern, sample)
    except re.error as exc:
        return {"ok": False, "error": str(exc)}
    if not match:
        return {"ok": False, "error": "no match"}
    if group is not None:
        try:
            value = match.group(group)
        except IndexError:
            return {"ok": False, "error": f"group {group} missing"}
        return {"ok": True, "value": value, "groups": match.groups()}
    return {"ok": True, "value": match.group(0), "groups": match.groups()}


def test_paste_split(paste_text: str, index: int, determiner: str) -> dict[str, Any]:
    parts = paste_text.split(determiner)
    if index < 0 or index >= len(parts):
        return {"ok": False, "error": f"index {index} out of range (parts={len(parts)})"}
    return {"ok": True, "value": parts[index].strip(), "part_count": len(parts)}


def pending_field_labels(cfg: GetTomlValues) -> list[str]:
    """Input_labels still needing paste index mapping."""
    labels: list[str] = []
    for row in cfg.field_rules:
        if row.index < 0:
            labels.append(row.Input_label)
    return labels


def field_batch_summary(cfg: GetTomlValues, labels: list[str]) -> str:
    """Compact batch description for LLM (not full TOML)."""
    by_label = {row.Input_label: row for row in cfg.field_rules}
    lines: list[str] = []
    for label in labels:
        row = by_label.get(label)
        if row is None:
            continue
        field = row.field or ""
        regex = row.regex or ""
        lines.append(f"{label}: index={row.index} field={field!r} regex={regex!r}")
    return "\n".join(lines)


def heuristic_field_index(
    input_label: str,
    paste_text: str,
    form_snapshot: dict[str, str],
    determiner: str,
) -> dict[str, Any] | None:
    """Guess paste column index from form snapshot value (no LLM)."""
    sample = str(form_snapshot.get(input_label, "")).strip()
    if not sample or not paste_text:
        return None
    parts = [part.strip() for part in paste_text.split(determiner)]
    for index, part in enumerate(parts):
        if part == sample or sample in part:
            return {"index": index}
    return None


def test_source_row(
    template_id: str,
    source_file: str,
    source_sheet: str,
    keys: list[str] | None = None,
    *,
    row_index: int = 0,
    template_xlsx: Path | None = None,
) -> dict[str, Any]:
    """Load one data row from a configured source xlsx."""
    cfg = load_toml(template_id)
    if cfg is None:
        return {"ok": False, "error": f"cannot load TOML for {template_id}"}
    reader = Template2DB(cfg)
    path = reader.resolve_source_path(source_file)
    if path is None or not path.is_file():
        return {"ok": False, "error": f"source path missing for {source_file!r}"}
    try:
        rows = _load_sheet_rows(path, source_sheet)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not rows:
        return {"ok": False, "error": "no data rows"}
    pick = row_index if 0 <= row_index < len(rows) else 0
    row = rows[pick]
    if keys:
        picked = {key: row.get(key, "") for key in keys}
        return {"ok": True, "row": picked, "row_index": pick}
    preview = dict(list(row.items())[:12])
    return {"ok": True, "row": preview, "row_index": pick}


def field_rule_for_label(cfg: GetTomlValues, input_label: str) -> TomlDefault | None:
    for row in cfg.field_rules:
        if row.Input_label == input_label:
            return row
    return None
