"""LiteRtSession: session_id -> persistent Conversation (docs §3.2.1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Mapping

from llm_gemma4.runtime.thinking import split_thought_answer
from llm_gemma4.backends.base import GenerateResult

if TYPE_CHECKING:
    import litert_lm as lm


class LiteRtSession:
    def __init__(
        self,
        conversation: "lm.Conversation",
        *,
        on_close: Callable[[], None] | None = None,
        default_max_tokens: int | None = None,
    ) -> None:
        self._conversation = conversation
        self._closed = False
        self._on_close = on_close
        self._default_max_tokens = default_max_tokens

    def send_turn(self, message: Mapping[str, Any], *, max_output_tokens: int | None = None) -> GenerateResult:
        """
        函数名: send_turn
        作用: 向持久 Conversation 发送一轮用户消息并返回生成结果
        输入:
            message (Mapping[str, Any]): 须含 content 键的用户消息
            max_output_tokens (int | None): 输出 token 上限；None 时用会话默认值
        输出:
            GenerateResult: 模型回答（thought 已剥离）
        """
        if self._closed:
            raise RuntimeError("LiteRtSession is closed.")
        budget = max_output_tokens if max_output_tokens is not None else self._default_max_tokens
        response = self._conversation.send_message(message["content"], max_output_tokens=budget)
        thought, answer = split_thought_answer(response)
        return GenerateResult(text=answer, thought=thought, raw=response)

    def close(self) -> None:
        """
        函数名: close
        作用: 关闭底层 Conversation 并触发 backend 缓存清理
        输入: 无
        输出: 无
        """
        if not self._closed:
            self._conversation.close()
            self._closed = True
            if self._on_close is not None:
                self._on_close()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def token_count(self) -> int:
        return self._conversation.token_count
