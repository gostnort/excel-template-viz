"""从 sidecar TOML 预填向导 intake 数据。"""

from __future__ import annotations

from app.core_toml import load_toml


def sidecar_data_sources(template_id: str) -> list[dict[str, str]]:
    """
    函数名: sidecar_data_sources
    作用: 读取模板 sidecar TOML 的 [[sources]]，供向导跳过 ask_sources
    输入:
        template_id (str): 模板 ID
    输出:
        list[dict[str, str]]: 含 Google URL 或别名的数据源列表；无有效项时 []
    """
    cfg = load_toml(template_id)
    if cfg is None:
        return []
    result: list[dict[str, str]] = []
    for item in cfg.sources or []:
        if not isinstance(item, dict):
            continue
        entry: dict[str, str] = {}
        for key, value in item.items():
            text = str(value or "").strip()
            entry[str(key)] = text
            if not text:
                continue
            lower = text.lower()
            if text.startswith("http") and "docs.google.com" in lower:
                entry["type"] = "google_sheet"
        # [[sources]] 块存在即视为已配置（含 source1="" 的无 Google 模板）
        result.append(entry if entry else {"source1": ""})
    return result
