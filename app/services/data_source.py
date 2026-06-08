import json
from dataclasses import asdict, dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_CONFIG_PATH = PROJECT_ROOT / "config" / "templates.json"
DEFAULT_ID_COLUMN = "PO"


@dataclass
class DataSourceConfig:
    sheet_url: str
    spreadsheet_id: str
    worksheet_name: str
    id_column: str = DEFAULT_ID_COLUMN


def _load_templates_config() -> dict:
    # 读取模板注册表 JSON
    if not TEMPLATES_CONFIG_PATH.exists():
        return {"templates": []}
    return json.loads(TEMPLATES_CONFIG_PATH.read_text(encoding="utf-8"))



def _write_templates_config(payload: dict) -> None:
    # 写回模板注册表 JSON
    TEMPLATES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATES_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")



def _find_template_entry(payload: dict, template_id: str) -> dict | None:
    # 查找模板条目
    for entry in payload.get("templates", []):
        if entry.get("id") == template_id:
            return entry
    return None



def load_template_data_source(template_id: str) -> DataSourceConfig | None:
    # 从 templates.json 加载指定模板的数据源配置
    payload = _load_templates_config()
    entry = _find_template_entry(payload, template_id)
    if not entry:
        return None
    raw = entry.get("data_source") or {}
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
    payload = _load_templates_config()
    entry = _find_template_entry(payload, template_id)
    if not entry:
        raise ValueError(f"模板 {template_id!r} 不存在")
    entry["data_source"] = asdict(config)
    _write_templates_config(payload)



def clear_template_data_source(template_id: str) -> None:
    # 清除指定模板的数据源配置
    payload = _load_templates_config()
    entry = _find_template_entry(payload, template_id)
    if not entry:
        return
    entry.pop("data_source", None)
    _write_templates_config(payload)
