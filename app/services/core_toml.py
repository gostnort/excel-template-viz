from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit import aot, document, string, table
import tomlkit.exceptions

from app.services.core_registry import TEMPLATES_DIR


CORE_CONFIG_SUFFIX = ".toml"
DEFAULT_DETERMINER = "\t"
DEFAULT_SOURCES: list[dict[str, str | None]] = [{"source1": None}]
FIELD_LABEL_KEY = "Input_label"
OPTIONAL_FIELD_KEYS = ("field", "source_file", "source_sheet", "regex")


def _core_toml_path(template_id: str) -> Path:
    """
    函数名: _core_toml_path
    作用: 根据模板ID获取其TOML配置文件的磁盘绝对路径
    输入: 
        template_id (str) - 模板的唯一标识ID
    输出: 
        Path - TOML配置文件的Path对象
    """
    return TEMPLATES_DIR / template_id / f"{template_id}{CORE_CONFIG_SUFFIX}"


def _is_unmapped(value: str | None) -> bool:
    """
    函数名: _is_unmapped
    作用: 判断值是否未映射（为None或空字符串）
    输入: 
        value (str | None) - 待校验的字符串值
    输出: 
        bool - 若未映射返回True，否则返回False
    """
    return value is None or value == ""


def _needs_literal_string(key: str, value: str) -> bool:
    """
    函数名: _needs_literal_string
    作用: 判断给定的键值对是否需要使用TOML字面量字符串（单引号形式，防止转义）
    输入: 
        key (str) - 字段键名
        value (str) - 字段字符串值
    输出: 
        bool - 若需要字面量格式返回True，否则返回False
    """
    if "'" in value:
        return False
    if key == "regex":
        return True
    if "\\" in value:
        return True
    return False


def _extract_toml_text(model_output: str) -> str:
    """
    函数名: _extract_toml_text
    作用: 从模型输出文本中提取纯TOML配置段（过滤Markdown代码块标记）
    输入: 
        model_output (str) - 大模型原始输出的文本内容
    输出: 
        str - 提取清洗后的纯TOML文本
    """
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
    """
    函数名: _parse_sources
    作用: 解析并清洗原始sources列表，转换空映射为None，保证数据结构规范
    输入: 
        raw_sources (Any) - 原始读入的sources字段数据
    输出: 
        list[dict[str, str | None]] - 规范化后的数据源列表
    """
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
    """
    函数名: _dict_to_toml
    作用: 将配置字典转换并序列化为严格符合TOML 1.0规范的文本字符串
    输入: 
        config (dict[str, Any]) - 包含各项配置信息的Python字典
    输出: 
        str - 格式化后的TOML文本
    """
    # ==================== 1. 初始化 TOML 文档与基础字段 ====================
    doc = document()
    doc["determiner"] = str(config.get("determiner", DEFAULT_DETERMINER))
    worksheet = config.get("worksheet")
    if worksheet:
        doc["worksheet"] = str(worksheet)
    # ==================== 2. 处理 sources (数据源) 配置 ====================
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
                    src[source_key] = ""
                else:
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
    # ==================== 3. 处理 sections (区域范围) 配置 ====================
    sections = config.get("sections")
    if isinstance(sections, list) and sections:
        sections_aot = aot()
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            sec_row = table()
            has_sec_key = False
            input_area = sec.get("input_area")
            if input_area is not None:
                sec_row["input_area"] = str(input_area)
                has_sec_key = True
            move_to = sec.get("move_to")
            if move_to is not None:
                sec_row["move_to"] = str(move_to)
                has_sec_key = True
            offset_val = sec.get("offset")
            if offset_val is not None:
                try:
                    sec_row["offset"] = int(offset_val)
                    has_sec_key = True
                except (ValueError, TypeError):
                    pass
            if has_sec_key:
                sections_aot.append(sec_row)
        if len(sections_aot) > 0:
            doc["sections"] = sections_aot
    # ==================== 4. 处理 fields (字段映射规则) 配置 ====================
    fields = config.get("fields")
    if isinstance(fields, list) and fields:
        fields_aot = aot()
        for item in fields:
            rule = _field_from_dict(item) if isinstance(item, dict) else item
            if not isinstance(rule, TomlDefault):
                continue
            row = table()
            row[FIELD_LABEL_KEY] = rule.Input_label
            rule_dict = rule.to_dict()
            for key in OPTIONAL_FIELD_KEYS:
                val = rule_dict.get(key)
                if _is_unmapped(val):
                    row[key] = ""
                else:
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
    # ==================== 5. 序列化并返回 TOML 字符串 ====================
    dumped = tomlkit.dumps(doc)
    if not dumped.endswith("\n"):
        dumped += "\n"
    return dumped



