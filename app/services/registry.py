import json
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
CONFIG_SUFFIXES = [".config.json", ".json"]
DEFAULT_SHEET_NAME = ""
DEFAULT_HEADER_ROW = 0
DEFAULT_DATA_START_ROW = 1


@dataclass(frozen=True)
class TemplateConfig:
    id: str
    display_name: str
    description: str
    file_path: Path
    sheet_name: str
    header_row: int
    data_start_row: int
    config_path: Path


def _derive_display_name(template_id: str) -> str:
    # 由文件名生成默认显示名称
    return template_id.replace("_", " ").replace("-", " ").title()


def _config_candidates(template_path: Path) -> list[Path]:
    # 生成配置文件候选路径
    return [template_path.with_suffix(suffix) for suffix in CONFIG_SUFFIXES]


def _find_existing_config_path(template_path: Path) -> Path | None:
    # 查找已存在的配置文件
    for candidate in _config_candidates(template_path):
        if candidate.exists():
            return candidate
    return None


def _default_config_path(template_path: Path) -> Path:
    # 默认使用 .config.json
    return template_path.with_suffix(CONFIG_SUFFIXES[0])


def _read_config_payload(config_path: Path) -> dict:
    # 读取配置文件原始数据
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_config_payload(config_path: Path, payload: dict) -> None:
    # 写回模板配置文件
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_default_payload(template_path: Path) -> dict:
    # 构建默认配置内容
    template_id = template_path.stem
    return {
        "display_name": _derive_display_name(template_id),
        "description": "",
        "sheet_name": DEFAULT_SHEET_NAME,
        "header_row": DEFAULT_HEADER_ROW,
        "data_start_row": DEFAULT_DATA_START_ROW,
    }


def _ensure_template_config(template_path: Path) -> tuple[Path, dict]:
    # 确保模板配置存在
    config_path = _find_existing_config_path(template_path)
    if config_path is None:
        config_path = _default_config_path(template_path)
        payload = _build_default_payload(template_path)
        _write_config_payload(config_path, payload)
        return config_path, payload
    payload = _read_config_payload(config_path)
    if not payload:
        payload = _build_default_payload(template_path)
        _write_config_payload(config_path, payload)
    return config_path, payload


def _template_path_from_id(template_id: str) -> Path | None:
    # 由模板 id 解析文件路径
    candidate = TEMPLATES_DIR / f"{template_id}.xlsx"
    if candidate.exists():
        return candidate
    return None


def _is_excel_lock_name(name: str) -> bool:
    # Excel 打开工作簿时会创建 ~$*.xlsx 临时锁文件
    return name.startswith("~")


def load_templates() -> list[TemplateConfig]:
    # 扫描 templates/ 下的全部 xlsx
    if not TEMPLATES_DIR.exists():
        return []
    templates: list[TemplateConfig] = []
    for template_path in sorted(TEMPLATES_DIR.glob("*.xlsx")):
        if _is_excel_lock_name(template_path.name):
            continue
        config_path, payload = _ensure_template_config(template_path)
        template_id = template_path.stem
        display_name = str(payload.get("display_name") or _derive_display_name(template_id))
        description = str(payload.get("description") or "")
        sheet_name = str(payload.get("sheet_name") or DEFAULT_SHEET_NAME)
        header_row = int(payload.get("header_row", DEFAULT_HEADER_ROW))
        data_start_row = int(payload.get("data_start_row", DEFAULT_DATA_START_ROW))
        templates.append(
            TemplateConfig(
                id=template_id,
                display_name=display_name,
                description=description,
                file_path=template_path,
                sheet_name=sheet_name,
                header_row=header_row,
                data_start_row=data_start_row,
                config_path=config_path,
            )
        )
    return templates


def get_template(template_id: str) -> TemplateConfig | None:
    # 按 id 查找单个模板
    for item in load_templates():
        if item.id == template_id:
            return item
    return None


def load_template_payload(template_id: str) -> dict | None:
    # 加载指定模板配置
    template_path = _template_path_from_id(template_id)
    if template_path is None:
        return None
    _, payload = _ensure_template_config(template_path)
    return payload


def save_template_payload(template_id: str, payload: dict) -> None:
    # 保存模板配置
    template_path = _template_path_from_id(template_id)
    if template_path is None:
        raise ValueError(f"模板 {template_id!r} 不存在")
    config_path, _ = _ensure_template_config(template_path)
    _write_config_payload(config_path, payload)


def update_template_sheet_name(template_id: str, sheet_name: str) -> TemplateConfig | None:
    # 更新模板默认工作表并落盘
    payload = load_template_payload(template_id)
    if payload is None:
        return None
    payload["sheet_name"] = sheet_name
    save_template_payload(template_id, payload)
    return get_template(template_id)
