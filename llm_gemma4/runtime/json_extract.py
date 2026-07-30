"""从模型 answer 文本抽取单个 JSON 对象（fenced / bare）。"""

from __future__ import annotations

import json
import re

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)



def extract_json_object(text: str) -> tuple[dict | None, str | None]:
    """
    函数名: extract_json_object
    作用: 从模型输出中抽取一个 JSON 对象，容忍 markdown 围栏与前后废话
    输入:
        text (str): 模型 answer 原文
    输出:
        tuple[dict | None, str | None]: (payload, error_message)；成功时 error 为 None
    """
    stripped = text.strip()
    fenced = _FENCED_JSON_RE.search(stripped)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        bare = _BARE_JSON_RE.search(stripped)
        candidate = bare.group(0) if bare else None
    if candidate is None:
        return None, "no JSON object found"
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "parsed JSON is not an object"
    return payload, None
