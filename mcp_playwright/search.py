"""web_search：用 Playwright 打开 Bing 并回收结果摘要。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

from mcp_playwright.session import close_session, emit_status, ensure_session


_MAX_CHARS = 6000
_MAX_HITS = 8
_NAV_TIMEOUT_MS = 25000


def web_search(query: str) -> str:
    """
    函数名: web_search
    作用: 用自带 Chromium 打开 bing.com 搜索并抽取可见结果
    输入:
        query (str): 搜索词（陌生名词、术语、代码）
    输出:
        str: 摘要或 Error: 前缀的失败说明
    """
    q = str(query or "").strip()
    if not q:
        return "Error: empty search query"
    page: Any = None
    try:
        emit_status(f"playwright: bing search {q!r}")
        session = ensure_session()
        page = session.new_page()
        page.set_default_timeout(_NAV_TIMEOUT_MS)
        page.goto(bing_url(q), wait_until="domcontentloaded")
        _dismiss_consent(page)
        page.wait_for_selector("#b_results .b_algo", timeout=_NAV_TIMEOUT_MS)
        text = _bing_results(page)
        if not text:
            return f"Error: empty Bing results for {q!r}"
        if len(text) > _MAX_CHARS:
            return text[:_MAX_CHARS]
        return text
    except Exception as exc:
        close_session()
        return f"Error: bing search failed ({exc})"
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass


def bing_url(query: str) -> str:
    """
    函数名: bing_url
    作用: 组装 Bing 搜索 URL
    输入:
        query (str): 查询串
    输出:
        str
    """
    return "https://www.bing.com/search?q=" + quote_plus(query or "")


def _dismiss_consent(page: Any) -> None:
    """
    函数名: _dismiss_consent
    作用: 点掉 Bing Cookie 条（有则点，没有就跳过）
    输入:
        page: Playwright Page
    输出: 无
    """
    for sel in ("#bnp_btn_accept", "#bnp_btn_reject", "button[id*='bnp_btn_accept']"):
        loc = page.locator(sel)
        try:
            if loc.count() < 1:
                continue
            if loc.first.is_visible():
                loc.first.click(timeout=1500)
                return
        except Exception:
            continue


def _bing_results(page: Any) -> str:
    """
    函数名: _bing_results
    作用: 抽 #b_results 里前若干条标题和摘要，避免整页 DOM
    输入:
        page: Playwright Page
    输出:
        str
    """
    cards = page.locator("#b_results .b_algo")
    try:
        total = int(cards.count())
    except Exception:
        total = 0
    bits: list[str] = []
    limit = total if total < _MAX_HITS else _MAX_HITS
    # 中文注释: 只要标题 + 短摘要，不把整页可访问性树交给模型
    for idx in range(limit):
        block = cards.nth(idx)
        title = _inner(block.locator("h2 a").first, 400)
        snippet = _inner(block.locator(".b_caption p, .b_lineclamp, .b_algoSlug").first, 700)
        if not snippet:
            snippet = _inner(block, 700)
        if not title and not snippet:
            continue
        if title and snippet:
            bits.append(f"{title}\n{snippet}")
        else:
            bits.append(title or snippet)
    if bits:
        return "\n\n".join(bits).strip()
    body = _inner(page.locator("body"), _MAX_CHARS)
    return body.strip()


def _inner(locator: Any, cap: int) -> str:
    """
    函数名: _inner
    作用: 读 locator 可见文本并截断
    输入:
        locator: Playwright Locator
        cap (int): 最大字符
    输出:
        str
    """
    try:
        raw = str(locator.inner_text(timeout=2000) or "").strip()
    except Exception:
        return ""
    if len(raw) > cap:
        return raw[:cap]
    return raw
