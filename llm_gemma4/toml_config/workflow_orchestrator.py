"""Workflow orchestrator: Graph dispatch (start/resume/stop) + decide/execute nodes.

NiceGUI compatibility facade: keeps WorkflowState + interrupt kinds (ask_sources /
ask_layout / ask_sample / ask_db_id). CLI uses TomlGuideSpec + DialogOrchestrator
instead; this module must keep toml_wizard imports working.

Phase B: Gemma-driven decide() replaces hard-coded stub (stub available via WORKFLOW_DECIDE_STUB=1).
NiceGUI LLM work runs on the Gemma worker thread; UI main thread does not block.
"""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from llm_gemma4 import config
from llm_gemma4.backends.base import LlmBackend, SessionOptions
from llm_gemma4.toml_config.context import build_main_turn_prefix
from llm_gemma4.toml_config.decision import decide
from llm_gemma4.toml_config.design_doc import build_design_doc
from llm_gemma4.toml_config.executor import ACTION_HANDLERS, execute
from llm_gemma4.toml_config.intake_plan import build_intake_plan, init_progress
from llm_gemma4.toml_config.intake_seed import sidecar_data_sources
from llm_gemma4.toml_config.payload import merge_payload_into_state, merge_state_patch
from llm_gemma4.toml_config.prompts import DETERMINER_PROMPT, MAIN_SYSTEM_PROMPT
from llm_gemma4.workflow.checkpoint import MemoryCheckpoint
from llm_gemma4.workflow.events import (
    EVENT_RESUME,
    EVENT_START,
    EVENT_STOP,
    WorkflowEvent,
)
from llm_gemma4.workflow.graph import CompiledWorkflow, WorkflowGraph
from llm_gemma4.workflow.state import (
    Decision,
    ExecutorResult,
    FieldState,
    InterruptPayload,
    WorkflowState,
)


def _stub_mode() -> bool:
    return os.environ.get("WORKFLOW_DECIDE_STUB", "").strip() in ("1", "true", "yes")


def _state_snapshot(state: WorkflowState) -> dict[str, Any]:
    """
    函数名: _state_snapshot
    作用: 将 WorkflowState 序列化为可存入 checkpoint 的字典快照
    输入:
        state (WorkflowState): 当前工作流状态
    输出:
        dict[str, Any]: 可 JSON 化的状态快照
    """
    snap = asdict(state)
    tpath = snap.get("template_path")
    if tpath is not None:
        snap["template_path"] = str(tpath)
    return snap


def _state_from_snapshot(snap: dict[str, Any]) -> WorkflowState:
    """
    函数名: _state_from_snapshot
    作用: 从 checkpoint 快照反序列化 WorkflowState
    输入:
        snap (dict[str, Any]): 序列化状态字典
    输出:
        WorkflowState: 恢复后的状态对象
    """
    state = WorkflowState()
    fields_raw = snap.get("fields") or {}
    for key, value in snap.items():
        if key == "fields":
            continue
        if key == "template_path":
            state.template_path = Path(str(value)) if value else None
            continue
        if hasattr(state, key):
            setattr(state, key, value)
    restored_fields: dict[str, FieldState] = {}
    for label, fdata in fields_raw.items():
        if isinstance(fdata, FieldState):
            restored_fields[str(label)] = fdata
        elif isinstance(fdata, dict):
            restored_fields[str(label)] = FieldState(
                **{k: v for k, v in fdata.items() if k in FieldState.__dataclass_fields__}
            )
    state.fields = restored_fields
    return state


