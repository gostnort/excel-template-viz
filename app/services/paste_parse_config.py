import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.services.registry import TEMPLATES_DIR

PASTE_CONFIG_SUFFIX = ".paste.yaml"
RESERVED_TOP_KEYS = frozenset({"determiner", "order", "worksheet", "sections"})


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
    worksheet: str | None = None
    sections: list[dict[str, Any]] | None = None  # Section configurations for multi-area detection
    
    def to_dict(self) -> dict[str, Any]:
        """
        Convert config to dict for field matching and other operations
        
        Returns:
            Dict representation of the config with field rules converted to dict format
        """
        result: dict[str, Any] = {}
        
        # Convert field_rules to dict format
        for field_name, rules in self.field_rules.items():
            result[field_name] = [
                {
                    "filed": rule.filed,
                    "index": rule.index,
                    "regex": rule.regex,
                    "ID": rule.id_flag
                }
                for rule in rules
            ]
        
        # Add optional fields if present
        if self.order:
            result["order"] = self.order
        if self.worksheet:
            result["worksheet"] = self.worksheet
        if self.sections:
            result["sections"] = self.sections
        
        result["determiner"] = self.determiner
        
        return result


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
    
    worksheet = raw.get("worksheet")
    if worksheet is not None:
        worksheet = str(worksheet).strip()
    
    # Parse sections configuration
    sections = raw.get("sections")
    if sections is not None and not isinstance(sections, list):
        sections = None
    
    return PasteParseConfig(
        determiner=_normalize_determiner(str(raw.get("determiner", "tab"))),
        field_rules=field_rules,
        order=order,
        worksheet=worksheet,
        sections=sections
    )


