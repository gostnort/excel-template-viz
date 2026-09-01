"""LM Studio POST /api/v1/chat（文本 / 读图 / 可选 stateful）。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Callable

from llm_cli.lm_studio.client import LmStudioError, iter_sse, request_json
from llm_cli.lm_studio.config import load_user_config
from llm_cli.lm_studio.models import load_model, reasoning_allowed


CHAT_TIMEOUT = 120.0


def _reasoning_for_chat(thinking: bool, allowed: list[str]) -> str | None:
    """
    函数名: _reasoning_for_chat
    作用: 为 /api/v1/chat 选定 reasoning；默认 off，不因模型 default=on 而打开
    输入:
        thinking (bool): 用户/Agent 开关
        allowed (list[str]): 模型 allowed_options
    输出:
        str | None: 写入 body 的值；None 表示不发该字段
    """
    opts = [str(item) for item in allowed]
    if thinking:
        if "on" in opts:
            return "on"
        for item in opts:
            if item != "off":
                return item
        if not opts:
            return "on"
        return None
    if "off" in opts or not opts:
        return "off"
    return None


def _data_url_from_image(image: str | Path | bytes) -> str:
    """
    函数名: _data_url_from_image
    作用: 把路径或字节编成 data URL
    输入:
        image (str | Path | bytes): 文件路径或已编码图片字节
    输出:
        str: data:image/...;base64,...
    """
    mime = "image/jpeg"
    if isinstance(image, bytes):
        data = image
    else:
        path = Path(image)
        suffix = path.suffix.lower()
        if suffix == ".png":
            mime = "image/png"
        elif suffix in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif suffix == ".webp":
            mime = "image/webp"
        data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"



def _as_int(value: Any) -> int | None:
    """
    函数名: _as_int
    作用: 把 JSON 数字收成非负 int
    输入:
        value (Any): 字段值
    输出:
        int | None: 合法则返回整数
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        n = int(value)
        return n if n >= 0 else None
    return None



def _extract_usage(payload: dict[str, Any] | None) -> dict[str, int] | None:
    """
    函数名: _extract_usage
    作用: 从 chat JSON 抽出 token 用量（stats 或 usage）
    输入:
        payload (dict | None): /api/v1/chat 正文或 chat.end.result
    输出:
        dict | None: input_tokens / output_tokens / total_tokens
    """
    if not isinstance(payload, dict):
        return None
    input_n: int | None = None
    output_n: int | None = None
    # 中文注释: 原生 v1 把用量放在 stats
    stats = payload.get("stats")
    if isinstance(stats, dict):
        input_n = _as_int(stats.get("input_tokens"))
        output_n = _as_int(stats.get("total_output_tokens"))
        if output_n is None:
            out = _as_int(stats.get("output_tokens")) or 0
            reason = _as_int(stats.get("reasoning_output_tokens")) or 0
            combo = out + reason
            output_n = combo if combo > 0 else None
    usage = payload.get("usage")
    if isinstance(usage, dict):
        if input_n is None:
            input_n = _as_int(usage.get("input_tokens")) or _as_int(usage.get("prompt_tokens"))
        if output_n is None:
            output_n = _as_int(usage.get("output_tokens")) or _as_int(usage.get("completion_tokens"))
        total = _as_int(usage.get("total_tokens"))
        if total is not None and total > 0 and input_n is None and output_n is None:
            return {"input_tokens": 0, "output_tokens": 0, "total_tokens": total}
    if input_n is None and output_n is None:
        return None
    total = (input_n or 0) + (output_n or 0)
    if total <= 0:
        return None
    return {"input_tokens": input_n or 0, "output_tokens": output_n or 0, "total_tokens": total}



