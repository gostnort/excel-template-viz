"""通用对话编排：Graph start/resume/stop + 主会话 + decide + 子代理动作。"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable

from llm_lmstudio import config
from llm_lmstudio.backend import LlmBackend, SessionOptions
from llm_toml_wizard.dialog.actions import ACTION_HANDLERS
from llm_toml_wizard.dialog.decide import decide
from llm_toml_wizard.dialog.spec import DialogSpec
from llm_toml_wizard.dialog.state import (
    DialogState,
    IntakeNeed,
    init_progress,
    upsert_intake,
)
from llm_toml_wizard.workflow.checkpoint import MemoryCheckpoint
from llm_toml_wizard.workflow.events import (
    EVENT_RESUME,
    EVENT_START,
    EVENT_STOP,
    WorkflowEvent,
)
from llm_toml_wizard.workflow.graph import CompiledWorkflow, WorkflowGraph
from llm_toml_wizard.workflow.state import Decision, ExecutorResult, InterruptPayload


def _state_snapshot(state: DialogState) -> dict[str, Any]:
    """
    函数名: _state_snapshot
    作用: 将 DialogState 序列化为检查点字典
    输入:
        state (DialogState): 当前状态
    输出:
        dict[str, Any]: 可 JSON 化快照
    """
    snap = asdict(state)
    snap["intake"] = [asdict(item) for item in state.intake]
    return snap


def _state_from_snapshot(snap: dict[str, Any]) -> DialogState:
    """
    函数名: _state_from_snapshot
    作用: 从检查点恢复 DialogState
    输入:
        snap (dict[str, Any]): 快照
    输出:
        DialogState: 恢复后的状态
    """
    raw_intake = snap.get("intake") or []
    needs: list[IntakeNeed] = []
    for item in raw_intake:
        if isinstance(item, IntakeNeed):
            needs.append(item)
        elif isinstance(item, dict) and item.get("key"):
            needs.append(
                IntakeNeed(
                    key=str(item.get("key") or ""),
                    question=str(item.get("question") or ""),
                    required=bool(item.get("required", True)),
                )
            )
    state = DialogState()
    for key, value in snap.items():
        if key == "intake":
            continue
        if hasattr(state, key):
            setattr(state, key, value)
    state.intake = needs
    return state


def _merge_payload(state: DialogState, payload: dict[str, Any]) -> None:
    """
    函数名: _merge_payload
    作用: 将用户恢复数据写入 facts / goal（不覆盖空值）
    输入:
        state (DialogState): 当前状态
        payload (dict): start/resume 载荷
    输出: 无
    """
    if not payload:
        return
    if payload.get("goal"):
        state.goal = str(payload.get("goal") or "")
        state.facts["goal"] = state.goal
        state.progress["goal"] = "done"
    incoming_facts = payload.get("facts")
    if isinstance(incoming_facts, dict):
        for key, value in incoming_facts.items():
            text = str(value or "").strip()
            if not text:
                continue
            state.facts[str(key)] = text
            state.progress[str(key)] = "done"
            if str(key) == "goal" and not state.goal:
                state.goal = text
    fact_key = str(payload.get("fact_key") or "").strip()
    if fact_key:
        text = str(payload.get("fact_value") or "").strip()
        state.facts[fact_key] = text
        state.progress[fact_key] = "done" if text else state.progress.get(fact_key, "pending")
        if fact_key == "goal" and text:
            state.goal = text


class DialogOrchestrator:
    """
    类名: DialogOrchestrator
    作用: 域无关的主对话 + 动态 intake + 子代理分派；toml_config 不是依赖
    """

    def __init__(
        self,
        backend: LlmBackend,
        spec: DialogSpec,
        *,
        stub: bool = False,
        thread_id: str = "dialog:default",
        on_progress: Callable[[str], None] | None = None,
        on_chat: Callable[[str, str], None] | None = None,
    ) -> None:
        """
        函数名: __init__
        作用: 绑定后端与域插件，编译通用 Graph
        输入:
            backend (LlmBackend): 推理后端
            spec (DialogSpec): 对话域插件
            stub (bool): True 时 decide 走固定顺序
            thread_id (str): 检查点键
            on_progress / on_chat: 日志回调
        输出: 无
        """
        self._backend = backend
        self.spec = spec
        self._stub = stub
        self._thread_id = thread_id
        self._on_progress = on_progress or (lambda _msg: None)
        self._on_chat = on_chat or (lambda _role, _text: None)
        self.state = DialogState(domain=spec.name)
        upsert_intake(self.state, list(spec.initial_intake))
        self.state.progress = init_progress(self.state.intake)
        self._checkpoint = MemoryCheckpoint()
        self._main_session_id = "dialog_main"
        self._main_opened = False
        self._thinking_budget_cached: int | None = None
        self.last_event: WorkflowEvent | None = None
        # 中文注释: 域 spec 可替换节点表；BriefingSpec 仍用通用五动作
        self._handlers = spec.get_action_handlers() or dict(ACTION_HANDLERS)
        graph = WorkflowGraph()
        for name, handler in self._handlers.items():
            graph.add_node(name, handler)
        graph.set_router(self._route)
        self._compiled: CompiledWorkflow = graph.compile(self._checkpoint)


    @property
    def thread_id(self) -> str:
        """
        函数名: thread_id
        作用: 检查点线程标识
        输入: 无
        输出:
            str: thread_id
        """
        return self._thread_id

    def is_interrupted(self) -> bool:
        """
        函数名: is_interrupted
        作用: 是否有未恢复中断
        输入: 无
        输出:
            bool: 中断中为 True
        """
        return self._checkpoint.is_interrupted(self._thread_id)

    @property
    def pending_interrupt(self) -> InterruptPayload | None:
        """
        函数名: pending_interrupt
        作用: 当前挂起的中断
        输入: 无
        输出:
            InterruptPayload | None
        """
        raw = self.state.pending_interrupt
        if raw is None:
            return None
        if isinstance(raw, InterruptPayload):
            return raw
        if isinstance(raw, dict) and raw.get("kind"):
            return InterruptPayload(
                kind=str(raw.get("kind") or ""),
                expected_input=str(raw.get("expected_input") or ""),
                auto_chain=bool(raw.get("auto_chain")),
                meta=dict(raw.get("meta") or {}),
            )
        return None

    def _progress(self, msg: str) -> None:
        """
        函数名: _progress
        作用: 转发进度日志
        输入:
            msg (str): 日志行
        输出: 无
        """
        self._on_progress(msg)


    def _chat(self, role: str, text: str) -> None:
        """
        函数名: _chat
        作用: 转发主/子会话文本
        输入:
            role (str): user / assistant
            text (str): 正文
        输出: 无
        """
        self._on_chat(role, text)


    def _thinking_budget(self) -> int:
        """
        函数名: _thinking_budget
        作用: 按硬件 profile 取 pass2 thinking token 预算
        输入: 无
        输出:
            int: thinking_budget
        """
        if self._thinking_budget_cached is None:
            health = self._backend.health_check()
            self._thinking_budget_cached = config.load_thinking_budget(
                health.profile, litert_backend=health.litert_backend
            )
        return self._thinking_budget_cached


    def _ensure_main_session(self) -> None:
        """
        函数名: _ensure_main_session
        作用: 打开持久 dialog_main（thinking=False）
        输入: 无
        输出: 无
        """
        if not self._main_opened:
            self._backend.open_session(
                self._main_session_id,
                options=SessionOptions(system_message=self.spec.main_system, thinking=False),
            )
            self._main_opened = True

    def _main_turn(self, user_body: str) -> str:
        """
        函数名: _main_turn
        作用: 持久 dialog_main 会话发送一轮（thinking 关闭）
        输入:
            user_body (str): 本轮任务正文
        输出:
            str: 模型回复
        """
        self._ensure_main_session()
        content = self.spec.main_prefix(self.state) + user_body
        self._chat("user", content)
        session = self._backend.open_session(self._main_session_id)
        result = session.send_turn({"role": "user", "content": content})
        self._chat("assistant", result.text)
        return result.text


    def _route(self, user_input: dict[str, Any] | None) -> Decision:
        """
        函数名: _route
        作用: Graph 动态路由：decide()
        输入:
            user_input (dict | None): 本轮恢复数据
        输出:
            Decision: 下一步
        """
        custom = self.spec.route_decision(
            self.state,
            self._backend,
            user_input,
            stub=self._stub,
        )
        if custom is not None:
            return custom
        return decide(
            self.state,
            self.spec,
            self._backend,
            user_input,
            stub=self._stub,
        )

    def apply_resume(self, payload: dict[str, Any]) -> None:
        """
        函数名: apply_resume
        作用: 从检查点恢复并合并用户事实
        输入:
            payload (dict): 用户恢复数据
        输出: 无
        """
        snap = self._checkpoint.get_snapshot(self._thread_id)
        if snap:
            self.state = _state_from_snapshot(snap)
        self._checkpoint.clear(self._thread_id)
        merged = dict(payload or {})
        _merge_payload(self.state, merged)
        self.spec.merge_resume(self.state, merged)
        self.state.pending_interrupt = None

    def apply_start_payload(self, payload: dict[str, Any]) -> None:
        """
        函数名: apply_start_payload
        作用: 启动载荷写入状态
        输入:
            payload (dict): 启动数据
        输出: 无
        """
        merged = dict(payload or {})
        _merge_payload(self.state, merged)
        self.spec.merge_resume(self.state, merged)

    def note_decision(self, decision: Decision) -> None:
        """
        函数名: note_decision
        作用: 记录 decide 结果
        输入:
            decision (Decision): 本轮决策
        输出: 无
        """
        self._progress(f"[decide] {decision.action_id} ({decision.next_action}): {decision.reason}")
        self.state.history.append({"decision": asdict(decision)})

    def run_handler(self, handler: Callable[..., ExecutorResult], decision: Decision) -> ExecutorResult:
        """
        函数名: run_handler
        作用: 按 action_id 执行通用动作（handler 参数仅满足 Graph 协议）
        输入:
            handler (Callable): 图节点（忽略，改查 ACTION_HANDLERS）
            decision (Decision): 本轮决策
        输出:
            ExecutorResult: 执行结果
        """
        ctx = {
            "main_turn": self._main_turn,
            "thinking_budget": self._thinking_budget(),
        }
        extra = self.spec.handler_ctx(
            self._backend,
            on_chat=self._chat,
            on_progress=self._progress,
            thinking_budget=int(ctx["thinking_budget"]),
        )
        if extra:
            ctx.update(extra)
        custom = self.spec.execute_action(
            decision,
            self.state,
            self._backend,
            on_progress=self._progress,
            on_chat=self._chat,
            ctx=ctx,
        )
        if custom is not None:
            return custom
        fn = self._handlers.get(decision.action_id)
        if fn is None:
            return ExecutorResult(
                ok=False,
                messages=[f"unknown action_id: {decision.action_id}"],
                state_patch={},
                route_key=decision.action_id,
            )
        return fn(
            self.state,
            self.spec,
            self._backend,
            on_progress=self._progress,
            on_chat=self._chat,
            ctx=ctx,
        )

    def note_result(self, decision: Decision, result: ExecutorResult) -> None:
        """
        函数名: note_result
        作用: 合并补丁并写日志
        输入:
            decision (Decision): 本轮决策
            result (ExecutorResult): 节点结果
        输出: 无
        """
        for key, value in (result.state_patch or {}).items():
            if hasattr(self.state, key):
                setattr(self.state, key, value)
        # 中文注释: 动作内已通过 on_progress 即时打日志，此处不再重放 messages
        self.spec.after_result(self.state, decision, result, stub=self._stub)
        self.state.history.append({
            "result_ok": result.ok,
            "waiting_input": result.interrupt is not None,
            "route_key": result.route_key,
        })
        self.state.route_key = result.route_key or decision.route_key

    def save_interrupt(self, interrupt: InterruptPayload) -> None:
        """
        函数名: save_interrupt
        作用: 写入 MemoryCheckpoint
        输入:
            interrupt (InterruptPayload): 中断描述
        输出: 无
        """
        self._checkpoint.save_interrupt(
            self._thread_id,
            _state_snapshot(self.state),
            asdict(interrupt),
        )
        self.state.pending_interrupt = asdict(interrupt)

    def on_stop(self) -> None:
        """
        函数名: on_stop
        作用: 关闭持久主会话
        输入: 无
        输出: 无
        """
        self.close()

    def dispatch(self, event: WorkflowEvent) -> WorkflowEvent:
        """
        函数名: dispatch
        作用: 处理 start/resume/stop；内部 Continue 直到 interrupt/finished/error
        输入:
            event (WorkflowEvent): 入站事件
        输出:
            WorkflowEvent: 出站事件
        """
        if event.type == EVENT_STOP:
            self.on_stop()
            outbound = WorkflowEvent(type=EVENT_STOP)
            self.last_event = outbound
            return outbound
        outbound = self._compiled.dispatch(event, self)
        self.last_event = outbound
        return outbound

    def tick(self, payload: dict[str, Any] | None = None) -> DialogState:
        """
        函数名: tick
        作用: 单轮 decide→execute（测试用）
        输入:
            payload (dict | None): 恢复数据
        输出:
            DialogState: 更新后状态
        """
        if self.state.is_finished:
            return self.state
        event_type = EVENT_RESUME if self.is_interrupted() else EVENT_START
        self._compiled.dispatch(
            WorkflowEvent(type=event_type, payload=dict(payload or {})),
            self,
            max_cycles=1,
        )
        return self.state

    def close(self) -> None:
        """
        函数名: close
        作用: 关闭 dialog_main
        输入: 无
        输出: 无
        """
        if self._main_opened:
            try:
                session = self._backend.open_session(self._main_session_id)
                session.close()
            except Exception:
                pass
            self._main_opened = False
