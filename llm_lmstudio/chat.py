"""LM Studio POST /api/v1/chat（文本 / 读图 / 可选 stateful）。"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from llm_lmstudio.client import request_json
from llm_lmstudio.config import load_user_config
from llm_lmstudio.models import load_model, reasoning_allowed


CHAT_TIMEOUT = 120.0



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
        if kind == "message" and content:
            chunks.append(content)
        elif kind == "reasoning" and content:
            thoughts.append(content)
        elif kind == "text" and content:
            chunks.append(content)
    text = "\n".join(chunks).strip()
    if not text:
        text = str(payload.get("content") or payload.get("text") or "").strip()
    thought = "\n".join(thoughts).strip() or None
    rid = payload.get("response_id")
    response_id = str(rid) if rid else None
    return text, thought, response_id



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
    输出:
        dict: text / thought / response_id / raw
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
    # 中文注释: 仅在模型声明支持时发送 reasoning，避免 API 报错
    allowed = reasoning_allowed(key)
    if thinking and allowed:
        choice = "on" if "on" in allowed else allowed[0]
        body["reasoning"] = choice
    elif (not thinking) and allowed and "off" in allowed:
        body["reasoning"] = "off"
    raw = request_json("POST", "/api/v1/chat", body=body, timeout=CHAT_TIMEOUT)
    if not isinstance(raw, dict):
        return {"text": "", "thought": None, "response_id": None, "raw": raw}
    text, thought, response_id = _extract_text(raw)
    return {"text": text, "thought": thought, "response_id": response_id, "raw": raw}



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
) -> dict[str, Any]:
    """
    函数名: chat_text
    作用: 纯文本一轮 chat
    输入:
        user_text (str): 用户正文
        其余同 chat
    输出:
        dict: text / thought / response_id / raw
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
