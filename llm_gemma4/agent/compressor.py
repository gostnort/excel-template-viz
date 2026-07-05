"""Rule-based context compression (embed_gemma4.md §8.3 档 A)."""

from __future__ import annotations

import re

from llm_gemma4.agent.context_store import ContextStore, Turn


_THOUGHT_TAIL = re.compile(r"<\|channel\|>thought[\s\S]*?<\|channel\|>", re.IGNORECASE)


class Compressor:
    """Trim ContextStore when token budget is exceeded."""

    def __init__(self, store: ContextStore):
        self.store = store


    def run(self, *, drop_turns: int | None = None) -> bool:
        """Compress in place; return True if anything changed."""
        if not self.store.should_compress() and drop_turns is None:
            return False
        k = self.store.config.recent_turns_k
        profile_drop = 1 if k >= 4 else 2
        count = drop_turns if drop_turns is not None else profile_drop
        removed = self.store.pop_oldest_turns(count)
        if removed:
            bullets = _turns_to_bullets(removed, max_lines=8)
            self.store.tool_trace_summary.extend(bullets)
            if len(self.store.tool_trace_summary) > 24:
                self.store.tool_trace_summary = self.store.tool_trace_summary[-24:]
        for turn in self.store.recent_turns:
            if turn.role == "assistant":
                turn.content = _THOUGHT_TAIL.sub("", turn.content).strip()
        return bool(removed)


    def emergency_trim(self) -> None:
        """Drop Layer 3 and keep only task + last turn + browser (§8.4)."""
        self.store.tool_trace_summary.clear()
        if len(self.store.recent_turns) > 1:
            self.store.recent_turns = self.store.recent_turns[-1:]


def _turns_to_bullets(turns: list[Turn], max_lines: int = 8) -> list[str]:
    lines: list[str] = []
    for turn in turns:
        prefix = turn.meta.get("tool") or turn.role
        snippet = turn.content.replace("\n", " ").strip()[:120]
        if snippet:
            lines.append(f"{prefix}: {snippet}")
    return lines[:max_lines]