def _extract_text(payload: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """
    函数名: _extract_text
    作用: 从 chat 响应抽出 message 文本、reasoning、response_id
    输入:
        payload (dict): /api/v1/chat JSON
    输出:
        tuple: (text, thought, response_id)
    """
    chunks: list[str] = []
    thoughts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        content = str(item.get("content") or "")
        if kind in ("message", "text") and content:
            chunks.append(content)
        elif kind in ("reasoning", "thinking", "thought") and content:
            thoughts.append(content)
    # 中文注释: 顶层或 OpenAI message 里的 reasoning 兼容字段
    for key in ("reasoning", "thought", "reasoning_content"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            thoughts.append(val.strip())
    msg = payload.get("message")
    if isinstance(msg, dict):
        for key in ("reasoning", "reasoning_content", "thought"):
            val = msg.get(key)
            if isinstance(val, str) and val.strip():
                thoughts.append(val.strip())
        if not chunks:
            body = msg.get("content")
            if isinstance(body, str) and body.strip():
                chunks.append(body.strip())
    text = "\n".join(chunks).strip()
    if not text:
        text = str(payload.get("content") or payload.get("text") or "").strip()
    seen: set[str] = set()
    uniq: list[str] = []
    for item in thoughts:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    thought = "\n".join(uniq).strip() or None
    rid = payload.get("response_id")
    response_id = str(rid) if rid else None
    return text, thought, response_id



def _delta_piece(event: dict[str, Any]) -> str:
    """
    函数名: _delta_piece
    作用: 从 SSE 事件取出 message 增量文本（不含 reasoning）
    输入:
        event (dict): 单条流事件
    输出:
        str: 增量；非 message 则为空
    """
    kind = str(event.get("type") or "")
    if kind in ("message.delta", "text.delta"):
        return str(event.get("content") or event.get("delta") or "")
    if kind:
        return ""
    # 中文注释: 无 type 时兼容 OpenAI choices[].delta.content
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first, dict) else {}
        if isinstance(delta, dict):
            return str(delta.get("content") or "")
    return ""



def _thought_piece(event: dict[str, Any]) -> str:
    """
    函数名: _thought_piece
    作用: 从 SSE 事件取出 reasoning / thought 增量
    输入:
        event (dict): 单条流事件
    输出:
        str: 增量；非 thought 则为空
    """
    kind = str(event.get("type") or "")
    if kind in ("reasoning.delta", "thought.delta", "thinking.delta"):
        return str(event.get("content") or event.get("delta") or "")
    if kind in ("reasoning", "thought", "thinking"):
        return str(event.get("content") or event.get("delta") or "")
    # 中文注释: OpenAI 风格 choices[].delta.reasoning
    choices = event.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        delta = first.get("delta") if isinstance(first, dict) else {}
        if isinstance(delta, dict):
            return str(delta.get("reasoning") or delta.get("reasoning_content") or delta.get("thought") or "")
    extra = event.get("delta")
    if isinstance(extra, dict):
        return str(extra.get("reasoning") or extra.get("reasoning_content") or extra.get("thought") or "")
    return ""


def _consume_chat_stream(
    body: dict[str, Any],
    on_delta: Callable[[str], None] | None,
    on_thought: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    函数名: _consume_chat_stream
    作用: 读 /api/v1/chat SSE，把 thought / message 增量回调给 UI
    输入:
        body (dict): 已含 stream=true 的请求体
        on_delta (callable | None): 每段 message 文本
        on_thought (callable | None): 每段 reasoning 文本
    输出:
        dict: text / thought / response_id / raw / usage（与非流 chat 同形）
    """
    chunks: list[str] = []
    thoughts: list[str] = []
    raw_end: Any = None
    # 中文注释: reasoning.delta 先推灰字；message.delta 推绿框；chat.end 收完整包
    for event in iter_sse("POST", "/api/v1/chat?stream=true", body=body, timeout=CHAT_TIMEOUT):
        kind = str(event.get("type") or "")
        if kind == "error":
            err = event.get("error") if event.get("error") is not None else event.get("message")
            raise LmStudioError(f"LM Studio stream error: {str(err)[:400]}")
        if kind == "chat.end":
            maybe = event.get("result")
            raw_end = maybe if isinstance(maybe, dict) else event
        thought_bit = _thought_piece(event)
        if thought_bit:
            thoughts.append(thought_bit)
            if on_thought is not None:
                on_thought(thought_bit)
        piece = _delta_piece(event)
        if piece:
            chunks.append(piece)
            if on_delta is not None:
                on_delta(piece)
    if isinstance(raw_end, dict):
        text, thought, response_id = _extract_text(raw_end)
        if not text:
            msg = raw_end.get("message")
            if isinstance(msg, dict):
                text = str(msg.get("content") or "").strip()
        if not text:
            text = "".join(chunks)
        if not thought:
            thought = "".join(thoughts).strip() or None
        rid = response_id
        if not rid and raw_end.get("response_id"):
            rid = str(raw_end.get("response_id"))
        return {
            "text": text,
            "thought": thought,
            "response_id": rid,
            "raw": raw_end,
            "usage": _extract_usage(raw_end),
        }
    return {
        "text": "".join(chunks),
        "thought": "".join(thoughts).strip() or None,
        "response_id": None,
        "raw": None,
        "usage": None,
    }


def chat(
    input_payload: str | list[dict[str, Any]],
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int | None = None,
    thinking: bool = False,
    store: bool = False,
    previous_response_id: str | None = None,
    stream: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    函数名: chat
    作用: 若指定模型未加载则先 load，再调用 POST /api/v1/chat
    输入:
        input_payload (str | list): 文本或 message/image 数组
        model (str | None): 模型 key；空则用配置
        system_prompt (str | None): 系统提示
        temperature (float): 采样温度
        max_output_tokens (int | None): 输出上限
        thinking (bool): True 时在模型允许范围内发 reasoning=on
        store (bool): True 时保留会话并返回 response_id
        previous_response_id (str | None): 续写 resp_...
        stream (bool): True 时走 SSE，按 token 回调
        on_delta (callable | None): 流式 message 增量；有则强制 stream
        on_thought (callable | None): 流式 reasoning 增量
    输出:
        dict: text / thought / response_id / raw / usage
    """
    cfg = load_user_config()
    key = str(model or cfg.get("model") or "").strip()
    if not key:
        raise ValueError("未指定 LM Studio 模型名称")
    # 中文注释: 模型已在 LM Studio 但未加载时先 load，再发 chat
    load_model(key, remember=True)
    body: dict[str, Any] = {
        "model": key,
        "input": input_payload,
        "temperature": temperature,
        "store": store,
    }
    if system_prompt:
        body["system_prompt"] = system_prompt
    if max_output_tokens is not None:
        body["max_output_tokens"] = int(max_output_tokens)
    if previous_response_id:
        body["previous_response_id"] = previous_response_id
    # 中文注释: 显式 off，避免模型 default=on 时不传字段就一直 thinking
    allowed = reasoning_allowed(key)
    choice = _reasoning_for_chat(thinking, allowed)
    if choice is not None:
        body["reasoning"] = choice
    if stream or on_delta is not None or on_thought is not None:
        body["stream"] = True
        return _consume_chat_stream(body, on_delta, on_thought)
    raw = request_json("POST", "/api/v1/chat", body=body, timeout=CHAT_TIMEOUT)
    if not isinstance(raw, dict):
        return {"text": "", "thought": None, "response_id": None, "raw": raw, "usage": None}
    text, thought, response_id = _extract_text(raw)
    return {
        "text": text,
        "thought": thought,
        "response_id": response_id,
        "raw": raw,
        "usage": _extract_usage(raw),
    }



def chat_text(
    user_text: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int | None = None,
    thinking: bool = False,
    store: bool = False,
    previous_response_id: str | None = None,
    stream: bool = False,
    on_delta: Callable[[str], None] | None = None,
    on_thought: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    函数名: chat_text
    作用: 纯文本一轮 chat
    输入:
        user_text (str): 用户正文
        其余同 chat
    输出:
        dict: text / thought / response_id / raw / usage
    """
    return chat(
        user_text,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking=thinking,
        store=store,
        previous_response_id=previous_response_id,
        stream=stream,
        on_delta=on_delta,
        on_thought=on_thought,
    )



def chat_vision(
    image: str | Path | bytes,
    prompt: str,
    *,
    model: str | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.0,
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """
    函数名: chat_vision
    作用: 文本 + data_url 图片发给 /api/v1/chat
    输入:
        image (str | Path | bytes): 图片
        prompt (str): 文本提示
        model / system_prompt / temperature / max_output_tokens: 同 chat
    输出:
        dict: text / thought / response_id / raw
    """
    items = [
        {"type": "message", "content": prompt},
        {"type": "image", "data_url": _data_url_from_image(image)},
    ]
    return chat(
        items,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        thinking=False,
        store=False,
    )
