from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import aot, document, string, table

from app.services.core_registry import TEMPLATES_DIR


CORE_CONFIG_SUFFIX = ".toml"
DEFAULT_DETERMINER = "\t"
DEFAULT_SOURCES: list[dict[str, str | None]] = [{"source1": None}]
FIELD_LABEL_KEY = "Input_label"
OPTIONAL_FIELD_KEYS = ("filed", "source_file", "source_sheet", "regex")


def _core_toml_path(template_id: str) -> Path:
    return TEMPLATES_DIR / template_id / f"{template_id}{CORE_CONFIG_SUFFIX}"


def _is_unmapped(value: str | None) -> bool:
    return value is None or value == ""


def _needs_literal_string(key: str, value: str) -> bool:
    if key == "regex":
        return True
    if "\\" in value:
        return True
    return False


def _extract_toml_text(model_output: str) -> str:
    text = model_output.strip()
    if not text:
        return text
    fenced = re.search(
        r"```(?:toml)?\s*\r?\n?(.*?)```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if fenced:
        return fenced.group(1).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:toml)?\s*\r?\n?", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"```\s*$", "", text.strip())
    return text.strip()


def _parse_sources(raw_sources: Any) -> list[dict[str, str | None]]:
    if not isinstance(raw_sources, list) or not raw_sources:
        return [dict(item) for item in DEFAULT_SOURCES]
    sources: list[dict[str, str | None]] = []
    for item in raw_sources:
        if not isinstance(item, dict):
            continue
        parsed_item: dict[str, str | None] = {}
        for key, value in item.items():
            if _is_unmapped(value):
                parsed_item[str(key)] = None
            else:
                parsed_item[str(key)] = str(value)
        if parsed_item:
            sources.append(parsed_item)
    if not sources:
        return [dict(item) for item in DEFAULT_SOURCES]
    return sources


def _dict_to_toml(config: dict[str, Any]) -> str:
    doc = document()
    doc["determiner"] = str(config.get("determiner", DEFAULT_DETERMINER))
    worksheet = config.get("worksheet")
    if worksheet:
        doc["worksheet"] = str(worksheet)
    sources = config.get("sources")
    if isinstance(sources, list) and sources:
        sources_aot = aot()
        for item in sources:
            if not isinstance(item, dict):
                continue
            src = table()
            has_key = False
            for source_key, source_value in item.items():
                if _is_unmapped(source_value):
                    continue
                text = str(source_value)
                src[source_key] = (
                    string(text, literal=True)
                    if _needs_literal_string(str(source_key), text)
                    else text
                )
                has_key = True
            if has_key:
                sources_aot.append(src)
        if len(sources_aot) > 0:
            doc["sources"] = sources_aot
    sections = config.get("sections")
    if isinstance(sections, list) and sections:
        sections_aot = aot()
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_row = table()
            input_area = sec.get("input_area")
            if input_area is not None:
                sec_row["input_area"] = str(input_area)
            move_to = sec.get("move_to")
            if move_to is not None:
                sec_row["move_to"] = str(move_to)
            if "offset" in sec:
                sec_row["offset"] = int(sec.get("offset", 0))
            sections_aot.append(sec_row)
        if len(sections_aot) > 0:
            doc["sections"] = sections_aot
    fields = config.get("fields")
    if isinstance(fields, list) and fields:
        fields_aot = aot()
        for item in fields:
            rule = _field_from_dict(item) if isinstance(item, dict) else item
            if not isinstance(rule, TomalDefault):
                continue
            row = table()
            row[FIELD_LABEL_KEY] = rule.Input_label
            rule_dict = rule.to_dict()
            for key in OPTIONAL_FIELD_KEYS:
                val = rule_dict.get(key)
                if _is_unmapped(val):
                    continue
                text = str(val)
                row[key] = (
                    string(text, literal=True)
                    if _needs_literal_string(key, text)
                    else text
                )
            row["index"] = rule.index
            row["id"] = rule.id
            fields_aot.append(row)
        if len(fields_aot) > 0:
            doc["fields"] = fields_aot
    dumped = tomlkit.dumps(doc)
    if not dumped.endswith("\n"):
        dumped += "\n"
    return dumped


def _field_from_dict(raw: Any) -> TomalDefault | None:
    if not isinstance(raw, dict):
        return None
    if FIELD_LABEL_KEY not in raw or "index" not in raw:
        return None
    input_label = str(raw.get(FIELD_LABEL_KEY, "")).strip()
    if not input_label:
        return None
    filed_raw = raw.get("filed")
    filed = None if _is_unmapped(filed_raw) else str(filed_raw).strip()
    source_file_raw = raw.get("source_file")
    source_file = (
        None
        if _is_unmapped(source_file_raw)
        else str(source_file_raw).strip()
    )
    source_sheet_raw = raw.get("source_sheet")
    source_sheet = (
        None
        if _is_unmapped(source_sheet_raw)
        else str(source_sheet_raw).strip()
    )
    regex_raw = raw.get("regex")
    regex = None if _is_unmapped(regex_raw) else str(regex_raw).strip()
    return TomalDefault(
        Input_label=input_label,
        filed=filed,
        source_file=source_file,
        source_sheet=source_sheet,
        index=int(raw["index"]),
        regex=regex,
        id=bool(raw.get("id", False)),
    )


@dataclass
class TomalDefault:
    """
    One [[fields]] row. Index is ZERO base.
    """

    Input_label: str
    filed: str | None = None
    source_file: str | None = None
    source_sheet: str | None = None
    index: int = -1
    regex: str | None = None
    id: bool = False


    def to_dict(self) -> dict[str, Any]:
        return {
            FIELD_LABEL_KEY: self.Input_label,
            "filed": self.filed if not _is_unmapped(self.filed) else None,
            "source_file": self.source_file if not _is_unmapped(self.source_file) else None,
            "source_sheet": self.source_sheet if not _is_unmapped(self.source_sheet) else None,
            "index": self.index,
            "regex": self.regex if not _is_unmapped(self.regex) else None,
            "id": self.id,
        }


def _config_from_dict(raw: dict[str, Any]) -> GetTomlValues | None:
    field_rules: list[TomalDefault] = []
    fields_raw = raw.get("fields")
    if isinstance(fields_raw, list):
        for item in fields_raw:
            rule = _field_from_dict(item)
            if rule:
                field_rules.append(rule)
    if not field_rules:
        return None
    determiner = str(raw.get("determiner", DEFAULT_DETERMINER)).strip() or DEFAULT_DETERMINER
    worksheet = raw.get("worksheet")
    if worksheet is not None:
        worksheet = str(worksheet).strip() or None
    sources = _parse_sources(raw.get("sources"))
    sections = raw.get("sections")
    if sections is not None and not isinstance(sections, list):
        sections = None
    return GetTomlValues(
        determiner=determiner,
        sources=sources,
        field_rules=field_rules,
        worksheet=worksheet,
        sections=sections,
    )



class TomlGenerator:
    """
    First-time creation of empty TOML config and serialization only.
    """

    def _read_template_headers(
        self,
        template_path: Path,
        worksheet_name: str | None,
        input_area: str,
    ) -> list[str]:
        from openpyxl import load_workbook
        from app.services.section_detector import parse_area_range

        coords = parse_area_range(input_area)
        header_row = coords.start_row - 1 if coords.start_row > 1 else 1
        wb = load_workbook(template_path, read_only=True, data_only=True)
        try:
            if worksheet_name and worksheet_name in wb.sheetnames:
                ws = wb[worksheet_name]
            else:
                ws = wb.active
            if ws is None:
                return []
            headers: list[str] = []
            for col in range(coords.start_col, coords.end_col + 1):
                val = ws.cell(header_row, col).value
                if val is not None:
                    text = str(val).strip()
                    if text:
                        headers.append(text)
            while headers and headers[-1].startswith("col_"):
                headers.pop()
            seen: set[str] = set()
            unique: list[str] = []
            for header in headers:
                key = header.strip()
                if key and key not in seen:
                    seen.add(key)
                    unique.append(header)
            return unique
        finally:
            wb.close()


    def _generate_field_mappings_from_template(
        self,
        template_path: Path,
        worksheet_name: str | None,
        sections: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        if not sections:
            return []
        first_area = sections[0].get("input_area")
        if not first_area:
            return []
        headers = self._read_template_headers(template_path, worksheet_name, first_area)
        fields: list[dict[str, Any]] = []
        for idx, header in enumerate(headers):
            fields.append(
                TomalDefault(
                    Input_label=header,
                    index=idx,
                ).to_dict()
            )
        return fields


    def CreateDefaultFromTemplate(
        self,
        template_path: Path,
        worksheet_name: str | None = None,
        sections: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        函数名: CreateDefaultFromTemplate
        作用: 根据 Excel 模板自动生成默认 TOML 配置字典；sources 固定为默认值，由其他模块写入。
        """
        result: dict[str, Any] = {
            "determiner": DEFAULT_DETERMINER,
            "sources": [dict(item) for item in DEFAULT_SOURCES],
            "fields": self._generate_field_mappings_from_template(
                template_path, worksheet_name, sections
            ),
        }
        if worksheet_name:
            result["worksheet"] = worksheet_name
        if sections:
            result["sections"] = sections
        return result


    def ConfigToToml(self, config: dict[str, Any]) -> str:
        """
        函数名: ConfigToToml
        作用: 将配置字典序列化为严格 TOML 1.0 文本；未映射键省略。
        """
        return _dict_to_toml(config)


    def Reset(self, template_id: str, template_path: Path) -> bool:
        """
        函数名: Reset
        作用: 重置指定模板的 TOML 配置为默认空映射。
        """
        path = _core_toml_path(template_id)
        try:
            default_cfg = self.CreateDefaultFromTemplate(template_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.ConfigToToml(default_cfg), encoding="utf-8")
            return True
        except Exception:
            return False



class GetTomlValues:
    """
    Loaded TOML config: query, modify in memory, persist via Save / ToDict.
    """

    def __init__(
        self,
        determiner: str,
        sources: list[dict[str, str | None]],
        field_rules: list[TomalDefault],
        worksheet: str | None = None,
        sections: list[dict[str, Any]] | None = None,
    ) -> None:
        self.determiner = determiner
        self.sources = sources
        self.field_rules = field_rules
        self.worksheet = worksheet
        self.sections = sections


    def Load(self, template_id: str) -> GetTomlValues | None:
        """
        函数名: Load
        作用: 从磁盘加载 TOML 并返回新实例。
        """
        path = _core_toml_path(template_id)
        if not path.exists():
            return None
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            return None
        if not isinstance(raw, dict):
            return None
        return _config_from_dict(raw)


    def Save(
        self,
        template_id: str,
        toml_text: str | None = None,
        template_headers: list[str] | None = None,
    ) -> None:
        """
        函数名: Save
        作用: 将配置写入磁盘；无 toml_text 时保存当前实例（ToDict 后序列化）。
        """
        if toml_text is None:
            cleaned = TomlGenerator().ConfigToToml(self.ToDict())
        else:
            cleaned = _extract_toml_text(toml_text)
            if template_headers is not None:
                parsed = self.Validate(cleaned, template_headers)
                cleaned = TomlGenerator().ConfigToToml(parsed)
            else:
                parsed = tomllib.loads(cleaned)
                if not isinstance(parsed, dict) or _config_from_dict(parsed) is None:
                    raise ValueError("TOML must contain at least one field mapping")
                cleaned = TomlGenerator().ConfigToToml(parsed)
        path = _core_toml_path(template_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cleaned, encoding="utf-8")


    def Validate(self, toml_text: str, template_headers: list[str]) -> dict[str, Any]:
        """
        函数名: Validate
        作用: 解析并校验 TOML 文本，返回配置字典。
        """
        normalized = _extract_toml_text(toml_text)
        try:
            parsed = tomllib.loads(normalized)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"Invalid TOML: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Model output is not a valid TOML object")
        config = _config_from_dict(parsed)
        if config is None:
            raise ValueError("TOML must contain at least one field mapping")
        allowed = {header.strip() for header in template_headers}
        for rule in config.field_rules:
            if rule.Input_label.strip() not in allowed:
                raise ValueError(f"Unknown template field {rule.Input_label!r}")
        parsed.setdefault("determiner", config.determiner)
        return parsed


    def EnsureExists(self, template_id: str, template_path: Path) -> bool:
        """
        函数名: EnsureExists
        作用: 配置文件不存在时生成默认 TOML。
        """
        path = _core_toml_path(template_id)
        if path.exists():
            return True
        return TomlGenerator().Reset(template_id, template_path)


    def ToDict(self) -> dict[str, Any]:
        """
        函数名: ToDict
        作用: 转为可序列化的配置字典。
        """
        result: dict[str, Any] = {
            "determiner": self.determiner,
            "sources": [dict(item) for item in self.sources],
            "fields": [rule.to_dict() for rule in self.field_rules],
        }
        if self.worksheet:
            result["worksheet"] = self.worksheet
        if self.sections:
            result["sections"] = [dict(item) for item in self.sections]
        return result
