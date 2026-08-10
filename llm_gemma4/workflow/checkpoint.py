"""中断检查点：保存 / 恢复 WorkflowState + InterruptPayload。"""

from __future__ import annotations

from typing import Any


class MemoryCheckpoint:
    """内存检查点，按 thread_id 存储状态快照与中断 payload。"""

    def __init__(self) -> None:
        self._store: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    def is_interrupted(self, thread_id: str) -> bool:
        """
        函数名: is_interrupted
        作用: 检查指定线程是否有未恢复的中断
        输入:
            thread_id (str): 线程标识
        输出:
            bool: 存在中断时为 True
        """
        return thread_id in self._store

    def get_interrupt(self, thread_id: str) -> dict[str, Any] | None:
        """
        函数名: get_interrupt
        作用: 获取指定线程的中断 payload
        输入:
            thread_id (str): 线程标识
        输出:
            InterruptPayload 数据或 None
        """
        if thread_id not in self._store:
            return None
        _, payload = self._store[thread_id]
        return payload

    def get_snapshot(self, thread_id: str) -> dict[str, Any] | None:
        """
        函数名: get_snapshot
        作用: 获取中断时保存的 WorkflowState 快照
        输入:
            thread_id (str): 线程标识
        输出:
            dict[str, Any] | None: 状态快照或 None
        """
        if thread_id not in self._store:
            return None
        state, _ = self._store[thread_id]
        return state

    def save_interrupt(
        self,
        thread_id: str,
        state: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        """
        函数名: save_interrupt
        作用: 保存状态快照与中断 payload，设置 pending_interrupt
        输入:
            thread_id (str): 线程标识
            state (dict): WorkflowState 序列化数据
            payload (dict): InterruptPayload 序列化数据
        输出: 无
        """
        self._store[thread_id] = (state, payload)

    def resume(
        self,
        thread_id: str,
        user_value: dict | None,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        函数名: resume
        作用: 合并用户输入到状态，清除中断标志
        输入:
            thread_id (str): 线程标识
            user_value (dict | None): 用户提供的恢复值
            state (dict): WorkflowState 序列化数据（可能为空占位）
        输出:
            dict[str, Any]: 合并后的状态
        """
        if user_value is not None and len(user_value) > 0:
            # 用户输入：合并到 state 中
            state.update({
                "user_inputs": {
                    k: v for k, v in user_value.items()
                    if isinstance(v, (str, int, float, bool)) or isinstance(v, list) and all(
                        isinstance(x, (str, int, float, bool)) for x in v
                    )
                }
            })
        # 清除中断记录
        self._store.pop(thread_id, None)
        return state

    def clear(self, thread_id: str) -> None:
        """
        函数名: clear
        作用: 清除指定线程的中断记录
        输入:
            thread_id (str): 线程标识
        输出: 无
        """
        self._store.pop(thread_id, None)
