"""通用提供方入口：默认 lm_studio。toml 等应用不应写死提供方。"""

from __future__ import annotations

from typing import Any, Protocol, Sequence


class LlmProvider(Protocol):
    """
    类名: LlmProvider
    作用: CLI 内核认的提供方形状（complete / health / generate / session）
    """

    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str = "",
        thinking: bool = False,
        **kwargs: Any,
    ) -> Any: ...

    def health_check(self) -> Any: ...

    def generate(self, messages: Any, **kwargs: Any) -> Any: ...

    def open_session(self, session_id: str, **kwargs: Any) -> Any: ...

    def close(self) -> None: ...



def get_provider() -> Any:
    """
    函数名: get_provider
    作用: 返回当前默认提供方（LM Studio 适配器）
    输入: 无
    输出:
        LmStudioBackend
    """
    from llm_cli.lm_studio.backend import get_backend
    return get_backend()
