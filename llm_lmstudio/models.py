"""LM Studio 模型列表 / 详情 / 加载 / 卸载。"""

from __future__ import annotations

from typing import Any

from llm_lmstudio.client import request_json
from llm_lmstudio.config import load_user_config, save_user_config


LOAD_TIMEOUT = 300.0
QUERY_TIMEOUT = 20.0
_known_loaded: set[str] = set()
_catalog: list[dict[str, Any]] | None = None


def list_models(*, refresh: bool = False) -> list[dict[str, Any]]:
    """
    函数名: list_models
    作用: GET /api/v1/models；同进程内默认复用第一次列表
    输入:
        refresh (bool): True 时强制再问一次服务器
    输出:
        list[dict]: 模型条目（含 key / loaded_instances / capabilities）
    """
    global _catalog
    if _catalog is not None and not refresh:
        return _catalog
    payload = request_json("GET", "/api/v1/models", timeout=QUERY_TIMEOUT)
    items: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        models = payload.get("models")
        if isinstance(models, list):
            items = [item for item in models if isinstance(item, dict)]
    elif isinstance(payload, list):
        items = [item for item in payload if isinstance(item, dict)]
    _catalog = items
    return items


def remember_loaded(model_key: str) -> None:
    """
    函数名: remember_loaded
    作用: 握手成功后记下已加载，后续不再探测存在
    输入:
        model_key (str): 模型 key
    输出: 无
    """
    key = str(model_key or "").strip()
    if key:
        _known_loaded.add(key)


def reset_model_session() -> None:
    """
    函数名: reset_model_session
    作用: 断线后丢掉列表缓存，下次再握手
    输入: 无
    输出: 无
    """
    global _catalog
    _catalog = None
    _known_loaded.clear()


def get_model(model_key: str) -> dict[str, Any] | None:
    """
    函数名: get_model
    作用: 从 GET /api/v1/models 列表按 key 查找（本机不支持 /models/{key}）
    输入:
        model_key (str): 模型唯一 key
    输出:
        dict | None: 模型对象
    """
    key = str(model_key or "").strip()
    if not key:
        return None
    # 中文注释: 本机 LM Studio 不支持 GET /api/v1/models/{key}，只用列表
    for item in list_models():
        if str(item.get("key") or item.get("id") or "") == key:
            return item
    return None



def loaded_instance_ids(model_key: str) -> list[str]:
    """
    函数名: loaded_instance_ids
    作用: 读取某模型当前已加载实例 id
    输入:
        model_key (str): 模型 key
    输出:
        list[str]: instance_id 列表
    """
    info = get_model(model_key)
    if not info:
        return []
    instances = info.get("loaded_instances") or []
    ids: list[str] = []
    if isinstance(instances, list):
        for item in instances:
            if isinstance(item, dict):
                iid = str(item.get("id") or "").strip()
                if iid:
                    ids.append(iid)
            elif isinstance(item, str) and item.strip():
                ids.append(item.strip())
    return ids



def is_model_loaded(model_key: str | None = None) -> bool:
    """
    函数名: is_model_loaded
    作用: 判断指定（或配置中的）模型是否已加载
    输入:
        model_key (str | None): 空则用 user.toml 的 model
    输出:
        bool: 已加载为 True
    """
    key = str(model_key or load_user_config().get("model") or "").strip()
    if not key:
        return False
    return bool(loaded_instance_ids(key))



def has_vision(model_key: str | None = None) -> bool:
    """
    函数名: has_vision
    作用: 查询 capabilities.vision
    输入:
        model_key (str | None): 空则用当前配置模型
    输出:
        bool: 支持读图为 True
    """
    key = str(model_key or load_user_config().get("model") or "").strip()
    info = get_model(key) if key else None
    if not info:
        return False
    caps = info.get("capabilities") or {}
    if isinstance(caps, dict):
        return bool(caps.get("vision"))
    return False



def reasoning_allowed(model_key: str | None = None) -> list[str]:
    """
    函数名: reasoning_allowed
    作用: 读取 capabilities.reasoning.allowed_options
    输入:
        model_key (str | None): 模型 key
    输出:
        list[str]: 如 off / on / low
    """
    key = str(model_key or load_user_config().get("model") or "").strip()
    info = get_model(key) if key else None
    if not info:
        return []
    caps = info.get("capabilities") or {}
    if not isinstance(caps, dict):
        return []
    reasoning = caps.get("reasoning") or {}
    if not isinstance(reasoning, dict):
        return []
    options = reasoning.get("allowed_options") or []
    if not isinstance(options, list):
        return []
    return [str(item) for item in options if item]



def load_model(model_key: str | None = None, *, remember: bool = True) -> dict[str, Any]:
    """
    函数名: load_model
    作用: POST /api/v1/models/load；已加载则直接返回
    输入:
        model_key (str | None): 要加载的 key；空则用配置
        remember (bool): 写回 user.toml 的 model / history
    输出:
        dict: load 响应或 {status: already_loaded, instance_ids}
    """
    key = str(model_key or load_user_config().get("model") or "").strip()
    if not key:
        raise ValueError("未指定 LM Studio 模型名称")
    if remember:
        save_user_config(model=key, remember_model=True)
    if key in _known_loaded:
        return {"status": "already_loaded", "instance_ids": [], "model": key}
    existing = loaded_instance_ids(key)
    if existing:
        _known_loaded.add(key)
        return {"status": "already_loaded", "instance_ids": existing, "model": key}
    payload = request_json(
        "POST",
        "/api/v1/models/load",
        body={"model": key},
        timeout=LOAD_TIMEOUT,
    )
    _known_loaded.add(key)
    return payload if isinstance(payload, dict) else {"status": "loaded", "model": key}



def unload_model(model_key: str | None = None) -> list[str]:
    """
    函数名: unload_model
    作用: 对该模型全部 loaded_instances 逐个 POST /api/v1/models/unload
    输入:
        model_key (str | None): 空则用当前配置模型
    输出:
        list[str]: 已卸载的 instance_id
    """
    global _catalog
    key = str(model_key or load_user_config().get("model") or "").strip()
    if not key:
        return []
    unloaded: list[str] = []
    for iid in loaded_instance_ids(key):
        request_json(
            "POST",
            "/api/v1/models/unload",
            body={"instance_id": iid},
            timeout=QUERY_TIMEOUT,
        )
        unloaded.append(iid)
    _catalog = None
    _known_loaded.discard(key)
    return unloaded
