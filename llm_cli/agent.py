"""通用 Agent 对话管理（极简研发/调试版本）。"""

from __future__ import annotations

from typing import Any, Callable

from llm_cli.provider import get_provider

WORKER_SYSTEM = (
    "You are a research worker. Given a task, investigate and return only findings."
)

COMPRESSOR_SYSTEM = (
    "You compress a worker report for a parent agent. Output a short digest."
)

MAIN_SYSTEM = (
    "You are the assistant for Excel template visualization and data analysis."
)


class Agent:
    """轻量 Agent：管理多轮对话历史，调用 lms.complete，支持 thinking 与流式输出。"""

    def __init__(
        self,
        *,
        system: str = MAIN_SYSTEM,
        tools: dict[str, Callable[..., Any]] | None = None,
        model: str = "",
        name: str = "main",
        thinking: bool = True,
        stream: bool = False,
    ) -> None:
        self.name = name
        self.model = model
        self.system = system
        self.thinking = thinking
        self.stream = stream
        self.tools = dict(tools or {})
        self.history: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.last_thought: str | None = None
        self.last_tokens_used: int | None = None
        self.last_context_limit: int | None = None
        self.on_tool: Callable[[str], None] | None = None

    def set_thinking(self, val: bool) -> None:
        self.thinking = bool(val)

    def set_stream(self, val: bool) -> None:
        self.stream = bool(val)

    def reset(self) -> None:
        self.history = [{"role": "system", "content": self.system}]
        self.last_thought = None
        self.last_tokens_used = None

    def run(
        self,
        user: str,
        on_delta: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> str:
        self.history.append({"role": "user", "content": user})
        provider = get_provider()

        cb = on_delta if self.stream else None
        thought_cb = on_thought if self.stream else None

        res = provider.complete(
            self.history,
            model=self.model,
            thinking=self.thinking,
            stream=self.stream,
            on_delta=cb,
            on_thought=thought_cb,
        )

        self.last_thought = getattr(res, "thought", None)
        self.last_tokens_used = getattr(res, "tokens_used", None)
        self.last_context_limit = getattr(res, "context_limit", None)

        text = getattr(res, "text", "") or ""
        self.history.append({"role": "assistant", "content": text})
        return text


__all__ = ["Agent", "MAIN_SYSTEM", "WORKER_SYSTEM", "COMPRESSOR_SYSTEM"]
