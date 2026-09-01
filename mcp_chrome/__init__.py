"""Chrome DevTools MCP + 谷歌搜索。启动失败返回错误字符串，不抛穿 CLI。"""

from mcp_chrome.search import google_search
from mcp_chrome.session import close_session

__all__ = ["close_session", "google_search"]
