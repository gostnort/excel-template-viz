"""LiteRtSession: session_id -> persistent Conversation (docs §3.2.1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from llm_gemma4.runtime.thinking import split_thought_answer
from llm_gemma4.backends.base import GenerateResult

if TYPE_CHECKING:
    import litert_lm as lm


class LiteRtSession:
    def __init__(self, conversation: "lm.Conversation") -> None:
        self._conversation = conversation
        self._closed = False

    def send_turn(self, message: Mapping[str, Any], *, max_output_tokens: int | None = None) -> GenerateResult:
        if self._closed:
            raise RuntimeError("LiteRtSession is closed.")
        response = self._conversation.send_message(message["content"], max_output_tokens=max_output_tokens)
        thought, answer = split_thought_answer(response)
        return GenerateResult(text=answer, thought=thought, raw=response)

    def close(self) -> None:
        if not self._closed:
            self._conversation.close()
            self._closed = True

    @property
    def token_count(self) -> int:
        return self._conversation.token_count
