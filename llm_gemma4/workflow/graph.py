"""Workflow 轻量图运行时代码。

实际 tick 循环由 WorkflowOrchestrator.tick() 驱动；本模块保留 WorkflowInterrupt 供未来图节点接入。
"""

from __future__ import annotations

from llm_gemma4.workflow.state import InterruptPayload


class WorkflowInterrupt(Exception):
    """
    类名: WorkflowInterrupt
    作用: 工作流中断异常，携带中断 payload 供恢复使用
    输入:
        payload (InterruptPayload): 中断信息（kind / expected_input 等）
    输出: 无
    """

    def __init__(self, payload: InterruptPayload) -> None:
        super().__init__(payload.kind if hasattr(payload, "kind") else str(payload))
        self.payload = payload


class WorkflowGraph:
    """
    类名: WorkflowGraph
    作用: 轻量图运行时占位；路由由 toml_config.decision.decide() 承担
    输入: 无（构造时可传回调）
    输出: 无
    """

    def __init__(self) -> None:
        self._node_handlers: dict[str, callable] = {}

    def register(self, name: str, handler: callable) -> None:
        self._node_handlers[name] = handler

    def run(self, thread_id: str, state: dict | None = None) -> bool:
        return True  # Phase A 最小实现：直接返回成功
