import json
from dataclasses import dataclass
from os import environ
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "templates.json"


@dataclass(frozen=True)
class TemplateConfig:
    id: str
    display_name: str
    description: str
    file_path: Path
    sheet_name: str
    header_row: int
    data_start_row: int


def _resolve_file_path(entry: dict) -> Path:
    # 优先使用环境变量覆盖路径
    env_key = entry.get("file_path_env")
    if env_key:
        env_value = environ.get(env_key, "").strip()
        if env_value:
            return Path(env_value).expanduser()
    relative = entry.get("file_path", "")
    return (PROJECT_ROOT / relative).resolve()


def load_templates() -> list[TemplateConfig]:
    # 从 JSON 注册表加载全部模板配置
    if not CONFIG_PATH.exists():
        return []
    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    templates: list[TemplateConfig] = []
    for entry in raw.get("templates", []):
        templates.append(
            TemplateConfig(
                id=entry["id"],
                display_name=entry["display_name"],
                description=entry.get("description", ""),
                file_path=_resolve_file_path(entry),
                sheet_name=entry["sheet_name"],
                header_row=int(entry.get("header_row", 0)),
                data_start_row=int(entry.get("data_start_row", 1)),
            )
        )
    return templates


def get_template(template_id: str) -> TemplateConfig | None:
    # 按 id 查找单个模板
    for item in load_templates():
        if item.id == template_id:
            return item
    return None


def _read_registry() -> dict:
    # 读取模板注册表原始数据
    if not CONFIG_PATH.exists():
        return {"templates": []}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _write_registry(payload: dict) -> None:
    # 写回模板注册表
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def update_template_sheet_name(template_id: str, sheet_name: str) -> TemplateConfig | None:
    # 更新模板默认工作表并落盘
    payload = _read_registry()
    templates = payload.get("templates", [])
    updated = False
    for entry in templates:
        if entry.get("id") == template_id:
            entry["sheet_name"] = sheet_name
            updated = True
            break
    if not updated:
        return None
    payload["templates"] = templates
    _write_registry(payload)
    return get_template(template_id)
