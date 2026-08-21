"""字段 JSON 解析：将 LLM 回复解析为结构化数据。

Phase A: 与 wizard/parse_field_json.py 完全一致（无 wizard 导入）。
"""

from __future__ import annotations

import json
from typing import Any


class ParseFieldError(Exception):
    """JSON 解析失败异常，携带原始文本以供重试提示。"""

    def __init__(self, message: str = "", raw_text: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.raw_text = raw_text


def parse_field_json(text: str) -> Any:
    """
    函数名: parse_field_json
    作用: 从 LLM 回复文本中提取 JSON，失败时返回 ParseFieldError（供 pass2 重试）
    输入:
        text (str): LLM 回复全文
    输出:
        dict | ParseFieldError: 解析结果或错误
    """
    # 尝试提取最外层的 JSON 对象
    try:
        start = _find_json_start(text)
        if start < 0:
            raise ValueError("no JSON object found")
        end = text.rfind("}", start)
        if end < 0:
            raise ValueError("unterminated JSON")
        json_str = text[start:end + 1]
        try:
            return json.loads(json_str, strict=False)
        except (json.JSONDecodeError, ValueError):
            # 尝试宽松解析：提取第一个完整 { ... } 块
            inner_start = _find_json_brace(text, start)
            if inner_start < 0:
                raise ParseFieldError("无法从回复中提取 JSON", text[:500])
            end = _find_json_brace_end(text, inner_start)
            if end < 0:
                raise ParseFieldError("无法从回复中提取 JSON", text[:500])
            try:
                return json.loads(text[inner_start:end], strict=False)
            except (json.JSONDecodeError, ValueError):
                raise ParseFieldError(
                    f"JSON 解析失败: {text[start:start+200]!r}", text[:500]
                )
    except ParseFieldError:
        raise
    except Exception as exc:
        raise ParseFieldError(f"未知错误: {exc}", text[:500]) from exc


def _find_json_start(text: str) -> int:
    """查找文本中最外层的 JSON 对象起始位置。"""
    # 跳过引号内的内容（简单实现：逐字符扫描）
    in_string = False
    escape_next = False
    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == '\\' and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        # 不在引号内，寻找 { 或 [
        if ch in ('{', '['):
            return i
    return -1


def _find_json_brace(text: str, start: int) -> int:
    """从 start 位置找到第一个 { 的起始索引。"""
    brace = text.find('{', start)
    return brace


def _find_json_brace_end(text: str, start: int) -> int:
    """从 start 位置找到匹配 } 之后的结束索引（不含）。"""
    brace = text.find('{', start)
    if brace < 0:
        return -1
    depth = 0
    for i in range(brace, len(text)):
        ch = text[i]
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
    return -1
