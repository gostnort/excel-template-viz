from dataclasses import asdict, dataclass

from app.services.registry import load_template_payload, load_templates, save_template_payload

DEFAULT_ID_COLUMN = "PO"


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
    )


def save_template_data_source(template_id: str, config: DataSourceConfig) -> None:
    # 保存指定模板的数据源配置
    payload = load_template_payload(template_id)
    if payload is None:
        raise ValueError(f"模板 {template_id!r} 不存在")
    payload["data_source"] = asdict(config)
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
