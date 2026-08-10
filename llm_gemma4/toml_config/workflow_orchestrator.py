"""Workflow orchestrator: ties executor actions + checkpoint together for interrupt-driven tick loop.

Phase B: Gemma-driven decide() replaces hard-coded stub (stub available via WORKFLOW_DECIDE_STUB=1).
NiceGUI LLM work runs on io_bound worker thread; UI main thread does not block.
"""

from __future__ import annotations

import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from llm_gemma4 import config
from llm_gemma4.backends.base import LlmBackend, SessionOptions
from llm_gemma4.toml_config.context import build_main_turn_prefix
from llm_gemma4.toml_config.decision import decide
from llm_gemma4.toml_config.design_doc import build_design_doc
from llm_gemma4.toml_config.executor import execute
from llm_gemma4.toml_config.intake_plan import already_captured, build_intake_plan, init_progress
from llm_gemma4.toml_config.prompts import DETERMINER_PROMPT, MAIN_SYSTEM_PROMPT
from llm_gemma4.workflow.checkpoint import MemoryCheckpoint
from llm_gemma4.workflow.state import FieldState, InterruptPayload, WorkflowState


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


def _sanitize_template_labels(raw: list[Any]) -> list[str]:
    """
    函数名: _sanitize_template_labels
    作用: 去重并过滤空白的 template_labels
    输入:
        raw (list): UI 传入的标签列表
    输出:
        list[str]: 清洗后的标签
    """
    seen: set[str] = set()
    labels: list[str] = []
    for item in raw:
        label = str(item or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels


def _merge_payload_into_state(state: WorkflowState, payload: dict[str, Any]) -> None:
    """
    函数名: _merge_payload_into_state
    作用: 将 UI tick payload 合并进 WorkflowState
    输入:
        state (WorkflowState): 当前状态
        payload (dict): UI 传入字段
    输出: 无
    """
    if not payload:
        return
    if payload.get("template_id"):
        state.template_id = str(payload.get("template_id") or state.template_id)
    tpath = payload.get("template_path")
    if tpath:
        state.template_path = Path(str(tpath))
    if "data_sources" in payload:
        state.data_sources = list(payload.get("data_sources") or [])
    if "input_area" in payload:
        state.input_area = payload.get("input_area") or ""
    if "move_to" in payload:
        state.move_to = payload.get("move_to") or ""
    if "offset" in payload:
        try:
            state.offset = int(payload.get("offset") or 1)
        except (TypeError, ValueError):
            state.offset = 1
    if "ghost_text_sample" in payload:
        state.ghost_text_sample = str(payload.get("ghost_text_sample") or "")
    if "user_draft" in payload:
        draft = payload.get("user_draft") or {}
        state.user_draft = {str(k): str(v) for k, v in draft.items() if str(v or "").strip()}
        state.user_inputs["field_drafts_captured"] = True
    if "template_labels" in payload:
        labels = _sanitize_template_labels(list(payload.get("template_labels") or []))
        state.template_labels = labels
        for label in labels:
            if label not in state.fields:
                from llm_gemma4.workflow.state import FieldState
                state.fields[label] = FieldState(input_label=label)
    if "google_sheet_headers" in payload:
        state.google_sheet_headers = list(payload.get("google_sheet_headers") or [])
    if "google_sheet_sample" in payload:
        state.google_sheet_sample = list(payload.get("google_sheet_sample") or [])
    if "db_id" in payload:
        raw_id = str(payload.get("db_id") or "").strip()
        state.db_id = "" if raw_id in ("", "None") else raw_id
        state.user_inputs["db_id_confirmed"] = True
    if payload.get("data_sources_skipped"):
        state.user_inputs["data_sources_skipped"] = True


def _merge_patch(state: WorkflowState, patch: dict[str, Any]) -> None:
    """
    函数名: _merge_patch
    作用: 将 executor state_patch 写回 dataclass（fields 原地变更不覆盖）
    输入:
        state (WorkflowState): 当前状态
        patch (dict): executor 返回补丁
    输出: 无
    """
    if not patch:
        return
    for key, value in patch.items():
        if key == "fields":
            continue
        if hasattr(state, key):
            setattr(state, key, value)


class WorkflowOrchestrator:
    """
    类名: WorkflowOrchestrator
    作用: tick 驱动 Gemma decide + executor；支持中断/恢复与持久 wizard_main 会话
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
        import uuid
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

    def tick(self, payload: dict[str, Any] | None = None) -> WorkflowState:
        """
        函数名: tick
        作用: decide → execute 一轮；遇中断则挂起等待 UI 恢复
        输入:
            payload (dict | None): UI 恢复/步骤数据
        输出:
            WorkflowState: 更新后的状态
        """
        if self.state.is_finished:
            return self.state
        user_input: dict[str, Any] | None = None
        if self.is_interrupted():
            snap = self._checkpoint.get_snapshot(self._thread_id)
            if snap:
                self.state = _state_from_snapshot(snap)
            user_input = dict(payload or {})
            _merge_payload_into_state(self.state, user_input)
            self._checkpoint.clear(self._thread_id)
            self.state.pending_interrupt = None
        elif payload:
            user_input = dict(payload)
            _merge_payload_into_state(self.state, user_input)
        intake = build_intake_plan(self.state)
        decision, self._stub_index = decide(
            self.state,
            user_input,
            intake,
            self._backend,
            stub_index=self._stub_index,
        )
        reason = decision.reason or decision.action_id
        self._progress(f"[decide] {decision.action_id} ({decision.next_action}): {reason}")
        self.state.history.append({
            "decision": asdict(decision),
            "intake_pending": [item.key for item in intake if item.status == "pending"],
        })
        if decision.context_update:
            _merge_payload_into_state(self.state, decision.context_update)
        if decision.next_action == "error":
            self._progress(f"decision error: {decision.reason}")
            return self.state
        if self.state.is_finished and decision.action_id != "finalize_toml":
            return self.state
        result = execute(
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
        _merge_patch(self.state, result.state_patch)
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
        if result.interrupt:
            self._checkpoint.save_interrupt(
                self._thread_id,
                _state_snapshot(self.state),
                asdict(result.interrupt),
            )
            self.state.pending_interrupt = asdict(result.interrupt)
            return self.state
        if result.ok and _stub_mode():
            self._stub_index += 1
        self.state.route_key = result.route_key or decision.route_key
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
