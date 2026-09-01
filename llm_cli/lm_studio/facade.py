"""对外便捷 API：load/unload/conversation/pic2str。"""

from __future__ import annotations

from pathlib import Path

from llm_cli.lm_studio.backend import get_backend, reset_backend
from llm_cli.lm_studio.models import has_vision, is_model_loaded, load_model, unload_model



def conversation_once(
    input_string: str,
    *,
    system: str | None = None,
    thinking: bool = False,
    temperature: float = 0.0,
) -> str:
    """
    函数名: conversation_once
    作用: 一次性问答，只返回最终文本
    输入:
        input_string (str): 用户问题
        system (str | None): 系统提示
        thinking (bool): 是否请求 reasoning
        temperature (float): 采样温度
    输出:
        str: 模型回答
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": input_string})
    return get_backend().generate(messages, thinking=thinking, temperature=temperature).text



def pic2str(
    image: str | Path | bytes,
    prompt: str,
    *,
    system: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> str:
    """
    函数名: pic2str
    作用: 图片 + 提示 → 文本；调用前应由调用方检查 has_vision
    输入:
        image (str | Path | bytes): 图片
        prompt (str): 文本提示
        system (str | None): 系统提示
        max_tokens (int | None): 输出上限
        temperature (float): 采样温度
    输出:
        str: 模型文本
    """
    return get_backend().generate_vision(
        image, prompt, system=system, max_tokens=max_tokens, temperature=temperature
    ).text


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
