"""文本拆分与 JSON index 字典构建（向导与 UiProvider 共用）。"""

from __future__ import annotations

import re

_JSON_STRUCTURAL = frozenset("{}[]:,\n")


def is_brace_json(raw: str) -> bool:
    """
    函数名: is_brace_json
    作用: 判断 trim 后是否同时包含大括号，视为 JSON 类样本
    输入:
        raw (str): Ghost 粘贴原文
    输出:
        bool: 含 { 与 } 时为 True
    """
    stripped = raw.strip()
    return "{" in stripped and "}" in stripped



def split_by_determiner(raw: str, determiner: str | list[str]) -> list[str]:
    """
    函数名: split_by_determiner
    作用: 按 TOML determiner 拆分文本；引号内内容视为原子，不被分隔符切开
    输入:
        raw (str): 待拆分原文
        determiner (str | list[str]): 分隔符
    输出:
        list[str]: 拆分后的段列表
    """
    if isinstance(determiner, list):
        dets = [d for d in determiner if d is not None and str(d) != ""]
        if not dets:
            return [raw]
    else:
        dets = [determiner]
    # 引号原子：先抽出 "..." / '...'，用占位符保护后再 re.split
    placeholders: list[str] = []
    def _protect(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x00Q{len(placeholders) - 1}\x00"
    protected = re.sub(r'"[^"]*"|\'[^\']*\'', _protect, raw)
    pattern = "|".join(re.escape(d) for d in sorted(dets, key=len, reverse=True))
    chunks = re.split(pattern, protected)
    restored: list[str] = []
    for chunk in chunks:
        for i, quoted in enumerate(placeholders):
            chunk = chunk.replace(f"\x00Q{i}\x00", quoted)
        restored.append(chunk)
    return restored



def _strip_non_printable(text: str) -> str:
    # isprintable 保留 CJK 等 Unicode 可打印字符
    return "".join(c for c in text if c.isprintable() or c in "\t\n\r")



def json_to_indexed_dict(raw: str) -> dict[int, str]:
    """
    函数名: json_to_indexed_dict
    作用: 移除 JSON 结构符后按 token 构建 index→value 字典（保留空串 ""）
    输入:
        raw (str): 含大括号的 JSON 类文本
    输出:
        dict[int, str]: 连续下标到 token 值的映射
    """
    text = _strip_non_printable(raw.strip())
    for ch in _JSON_STRUCTURAL:
        text = text.replace(ch, " ")
    token_pattern = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
    tokens: list[str] = []
    for match in token_pattern.finditer(text):
        quoted = match.group(1)
        single_quoted = match.group(2)
        bare = match.group(3)
        # 引号 token（含空串 ""）一律保留；仅跳过未匹配分支
        if quoted is not None:
            tokens.append(quoted)
        elif single_quoted is not None:
            tokens.append(single_quoted)
        elif bare:
            tokens.append(bare)
    return {idx: token for idx, token in enumerate(tokens)}



def tokenize_cleaned_string(cleaned: str) -> list[str]:
    """
    函数名: tokenize_cleaned_string
    作用: 按引号块与空白切分 Gemma cleaned string（保留空串 ""）
    输入:
        cleaned (str): 模型返回的 cleaned string
    输出:
        list[str]: token 列表
    """
    token_pattern = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')
    tokens: list[str] = []
    for match in token_pattern.finditer(cleaned):
        quoted = match.group(1)
        single_quoted = match.group(2)
        bare = match.group(3)
        # 引号 token（含空串 ""）一律保留；与 json_to_indexed_dict 一致
        if quoted is not None:
            tokens.append(quoted)
        elif single_quoted is not None:
            tokens.append(single_quoted)
        elif bare:
            tokens.append(bare)
    return tokens



def parts_to_indexed_dict(parts: list[str]) -> dict[int, str]:
    """
    函数名: parts_to_indexed_dict
    作用: 将 determiner 拆分后的段列表转为 index 字典，跳过空段
    输入:
        parts (list[str]): 拆分后的段
    输出:
        dict[int, str]: 连续下标字典
    """
    indexed: dict[int, str] = {}
    idx = 0
    for part in parts:
        stripped = part.strip().strip('"').strip("'")
        if stripped:
            indexed[idx] = stripped
            idx += 1
    return indexed



def indexed_dict_to_parts(indexed: dict[int, str]) -> list[str]:
    """
    函数名: indexed_dict_to_parts
    作用: 将 index 字典按 key 排序还原为段列表
    输入:
        indexed (dict[int, str]): index 字典
    输出:
        list[str]: 有序段列表
    """
    if not indexed:
        return []
    max_idx = max(indexed.keys())
    return [indexed.get(i, "") for i in range(max_idx + 1)]
