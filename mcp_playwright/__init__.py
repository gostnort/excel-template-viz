"""Playwright 自带 Chromium + Bing 搜索。启动失败返回错误字符串，不抛穿 CLI。"""

from mcp_playwright.search import web_search
from mcp_playwright.session import close_session, probe_playwright

__all__ = ["close_session", "probe_playwright", "web_search"]
