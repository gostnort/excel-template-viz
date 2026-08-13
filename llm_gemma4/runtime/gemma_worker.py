"""Gemma/LiteRT 专用单线程队列：所有 Engine 调用在同一线程执行。"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, TypeVar

T = TypeVar("T")

_STOP = object()
_queue: queue.Queue[Any] | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()



def _worker_main() -> None:
    # 中文注释: 常驻循环，从队列取任务并在同一线程执行 LiteRT 调用
    assert _queue is not None
    while True:
        item = _queue.get()
        try:
            if item is _STOP:
                break
            fn, args, kwargs, future = item
            if not future.cancelled():
                try:
                    result = fn(*args, **kwargs)
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc)
        finally:
            _queue.task_done()



def _ensure_worker() -> queue.Queue[Any]:
    global _queue, _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return _queue  # type: ignore[return-value]
        _queue = queue.Queue()
        _thread = threading.Thread(
            target=_worker_main,
            name="gemma-worker",
            daemon=True,
        )
        _thread.start()
        return _queue



def run_on_gemma_thread(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
    """
    函数名: run_on_gemma_thread
    作用: 将可调用对象投递到 Gemma 专用工作线程并返回 Future
    输入:
        fn (Callable): 要在工作线程执行的函数（如 StartGemma、tick、EndGemma）
        *args: 位置参数
        **kwargs: 关键字参数
    输出:
        Future[T]: 异步结果句柄
    """
    q = _ensure_worker()
    future: Future[T] = Future()
    q.put((fn, args, kwargs, future))
    return future



def run_on_gemma_thread_blocking(
    fn: Callable[..., T],
    /,
    *args: Any,
    timeout: float | None = None,
    **kwargs: Any,
) -> T:
    """
    函数名: run_on_gemma_thread_blocking
    作用: 同步等待 Gemma 工作线程执行完毕（用于无事件循环的 stop 路径）
    输入:
        fn (Callable): 要执行的函数
        timeout (float | None): 最长等待秒数
        *args: 位置参数
        **kwargs: 关键字参数
    输出:
        T: fn 的返回值
    """
    return run_on_gemma_thread(fn, *args, **kwargs).result(timeout=timeout)



async def await_gemma_thread(fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """
    函数名: await_gemma_thread
    作用: NiceGUI 协程内异步等待 Gemma 工作线程结果，不阻塞事件循环
    输入:
        fn (Callable): 要执行的函数
        *args: 位置参数
        **kwargs: 关键字参数
    输出:
        T: fn 的返回值
    """
    future = run_on_gemma_thread(fn, *args, **kwargs)
    return await asyncio.wrap_future(future)
