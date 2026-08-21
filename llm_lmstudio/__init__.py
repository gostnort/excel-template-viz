"""LM Studio 平台：原生 REST /api/v1 客户端与薄推理适配器。"""

from __future__ import annotations

__all__ = [
    "conversation_once",
    "get_backend",
    "has_vision",
    "is_model_loaded",
    "load_model",
    "pic2str",
    "reset_backend",
    "unload_model",
]


_LAZY_NAMES = frozenset(__all__)



def __getattr__(name: str):
    """
    函数名: __getattr__
    作用: 惰性导出公开 API，避免 python -m llm_lmstudio 与包初始化循环
    输入:
        name (str): 属性名
    输出:
        对应对象
    """
    if name in _LAZY_NAMES:
        from llm_lmstudio import facade
        return getattr(facade, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
