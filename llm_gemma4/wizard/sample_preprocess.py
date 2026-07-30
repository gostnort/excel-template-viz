"""Ghost 样本预处理：构建 index 字典供步骤 3 字段匹配。"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core_split import (
    is_brace_json,
    json_to_indexed_dict,
    parts_to_indexed_dict,
    split_by_determiner,
)


@dataclass
class IndexedBuildResult:
    indexed_segments: dict[int, str]
    determiner: str | list[str]
    sample_kind: str
    reason: str = ""
    cleaned_preview: str = ""


def _extract_bracket_list(text: str, start: int) -> list[str]:
    bracket = text.find("[", start)
    if bracket < 0:
        return []
    depth = 0
    for pos in range(bracket, len(text)):
        ch = text[pos]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                raw_list = text[bracket:pos + 1]
                try:
                    parsed = ast.literal_eval(raw_list)
                except (SyntaxError, ValueError):
                    return []
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
                return []
    return []



def parse_determiner_reply(text: str) -> tuple[list[str], str]:
    """
    函数名: parse_determiner_reply
    作用: 从 Gemma determiner 回复中解析分隔符列表与 cleaned string
    输入:
        text (str): 模型回复全文
    输出:
        tuple[list[str], str]: (determiners, cleaned_string)
    """
    determiners: list[str] = []
    cleaned = ""
    det_block = re.search(
        r"(?:\*\*)?Determiners?(?:\*\*)?\s*:?",
        text,
        re.IGNORECASE,
    )
    if det_block:
        determiners = _extract_bracket_list(text, det_block.start())
    if not determiners:
        inline = re.search(r"`(\[[^\]]+\])`", text)
        if inline:
            determiners = _extract_bracket_list(text, inline.start(1))
    clean_anchor = re.search(
        r"\*\*Cleaned String\*\*\s*:?\s*|\bCleaned String\s*:?\s*",
        text,
        re.IGNORECASE,
    )
    if clean_anchor:
        tail = text[clean_anchor.end():].lstrip("\n").strip()
        if tail.startswith("`"):
            end = tail.find("`", 1)
            cleaned = tail[1:end].strip() if end > 0 else tail.strip("`").strip()
        else:
            cleaned = tail.split("\n\n")[0].strip().strip("`").strip()
        cleaned = re.sub(r"^\*\*\s*", "", cleaned).strip()
    return determiners, cleaned



def normalize_determiner(value: Any, fallback: str | list[str] = "\t") -> str | list[str]:
    """
    函数名: normalize_determiner
    作用: 将模型或配置中的 determiner 规范为 str 或 list[str]（保留完整列表）
    输入:
        value (Any): 原始 determiner 值
        fallback (str | list[str]): 回退分隔符
    输出:
        str | list[str]: 可用分隔符
    """
    if value is None:
        return fallback
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item)
            if text in ("\\t", "tab"):
                text = "\t"
            elif text in ("\\n", "newline"):
                text = "\n"
            if text:
                items.append(text)
        return items if items else fallback
    text = str(value)
    if text in ("\\t", "tab"):
        return "\t"
    if text in ("\\n", "newline"):
        return "\n"
    return text if text else fallback



def build_indexed_segments(
    raw: str,
    *,
    one_shot: Callable[[str], str] | None = None,
) -> IndexedBuildResult:
    """
    函数名: build_indexed_segments
    作用: 将 Ghost 样本预处理为 dict[int,str]；非 JSON 时用 one-shot 推断 determiners 后 split(raw)
    输入:
        raw (str): Ghost 粘贴原文
        one_shot (Callable | None): 独立会话回调（禁止传入 wizard_main）
    输出:
        IndexedBuildResult: index 字典、determiner、样本类型
    """
    normalized = raw.strip()
    if is_brace_json(normalized):
        indexed = json_to_indexed_dict(normalized)
        return IndexedBuildResult(
            indexed_segments=indexed,
            determiner="",
            sample_kind="brace_json",
            reason="structural JSON tokenization",
        )
    if one_shot is None:
        parts = split_by_determiner(normalized, "\t")
        indexed = parts_to_indexed_dict(parts)
        return IndexedBuildResult(
            indexed_segments=indexed,
            determiner="\t",
            sample_kind="plain_text",
            reason="no one-shot callback, fallback tab split",
        )
    reply = one_shot(normalized[:4000])
    determiners, cleaned = parse_determiner_reply(reply)
    if not determiners:
        determiners = [" ", ",", "\t", "\n"]
    det = normalize_determiner(determiners)
    parts = split_by_determiner(normalized, det)
    indexed = parts_to_indexed_dict(parts)
    return IndexedBuildResult(
        indexed_segments=indexed,
        determiner=det,
        sample_kind="plain_text",
        reason="gemma determiner one-shot + split(raw)",
        cleaned_preview=cleaned,
    )
