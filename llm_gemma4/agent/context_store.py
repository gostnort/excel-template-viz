"""Layered LLM context (embed_gemma4.md §8.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from llm_gemma4.agent.context_config import ContextConfig


@dataclass
class Turn:
    role: str
    content: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContextStore:
    config: ContextConfig
    system_prompt: str = ""
    task_anchor: str = ""
    recent_turns: list[Turn] = field(default_factory=list)
    tool_trace_summary: list[str] = field(default_factory=list)
    latest_browser_state: str | None = None
    _token_counter: Callable[[str], int] | None = None


    def set_token_counter(self, counter: Callable[[str], int] | None) -> None:
        self._token_counter = counter


    def set_system(self, text: str) -> None:
        self.system_prompt = text


    def set_task_anchor(self, text: str) -> None:
        self.task_anchor = text


    def append_turn(self, role: str, content: str, **meta: Any) -> None:
        self.recent_turns.append(Turn(role=role, content=content, meta=dict(meta)))


    def append_tool_observation(self, text: str, *, tool_name: str = "") -> None:
        clipped = self._clip(text, self.config.tool_observation_max_chars)
        self.append_turn("tool", clipped, tool=tool_name)


    def set_browser_state(self, text: str) -> None:
        clipped = self._clip(text, self.config.browser_observation_max_chars)
        self.latest_browser_state = clipped


    def estimate_tokens(self) -> int:
        parts = [self.system_prompt, self.task_anchor]
        parts.extend(t.content for t in self.recent_turns)
        parts.extend(self.tool_trace_summary)
        if self.latest_browser_state:
            parts.append(self.latest_browser_state)
        blob = "\n".join(parts)
        if self._token_counter:
            return self._token_counter(blob)
        return max(1, len(blob) // 3)


    def should_compress(self) -> bool:
        limit = int(self.config.n_ctx * self.config.compress_trigger_ratio)
        return self.estimate_tokens() > limit


    def build_messages(self) -> list[dict[str, str]]:
        """Flatten layers into chat messages for backend.generate."""
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.task_anchor:
            messages.append({"role": "user", "content": f"[task]\n{self.task_anchor}"})
        if self.tool_trace_summary:
            summary = "\n".join(f"- {line}" for line in self.tool_trace_summary)
            messages.append({"role": "user", "content": f"[history_summary]\n{summary}"})
        if self.latest_browser_state:
            messages.append({"role": "user", "content": f"[browser]\n{self.latest_browser_state}"})
        for turn in self.recent_turns:
            role = turn.role if turn.role in {"user", "assistant", "system"} else "user"
            messages.append({"role": role, "content": turn.content})
        return messages


    def pop_oldest_turns(self, count: int) -> list[Turn]:
        if count <= 0 or not self.recent_turns:
            return []
        removed = self.recent_turns[:count]
        self.recent_turns = self.recent_turns[count:]
        return removed


    def _clip(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        half = max_chars // 2
        return text[:half] + "\n…\n" + text[-half:]
