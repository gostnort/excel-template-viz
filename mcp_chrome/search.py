"""google_search：开谷歌并回收可见摘要；失败返回 Error: 字符串。"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote_plus

from mcp_chrome.session import close_session, ensure_session, google_url


_MAX_CHARS = 8000



def google_search(query: str) -> str:
    """
    函数名: google_search
    作用: 用 Chrome DevTools MCP 打开谷歌搜索并取页面可见文本
    输入:
        query (str): 搜索词
    输出:
        str: 摘要或 Error: 前缀的失败说明
    """
    q = str(query or "").strip()
    if not q:
        return "Error: empty search query"
    try:
        session = ensure_session()
        names = session.list_tools()
        url = google_url(q)
        # 中文注释: new_page 必须带 url；后续 page 工具默认要 pageId
        new_page = _pick_tool(names, ("new_page",))
        nav = _pick_tool(names, ("navigate_page", "navigate"))
        snap = _pick_tool(names, ("take_snapshot", "snapshot"))
        list_pages = _pick_tool(names, ("list_pages",))
        page_id: int | None = None
        loaded = False
        if new_page:
            try:
                created = session.call_tool(new_page, {"url": url})
                page_id = _page_id_from(created)
                loaded = True
            except Exception:
                loaded = False
        if page_id is None and list_pages:
            try:
                page_id = _page_id_from(session.call_tool(list_pages, {}))
            except Exception:
                page_id = None
        if not loaded:
            if not nav:
                close_session()
                return "Error: chrome MCP has no navigate tool"
            args: dict[str, Any] = {"url": url, "type": "url"}
            if page_id is not None:
                args["pageId"] = page_id
            try:
                nav_result = session.call_tool(nav, args)
            except Exception:
                try:
                    nav_result = session.call_tool(nav, {"url": url})
                except Exception as exc:
                    close_session()
                    return f"Error: chrome navigate failed ({exc})"
            if page_id is None:
                page_id = _page_id_from(nav_result)
        if not snap:
            close_session()
            return "Error: chrome MCP has no snapshot tool"
        snap_args: dict[str, Any] = {}
        if page_id is not None:
            snap_args["pageId"] = page_id
        try:
            raw = session.call_tool(snap, snap_args)
        except Exception:
            raw = session.call_tool(snap, {})
        text = _result_text(raw)
        if not text:
            return f"Error: empty Google snapshot for {q!r}"
        if len(text) > _MAX_CHARS:
            return text[:_MAX_CHARS]
        return text
    except Exception as exc:
        close_session()
        return f"Error: chrome search failed ({exc})"


def _as_page_id(val: Any) -> int | None:
    """
    函数名: _as_page_id
    作用: 把 MCP 字段收成正整数 pageId
    输入:
        val (Any): 原始值
    输出:
        int | None
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, int) and val > 0:
        return val
    if isinstance(val, float) and val > 0 and val == int(val):
        return int(val)
    if isinstance(val, str) and val.strip().isdigit():
        n = int(val.strip())
        return n if n > 0 else None
    return None


def _walk_page_id(obj: Any) -> int | None:
    """
    函数名: _walk_page_id
    作用: 在 MCP result 树里找 pageId
    输入:
        obj (Any): tools/call 结果
    输出:
        int | None
    """
    if isinstance(obj, dict):
        for key in ("pageId", "page_id"):
            got = _as_page_id(obj.get(key))
            if got is not None:
                return got
        found: list[int] = []
        for val in obj.values():
            got = _walk_page_id(val)
            if got is not None:
                found.append(got)
        if found:
            return found[-1]
        return None
    if isinstance(obj, list):
        found = []
        for item in obj:
            got = _walk_page_id(item)
            if got is not None:
                found.append(got)
        if found:
            return found[-1]
    return None


def _page_id_from(raw: Any) -> int | None:
    """
    函数名: _page_id_from
    作用: 从 new_page / list_pages / navigate 结果抽出 pageId
    输入:
        raw (Any): MCP result
    输出:
        int | None
    """
    walked = _walk_page_id(raw)
    if walked is not None:
        return walked
    text = _result_text(raw)
    if not text:
        return None
    ids: list[int] = []
    for match in re.finditer(r"pageId['\"]?\s*[:=]\s*(\d+)", text, re.I):
        n = int(match.group(1))
        if n > 0:
            ids.append(n)
    if ids:
        return ids[-1]
    for match in re.finditer(r"(?m)^(?:[-*#]\s*)?(\d+)\s*[:.\)]", text):
        n = int(match.group(1))
        if n > 0:
            ids.append(n)
    if ids:
        return ids[-1]
    return None


def _pick_tool(names: list[str], candidates: tuple[str, ...]) -> str | None:
    """
    函数名: _pick_tool
    作用: 按候选名或包含关系选 MCP 工具
    输入:
        names (list): tools/list
        candidates (tuple): 优先名
    输出:
        str | None
    """
    lower = {item.lower(): item for item in names}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    for cand in candidates:
        for item in names:
            if cand.lower() in item.lower():
                return item
    return None



def _result_text(raw: Any) -> str:
    """
    函数名: _result_text
    作用: 从 MCP tools/call 结果抽出文本
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



def search_url(query: str) -> str:
    """
    函数名: search_url
    作用: 暴露给测试的 URL 组装
    输入:
        query (str): 查询
    输出:
        str
    """
    return "https://www.google.com/search?q=" + quote_plus(query or "")
