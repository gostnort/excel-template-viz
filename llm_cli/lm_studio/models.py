"""LM Studio 模型列表 / 详情 / 加载 / 卸载。"""

from __future__ import annotations

import time
from typing import Any

from llm_cli.lm_studio.client import request_json
from llm_cli.lm_studio.config import load_user_config, save_user_config


LOAD_TIMEOUT = 300.0
QUERY_TIMEOUT = 20.0
_LIST_TTL_SEC = 5.0
_LIST_CACHE: tuple[float, list[dict[str, Any]]] | None = None



def invalidate_models_list() -> None:
    """
    函数名: invalidate_models_list
    作用: 丢掉 GET /api/v1/models 短缓存（load/unload 之后必须调用）
    输入: 无
    输出: 无
    """
    global _LIST_CACHE
    _LIST_CACHE = None


def list_models(*, force: bool = False) -> list[dict[str, Any]]:
    """
    函数名: list_models
    作用: GET /api/v1/models；数秒内复用同一次结果，避免握手连打
    输入:
        force (bool): True 则跳过缓存
    输出:
        list[dict]: 模型条目（含 key / loaded_instances / capabilities）
    """
    global _LIST_CACHE
    now = time.monotonic()
    if not force and _LIST_CACHE is not None:
        cached_at, rows = _LIST_CACHE
        if now - cached_at < _LIST_TTL_SEC:
            return rows
    payload = request_json("GET", "/api/v1/models", timeout=QUERY_TIMEOUT)
    models: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        raw = payload.get("models")
        if isinstance(raw, list):
            models = [item for item in raw if isinstance(item, dict)]
    elif isinstance(payload, list):
        models = [item for item in payload if isinstance(item, dict)]
    _LIST_CACHE = (now, models)
    return models



def get_model(model_key: str) -> dict[str, Any] | None:
    """
    函数名: get_model
    作用: 从 GET /api/v1/models 列表按 key 匹配；不请求 /api/v1/models/{key}
    输入:
        model_key (str): 模型唯一 key
    输出:
        dict | None: 模型对象
    """
    key = str(model_key or "").strip()
    if not key:
        return None
    # 中文注释: 部分 LM Studio 对 GET /api/v1/models/{key} 记 ERROR，列表接口可用
    for item in list_models():
        if str(item.get("key") or item.get("id") or "") == key:
            return item
    return None



def model_context_limit(model_key: str | None = None) -> int | None:
    """
    函数名: model_context_limit
    作用: 从列表模型对象读上下文上限（已加载实例优先）
    输入:
        model_key (str | None): 空则用 user.toml 的 model
    输出:
        int | None: token 上限；未知则为 None
    """
    key = str(model_key or load_user_config().get("model") or "").strip()
    info = get_model(key) if key else None
    if not info:
        return None
    # 中文注释: 实测键为 loaded_instances[].config.context_length 与 max_context_length
    instances = info.get("loaded_instances") or []
    if isinstance(instances, list):
        for item in instances:
            if not isinstance(item, dict):
                continue
            cfg = item.get("config") or {}
            if not isinstance(cfg, dict):
                continue
            n = cfg.get("context_length")
            if isinstance(n, (int, float)) and int(n) > 0:
                return int(n)
    n = info.get("max_context_length")
    if isinstance(n, (int, float)) and int(n) > 0:
        return int(n)
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


def loaded_models_from(items: list[dict[str, Any]] | None = None) -> list[str]:
    """
    函数名: loaded_models_from
    作用: 列出当前已加载实例的模型 key
    输入:
        items (list | None): 已有 GET /api/v1/models 结果；空则现场拉一次
    输出:
        list[str]: 有 loaded_instances 的模型 key
    """
    rows = items if items is not None else list_models()
    keys: list[str] = []
    for item in rows:
        instances = item.get("loaded_instances") or []
        if not isinstance(instances, list) or not instances:
            continue
        key = str(item.get("key") or item.get("id") or "").strip()
        if key:
            keys.append(key)
    return keys


def model_size_bytes(model_key: str, items: list[dict[str, Any]] | None = None) -> int | None:
    """
    函数名: model_size_bytes
    作用: 从模型列表读 size_bytes
    输入:
        model_key (str): 模型 key
        items (list | None): 已有列表；空则现场拉一次
    输出:
        int | None: 字节数
    """
    want = str(model_key or "").strip()
    if not want:
        return None
    rows = items if items is not None else list_models()
    for item in rows:
        key = str(item.get("key") or item.get("id") or "").strip()
        if key != want:
            continue
        n = item.get("size_bytes")
        if isinstance(n, (int, float)) and int(n) > 0:
            return int(n)
        return None
    return None


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
    existing = loaded_instance_ids(key)
    if existing:
        return {"status": "already_loaded", "instance_ids": existing, "model": key}
    payload = request_json(
        "POST",
        "/api/v1/models/load",
        body={"model": key},
        timeout=LOAD_TIMEOUT,
    )
    invalidate_models_list()
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
    invalidate_models_list()
    return unloaded
