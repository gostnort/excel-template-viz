"""并行执行工具：带限线程池的 map 操作。"""

from __future__ import annotations

import threading
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar

T = TypeVar("T")


def map_send(
    fn: Callable[[str], T],
    items: list[str],
    cap: int = 2,
) -> list[T]:
    """
    函数名: map_send
    作用: 用 Semaphore + ThreadPoolExecutor 并行执行 fn，返回结果列表（顺序对应 items）
    输入:
        fn (Callable): 每个 item 的处理器
        items (list[str]): 输入项列表
        cap (int): 最大并发数
    输出:
        list[T]: 与 items 同序的结果列表
    """
    if not items:
        return []
    results: list[T] = [None] * len(items)
    sem = threading.Semaphore(cap)

    def _worker(idx: int, item: str) -> tuple[int, T]:
        with sem:
            return idx, fn(item)

    with ThreadPoolExecutor(max_workers=cap) as pool:
        futures = {pool.submit(_worker, i, item): i for i, item in enumerate(items)}
        for fut in as_completed(futures):
            idx, result = fut.result()
            results[idx] = result

    return results
