"""Playwright 自带 Chromium 会话；失败返回短错误，不抛穿 CLI。"""

from __future__ import annotations

import atexit
import threading
from pathlib import Path
from typing import Any, Callable

from playwright.sync_api import sync_playwright


_SESSION: "BrowserSession | None" = None
_LOCK = threading.Lock()
status_hook: Callable[[str], None] | None = None


def emit_status(msg: str) -> None:
    """
    函数名: emit_status
    作用: 可选进度钩子；未设置则静默
    输入:
        msg (str): 短状态
    输出: 无
    """
    hook = status_hook
    if hook is None:
        return
    try:
        hook(msg)
    except Exception:
        return


def _missing_hint() -> str:
    """
    函数名: _missing_hint
    作用: 未装 Playwright Chromium 时的安装说明（不要求用户级 Chrome）
    输入: 无
    输出:
        str
    """
    return (
        "Playwright Chromium not found. From repo root: "
        ".\\uv_run.ps1 playwright install chromium. "
        "A user-level Chrome install is not required."
    )


def probe_playwright() -> dict[str, Any]:
    """
    函数名: probe_playwright
    作用: 探活自带 Chromium，不打开搜索页
    输入: 无
    输出:
        dict: ok / how / message / exe
    """
    try:
        with sync_playwright() as pw:
            exe = Path(str(pw.chromium.executable_path or ""))
            if not exe.is_file():
                return {
                    "ok": False,
                    "how": "",
                    "exe": str(exe),
                    "message": f"playwright: down. {_missing_hint()}",
                }
            return {
                "ok": True,
                "how": "bundled chromium",
                "exe": str(exe),
                "message": f"playwright: up (bundled chromium at {exe.name})",
            }
    except Exception as exc:
        return {
            "ok": False,
            "how": "",
            "exe": "",
            "message": f"playwright: down ({exc}). {_missing_hint()}",
        }


class BrowserSession:
    """
    类名: BrowserSession
    作用: 复用一个 headless Chromium，按次开页
    """

    def __init__(self) -> None:
        self._pw: Any = None
        self.browser: Any = None
        self.context: Any = None


    def start(self) -> None:
        """
        函数名: start
        作用: 拉起 Playwright 自带 Chromium
        输入: 无
        输出: 无
        """
        emit_status("playwright: launching bundled chromium")
        self._pw = sync_playwright().start()
        exe = Path(str(self._pw.chromium.executable_path or ""))
        if not exe.is_file():
            self.close()
            raise RuntimeError(_missing_hint())
        self.browser = self._pw.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.context = self.browser.new_context(
            locale="en-US",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
            ),
        )
        emit_status("playwright: ready")


    def new_page(self) -> Any:
        """
        函数名: new_page
        作用: 在现有 context 开一页
        输入: 无
        输出:
            Page
        """
        if self.context is None:
            raise RuntimeError("Playwright session is not running")
        return self.context.new_page()


    def close(self) -> None:
        """
        函数名: close
        作用: 关掉浏览器与 Playwright 驱动
        输入: 无
        输出: 无
        """
        context = self.context
        browser = self.browser
        pw = self._pw
        self.context = None
        self.browser = None
        self._pw = None
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


def ensure_session() -> BrowserSession:
    """
    函数名: ensure_session
    作用: 懒启动全局 Playwright 会话
    输入: 无
    输出:
        BrowserSession
    """
    global _SESSION
    with _LOCK:
        if _SESSION is not None and _SESSION.browser is not None:
            return _SESSION
        session = BrowserSession()
        session.start()
        _SESSION = session
        return session


def close_session() -> None:
    """
    函数名: close_session
    作用: 关掉全局 Playwright 会话
    输入: 无
    输出: 无
    """
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            return
        _SESSION.close()
        _SESSION = None


atexit.register(close_session)