def _parse_bool(value: Any) -> bool:
    """
    函数名: _parse_bool
    作用: 安全地将输入值解析转换为布尔值，支持文本"true"/"false"等转换
    输入: 
        value (Any) - 待转换的值
    输出: 
        bool - 解析后的布尔结果
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _field_from_dict(raw: Any) -> TomlDefault | None:
    """
    函数名: _field_from_dict
    作用: 从原始字典数据中解析并构造一个TomlDefault实例
    输入: 
        raw (Any) - 原始输入的字段映射字典
    输出: 
        TomlDefault | None - 若解析成功返回TomlDefault实例，否则返回None
    """
    if not isinstance(raw, dict):
        return None
    if FIELD_LABEL_KEY not in raw or "index" not in raw:
        return None
    input_label = str(raw.get(FIELD_LABEL_KEY, "")).strip()
    if not input_label:
        return None
    try:
        index_val = int(raw["index"])
    except (ValueError, TypeError):
        return None
    field_raw = raw.get("field", raw.get("filed"))
    field = None if _is_unmapped(field_raw) else str(field_raw).strip()
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
    return TomlDefault(
        Input_label=input_label,
        field=field,
        source_file=source_file,
        source_sheet=source_sheet,
        index=index_val,
        regex=regex,
        id=_parse_bool(raw.get("id", False)),
    )


def _config_from_dict(raw: dict[str, Any]) -> GetTomlValues | None:
    """
    函数名: _config_from_dict
    作用: 从原始配置字典解析构造一个完整的GetTomlValues对象
    输入: 
        raw (dict[str, Any]) - 原始解析出的TOML字典
    输出: 
        GetTomlValues | None - 成功返回新实例，失败返回None
    """
    field_rules: list[TomlDefault] = []
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
    if isinstance(sections, list):
        parsed_sections: list[dict[str, Any]] = []
        for item in sections:
            if isinstance(item, dict):
                sec_item: dict[str, Any] = {}
                for k, v in item.items():
                    if v is not None:
                        sec_item[str(k)] = v
                if sec_item:
                    parsed_sections.append(sec_item)
        sections = parsed_sections if parsed_sections else None
    else:
        sections = None
    return GetTomlValues(
        determiner=determiner,
        sources=sources,
        field_rules=field_rules,
        worksheet=worksheet,
        sections=sections,
    )



@dataclass
class TomlDefault:
    """
    One [[fields]] row. Index is ZERO base.
    """

    Input_label: str
    field: str | None = None
    source_file: str | None = None
    source_sheet: str | None = None
    index: int = -1
    regex: str | None = None
    id: bool = False


    def to_dict(self) -> dict[str, Any]:
        """
        函数名: to_dict
        作用: 将当前字段规则对象转换成可序列化的Python字典，兼顾字段名兼容
        输入: 
            无
        输出: 
            dict[str, Any] - 序列化后的字典形式数据
        """
        return {
            FIELD_LABEL_KEY: self.Input_label,
            "field": self.field if not _is_unmapped(self.field) else None,
            "filed": self.field if not _is_unmapped(self.field) else None,
            "source_file": self.source_file if not _is_unmapped(self.source_file) else None,
            "source_sheet": self.source_sheet if not _is_unmapped(self.source_sheet) else None,
            "index": self.index,
            "regex": self.regex if not _is_unmapped(self.regex) else None,
            "id": self.id,
        }



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
        """
        函数名: _read_template_headers
        作用: 解析Excel模板指定工作表及区域的首行作为表头列表
        输入: 
            template_path (Path) - Excel模板文件的磁盘路径
            worksheet_name (str | None) - 目标工作表名称，若为None则读取首张活跃表
            input_area (str) - 数据输入区域单元格范围（如"A2:G10"）
        输出: 
            list[str] - 剥离空列后的表头字符串列表
        """
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
            row_values = []
            for row in ws.iter_rows(
                min_row=header_row,
                max_row=header_row,
                min_col=coords.start_col,
                max_col=coords.end_col,
                values_only=True
            ):
                row_values = list(row)
                break
            headers: list[str] = []
            for val in row_values:
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
        """
        函数名: _generate_field_mappings_from_template
        作用: 提取首个区域所处范围的表头并自动构造初始的空白字段映射列表
        输入: 
            template_path (Path) - Excel模板磁盘路径
            worksheet_name (str | None) - 目标工作表名称
            sections (list[dict[str, Any]] | None) - 区域参数列表
        输出: 
            list[dict[str, Any]] - 生成的空白字段映射字典列表
        """
        if not sections:
            return []
        first_area = sections[0].get("input_area")
        if not first_area:
            return []
        headers = self._read_template_headers(template_path, worksheet_name, first_area)
        fields: list[dict[str, Any]] = []
        for idx, header in enumerate(headers):
            fields.append(
                TomlDefault(
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
        输入: 
            template_path (Path) - Excel模板路径
            worksheet_name (str | None) - 工作表名称
            sections (list[dict[str, Any]] | None) - 区域配置列表
        输出: 
            dict[str, Any] - 自动生成的初始默认TOML配置字典
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
        输入: 
            config (dict[str, Any]) - 欲序列化的配置源字典
        输出: 
            str - 序列化得到的严格TOML 1.0文本
        """
        return _dict_to_toml(config)


    def Reset(self, template_id: str, template_path: Path) -> bool:
        """
        函数名: Reset
        作用: 重置指定模板的 TOML 配置为默认空映射。
        输入: 
            template_id (str) - 待重置的模板ID
            template_path (Path) - Excel模板文件路径
        输出: 
            bool - 重置成功返回True，否则返回False
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
        field_rules: list[TomlDefault],
        worksheet: str | None = None,
        sections: list[dict[str, Any]] | None = None,
    ) -> None:
        """
        函数名: __init__
        作用: 构造并初始化GetTomlValues配置对象实例
        输入: 
            determiner (str) - 字段值分界符
            sources (list[dict[str, str | None]]) - 关联外部文件源列表
            field_rules (list[TomlDefault]) - 单列字段校验及映射规则列表
            worksheet (str | None) - 目标工作表名称
            sections (list[dict[str, Any]] | None) - 输入模板多区域位置参数
        输出: 
            无
        """
        self.determiner = determiner
        self.sources = sources
        self.field_rules = field_rules
        self.worksheet = worksheet
        self.sections = sections


    @classmethod
    def Load(cls, template_id: str) -> GetTomlValues | None:
        """
        函数名: Load
        作用: 从磁盘加载 TOML 并返回新实例。
        输入: 
            template_id (str) - 待读取的模板唯一识别码
        输出: 
            GetTomlValues | None - 成功返回解析后的实例，否则返回None
        """
        path = _core_toml_path(template_id)
        if not path.exists():
            return None
        try:
            raw = tomlkit.loads(path.read_text(encoding="utf-8"))
        except tomlkit.exceptions.ParseError:
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
        输入: 
            template_id (str) - 模板ID
            toml_text (str | None) - 手工修改或LLM生成的TOML内容文本，若为None则保存内存中当前配置
            template_headers (list[str] | None) - 字段表头白名单列表，用于校验传入文本合法性
        输出: 
            无
        """
        if toml_text is None:
            cleaned = TomlGenerator().ConfigToToml(self.ToDict())
        else:
            cleaned = _extract_toml_text(toml_text)
            if template_headers is not None:
                parsed = self.Validate(cleaned, template_headers)
                cleaned = TomlGenerator().ConfigToToml(parsed)
            else:
                try:
                    parsed = tomlkit.loads(cleaned)
                except tomlkit.exceptions.ParseError as exc:
                    raise ValueError(f"Invalid TOML: {exc}") from exc
                if not isinstance(parsed, dict) or _config_from_dict(parsed) is None:
                    raise ValueError("TOML must contain at least one field mapping")
                cleaned = TomlGenerator().ConfigToToml(parsed)
        path = _core_toml_path(template_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cleaned, encoding="utf-8")


    @classmethod
    def Validate(cls, toml_text: str, template_headers: list[str]) -> dict[str, Any]:
        """
        函数名: Validate
        作用: 解析并校验 TOML 文本，返回配置字典。
        输入: 
            toml_text (str) - TOML配置的原文文本
            template_headers (list[str]) - 模板中允许存在的合法表头名称白名单
        输出: 
            dict[str, Any] - 校验通过的结构化配置字典
        """
        normalized = _extract_toml_text(toml_text)
        try:
            parsed = tomlkit.loads(normalized)
        except tomlkit.exceptions.ParseError as exc:
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


    @classmethod
    def EnsureExists(cls, template_id: str, template_path: Path) -> bool:
        """
        函数名: EnsureExists
        作用: 配置文件不存在时生成默认 TOML。
        输入: 
            template_id (str) - 模板的唯一ID
            template_path (Path) - 校验时用到的Excel模板磁盘路径
        输出: 
            bool - 若存在或重置成功返回True，否则返回False
        """
        path = _core_toml_path(template_id)
        if path.exists():
            return True
        return TomlGenerator().Reset(template_id, template_path)


    def ToDict(self) -> dict[str, Any]:
        """
        函数名: ToDict
        作用: 转为可序列化的配置字典。
        输入: 
            无
        输出: 
            dict[str, Any] - 配置的可序列化内存字典结构
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
