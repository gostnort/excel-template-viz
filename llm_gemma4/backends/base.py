"""LlmBackend / LlmSession protocols. No business-domain prompts here.

See docs/embed_gemma4.md §3.1-3.2.1 for the two conversation lifecycles this
protocol pair is designed around: stateless `generate()` for one-shot judgment
calls, stateful `open_session()`/`send_turn()` for the multi-turn wizard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class JudgmentToolSpec:
    """Backend-agnostic description of the "fake tool" used to force structured
    verdict output (docs/embed_gemma4.md §3.6.1a). Backends without constrained
    decoding support are free to ignore this and fall back to plain text.
    """
    name: str
    description: str
    verdict_key: str
    reason_key: str


@dataclass(frozen=True)
class GenerateResult:
    text: str
    thought: str | None = None
    tool_call_arguments: Mapping[str, Any] | None = None
    raw: Any = None


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    profile: str
    litert_backend: str
    mtp: bool
    model_path: str
    message: str


class LlmSession(Protocol):
    def send_turn(
        self, message: Mapping[str, Any], *, max_output_tokens: int | None = None,
    ) -> GenerateResult: ...
    """Send one turn on the persistent Conversation; history stays in the
    engine's own KV cache, this call never replays prior turns."""

    def close(self) -> None: ...

    @property
    def token_count(self) -> int: ...
    """Live KV-cache token count (docs/embed_gemma4.md §4.2), not an estimate."""


class LlmBackend(Protocol):
    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool: JudgmentToolSpec | None = None,
    ) -> GenerateResult: ...
    """Stateless single call: opens a temporary Conversation, sends one turn,
    closes it. `judgment_tool` set → attempt §3.6.1a constrained tool-call
    decoding; `GenerateResult.tool_call_arguments` is set only if it actually
    landed as a structured tool call (caller must still handle the None case)."""

    def open_session(self, session_id: str) -> LlmSession: ...
    """Stateful multi-turn: same session_id reuses the same Conversation."""

    def warm(self) -> None: ...
    """Force any lazy construction (e.g. the real Engine) to happen now
    instead of on the first generate()/open_session() call. Backends without
    lazy construction may make this a no-op."""

    def count_tokens(self, text: str) -> int: ...

    def health_check(self) -> HealthReport: ...
