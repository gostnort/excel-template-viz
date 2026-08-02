"""Windows asyncio 噪音抑制：浏览器断开 WebSocket/TCP 时的 WinError 10054 等。"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any


def _is_benign_win_transport_reset(exc: BaseException | None) -> bool:
    """
    函数名: _is_benign_win_transport_reset
    作用: 判断是否为客户端主动断开导致的 Windows 传输层错误（可安全忽略）
    输入:
        exc (BaseException | None): asyncio 回调上下文中的异常
    输出:
        bool: 可忽略则为 True
    """
    if exc is None:
        return False
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in (10054, 10053):
        return True
    return False


def _win_asyncio_exception_handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """
    函数名: _win_asyncio_exception_handler
    作用: 过滤 Proactor 在连接被远端关闭时的 ConnectionResetError，其余走默认处理
    输入:
        loop (AbstractEventLoop): 当前事件循环
        context (dict[str, Any]): asyncio 异常上下文
    输出: 无
    """
    if _is_benign_win_transport_reset(context.get("exception")):
        return
    # Proactor 回调里 exception 有时为空，仅 message 描述 connection_lost
    message = str(context.get("message") or "")
    if "_call_connection_lost" in message and "_ProactorBasePipeTransport" in message:
        return
    loop.default_exception_handler(context)


class _SuppressWinConnResetLog(logging.Filter):
    """
    类名: _SuppressWinConnResetLog
    作用: 日志层兜底，避免 asyncio 将同类断开错误打印到控制台
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        函数名: filter
        作用: 丢弃含 WinError 10054 / connection_lost 的 asyncio 日志行
        输入:
            record (logging.LogRecord): 日志记录
        输出:
            bool: False 表示不输出
        """
        msg = record.getMessage()
        if "ConnectionResetError" in msg or "WinError 10054" in msg:
            return False
        if "_ProactorBasePipeTransport" in msg and "_call_connection_lost" in msg:
            return False
        return True


def install_win_asyncio_reset_filter() -> None:
    """
    函数名: install_win_asyncio_reset_filter
    作用: 在 ui.run 之前安装 Windows 事件循环异常处理与日志过滤
    输入: 无
    输出: 无
    """
    if sys.platform != "win32":
        return
    policy = asyncio.get_event_loop_policy()
    orig_new = policy.new_event_loop
    # 包装策略：uvicorn 新建循环时自动挂上异常处理器
    def _new_event_loop_with_handler() -> asyncio.AbstractEventLoop:
        """
        函数名: _new_event_loop_with_handler
        作用: 创建事件循环并注册 Windows 传输层断开过滤
        输入: 无
        输出:
            AbstractEventLoop: 已设置 exception_handler 的循环
        """
        loop = orig_new()
        loop.set_exception_handler(_win_asyncio_exception_handler)
        return loop
    policy.new_event_loop = _new_event_loop_with_handler
    log_filter = _SuppressWinConnResetLog()
    for name in ("asyncio", "uvicorn.error", "uvicorn"):
        logging.getLogger(name).addFilter(log_filter)