class WorkflowOrchestrator:
    """
    类名: WorkflowOrchestrator
    作用: Graph dispatch 驱动 Gemma decide + executor 节点；支持中断/恢复与持久 wizard_main 会话
    输入: LlmBackend 与 UI 回调
    输出: 无
    """

    def __init__(
        self,
        backend: LlmBackend,
        on_progress: Callable[[str], None] | None = None,
        on_chat: Callable[[str, str], None] | None = None,
        on_match_notify: Callable[[str], None] | None = None,
        *,
        thread_id: str = "user:admin:workflow",
    ) -> None:
        self._backend = backend
        self._on_progress = on_progress or (lambda _msg: None)
        self._on_chat = on_chat or (lambda _role, _text: None)
        self._on_match_notify = on_match_notify or (lambda _msg: None)
        self.state = WorkflowState()
        self._checkpoint = MemoryCheckpoint()
        self._thread_id = thread_id
        self._stub_index = 0
        self._main_session_id = "wizard_main"
        self._main_opened = False
        self._thinking_budget_cached: int | None = None
        self._ui_lock = threading.Lock()
        self.last_event: WorkflowEvent | None = None
        self._last_intake_pending: list[str] = []
        graph = WorkflowGraph()
        for name, handler in ACTION_HANDLERS.items():
            graph.add_node(name, handler)
        graph.set_router(self._route)
        self._compiled: CompiledWorkflow = graph.compile(self._checkpoint)

    def init_workflow(
        self,
        template_id: str,
        template_path: Path,
        labels: list[str],
    ) -> None:
        """
        函数名: init_workflow
        作用: 向导启动时填充 design_doc、progress 与模板元数据
        输入:
            template_id (str): 模板 ID
            template_path (Path): 模板 xlsx 路径
            labels (list[str]): 字段标签
        输出: 无
        """
        self.state.template_id = template_id
        self.state.template_path = template_path
        self.state.template_labels = list(labels)
        self.state.design_doc = build_design_doc(template_id, template_path, labels)
        self.state.progress = init_progress(labels)
        # 信任 sidecar [[sources]]：已有 Google URL 时预填，避免仅 OAuth 才视为已采集
        seeded = sidecar_data_sources(template_id)
        if seeded and not self.state.data_sources:
            self.state.data_sources = seeded
            progress = dict(self.state.progress or {})
            has_google = any(
                ds.get("type") == "google_sheet" or ds.get("source1")
                for ds in seeded
            )
            progress["data_sources"] = "done" if has_google else "skip"
            self.state.progress = progress

    @property
    def thread_id(self) -> str:
        """
        函数名: thread_id
        作用: Graph 检查点使用的线程标识
        输入: 无
        输出:
            str: thread_id
        """
        return self._thread_id

    def is_interrupted(self) -> bool:
        """
        函数名: is_interrupted
        作用: 是否存在未恢复的中断
        输入: 无
        输出:
            bool: 中断中为 True
        """
        return self._checkpoint.is_interrupted(self._thread_id)

    @property
    def pending_interrupt(self) -> InterruptPayload | None:
        """
        函数名: pending_interrupt
        作用: 返回当前挂起的中断 payload
        输入: 无
        输出:
            InterruptPayload | None: 中断描述
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

    def reset_state(self) -> None:
        """
        函数名: reset_state
        作用: 重置工作流状态与 stub 索引（向导重开时调用）
        输入: 无
        输出: 无
        """
        template_id = self.state.template_id
        template_path = self.state.template_path
        labels = list(self.state.template_labels or [])
        self.close()
        self.state = WorkflowState()
        self._stub_index = 0
        self._checkpoint.clear(self._thread_id)
        if template_id and template_path:
            self.init_workflow(template_id, template_path, labels)

    def _progress(self, msg: str) -> None:
        with self._ui_lock:
            self._on_progress(msg)

    def _chat(self, role: str, text: str) -> None:
        with self._ui_lock:
            self._on_chat(role, text)

    def _match_notify(self, msg: str) -> None:
        with self._ui_lock:
            self._on_match_notify(msg)

    def _thinking_budget(self) -> int:
        if self._thinking_budget_cached is None:
            health = self._backend.health_check()
            self._thinking_budget_cached = config.load_thinking_budget(
                health.profile, litert_backend=health.litert_backend
            )
        return self._thinking_budget_cached

    def _ensure_main_session(self) -> None:
        if not self._main_opened:
            self._backend.open_session(
                self._main_session_id,
                options=SessionOptions(system_message=MAIN_SYSTEM_PROMPT, thinking=False),
            )
            self._main_opened = True

    def _main_turn(self, user_body: str) -> str:
        """
        函数名: _main_turn
        作用: 通过持久 wizard_main 会话发送一轮主对话
        输入:
            user_body (str): 用户消息正文
        输出:
            str: 模型回复文本
        """
        self._ensure_main_session()
        prefix = build_main_turn_prefix(self.state)
        content = prefix + user_body
        self._chat("user", content)
        session = self._backend.open_session(self._main_session_id)
        result = session.send_turn({"role": "user", "content": content})
        self._chat("assistant", result.text)
        return result.text

    def _determiner_one_shot(self, sample_excerpt: str) -> str:
        """
        函数名: _determiner_one_shot
        作用: 独立会话推断 plain-text determiners（禁止走 wizard_main）
        输入:
            sample_excerpt (str): 样本文本截断
        输出:
            str: 模型回复文本
        """
        sid = f"wizard_determiner_{uuid.uuid4().hex[:8]}"
        opts = SessionOptions(
            system_message=DETERMINER_PROMPT,
            thinking=False,
            max_tokens=512,
        )
        user_content = f"## Input data\n\n```\n{sample_excerpt}\n```"
        self._chat("user", f"[determiner] {user_content}")
        session = self._backend.open_session(sid, options=opts)
        try:
            result = session.send_turn({"role": "user", "content": user_content})
            self._chat("assistant", f"[determiner] {result.text}")
            return result.text
        finally:
            session.close()

    def _route(self, user_input: dict[str, Any] | None) -> Decision:
        """
        函数名: _route
        作用: Graph 动态路由：build_intake_plan + decide()
        输入:
            user_input (dict | None): 本轮 UI 输入（仅 resume/start 首轮非空）
        输出:
            Decision: 下一步动作
        """
        intake = build_intake_plan(self.state)
        decision, self._stub_index = decide(
            self.state,
            user_input,
            intake,
            self._backend,
            stub_index=self._stub_index,
        )
        self._last_intake_pending = [item.key for item in intake if item.status == "pending"]
        return decision

    def apply_resume(self, payload: dict[str, Any]) -> None:
        """
        函数名: apply_resume
        作用: 从 checkpoint 恢复快照并合并 UI payload，然后清除中断
        输入:
            payload (dict): UI 恢复数据
        输出: 无
        """
        snap = self._checkpoint.get_snapshot(self._thread_id)
        if snap:
            self.state = _state_from_snapshot(snap)
        self._checkpoint.clear(self._thread_id)
        merge_payload_into_state(self.state, dict(payload or {}))
        self.state.pending_interrupt = None

    def apply_start_payload(self, payload: dict[str, Any]) -> None:
        """
        函数名: apply_start_payload
        作用: 启动事件携带的初始 payload 合并进 state（不清 checkpoint）
        输入:
            payload (dict): 启动数据（template_id / data_sources 等）
        输出: 无
        """
        merge_payload_into_state(self.state, dict(payload or {}))

    def note_decision(self, decision: Decision) -> None:
        """
        函数名: note_decision
        作用: 记录 decide 结果到日志与 history，并合并 context_update
        输入:
            decision (Decision): 本轮决策
        输出: 无
        """
        reason = decision.reason or decision.action_id
        self._progress(f"[decide] {decision.action_id} ({decision.next_action}): {reason}")
        pending = getattr(self, "_last_intake_pending", [])
        self.state.history.append({
            "decision": asdict(decision),
            "intake_pending": list(pending),
        })
        if decision.context_update:
            merge_payload_into_state(self.state, decision.context_update)
        if decision.next_action == "error":
            self._progress(f"decision error: {decision.reason}")

    def run_handler(self, handler: Callable[..., ExecutorResult], decision: Decision) -> ExecutorResult:
        """
        函数名: run_handler
        作用: 通过 execute() 跑已注册节点（保留 skip-interrupt 守卫）
        输入:
            handler (Callable): 图节点（execute 按 action_id 再查 ACTION_HANDLERS）
            decision (Decision): 本轮决策
        输出:
            ExecutorResult: 执行结果
        """
        return execute(
            decision,
            self.state,
            self._backend,
            on_progress=self._progress,
            on_chat=self._chat,
            on_match_notify=self._match_notify,
            main_turn=self._main_turn,
            determiner_one_shot=self._determiner_one_shot,
            thinking_budget=self._thinking_budget(),
        )

    def note_result(self, decision: Decision, result: ExecutorResult) -> None:
        """
        函数名: note_result
        作用: 合并 executor patch、写进度日志与 history
        输入:
            decision (Decision): 本轮决策
            result (ExecutorResult): 节点执行结果
        输出: 无
        """
        merge_state_patch(self.state, result.state_patch)
        for msg in result.messages:
            self._progress(msg)
        route = result.route_key or decision.route_key
        if route == "skip_sheet":
            self._progress("[sheet_match] skipped — no Google source")
        elif route == "already_have":
            self._progress("[workflow] skip ask — already captured")
        self.state.history.append({
            "result_ok": result.ok,
            "waiting_input": result.interrupt is not None,
            "route_key": result.route_key,
            "interrupt": asdict(result.interrupt) if result.interrupt else None,
        })
        if result.ok and result.interrupt is None and _stub_mode():
            self._stub_index += 1
        self.state.route_key = result.route_key or decision.route_key

    def save_interrupt(self, interrupt: InterruptPayload) -> None:
        """
        函数名: save_interrupt
        作用: 将状态快照与中断 payload 写入 MemoryCheckpoint
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
        作用: Stop 事件回调，关闭持久会话
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

    def tick(self, payload: dict[str, Any] | None = None) -> WorkflowState:
        """
        函数名: tick
        作用: 单轮 decide→execute（不内部 Continue）；测试/调试兼容入口
        输入:
            payload (dict | None): UI 恢复/步骤数据
        输出:
            WorkflowState: 更新后的状态
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
        作用: 关闭持久 wizard_main 会话
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
