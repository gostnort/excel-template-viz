"""LMS 用户配置：api_url、token、当前模型名与历史。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit


PLATFORM_ROOT = Path(__file__).resolve().parent
USER_TOML = PLATFORM_ROOT / "user.toml"
EXAMPLE_TOML = PLATFORM_ROOT / "user.toml.example"
DEFAULT_API_URL = "http://127.0.0.1:9999"


def _empty_data() -> dict[str, Any]:
    """返回默认配置字典"""
    return {
        "api_url": DEFAULT_API_URL,
        "api_token": "",
        "model": "",
        "model_history": [],
    }


def load_user_config() -> dict[str, Any]:
    """读取 user.toml；缺失时回退 example 或内置默认"""
    path = USER_TOML if USER_TOML.is_file() else EXAMPLE_TOML
    data = _empty_data()
    if path.is_file():
        try:
            parsed = tomlkit.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data.update(dict(parsed))
        except Exception:
            pass
    url = str(data.get("api_url") or DEFAULT_API_URL).strip().rstrip("/")
    token = str(data.get("api_token") or "").strip()
    model = str(data.get("model") or "").strip()
    history_raw = data.get("model_history") or []
    history: list[str] = []
    if isinstance(history_raw, list):
        for item in history_raw:
            text = str(item or "").strip()
            if text and text not in history:
                history.append(text)
    return {
        "api_url": url or DEFAULT_API_URL,
        "api_token": token,
        "model": model,
        "model_history": history,
    }


def save_user_config(
    *,
    api_url: str | None = None,
    api_token: str | None = None,
    model: str | None = None,
    remember_model: bool = True,
) -> dict[str, Any]:
    """合并并写回 user.toml；可选把模型名追加进 history"""
    current = load_user_config()
    if api_url is not None:
        current["api_url"] = str(api_url).strip().rstrip("/") or DEFAULT_API_URL
    if api_token is not None:
        current["api_token"] = str(api_token).strip()
    if model is not None:
        current["model"] = str(model).strip()
    name = str(current.get("model") or "").strip()
    history = list(current.get("model_history") or [])
    if remember_model and name:
        history = [item for item in history if item != name]
        history.insert(0, name)
    current["model_history"] = history

    doc = tomlkit.document()
    doc["api_url"] = current["api_url"]
    doc["api_token"] = current["api_token"]
    doc["model"] = current["model"]
    doc["model_history"] = current["model_history"]
    USER_TOML.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return current
