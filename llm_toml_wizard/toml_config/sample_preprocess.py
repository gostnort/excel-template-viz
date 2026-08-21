"""Ghost 样本预处理与结构识别：index 字典构建 + OCR JSON 扁平化 + determiner 推断。

Phase A: 合并 wizard/sample_preprocess.py + sample_analysis.py，更新导入路径。
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core_split import (
    is_brace_json,
    json_to_indexed_dict,
    parts_to_indexed_dict,
    split_by_determiner as _core_split_by_determiner,
)
from llm_toml_wizard.toml_config.parse_field_json import ParseFieldError, parse_field_json


@dataclass
class IndexedBuildResult:
    indexed_segments: dict[int, str]
    determiner: str | list[str]
    sample_kind: str
    reason: str = ""
    cleaned_preview: str = ""


def normalize_key(key: str) -> str:
    return key.replace(" ", "").replace("\u3000", "")


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


def detect_ocr_json(raw: str) -> dict | None:
    """
    函数名: detect_ocr_json
    作用: 判断 Ghost 样本是否为合法 OCR JSON
    输入:
        raw (str): Ghost 粘贴原文
    输出:
        dict | None: OCR dict 或 None
    """
    stripped = raw.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        data = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("ok") is False:
        return None
    return data


def flat_kv_from_sample(raw: str, ocr_data: dict | None = None) -> dict[str, str]:
    """
    函数名: flat_kv_from_sample
    作用: 从 OCR JSON 提取扁平 key→value
    输入:
        raw (str): Ghost 原文
        ocr_data (dict | None): 已解析 OCR dict
    输出:
        dict[str, str]: 扁平键值对
    """
    data = ocr_data if ocr_data is not None else detect_ocr_json(raw)
    if data is None:
        return {}
    from app.core_store import _ocr_json_to_flat_kv
    return _ocr_json_to_flat_kv(data)


def lookup_flat_kv(label: str, flat: dict[str, str]) -> tuple[str, str] | None:
    """
    函数名: lookup_flat_kv
    作用: 在 OCR 扁平 KV 中查找字段（精确/规范化/唯一模糊）
    输入:
        label (str): Input_label
        flat (dict[str,str]): OCR 扁平键值
    输出:
        tuple[str, str] | None: (match_type, value) 或 None
    """
    if not flat:
        return None
    norm_target = normalize_key(label)
    if label in flat:
        return "exact", flat[label]
    for key, value in flat.items():
        if normalize_key(key) == norm_target:
            return "exact", value
    candidates: list[str] = []
    for key, value in flat.items():
        norm_key = normalize_key(key)
        if label in key or key in label or norm_target in norm_key or norm_key in norm_target:
            candidates.append(value)
    if len(candidates) == 1:
        return "fuzzy", candidates[0]
    return None


def field_likely_in_sample(
    label: str,
    flat: dict[str, str],
    raw_sample: str,
    draft_val: str = "",
) -> bool:
    """
    函数名: field_likely_in_sample
    作用: 判断字段是否可能在样本中出现（用于可选字段不误报 error）
    输入:
        label (str): Input_label
        flat (dict[str, str]): OCR 扁平键值
        raw_sample (str): Ghost 原文
        draft_val (str): 用户 draft 中的值
    输出:
        bool: 可能存在时为 True
    """
    if draft_val and draft_val in raw_sample:
        return True
    if lookup_flat_kv(label, flat) is not None:
        return True
    norm_target = normalize_key(label)
    for key, value in flat.items():
        norm_key = normalize_key(key)
        if norm_target in norm_key or norm_key in norm_target:
            return True
        if draft_val and draft_val in value:
            return True
    return False


def find_segment_index(label: str, parts: list[str], draft_val: str = "") -> int:
    """
    函数名: find_segment_index
    作用: 在 determiner 拆分后的段列表中启发式查找字段 index
    输入:
        label (str): Input_label
        parts (list[str]): 拆分后的段
        draft_val (str): draft 中的值
    输出:
        int: 匹配段下标，未找到为 -1
    """
    norm_label = normalize_key(label)
    if draft_val:
        for idx, part in enumerate(parts):
            if draft_val in part:
                return idx
    for idx, part in enumerate(parts):
        norm_part = normalize_key(part)
        if norm_label in norm_part or norm_part in norm_label:
            return idx
        if label in part or part in label:
            return idx
    return -1


def parse_structure_reply(text: str) -> dict[str, Any] | ParseFieldError:
    """
    函数名: parse_structure_reply
    作用: 解析主对话返回的样本结构 JSON
    输入:
        text (str): 模型回复
    输出:
        dict | ParseFieldError: 结构信息或错误
    """
    parsed = parse_field_json(text)
    if isinstance(parsed, ParseFieldError):
        return parsed
    kind = str(parsed.get("sample_kind") or "plain_text").strip().lower()
    if kind not in ("brace_json", "plain_text", "ocr_json"):
        kind = "brace_json" if kind == "json" else "plain_text"
    return {
        "sample_kind": kind,
        "reason": str(parsed.get("reason") or ""),
    }


def coerce_determiner(value: Any, fallback: str | list[str] = "\t") -> str | list[str]:
    """
    函数名: coerce_determiner
    作用: 将模型返回的 determiner 规范为单字符串或字符串列表
    输入:
        value (Any): 模型 JSON 中的 determiner
        fallback (str | list[str]): 回退分隔符
    输出:
        str | list[str]: 可用分隔符
    """
    return normalize_determiner(value, fallback)


def split_by_determiner(raw: str, determiner: str | list[str]) -> list[str]:
    """
    函数名: split_by_determiner
    作用: 按 determiner 拆分纯文本样本（委托 app.core_split）
    输入:
        raw (str): 样本文本
        determiner (str | list[str]): 分隔符
    输出:
        list[str]: 拆分后的段列表
    """
    return _core_split_by_determiner(raw, determiner)


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
        determiners = ["\t"] if "\t" in normalized else [" ", ",", "\t", "\n"]
    # 样本含制表符时只用 tab，避免空格拆碎公司名等字段
    if "\t" in normalized:
        det = "\t"
    else:
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
