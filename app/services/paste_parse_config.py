import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.services.registry import TEMPLATES_DIR

PASTE_CONFIG_SUFFIX = ".paste.yaml"
RESERVED_TOP_KEYS = frozenset({"determiner", "order"})


@dataclass
class PasteParseRule:
    filed: str
    index: int
    regex: str | None = None
    id_flag: bool = False


@dataclass
class PasteParseConfig:
    determiner: str
    field_rules: dict[str, list[PasteParseRule]]
    order: list[dict[str, Any]] | None = None


def paste_config_path(template_id: str) -> Path:
    return TEMPLATES_DIR / f"{template_id}{PASTE_CONFIG_SUFFIX}"


def _normalize_determiner(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"tab", "\\t"}:
        return "tab"
    return value


def _split_line(line: str, determiner: str) -> list[str]:
    if determiner == "tab":
        return line.split("\t")
    if determiner == "space":
        return line.split()
    return line.split(determiner)


def _parse_rules(raw_rules: Any) -> list[PasteParseRule]:
    if not isinstance(raw_rules, list):
        return []
    rules: list[PasteParseRule] = []
    for item in raw_rules:
        if not isinstance(item, dict):
            continue
        if "index" not in item:
            continue
        rules.append(
            PasteParseRule(
                filed=str(item.get("filed", "?")),
                index=int(item["index"]),
                regex=str(item["regex"]) if item.get("regex") is not None else None,
                id_flag=bool(item.get("ID", False)),
            )
        )
    return rules


def config_from_dict(raw: dict[str, Any]) -> PasteParseConfig | None:
    field_rules: dict[str, list[PasteParseRule]] = {}
    for key, value in raw.items():
        if key in RESERVED_TOP_KEYS:
            continue
        rules = _parse_rules(value)
        if rules:
            field_rules[str(key)] = rules
    if not field_rules:
        return None
    order = raw.get("order")
    if order is not None and not isinstance(order, list):
        order = None
    return PasteParseConfig(
        determiner=_normalize_determiner(str(raw.get("determiner", "tab"))),
        field_rules=field_rules,
        order=order,
    )


def load_paste_parse_config(template_id: str) -> PasteParseConfig | None:
    path = paste_config_path(template_id)
    if not path.exists():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    return config_from_dict(raw)


def save_paste_parse_yaml(template_id: str, yaml_text: str, template_headers: list[str] | None = None) -> None:
    if template_headers is not None:
        validate_mapping_yaml(yaml_text, template_headers)
    else:
        parsed = yaml.safe_load(yaml_text)
        if not isinstance(parsed, dict) or config_from_dict(parsed) is None:
            raise ValueError("YAML must contain at least one template field mapping")
    path = paste_config_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")


def config_to_yaml(config: dict[str, Any]) -> str:
    return yaml.dump(config, allow_unicode=True, sort_keys=False, default_flow_style=False)


def extract_yaml_text(model_output: str) -> str:
    text = model_output.strip()
    fenced = re.search(r"```(?:yaml)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    return text


def validate_mapping_yaml(yaml_text: str, template_headers: list[str]) -> dict[str, Any]:
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise ValueError("Model output is not a valid YAML object")
    config = config_from_dict(parsed)
    if config is None:
        raise ValueError("YAML must contain at least one template field mapping")
    allowed = {header.strip() for header in template_headers}
    for field_name in config.field_rules:
        if field_name.strip() not in allowed:
            raise ValueError(
                f"Unknown template field {field_name!r}; check that it exists in the template columns."
            )
    parsed.setdefault("determiner", config.determiner)
    return parsed


def id_target_field_from_config(config: PasteParseConfig | None) -> str | None:
    if config is None:
        return None
    for field_name, rules in config.field_rules.items():
        for rule in rules:
            if rule.id_flag:
                return field_name
    return None


def resolve_id_target_field(
    template_id: str,
    data_source_config: Any,
    headers: list[str],
) -> str | None:
    from app.services.data_source import id_target_field

    paste_config = load_paste_parse_config(template_id)
    paste_id = id_target_field_from_config(paste_config)
    header_by_stripped = {header.strip(): header for header in headers}
    if paste_id and paste_id.strip() in header_by_stripped:
        return header_by_stripped[paste_id.strip()]
    return id_target_field(data_source_config, headers)


def _safe_regex_search(pattern: str, raw: str) -> re.Match[str] | None:
    try:
        return re.search(pattern, raw)
    except re.error:
        pass
    if "(?<=" in pattern and r"\d{1,2}" in pattern:
        alt = re.sub(r"\(\?<=[^)]+\)", r"(?:\\d{1,2}/)", pattern, count=1)
        try:
            return re.search(alt, raw)
        except re.error:
            return None
    return None


def _extract_with_regex(raw: str, pattern: str) -> str | None:
    match = _safe_regex_search(pattern, raw)
    if not match:
        return None
    if match.lastindex and match.lastindex >= 1:
        return match.group(1).strip()
    return match.group(0).strip()


def _format_field_value(field_name: str, value: str) -> str:
    stripped_name = field_name.strip()
    if stripped_name in {"MM", "DD"} and value.isdigit():
        return value.zfill(2)
    if stripped_name == "Receiving Date" and "/" in value:
        parts = value.split("/", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}"
    return value


def _apply_field_rule(parts: list[str], rule: PasteParseRule) -> str | None:
    if rule.index < 0 or rule.index >= len(parts):
        return None
    raw = parts[rule.index].strip()
    if not raw:
        return None
    if rule.regex:
        extracted = _extract_with_regex(raw, rule.regex)
        if not extracted:
            return None
        return extracted
    return raw


def parse_line_with_config(
    line: str,
    config: PasteParseConfig,
    order: int,
    reference_year: int | None = None,
) -> dict[str, str]:
    del reference_year  # retained for call-site compatibility
    parts = _split_line(line, config.determiner)
    if not parts:
        raise ValueError("Empty line cannot be parsed")
    parsed: dict[str, str] = {"order": str(order)}
    for field_name, rules in config.field_rules.items():
        for rule in rules:
            value = _apply_field_rule(parts, rule)
            if value is None:
                continue
            parsed[field_name] = _format_field_value(field_name, value)
            break
    return parsed


def parse_text_with_config(
    text: str,
    config: PasteParseConfig,
    reference_year: int | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    order = 1
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(parse_line_with_config(line, config, order, reference_year))
        order += 1
    return rows
