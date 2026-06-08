import json
import os
from dataclasses import dataclass
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
        env_value = os.environ.get(env_key, "").strip()
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
