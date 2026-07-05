"""LlmBackend protocol for Gemma 4 inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GenerateResult:
    text: str
    thought: str | None
    completion_tokens: int | None
    finish_reason: str | None


class LlmBackend(Protocol):
    profile: str

    def health_check(self) -> str:
        """One-line status for CLI."""

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        thinking: bool = False,
    ) -> GenerateResult:
        ...
