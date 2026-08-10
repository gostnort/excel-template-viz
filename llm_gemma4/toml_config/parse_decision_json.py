"""决策 JSON 解析：从 Gemma decide 回复提取结构化决策。"""

from __future__ import annotations

import json
from typing import Any

from llm_gemma4.toml_config.parse_field_json import _find_json_brace, _find_json_start


class ParseDecisionError(Exception):
    """决策 JSON 解析失败。"""

    def __init__(self, message: str = "", raw_text: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.raw_text = raw_text


_REQUIRED_KEYS = ("next_action", "action_id")


def parse_decision_json(text: str) -> dict[str, Any]:
    """
    函数名: parse_decision_json
    作用: 从 LLM 回复中提取含 next_action、action_id 的 JSON 对象
    输入:
        text (str): LLM 回复全文
    输出:
        dict[str, Any]: 解析后的决策字典
    """
    try:
        start = _find_json_start(text)
        if start < 0:
            raise ValueError("no JSON object found")
        end = text.rfind("}", start)
        if end < 0:
            raise ValueError("unterminated JSON")
        json_str = text[start:end + 1]
        try:
            data = json.loads(json_str, strict=False)
        except (json.JSONDecodeError, ValueError):
            inner_start = _find_json_brace(text, start)
            if inner_start < 0:
                raise ParseDecisionError("无法从回复中提取 JSON", text[:500])
            brace_end = _find_json_brace(text, start)
            if brace_end < 0:
                raise ParseDecisionError("JSON 花括号未闭合", text[:500])
            data = json.loads(text[start:brace_end + 1], strict=False)
        if not isinstance(data, dict):
            raise ParseDecisionError("决策 JSON 必须是对象", text[:500])
        for key in _REQUIRED_KEYS:
            if key not in data:
                raise ParseDecisionError(f"缺少必填键 {key!r}", text[:500])
        return data
    except ParseDecisionError:
        raise
    except Exception as exc:
        raise ParseDecisionError(f"未知错误: {exc}", text[:500]) from exc