def load_paste_parse_config(template_id: str) -> PasteParseConfig | None:
    path = paste_config_path(template_id)
    if not path.exists():
        return None
    try:
        raw = _safe_load_mapping_yaml(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(raw, dict):
        return None
    try:
        raw = _normalize_field_rule_lists(raw)
    except ValueError:
        return None
    return config_from_dict(raw)


def save_paste_parse_yaml(template_id: str, yaml_text: str, template_headers: list[str] | None = None) -> None:
    cleaned = extract_yaml_text(yaml_text)
    if template_headers is not None:
        config = validate_mapping_yaml(cleaned, template_headers)
        cleaned = config_to_yaml(config)
    else:
        parsed = _safe_load_mapping_yaml(cleaned)
        if not isinstance(parsed, dict) or config_from_dict(parsed) is None:
            raise ValueError("YAML must contain at least one template field mapping")
        cleaned = config_to_yaml(parsed)
    path = paste_config_path(template_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned, encoding="utf-8")


_RULE_KEY_ORDER = ("ID", "filed", "index", "regex")


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if "regex" in value or "\\" in value or "(" in value:
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if value in {"", "?", "tab"} or " " in value or "#" in value or "." in value:
            return f'"{value}"'
        return f'"{value}"'
    return f'"{value}"'


def _format_rule_lines(rule: dict[str, Any], indent: int) -> list[str]:
    if not isinstance(rule, dict):
        return []
    keys = [key for key in _RULE_KEY_ORDER if key in rule]
    keys.extend(key for key in rule if key not in keys)
    lines: list[str] = []
    for idx, key in enumerate(keys):
        if idx == 0:
            lines.append(f"{' ' * indent}- {key}: {_yaml_scalar(rule[key])}")
        else:
            lines.append(f"{' ' * (indent + 2)}{key}: {_yaml_scalar(rule[key])}")
    return lines


def _normalize_field_rule_lists(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    for key, value in raw.items():
        if key in RESERVED_TOP_KEYS:
            if key == "order" and value is not None and not isinstance(value, list):
                raise ValueError(f"'{key}' must be a YAML list; each entry must start with '-'")
            continue
        if isinstance(value, dict):
            normalized[key] = [value]
            continue
        if not isinstance(value, list):
            raise ValueError(
                f"Field {key!r} must be a YAML list. Put '-' before each rule, e.g.\n"
                f"{key}:\n  - filed: \"?\"\n    index: -1"
            )
        for item in value:
            if not isinstance(item, dict):
                raise ValueError(f"Field {key!r}: each '-' item must be a mapping with filed/index")
    return normalized


def config_to_yaml(config: dict[str, Any]) -> str:
    config = _normalize_field_rule_lists(config)
    lines: list[str] = [f'determiner: {_yaml_scalar(str(config.get("determiner", "tab")))}']
    worksheet = config.get("worksheet")
    if worksheet is not None:
        lines.append(f'worksheet: {_yaml_scalar(str(worksheet))}')
    order = config.get("order")
    if isinstance(order, list) and order:
        lines.append("order:")
        for item in order:
            lines.extend(_format_rule_lines(item, indent=2))
    
    # Handle sections configuration
    sections = config.get("sections")
    if isinstance(sections, list) and sections:
        lines.append("sections:")
        for section in sections:
            if isinstance(section, dict):
                lines.append("  - input_area: " + _yaml_scalar(str(section.get("input_area", ""))))
                lines.append("    move_to: " + _yaml_scalar(str(section.get("move_to", ""))))
                lines.append("    offset: " + str(section.get("offset", 0)))
    
    for key, value in config.items():
        if key in RESERVED_TOP_KEYS or key == "determiner":
            continue
        if not isinstance(value, list):
            continue
        lines.append(str(key) + ":")
        for rule in value:
            if isinstance(rule, dict):
                lines.extend(_format_rule_lines(rule, indent=2))
    return "\n".join(lines) + "\n"


def build_empty_mapping_yaml(template_headers: list[str]) -> str:
    skip_fields = frozenset({"order"})
    config: dict[str, Any] = {"determiner": "tab"}
    for header in template_headers:
        if header.strip() in skip_fields:
            continue
        rule: dict[str, Any] = {"filed": "?", "index": -1}
        if header.strip() == "P.O. No.":
            rule["ID"] = True
        config[header] = [rule]
    return config_to_yaml(config)


_REGEX_DOUBLE_QUOTED = re.compile(r'^(\s*regex:\s*)"(.*)"\s*$')


def _normalize_yaml_regex_quotes(yaml_text: str) -> str:
    # YAML double-quoted scalars treat \d as invalid escapes; regex must use single quotes.
    lines: list[str] = []
    for line in yaml_text.splitlines():
        match = _REGEX_DOUBLE_QUOTED.match(line)
        if not match:
            lines.append(line)
            continue
        prefix, inner = match.group(1), match.group(2)
        inner = inner.replace("\\\\", "\\")
        escaped = inner.replace("'", "''")
        lines.append(f"{prefix}'{escaped}'")
    return "\n".join(lines)


def _safe_load_mapping_yaml(yaml_text: str) -> Any:
    normalized = _normalize_yaml_regex_quotes(yaml_text)
    return yaml.safe_load(normalized)


def extract_yaml_text(model_output: str) -> str:
    text = model_output.strip()
    if not text:
        return text

    fenced = re.search(
        r"```(?:yaml|yml)?\s*\r?\n?(.*?)```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        return fenced.group(1).strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:yaml|yml)?\s*\r?\n?", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"```\s*$", "", text.strip())

    return text.strip()


def validate_mapping_yaml(yaml_text: str, template_headers: list[str]) -> dict[str, Any]:
    normalized = extract_yaml_text(yaml_text)
    try:
        parsed = _safe_load_mapping_yaml(normalized)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Model output is not a valid YAML object")
    parsed = _normalize_field_rule_lists(parsed)
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


def id_column_from_config(config: PasteParseConfig | None) -> str | None:
    if config is None:
        return None
    for field_name, rules in config.field_rules.items():
        for rule in rules:
            if rule.id_flag and rule.filed and rule.filed != "?":
                return rule.filed
    return None


def resolve_sheet_header(filed: str, sheet_headers: list[str]) -> str | None:
    if not filed or filed == "?":
        return None
    filed_stripped = filed.strip()
    for h in sheet_headers:
        if h == filed_stripped:
            return h
    filed_lower = filed_stripped.lower()
    for h in sheet_headers:
        if h.strip().lower() == filed_lower:
            return h
    return None


def map_sheet_row_from_paste_config(
    row: dict[str, str],
    config: PasteParseConfig,
) -> dict[str, str]:
    parsed: dict[str, str] = {}
    sheet_headers = list(row.keys())
    for field_name, rules in config.field_rules.items():
        for rule in rules:
            if not rule.filed or rule.filed == "?":
                continue
            resolved_header = resolve_sheet_header(rule.filed, sheet_headers)
            if resolved_header is None:
                continue
            raw_val = row.get(resolved_header, "")
            if raw_val is None:
                raw_val = ""
            raw_val = str(raw_val).strip()
            if not raw_val:
                continue
            if rule.regex:
                extracted = _extract_with_regex(raw_val, rule.regex)
                if extracted is None:
                    continue
                val = extracted
            else:
                val = raw_val
            parsed[field_name] = _format_field_value(field_name, val)
            break
    return parsed


def validate_yaml_against_sheet_headers(
    config: PasteParseConfig,
    sheet_headers: list[str],
) -> dict[str, Any]:
    matched: dict[str, str] = {}
    missing: list[str] = []
    id_filed = id_column_from_config(config)
    id_matched = True
    if id_filed:
        resolved_id_header = resolve_sheet_header(id_filed, sheet_headers)
        if not resolved_id_header:
            id_matched = False
    for field_name, rules in config.field_rules.items():
        for rule in rules:
            if not rule.filed or rule.filed == "?":
                continue
            resolved = resolve_sheet_header(rule.filed, sheet_headers)
            if resolved:
                matched[rule.filed] = resolved
            else:
                if rule.filed not in missing:
                    missing.append(rule.filed)
    return {
        "matched": matched,
        "missing": missing,
        "id_matched": id_matched,
    }


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


def create_default_config_from_template(template_path: Path, worksheet_name: str | None = None) -> PasteParseConfig:
    """
    Create default configuration from Excel template
    
    Reads the first row of the template as field names and creates a basic configuration
    with default field mappings and sections (if applicable).
    
    Args:
        template_path: Path to the Excel template file
        worksheet_name: Optional worksheet name (uses first sheet if None)
        
    Returns:
        PasteParseConfig with default settings
        
    Raises:
        ValueError: If template cannot be read or has no data
    """
    from openpyxl import load_workbook
    
    try:
        wb = load_workbook(template_path, read_only=True, data_only=True)
        
        # Select worksheet
        if worksheet_name and worksheet_name in wb.sheetnames:
            ws = wb[worksheet_name]
        else:
            ws = wb.active
        
        if ws is None:
            raise ValueError("No worksheet found in template")
        
        # Read first row as field names
        first_row = []
        last_col_with_data = 0
        
        for col_idx, cell in enumerate(ws[1], start=1):
            value = cell.value
            if value is not None and str(value).strip():
                first_row.append(str(value).strip())
                last_col_with_data = col_idx
            elif last_col_with_data > 0:
                # Keep empty columns between filled columns
                first_row.append("")
        
        if not first_row:
            raise ValueError("Template first row has no field names")
        
        # Remove trailing empty columns
        first_row = first_row[:last_col_with_data]
        
        # Create field rules (filed = field name itself)
        field_rules: dict[str, list[PasteParseRule]] = {}
        
        for field_name in first_row:
            if not field_name:  # Skip empty columns
                continue
            
            # Create simple rule: filed = field name
            rule = PasteParseRule(
                filed=field_name,
                index=0,  # Will be set dynamically
                regex=None,
                id_flag=False
            )
            
            field_rules[field_name] = [rule]
        
        # Create sections configuration if there are multiple columns
        sections = None
        if len(first_row) > 1:
            # Detect data area from row 2, column 1 to last column with data
            from openpyxl.utils import get_column_letter
            
            start_col = get_column_letter(1)
            end_col = get_column_letter(last_col_with_data)
            
            sections = [{
                "input_area": f"{start_col}2:{end_col}2",  # Second row as input area
                "move_to": "down",  # Move down by default
                "offset": 1  # Offset by 1 row
            }]
        
        wb.close()
        
        return PasteParseConfig(
            determiner="tab",
            field_rules=field_rules,
            order=None,
            worksheet=ws.title if ws.title else None,
            sections=sections
        )
        
    except Exception as e:
        raise ValueError(f"Failed to create default config from template: {e}") from e


def ensure_config_exists(template_id: str, template_path: Path) -> bool:
    """
    Ensure a configuration file exists for the template
    
    Creates a default configuration if none exists.
    
    Args:
        template_id: Template identifier
        template_path: Path to the Excel template file
        
    Returns:
        True if config exists or was created successfully
    """
    config_path = paste_config_path(template_id)
    
    # If config already exists, nothing to do
    if config_path.exists():
        return True
    
    try:
        # Create default config from template
        default_config = create_default_config_from_template(template_path)
        
        # Convert to YAML and save
        config_dict = default_config.to_dict()
        yaml_text = config_to_yaml(config_dict)
        
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Save config
        config_path.write_text(yaml_text, encoding='utf-8')
        
        return True
    except Exception as e:
        # Log error but don't fail
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to create default config for {template_id}: {e}")
        return False

