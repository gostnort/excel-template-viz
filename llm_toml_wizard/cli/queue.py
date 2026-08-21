"""CLI 主轮次 FIFO 队列（仅 CLI；NiceGUI 不做排队）。"""

from __future__ import annotations

import time
from collections import deque
from threading import Condition
from typing import Any


class MainTurnQueue:
    """
    类名: MainTurnQueue
    作用: 线程安全 FIFO，供 dialog repl 把 stdin 行交给 worker 的 dispatch(Resume)
    """

    def __init__(self) -> None:
        """
        函数名: __init__
        作用: 初始化空队列与条件变量
        输入: 无
        输出: 无
        """
        self._items: deque[dict[str, Any]] = deque()
        self._cv = Condition()
        self._closed = False


    def put(self, payload: dict[str, Any]) -> None:
        """
        函数名: put
        作用: 将一轮 Resume 载荷追加到队尾；关闭后拒绝入队
        输入:
            payload (dict): 入队字典；内部拷贝一份，避免调用方后续原地修改
        输出: 无
        """
        with self._cv:
            # 中文注释: 关闭后不再接受新轮次，避免 worker 已退出仍写入
            if self._closed:
                raise RuntimeError("MainTurnQueue is closed")
            self._items.append(dict(payload))
            self._cv.notify()


    def get(self, timeout: float | None = None) -> dict[str, Any] | None:
        """
        函数名: get
        作用: 阻塞取出队首；关闭且空时返回 None；超时未取到也返回 None
        输入:
            timeout (float | None): 最长等待秒数；None 表示等到有数据或关闭
        输出:
            dict | None: 载荷副本；超时或关闭且空则为 None
        """
        with self._cv:
            # 中文注释: 无限等待，直到有元素或队列被 close
            if timeout is None:
                while not self._items and not self._closed:
                    self._cv.wait()
            else:
                # 中文注释: 有限等待，按剩余秒数循环，避免虚假唤醒耗尽超时
                remaining = float(timeout)
                while not self._items and not self._closed and remaining > 0:
                    started = time.monotonic()
                    self._cv.wait(timeout=remaining)
                    remaining -= time.monotonic() - started
            # 中文注释: 关闭后仍先排空已入队载荷，空了才返回 None
            if not self._items:
                return None
            return dict(self._items.popleft())


    def qsize(self) -> int:
        """
        函数名: qsize
        作用: 返回当前队列长度（快照）
        输入: 无
        输出:
            int: 待消费载荷条数
        """
        with self._cv:
            return len(self._items)


    def empty(self) -> bool:
        """
        函数名: empty
        作用: 判断队列是否为空
        输入: 无
        输出:
            bool: 无待消费载荷时为 True
        """
        return self.qsize() == 0


    @property
    def closed(self) -> bool:
        """
        函数名: closed
        作用: 查询队列是否已 close
        输入: 无
        输出:
            bool: 已关闭为 True
        """
        with self._cv:
            return self._closed


    def close(self) -> None:
        """
        函数名: close
        作用: 标记队列结束并唤醒所有等待者；此后 put 会失败
        输入: 无
        输出: 无
        """
        with self._cv:
            self._closed = True
            self._cv.notify_all()
