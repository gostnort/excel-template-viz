"""LM Studio OpenAI 兼容 POST /v1/chat/completions（完整历史 + tools）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from llm_cli.lm_studio.client import LmStudioError, request_json
from llm_cli.lm_studio.config import load_user_config
from llm_cli.lm_studio.models import load_model, model_context_limit, reasoning_allowed


COMPLETE_TIMEOUT = 180.0



@dataclass(frozen=True)
class CompletionResult:
    """一次 complete：文本、OpenAI 风格 tool_calls、thought、用量。"""

    text: str
    tool_calls: list[dict[str, Any]] | None = None
    thought: str | None = None
    tokens_used: int | None = None
    context_limit: int | None = None
    raw: Any = None



def complete(
    messages: Sequence[dict[str, Any]],
    *,
    tools: Sequence[dict[str, Any]] | None = None,
    model: str = "",
    thinking: bool = False,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    stream: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> CompletionResult:
    """
    函数名: complete
    作用: 把完整 messages 与可选 tools 发给 /v1/chat/completions
    输入:
        messages (Sequence): OpenAI 风格消息（含 system / assistant / tool）
        tools (Sequence | None): OpenAI function schema 列表；空则不带 tools
        model (str): 模型 key；空则用 user.toml
        thinking (bool): True 时在模型允许范围内请求 reasoning
        temperature (float): 采样温度
        max_tokens (int | None): 输出上限
        stream (bool): 预留；当前仍等完整响应（增量回调在非流式下不触发）
        on_delta / on_thought: 预留流式回调；非 stream 时忽略
    输出:
        CompletionResult
    """
    _ = stream, on_delta, on_thought
    cfg = load_user_config()
    key = str(model or cfg.get("model") or "").strip()
    if not key:
        raise ValueError("未指定 LM Studio 模型名称")
    load_model(key, remember=True)
    body: dict[str, Any] = {
        "model": key,
        "messages": [dict(item) for item in messages],
        "temperature": float(temperature),
    }
    if tools:
        body["tools"] = list(tools)
    if max_tokens is not None:
        body["max_tokens"] = int(max_tokens)
    # 中文注释: 与原生 /api/v1/chat 一样显式 off，避免默认一直 thinking
    allowed = reasoning_allowed(key)
    if thinking:
        if "on" in allowed or not allowed:
            body["reasoning"] = "on"
    elif "off" in allowed or not allowed:
        body["reasoning"] = "off"
    try:
        raw = request_json("POST", "/v1/chat/completions", body=body, timeout=COMPLETE_TIMEOUT)
    except LmStudioError as exc:
        if exc.status != 404:
            raise
        raw = request_json(
            "POST",
            "/api/v1/chat/completions",
            body=body,
            timeout=COMPLETE_TIMEOUT,
        )
    return _parse_completion(raw, key)



def _parse_completion(raw: Any, model_key: str) -> CompletionResult:
    """
    函数名: _parse_completion
    作用: 从 OpenAI chat.completion JSON 抽出文本与 tool_calls
    输入:
        raw (Any): HTTP JSON
        model_key (str): 用于查 context 上限
    输出:
        CompletionResult
    """
    if not isinstance(raw, dict):
        return CompletionResult(text="", raw=raw)
    text = ""
    thought: str | None = None
    calls: list[dict[str, Any]] = []
    choices = raw.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        msg = first.get("message") if isinstance(first, dict) else None
        if isinstance(msg, dict):
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                bits: list[str] = []
                for part in content:
                    if isinstance(part, dict) and str(part.get("type") or "") in ("text", "output_text"):
                        bits.append(str(part.get("text") or part.get("content") or ""))
                text = "".join(bits)
            reason = msg.get("reasoning_content") or msg.get("reasoning") or msg.get("thought")
            if isinstance(reason, str) and reason.strip():
                thought = reason.strip()
            raw_calls = msg.get("tool_calls")
            if isinstance(raw_calls, list):
                for item in raw_calls:
                    if isinstance(item, dict):
                        calls.append(_normalize_tool_call(item))
    used = _usage_total(raw.get("usage"))
    limit = None
    try:
        limit = model_context_limit(model_key)
    except Exception:
        limit = None
    return CompletionResult(
        text=text or "",
        tool_calls=calls or None,
        thought=thought,
        tokens_used=used,
        context_limit=limit,
        raw=raw,
    )



def _normalize_tool_call(item: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: _normalize_tool_call
    作用: 收成 OpenAI tool_call 字典
    输入:
        item (dict): 单条 tool_call
    输出:
        dict
    """
    fn = item.get("function") if isinstance(item.get("function"), dict) else {}
    name = str(fn.get("name") or item.get("name") or "")
    args = fn.get("arguments")
    if args is None:
        args = item.get("arguments") or "{}"
    if not isinstance(args, str):
        args = json.dumps(args, ensure_ascii=False)
    cid = str(item.get("id") or "call_0")
    return {
        "id": cid,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }



def _usage_total(usage: Any) -> int | None:
    """
    函数名: _usage_total
    作用: 从 usage 抽出 total_tokens
    输入:
        usage (Any): OpenAI usage 对象
    输出:
        int | None
    """
    if not isinstance(usage, dict):
        return None
    n = usage.get("total_tokens")
    if isinstance(n, (int, float)) and int(n) > 0:
        return int(n)
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
    completion = usage.get("completion_tokens") or usage.get("output_tokens") or 0
    try:
        total = int(prompt) + int(completion)
    except (TypeError, ValueError):
        return None
    return total if total > 0 else None
