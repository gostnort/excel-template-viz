"""Parse Gemma 4 thinking channel from model output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedThinking:
    thought: str | None
    answer: str


_THOUGHT_BLOCK = re.compile(
    r"<\|channel\|>thought\s*(.*?)<\|channel\|>",
    re.DOTALL | re.IGNORECASE,
)


def parse_thinking(raw: str) -> ParsedThinking:
    """Split thought channel from final answer text."""
    text = raw or ""
    match = _THOUGHT_BLOCK.search(text)
    if not match:
        return ParsedThinking(thought=None, answer=text.strip())
    thought = match.group(1).strip() or None
    answer = _THOUGHT_BLOCK.sub("", text).strip()
    return ParsedThinking(thought=thought, answer=answer)
