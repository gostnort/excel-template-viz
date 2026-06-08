from dataclasses import asdict, dataclass, field

from app.services.registry import load_template_payload, load_templates, save_template_payload

DEFAULT_ID_COLUMN = "PO"

DEFAULT_COLUMN_MAPPINGS: list[dict[str, str]] = [
    {"source": "PO", "target": "P.O. No.", "kind": "sheet"},
    {"source": "Container#", "target": "Container No.", "kind": "sheet"},
    {"source": "recv. date", "target": "Receiving Date", "kind": "sheet"},
    {"source": "0", "target": "P.O. No.", "kind": "tab"},
    {"source": "4", "target": "Container No.", "kind": "tab"},
    {"source": "12", "target": "Receiving Date", "kind": "tab"},
]


@dataclass
class TemplateDataSourceEntry:
    template_id: str
    display_name: str
    data_source: "DataSourceConfig | None"


@dataclass
class DataSourceConfig:
    sheet_url: str
    spreadsheet_id: str
    worksheet_name: str
    id_column: str = DEFAULT_ID_COLUMN
    column_mappings: list[dict[str, str]] = field(default_factory=list)


def _normalize_mappings(raw_mappings: list | None) -> list[dict[str, str]]:
    if not raw_mappings:
        return [dict(item) for item in DEFAULT_COLUMN_MAPPINGS]
    normalized: list[dict[str, str]] = []
    for item in raw_mappings:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if not source or not target:
            continue
        kind = str(item.get("kind", "sheet")).strip() or "sheet"
        normalized.append({"source": source, "target": target, "kind": kind})
    return normalized or [dict(item) for item in DEFAULT_COLUMN_MAPPINGS]


def load_template_data_source(template_id: str) -> DataSourceConfig | None:
    # 从模板配置文件加载数据源配置
    payload = load_template_payload(template_id)
    if not payload:
        return None
    raw = payload.get("data_source") or {}
    if not raw.get("spreadsheet_id"):
        return None
    return DataSourceConfig(
        sheet_url=raw.get("sheet_url", ""),
        spreadsheet_id=raw["spreadsheet_id"],
        worksheet_name=raw.get("worksheet_name", ""),
        id_column=raw.get("id_column", DEFAULT_ID_COLUMN) or DEFAULT_ID_COLUMN,
        column_mappings=_normalize_mappings(raw.get("column_mappings")),
    )


def save_template_data_source(template_id: str, config: DataSourceConfig) -> None:
    # 保存指定模板的数据源配置
    payload = load_template_payload(template_id)
    if payload is None:
        raise ValueError(f"模板 {template_id!r} 不存在")
    payload["data_source"] = asdict(config)
    save_template_payload(template_id, payload)


def save_template_id_column(template_id: str, id_column: str) -> None:
    # 仅更新已保存配置中的默认 ID 列
    payload = load_template_payload(template_id)
    if payload is None:
        raise ValueError(f"模板 {template_id!r} 不存在")
    raw = payload.get("data_source") or {}
    if not raw.get("spreadsheet_id"):
        raise ValueError("请先保存数据源配置后再设置默认 ID 列")
    raw["id_column"] = id_column.strip() or DEFAULT_ID_COLUMN
    payload["data_source"] = raw
    save_template_payload(template_id, payload)


def clear_template_data_source(template_id: str) -> None:
    # 清除指定模板的数据源配置
    payload = load_template_payload(template_id)
    if payload is None:
        return
    payload.pop("data_source", None)
    save_template_payload(template_id, payload)


def list_template_data_sources() -> list[TemplateDataSourceEntry]:
    # 汇总全部模板的数据源配置
    entries: list[TemplateDataSourceEntry] = []
    for template in load_templates():
        entries.append(
            TemplateDataSourceEntry(
                template_id=template.id,
                display_name=template.display_name,
                data_source=load_template_data_source(template.id),
            )
        )
    return entries


def sheet_mappings(config: DataSourceConfig | None) -> list[dict[str, str]]:
    if config is None:
        return [item for item in DEFAULT_COLUMN_MAPPINGS if item["kind"] == "sheet"]
    return [item for item in config.column_mappings if item.get("kind", "sheet") == "sheet"]


def tab_mappings(config: DataSourceConfig | None) -> list[dict[str, str]]:
    if config is None:
        return [item for item in DEFAULT_COLUMN_MAPPINGS if item["kind"] == "tab"]
    return [item for item in config.column_mappings if item.get("kind") == "tab"]


def id_target_field(config: DataSourceConfig | None, headers: list[str]) -> str | None:
    # 根据 ID 列映射找到模板中对应的输入字段名
    if config is None or not config.id_column:
        return None
    header_by_stripped = {header.strip(): header for header in headers}
    for item in sheet_mappings(config):
        if item["source"] == config.id_column:
            target = item["target"].strip()
            return header_by_stripped.get(target, item["target"])
    if "P.O. No." in header_by_stripped:
        return header_by_stripped["P.O. No."]
    return None
