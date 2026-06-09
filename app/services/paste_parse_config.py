import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.services.registry import TEMPLATES_DIR
from app.services.source_parser import parse_md_date

PASTE_CONFIG_SUFFIX = ".paste.yaml"


@dataclass
class PasteParseConfig:
    delimiter: str
    index_base: int
    fields: list[dict[str, Any]]


def paste_config_path(template_id: str) -> Path:
    return TEMPLATES_DIR / f"{template_id}{PASTE_CONFIG_SUFFIX}"


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
    fields = raw.get("fields")
    if not isinstance(fields, list) or not fields:
        return None
    delimiter = str(raw.get("delimiter", "tab")).strip().lower()
    index_base = int(raw.get("index_base", 1))
    return PasteParseConfig(delimiter=delimiter, index_base=index_base, fields=fields)


def save_paste_parse_yaml(template_id: str, yaml_text: str) -> None:
    path = paste_config_path(template_id)
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict) or not parsed.get("fields"):
        raise ValueError("YAML 必须包含非空的 fields 列表")
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
        raise ValueError("模型输出不是有效的 YAML 对象")
    fields = parsed.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("YAML 缺少 fields 列表")
    allowed = {header.strip() for header in template_headers}
    for rule in fields:
        if not isinstance(rule, dict):
            raise ValueError("fields 中存在非法项")
        if "target" in rule:
            target = str(rule["target"]).strip()
            if target not in allowed:
                raise ValueError("模板字段不存在，请检查 YAML 中的 target 是否在模板列中。")
        derive = rule.get("derive")
        if isinstance(derive, dict) and derive.get("target"):
            target = str(derive["target"]).strip()
            if target not in allowed:
                raise ValueError("模板字段不存在，请检查 YAML 中的 derive.target 是否在模板列中。")
        for sub in rule.get("fields", []):
            if isinstance(sub, dict) and sub.get("target"):
                target = str(sub["target"]).strip()
                if target not in allowed:
                    raise ValueError("模板字段不存在，请检查 YAML 中的子字段 target 是否在模板列中。")
    parsed.setdefault("delimiter", "tab")
    parsed.setdefault("index_base", 1)
    return parsed


def _split_line(line: str, delimiter: str) -> list[str]:
    if delimiter in {"tab", "\\t"}:
        return line.split("\t")
    return line.split(delimiter)


def _pick_part(parts: list[str], index: int, index_base: int) -> str:
    pos = index - index_base if index_base == 1 else index
    if pos < 0 or pos >= len(parts):
        raise ValueError(f"列索引 {index} 超出范围（共 {len(parts)} 列）")
    return parts[pos].strip()


def _resolve_field_index(field_rule: dict[str, Any], default_index_base: int) -> tuple[int, int] | None:
    raw_index = field_rule.get("field_index", field_rule.get("index"))
    if raw_index is None:
        return None
    index_base = int(field_rule.get("index_base", default_index_base))
    return int(raw_index), index_base


def _resolve_local_index(field_rule: dict[str, Any], default_index_base: int) -> tuple[int, int] | None:
    raw_index = field_rule.get("local_index", field_rule.get("index"))
    if raw_index is None:
        return None
    index_base = int(field_rule.get("local_index_base", field_rule.get("index_base", default_index_base)))
    return int(raw_index), index_base


def _apply_field_rules(
    parts: list[str],
    field_rule: dict[str, Any],
    parsed: dict[str, str],
    reference_year: int | None,
    default_index_base: int,
) -> None:
    field_index = _resolve_field_index(field_rule, default_index_base)
    if "target" in field_rule and field_index is not None:
        index, index_base = field_index
        target = str(field_rule["target"])
        value = _pick_part(parts, index, index_base)
        if field_rule.get("date") == "M/D":
            yy, mm, dd, receiving = parse_md_date(value, reference_year)
            parsed["YY"] = yy
            parsed["MM"] = mm
            parsed["DD"] = dd
            parsed[target] = receiving
        else:
            parsed[target] = value
        return
    if field_index is None:
        raise ValueError("字段规则缺少 field_index 或 target")
    index, index_base = field_index
    raw = _pick_part(parts, index, index_base)
    split_delim = str(field_rule.get("split", "/"))
    sub_parts = raw.split(split_delim)
    for sub_rule in field_rule.get("fields", []):
        if "target" not in sub_rule:
            continue
        local_index = _resolve_local_index(sub_rule, default_index_base)
        if local_index is None:
            continue
        sub_target = str(sub_rule["target"])
        sub_index, sub_base = local_index
        sub_pos = sub_index - sub_base if sub_base == 1 else sub_index
        if sub_pos < 0 or sub_pos >= len(sub_parts):
            continue
        value = sub_parts[sub_pos].strip()
        pad = sub_rule.get("pad")
        if pad:
            value = value.zfill(int(pad))
        parsed[sub_target] = value
    derive = field_rule.get("derive")
    if isinstance(derive, dict):
        target = str(derive.get("target", ""))
        from_fields = derive.get("from", [])
        if target and isinstance(from_fields, list) and len(from_fields) >= 2:
            mm = parsed.get(str(from_fields[0]), "")
            dd = parsed.get(str(from_fields[1]), "")
            yy = parsed.get("YY", "")
            if mm and dd and not yy:
                yy = str((reference_year or 2026) % 100).zfill(2)
                parsed["YY"] = yy
            if mm and dd:
                parsed[target] = f"{mm}/{dd}/{yy or '00'}"


def parse_line_with_config(
    line: str,
    config: PasteParseConfig,
    order: int,
    reference_year: int | None = None,
) -> dict[str, str]:
    parts = _split_line(line, config.delimiter)
    if not parts:
        raise ValueError("空行无法解析")
    parsed: dict[str, str] = {"order": str(order)}
    for field_rule in config.fields:
        _apply_field_rules(parts, field_rule, parsed, reference_year, config.index_base)
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
