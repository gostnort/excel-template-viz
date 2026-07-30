"""Ghost 样本结构识别：OCR JSON 扁平化、determiner 推断、字段匹配。"""

from __future__ import annotations

import json
from typing import Any

from app.core_split import split_by_determiner as _core_split_by_determiner
from app.core_store import _ocr_json_to_flat_kv
from llm_gemma4.wizard.parse_field_json import ParseFieldError, parse_field_json
from llm_gemma4.wizard.sample_preprocess import normalize_determiner


def normalize_key(key: str) -> str:
    return key.replace(" ", "").replace("　", "")



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
    return _ocr_json_to_flat_kv(data)



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



def lookup_flat_kv(label: str, flat: dict[str, str]) -> tuple[str, str] | None:
    """
    函数名: lookup_flat_kv
    作用: 在 OCR 扁平 KV 中查找字段（精确/规范化/唯一模糊）
    输入:
        label (str): Input_label
        flat (dict[str, str]): OCR 扁平键值
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
