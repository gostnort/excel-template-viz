"""LMS 独立客户端模块：标准 OpenAI 协议 + 官方 `lms` CLI 支持。"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from llm_cli.lms.client import CompletionResult, HealthReport, LmsClient, LmsError
from llm_cli.lms.config import load_user_config, save_user_config
from llm_cli.lms.lms_cli import lms_load, lms_ps, lms_start_server, lms_status, lms_unload

_CLIENT: LmsClient | None = None


def get_backend() -> LmsClient:
    """获取单例 LmsClient"""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = LmsClient()
    return _CLIENT


def reset_backend() -> None:
    """重置单例"""
    global _CLIENT
    _CLIENT = None


def complete(
    messages: Sequence[dict[str, Any]],
    *,
    tools: Sequence[dict[str, Any]] | None = None,
    model: str = "",
    thinking: bool = False,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    stream: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> CompletionResult:
    """调用全局客户端进行补全"""
    return get_backend().complete(
        messages=messages,
        tools=tools,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
        on_delta=on_delta,
        on_thought=on_thought,
    )


def conversation_once(
    prompt: str,
    *,
    system: str = "",
    thinking: bool = False,
    temperature: float = 0.0,
    model: str = "",
) -> str:
    """单轮对话极简快捷函数（供 downstream 任务如 regex_deduce 调用）"""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    res = complete(messages, model=model, thinking=thinking, temperature=temperature)
    return res.text


def load_model(model_key: str, *, remember: bool = True) -> bool:
    """加载模型"""
    return get_backend().load_model(model_key, remember=remember)


def loaded_models_from() -> list[str]:
    """返回当前已加载的模型列表"""
    rep = get_backend().health_check()
    return rep.loaded_models


def model_context_limit(model_key: str) -> int | None:
    """
    函数名: model_context_limit
    作用: 从 /v1/models 读取该模型的上下文长度；接口没有该字段时返回空
    输入:
        model_key (str): 模型 id
    输出:
        int | None: 上下文 token 上限；未知则为 None
    """
    key = str(model_key or "").strip()
    if not key:
        return None
    try:
        return get_backend().context_limit_for(key)
    except Exception:
        return None


__all__ = [
    "CompletionResult",
    "HealthReport",
    "LmsClient",
    "LmsError",
    "complete",
    "conversation_once",
    "get_backend",
    "load_model",
    "load_user_config",
    "loaded_models_from",
    "model_context_limit",
    "reset_backend",
    "save_user_config",
    "lms_load",
    "lms_ps",
    "lms_status",
    "lms_start_server",
    "lms_unload",
]
