"""子代理：一次性独立 session；JSON 失败时新开 thinking session 重试。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from llm_gemma4.backends.base import LlmBackend, SessionOptions
from llm_gemma4.runtime.json_extract import extract_json_object


@dataclass
class SubagentResult:
    """
    类名: SubagentResult
    作用: 子代理一轮（含可选 pass2）的结果
    """

    ok: bool
    text: str
    payload: dict[str, Any] | None = None
    error: str = ""
    used_thinking: bool = False
    session_ids: list[str] | None = None


def _send(
    backend: LlmBackend,
    session_id: str,
    *,
    system: str,
    user: str,
    thinking: bool,
    max_tokens: int,
    on_chat: Callable[[str, str], None] | None,
) -> str:
    """
    函数名: _send
    作用: 打开一次性会话、发送一轮、关闭
    输入:
        backend (LlmBackend): 推理后端
        session_id (str): 会话 id（pass1 / pass2 必须不同）
        system (str): 系统提示
        user (str): 用户正文
        thinking (bool): 是否开启 thinking（会话级，创建时定死）
        max_tokens (int): 输出预算
        on_chat (Callable | None): 对话日志
    输出:
        str: 模型回答文本
    """
    if on_chat is not None:
        tag = "thinking" if thinking else "pass1"
        on_chat("user", f"[{session_id} {tag}] {user}")
    opts = SessionOptions(system_message=system, thinking=thinking, max_tokens=max_tokens)
    session = backend.open_session(session_id, options=opts)
    try:
        result = session.send_turn({"role": "user", "content": user})
        text = result.text or ""
        if on_chat is not None:
            thought = result.thought or ""
            shown = text if not thought else f"(thought omitted)\n{text}"
            on_chat("assistant", f"[{session_id}] {shown}")
        return text
    finally:
        session.close()


def run_subagent(
    backend: LlmBackend,
    *,
    job_id: str,
    system: str,
    user: str,
    parse_json: bool = True,
    allow_thinking_retry: bool = True,
    pass1_tokens: int = 256,
    thinking_budget: int = 512,
    on_chat: Callable[[str, str], None] | None = None,
) -> SubagentResult:
    """
    函数名: run_subagent
    作用: 分派一个子代理；pass1 无 thinking，解析失败则新 session thinking=True
    输入:
        backend (LlmBackend): 推理后端
        job_id (str): 任务标识（写入 session_id）
        system (str): 子代理系统提示
        user (str): 子代理用户消息
        parse_json (bool): 是否要求 JSON 对象
        allow_thinking_retry (bool): 解析失败是否 pass2
        pass1_tokens (int): pass1 max_tokens
        thinking_budget (int): pass2 max_tokens
        on_chat (Callable | None): 对话日志
    输出:
        SubagentResult: 文本 / JSON / 是否用过 thinking
    """
    token = uuid.uuid4().hex[:8]
    sid1 = f"sub_{job_id}_{token}_pass1"
    text1 = _send(
        backend,
        sid1,
        system=system,
        user=user,
        thinking=False,
        max_tokens=pass1_tokens,
        on_chat=on_chat,
    )
    sessions = [sid1]
    if not parse_json:
        return SubagentResult(ok=True, text=text1, session_ids=sessions)
    payload, err = extract_json_object(text1)
    if err is None and payload is not None:
        return SubagentResult(ok=True, text=text1, payload=payload, session_ids=sessions)
    if not allow_thinking_retry:
        return SubagentResult(ok=False, text=text1, error=err or "json parse failed", session_ids=sessions)
    sid2 = f"sub_{job_id}_{token}_pass2"
    retry_user = (
        f"{user}\n\nPrevious parse error: {err}\nPrevious output:\n{text1[:500]}\n"
        "Output ONLY one JSON object."
    )
    text2 = _send(
        backend,
        sid2,
        system=system,
        user=retry_user,
        thinking=True,
        max_tokens=thinking_budget,
        on_chat=on_chat,
    )
    sessions.append(sid2)
    payload2, err2 = extract_json_object(text2)
    if err2 is None and payload2 is not None:
        return SubagentResult(
            ok=True,
            text=text2,
            payload=payload2,
            used_thinking=True,
            session_ids=sessions,
        )
    return SubagentResult(
        ok=False,
        text=text2,
        error=err2 or "json parse failed after thinking retry",
        used_thinking=True,
        session_ids=sessions,
    )
