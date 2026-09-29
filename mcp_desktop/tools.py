"""wikipedia_lookup / read_local_file：经 desktop-commander read_file。"""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import quote, quote_plus

from mcp_desktop.session import close_session, emit_status, ensure_session


_MAX_CHARS = 6000


def wikipedia_lookup(term: str) -> str:
    """
    函数名: wikipedia_lookup
    作用: 用 desktop-commander 读取 Wikipedia 页面（未知名词首选）
    输入:
        term (str): 术语、专名、条目名
    输出:
        str: 纯文本摘要或 Error: 前缀
    """
    q = str(term or "").strip()
    if not q:
        return "Error: empty wikipedia term"
    title = q.replace(" ", "_")
    url = "https://en.wikipedia.org/wiki/" + quote(title, safe="_()'-")
    try:
        emit_status(f"desktop-commander: wikipedia {q!r}")
        session = ensure_session()
        raw = session.call_tool(
            "read_file",
            {"path": url, "isUrl": True, "origin": "llm"},
        )
        text = _result_text(raw)
        if not text:
            search = "https://en.wikipedia.org/w/index.php?search=" + quote_plus(q)
            raw = session.call_tool(
                "read_file",
                {"path": search, "isUrl": True, "origin": "llm"},
            )
            text = _result_text(raw)
        plain = _html_to_text(text)
        if not plain:
            return f"Error: empty Wikipedia page for {q!r}"
        if len(plain) > _MAX_CHARS:
            return plain[:_MAX_CHARS]
        return plain
    except Exception as exc:
        close_session()
        return f"Error: wikipedia lookup failed ({exc})"


def read_local_file(path: str) -> str:
    """
    函数名: read_local_file
    作用: 用 desktop-commander 读本地文件
    输入:
        path (str): 本地路径
    输出:
        str: 文本或 Error: 前缀
    """
    target = str(path or "").strip()
    if not target:
        return "Error: empty file path"
    try:
        emit_status(f"desktop-commander: read_file {target!r}")
        session = ensure_session()
        raw = session.call_tool("read_file", {"path": target, "origin": "llm"})
        text = _result_text(raw)
        if not text:
            return f"Error: empty file {target!r}"
        if len(text) > _MAX_CHARS:
            return text[:_MAX_CHARS]
        return text
    except Exception as exc:
        close_session()
        return f"Error: read_local_file failed ({exc})"


def _result_text(raw: Any) -> str:
    """
    函数名: _result_text
    作用: 从 MCP tools/call 抽出文本
    输入:
        raw (Any): result
    输出:
        str
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        content = raw.get("content")
        if isinstance(content, list):
            bits: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    bits.append(str(item.get("text") or item.get("data") or ""))
                else:
                    bits.append(str(item))
            return "\n".join(bit for bit in bits if bit).strip()
        if raw.get("text"):
            return str(raw.get("text")).strip()
        return str(raw)[:_MAX_CHARS]
    return str(raw).strip()


def _html_to_text(raw: str) -> str:
    """
    函数名: _html_to_text
    作用: 去掉脚本样式和标签，避免把整页 HTML 交给模型
    输入:
        raw (str): HTML 或纯文本
    输出:
        str
    """
    text = str(raw or "")
    if "<" not in text:
        return text.strip()
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
