"""工作流图运行时：action 节点 + 动态 router，dispatch 驱动 Continue/Interrupt。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from llm_gemma4.workflow.checkpoint import MemoryCheckpoint
from llm_gemma4.workflow.events import (
    EVENT_CONTINUE,
    EVENT_ERROR,
    EVENT_FINISHED,
    EVENT_INTERRUPT,
    EVENT_RESUME,
    EVENT_START,
    EVENT_STOP,
    WorkflowEvent,
)
from llm_gemma4.workflow.state import Decision, ExecutorResult, InterruptPayload

DEFAULT_MAX_CYCLES = 24


class WorkflowInterrupt(Exception):
    """
    类名: WorkflowInterrupt
    作用: 同一 dispatch 内第二次中断时抛出，强制单节点单中断
    输入:
        payload (InterruptPayload): 中断信息（kind / expected_input 等）
    输出: 无
    """

    def __init__(self, payload: InterruptPayload) -> None:
        super().__init__(payload.kind if hasattr(payload, "kind") else str(payload))
        self.payload = payload



def ensure_single_interrupt(
    already: InterruptPayload | None,
    incoming: InterruptPayload,
) -> InterruptPayload:
    """
    函数名: ensure_single_interrupt
    作用: 同一 dispatch 只允许一次中断；第二次抛 WorkflowInterrupt
    输入:
        already (InterruptPayload | None): 本轮已记录的中断
        incoming (InterruptPayload): 当前节点返回的中断
    输出:
        InterruptPayload: 第一次中断原样返回
    """
    if already is not None:
        raise WorkflowInterrupt(incoming)
    return incoming



class GraphDispatchContext(Protocol):
    """
    类名: GraphDispatchContext
    作用: Graph.dispatch 所需的状态/执行回调协议（由 Orchestrator 实现）。
        state 只需具备 is_finished；不绑定 toml_config 的 WorkflowState。
    """

    state: Any
    thread_id: str

    def apply_resume(self, payload: dict[str, Any]) -> None:
        ...

    def apply_start_payload(self, payload: dict[str, Any]) -> None:
        ...

    def note_decision(self, decision: Decision) -> None:
        ...

    def run_handler(
        self,
        handler: Callable[..., ExecutorResult],
        decision: Decision,
    ) -> ExecutorResult:
        ...

    def note_result(self, decision: Decision, result: ExecutorResult) -> None:
        ...

    def save_interrupt(self, interrupt: InterruptPayload) -> None:
        ...

    def on_stop(self) -> None:
        ...



class CompiledWorkflow:
    """
    类名: CompiledWorkflow
    作用: 编译后的图：dispatch 入站事件，内部 Continue 直到 Interrupt/Finished/Error
    输入:
        nodes (dict): action_id → handler
        router (Callable): user_input → Decision
        checkpointer (MemoryCheckpoint): 中断快照存储
        max_cycles (int): 内部 Continue 上限（与旧 UI auto-chain 24 对齐）
    输出: 无
    """

    def __init__(
        self,
        nodes: dict[str, Callable[..., ExecutorResult]],
        router: Callable[[dict[str, Any] | None], Decision],
        checkpointer: MemoryCheckpoint,
        max_cycles: int = DEFAULT_MAX_CYCLES,
    ) -> None:
        self._nodes = dict(nodes)
        self._router = router
        self._checkpointer = checkpointer
        self._max_cycles = max_cycles

    def dispatch(
        self,
        event: WorkflowEvent,
        ctx: GraphDispatchContext,
        *,
        max_cycles: int | None = None,
    ) -> WorkflowEvent:
        """
        函数名: dispatch
        作用: 处理 start/resume；循环 router→节点直至中断、完成或错误
        输入:
            event (WorkflowEvent): 入站事件
            ctx (GraphDispatchContext): 编排上下文
            max_cycles (int | None): 覆盖编译时上限；1 表示单轮（tick 兼容）
        输出:
            WorkflowEvent: interrupt / finished / error / continue / stop
        """
        if event.type == EVENT_STOP:
            ctx.on_stop()
            return WorkflowEvent(type=EVENT_STOP)
        if event.type not in (EVENT_START, EVENT_RESUME):
            return WorkflowEvent(
                type=EVENT_ERROR,
                payload={"reason": f"unsupported inbound event: {event.type}"},
            )
        # 中文注释: resume 或「启动时已有挂起中断」都先合并 UI payload 并清 checkpoint
        payload = dict(event.payload or {})
        interrupted = self._checkpointer.is_interrupted(ctx.thread_id)
        if event.type == EVENT_RESUME or interrupted:
            ctx.apply_resume(payload)
            user_input: dict[str, Any] | None = payload
        else:
            if payload:
                ctx.apply_start_payload(payload)
                user_input = payload
            else:
                user_input = None
        limit = self._max_cycles if max_cycles is None else max_cycles
        if limit < 1:
            limit = 1
        seen_interrupt: InterruptPayload | None = None
        for cycle in range(limit):
            if ctx.state.is_finished:
                return WorkflowEvent(type=EVENT_FINISHED)
            decision = self._router(user_input)
            user_input = None
            ctx.note_decision(decision)
            if decision.next_action == "error":
                return WorkflowEvent(
                    type=EVENT_ERROR,
                    payload={"reason": decision.reason or "decision error"},
                )
            if ctx.state.is_finished and decision.action_id != "finalize_toml":
                return WorkflowEvent(type=EVENT_FINISHED)
            handler = self._nodes.get(decision.action_id)
            if handler is None:
                return WorkflowEvent(
                    type=EVENT_ERROR,
                    payload={"reason": f"unknown graph node: {decision.action_id}"},
                )
            result = ctx.run_handler(handler, decision)
            ctx.note_result(decision, result)
            if result.interrupt is not None:
                seen_interrupt = ensure_single_interrupt(seen_interrupt, result.interrupt)
                ctx.save_interrupt(result.interrupt)
                return WorkflowEvent(
                    type=EVENT_INTERRUPT,
                    payload={"kind": result.interrupt.kind},
                    interrupt=result.interrupt,
                )
            if ctx.state.is_finished:
                return WorkflowEvent(type=EVENT_FINISHED)
            # 中文注释: 计算成功则内部 Continue；单轮 tick 在此返回 continue
            if cycle + 1 >= limit:
                if limit == 1:
                    return WorkflowEvent(type=EVENT_CONTINUE)
                return WorkflowEvent(
                    type=EVENT_ERROR,
                    payload={"reason": "continue cap exceeded"},
                )
        return WorkflowEvent(
            type=EVENT_ERROR,
            payload={"reason": "continue cap exceeded"},
        )



class WorkflowGraph:
    """
    类名: WorkflowGraph
    作用: 注册 action 节点与动态 router，compile 得到 CompiledWorkflow
    输入: 无（构造时可传回调）
    输出: 无
    """

    def __init__(self) -> None:
        self._node_handlers: dict[str, Callable[..., ExecutorResult]] = {}
        self._router: Callable[[dict[str, Any] | None], Decision] | None = None

    def add_node(self, name: str, handler: Callable[..., ExecutorResult]) -> None:
        """
        函数名: add_node
        作用: 注册一个 action 节点
        输入:
            name (str): action_id
            handler (Callable): 节点处理函数
        输出: 无
        """
        self._node_handlers[name] = handler

    def register(self, name: str, handler: Callable[..., ExecutorResult]) -> None:
        """
        函数名: register
        作用: add_node 的别名（兼容旧占位 API）
        输入:
            name (str): action_id
            handler (Callable): 节点处理函数
        输出: 无
        """
        self.add_node(name, handler)

    def set_router(self, fn: Callable[[dict[str, Any] | None], Decision]) -> None:
        """
        函数名: set_router
        作用: 设置动态路由（通常包装 decide()，不是静态边）
        输入:
            fn (Callable): user_input → Decision
        输出: 无
        """
        self._router = fn

    def compile(
        self,
        checkpointer: MemoryCheckpoint,
        *,
        max_cycles: int = DEFAULT_MAX_CYCLES,
    ) -> CompiledWorkflow:
        """
        函数名: compile
        作用: 冻结节点表与 router，绑定 checkpointer
        输入:
            checkpointer (MemoryCheckpoint): 中断检查点
            max_cycles (int): 内部 Continue 上限
        输出:
            CompiledWorkflow: 可 dispatch 的编译图
        """
        if self._router is None:
            raise ValueError("WorkflowGraph.set_router() must be called before compile()")
        return CompiledWorkflow(
            self._node_handlers,
            self._router,
            checkpointer,
            max_cycles=max_cycles,
        )

    def run(self, thread_id: str, state: dict | None = None) -> bool:
        """
        函数名: run
        作用: 旧占位 API；真实循环请用 compile().dispatch
        输入:
            thread_id (str): 线程标识（忽略）
            state (dict | None): 状态（忽略）
        输出:
            bool: 恒为 True
        """
        return True
