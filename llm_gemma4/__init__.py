"""Gemma 4 E4B LiteRT platform: inference driver + judgment interface.

See docs/embed_gemma4.md for the full spec. This package intentionally
contains no business-domain prompts (OCR, TOML wizard, ...); those live in
their own application packages (e.g. paddle_ocr/runtime/semantic_gate.py).
"""

from __future__ import annotations

__all__ = ["ConversationOnce"]


def __getattr__(name: str):
    """
    函数名: __getattr__
    作用: PEP 562 惰性属性——只有真的有人访问 `llm_gemma4.ConversationOnce`
        （或 `from llm_gemma4 import ConversationOnce`）时才去 import
        `llm_gemma4.__main__`，而不是包一加载就 import。如果在包初始化时就
        无条件 import，`python -m llm_gemma4` 跑的时候 `runpy` 会发现
        `llm_gemma4.__main__` 已经在 sys.modules 里，抛
        RuntimeWarning（已实测触发过）。
    输入:
        name (str): 被访问的属性名。
    输出: 对应属性值；未知属性名抛 AttributeError。
    """
    if name == "ConversationOnce":
        from llm_gemma4.__main__ import ConversationOnce
        return ConversationOnce
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
