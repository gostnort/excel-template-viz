"""TOML 向导域插件（weights）：prompts + intake + 九动作；不依赖 NiceGUI。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from app.core_split import is_brace_json
from llm_gemma4.backends.base import SessionOptions
from llm_gemma4.dialog.spec import DialogSpec, SubagentJob
from llm_gemma4.dialog.state import DialogState, IntakeNeed
from llm_gemma4.toml_config.decision import (
    ACTION_CATALOG as TOML_ACTION_CATALOG,
    ALLOWED_ACTION_IDS as TOML_ALLOWED_ACTION_IDS,
    ALLOWED_NEXT_ACTIONS as TOML_ALLOWED_NEXT_ACTIONS,
    DECISION_SYSTEM_PROMPT,
    decide as toml_decide,
)
from llm_gemma4.toml_config.decide_stub import decide_stub as toml_decide_stub
from llm_gemma4.toml_config.executor import ACTION_HANDLERS as TOML_ACTION_HANDLERS, execute
from llm_gemma4.toml_config.intake_plan import INTAKE_KEYS, already_captured, build_intake_plan, init_progress
from llm_gemma4.toml_config.payload import merge_payload_into_state, merge_state_patch
from llm_gemma4.toml_config.prompts import (
    DETERMINER_PROMPT,
    MAIN_SYSTEM_PROMPT,
    PLAN_GHOST_TASKS_PROMPT,
    STEP3_SYSTEM_PROMPT,
    STEP4_SYSTEM_PROMPT,
    STEP5_SYSTEM_PROMPT,
)
from llm_gemma4.workflow.state import Decision, ExecutorResult, WorkflowState


TOML_INTERRUPT_KINDS = frozenset({
    "ask_sources",
    "ask_layout",
    "ask_sample",
    "ask_db_id",
})

_INTAKE_QUESTIONS: dict[str, str] = {
    "data_sources": "配置 Google Sheet 或跳过数据源",
    "input_section": "请提供 input_area / move_to / offset",
    "ghost_sample": "请粘贴 Ghost 样本文本",
    "field_drafts": "请填写字段草稿（可与 Ghost 样本同一中断）",
    "ghost_preprocess": "预处理 indexed_segments（计算步）",
    "field_match": "Ghost 字段匹配（计算步）",
    "sheet_match": "Sheet 列匹配（无 Google 则跳过）",
    "regex_infer": "为 needs_regex 字段推断正则（计算步）",
    "db_id": "确认主键 db_id（可空）",
}

_COMPUTE_INTAKE = frozenset({
    "ghost_preprocess",
    "field_match",
    "sheet_match",
    "regex_infer",
})

TOML_DEMO_GOAL = "用 Ginger 风格制表符样本跑通 TOML 向导（dry-run，不写 sidecar）"

TOML_DEMO_LABELS = ["LotID", "Product", "Qty"]

TOML_DEMO_GHOST = "LotID\t10034\tProduct\tGinger\tQty\t12"

TOML_DEMO_DRAFT = {
    "LotID": "10034",
    "Product": "Ginger",
    "Qty": "12",
}

TOML_DEMO_AUTO: dict[str, dict[str, Any]] = {
    "ask_sources": {"data_sources_skipped": True},
    "ask_layout": {"input_area": "B2:F20", "move_to": "down", "offset": 1},
    "ask_sample": {
        "ghost_text_sample": TOML_DEMO_GHOST,
        "user_draft": dict(TOML_DEMO_DRAFT),
        "template_labels": list(TOML_DEMO_LABELS),
    },
    "ask_db_id": {"db_id": "", "db_id_confirmed": True},
}


def _intake_needs() -> list[IntakeNeed]:
    """
    函数名: _intake_needs
    作用: 按 INTAKE_KEYS 生成 DialogSpec.initial_intake
    输入: 无
    输出:
        list[IntakeNeed]: 采集项（计算步 required=False）
    """
    needs: list[IntakeNeed] = []
    for key in INTAKE_KEYS:
        needs.append(
            IntakeNeed(
                key=key,
                question=_INTAKE_QUESTIONS.get(key, key),
                required=key not in _COMPUTE_INTAKE,
            )
        )
    return needs


def _has_google_source(state: WorkflowState) -> bool:
    """
    函数名: _has_google_source
    作用: 是否配置了 Google Sheet 源
    输入:
        state (WorkflowState): 向导状态袋
    输出:
        bool: 有 google_sheet / source1 时为 True
    """
    return any(
        ds.get("type") == "google_sheet" or ds.get("source1")
        for ds in (state.data_sources or [])
    )


def _dialog_patch(state: DialogState) -> dict[str, Any]:
    """
    函数名: _dialog_patch
    作用: 只回写 DialogState 上存在的字段，避免把 WorkflowState 键塞进通用状态
    输入:
        state (DialogState): 已 sync 的对话状态
    输出:
        dict: note_result 可用的 state_patch
    """
    return {
        "progress": dict(state.progress),
        "artifacts": dict(state.artifacts),
        "facts": dict(state.facts),
        "is_finished": state.is_finished,
        "last_summary": state.last_summary,
        "user_inputs": dict(state.user_inputs),
    }



class TomlGuideSpec(DialogSpec):
    """
    类名: TomlGuideSpec
    作用: TOML 配置向导的 DialogSpec（weights）；NiceGUI 仍用 WorkflowOrchestrator 门面
    """

    def __init__(
        self,
        *,
        write_toml: bool = False,
        template_id: str = "cli_toml_demo",
        on_match_notify: Callable[[str], None] | None = None,
    ) -> None:
        """
        函数名: __init__
        作用: 填入向导 prompts / intake；默认 dry-run 不写 templates/{id}/{id}.toml
        输入:
            write_toml (bool): True 时允许 persist_wizard_toml 落盘
            template_id (str): 演示用模板 id（非生产 sidecar）
            on_match_notify (Callable | None): 字段匹配提醒；None 则回退 on_progress
        输出: 无
        """
        super().__init__(
            name="toml",
            main_system=MAIN_SYSTEM_PROMPT,
            decision_system=DECISION_SYSTEM_PROMPT,
            initial_intake=_intake_needs(),
            plan_intake_user=PLAN_GHOST_TASKS_PROMPT,
            synthesize_user="根据已匹配字段与预处理结果，用中文简述 TOML 向导结论；不要编造未匹配的列。",
        )
        self.write_toml = bool(write_toml)
        self._on_match_notify = on_match_notify
        self.workflow = WorkflowState()
        self.workflow.template_id = template_id
        self.workflow.user_inputs["write_toml"] = self.write_toml
        self.workflow.progress = init_progress([])
        self._stub_index = 0


    def get_action_handlers(self) -> dict[str, Callable[..., ExecutorResult]] | None:
        """
        函数名: get_action_handlers
        作用: 注册 toml executor 的九个 action_id 为 Graph 节点
        输入: 无
        输出:
            dict: action_id → 占位 handler（真正执行走 execute_action）
        """
        return dict(TOML_ACTION_HANDLERS)


    def get_decision_catalog(self) -> str:
        """
        函数名: get_decision_catalog
        作用: 返回 TOML 九动作表
        输入: 无
        输出:
            str: ACTION_CATALOG
        """
        return TOML_ACTION_CATALOG


    def get_allowed_action_ids(self) -> frozenset[str] | None:
        """
        函数名: get_allowed_action_ids
        作用: TOML action_id 白名单
        输入: 无
        输出:
            frozenset[str]
        """
        return TOML_ALLOWED_ACTION_IDS


    def get_allowed_next_actions(self) -> frozenset[str] | None:
        """
        函数名: get_allowed_next_actions
        作用: 含 validate 的 TOML next_action 白名单
        输入: 无
        输出:
            frozenset[str]
        """
        return TOML_ALLOWED_NEXT_ACTIONS


    def get_interrupt_kinds(self) -> frozenset[str]:
        """
        函数名: get_interrupt_kinds
        作用: NiceGUI / CLI 已映射的向导中断
        输入: 无
        输出:
            frozenset[str]
        """
        return TOML_INTERRUPT_KINDS


    def sync_to_dialog(self, state: DialogState) -> None:
        """
        函数名: sync_to_dialog
        作用: 把 WorkflowState 袋镜像到通用 facts/progress/artifacts
        输入:
            state (DialogState): 对话状态
        输出: 无
        """
        wf = self.workflow
        state.domain = self.name
        if wf.template_id:
            state.facts["template_id"] = wf.template_id
        if wf.user_inputs.get("data_sources_skipped"):
            state.facts["data_sources"] = "skipped"
        elif wf.data_sources:
            state.facts["data_sources"] = str(wf.data_sources)
        if wf.input_area:
            state.facts["input_section"] = f"area={wf.input_area}; move={wf.move_to}; offset={wf.offset}"
        if wf.ghost_text_sample:
            state.facts["ghost_sample"] = wf.ghost_text_sample
        if wf.user_draft:
            state.facts["field_drafts"] = str(wf.user_draft)
        if wf.user_inputs.get("db_id_confirmed"):
            state.facts["db_id"] = str(wf.db_id or "")
        # 中文注释: 合并 intake 与 field:* 进度，避免只剩字段键
        merged = dict(state.progress or {})
        if wf.progress:
            merged.update(wf.progress)
        for key in INTAKE_KEYS:
            if already_captured(wf, key) and merged.get(key) not in ("done", "skip"):
                merged[key] = "done"
        if wf.is_finished or wf.user_inputs.get("db_id_confirmed"):
            merged["db_id"] = "done"
        state.progress = merged
        state.user_inputs = dict(wf.user_inputs)
        artifacts = dict(state.artifacts)
        if wf.indexed_segments:
            artifacts["indexed_segments"] = dict(wf.indexed_segments)
        if wf.determiner != "" or wf.preprocess_done:
            artifacts["determiner"] = wf.determiner
            artifacts["sample_kind"] = wf.sample_kind
        if wf.fields:
            artifacts["fields"] = {label: asdict(fs) for label, fs in wf.fields.items()}
        preview = wf.user_inputs.get("toml_preview")
        if preview:
            artifacts["toml_preview"] = preview
        if wf.planned_labels:
            artifacts["planned_labels"] = list(wf.planned_labels)
        state.artifacts = artifacts
        state.is_finished = bool(wf.is_finished)
        if wf.is_finished and not str(state.last_summary or "").strip():
            parts = [
                f"{label}:{fs.match_type}/idx={fs.index}"
                for label, fs in (wf.fields or {}).items()
            ]
            state.last_summary = "toml guide finished; " + (", ".join(parts) if parts else "no fields")


    def merge_resume(self, state: DialogState, payload: dict[str, Any]) -> None:
        """
        函数名: merge_resume
        作用: 将 UI/CLI resume 载荷写入 WorkflowState 袋再同步 DialogState
        输入:
            state (DialogState): 对话状态
            payload (dict): start/resume 字典
        输出: 无
        """
        merge_payload_into_state(self.workflow, dict(payload or {}))
        labels = list(self.workflow.template_labels or [])
        seeded = init_progress(labels)
        seeded.update(self.workflow.progress or {})
        self.workflow.progress = seeded
        self.sync_to_dialog(state)


    def route_decision(
        self,
        state: DialogState,
        backend: Any,
        user_input: dict[str, Any] | None,
        *,
        stub: bool = False,
    ) -> Decision | None:
        """
        函数名: route_decision
        作用: 使用 toml_config.decide / decide_stub（含 compute 链 fallback）
        输入:
            state (DialogState): 对话状态（路由读 WorkflowState 袋）
            backend: LlmBackend
            user_input (dict | None): 本轮恢复数据
            stub (bool): 固定九动作顺序
        输出:
            Decision: 下一步
        """
        if stub:
            decision, self._stub_index = toml_decide_stub(self.workflow, self._stub_index)
            if decision is None:
                return Decision(
                    next_action="finalize",
                    action_id="finalize_toml",
                    reason="stub sequence complete",
                    route_key="stub_done",
                )
            return decision
        intake = build_intake_plan(self.workflow)
        decision, self._stub_index = toml_decide(
            self.workflow,
            user_input,
            intake,
            backend,
            stub_index=self._stub_index,
        )
        return decision


    def handler_ctx(
        self,
        backend: Any,
        *,
        on_chat: Callable[[str, str], None] | None,
        on_progress: Callable[[str], None] | None,
        thinking_budget: int,
    ) -> dict[str, Any]:
        """
        函数名: handler_ctx
        作用: 提供 determiner 一次性会话（thinking=False，禁止走 dialog_main）
        输入:
            backend: LlmBackend
            on_chat / on_progress: 日志回调
            thinking_budget (int): 透传给 executor
        输出:
            dict: determiner_one_shot / on_match_notify
        """
        def _determiner_one_shot(sample_excerpt: str) -> str:
            sid = f"wizard_determiner_{uuid.uuid4().hex[:8]}"
            opts = SessionOptions(
                system_message=DETERMINER_PROMPT,
                thinking=False,
                max_tokens=512,
            )
            user_content = f"## Input data\n\n```\n{sample_excerpt}\n```"
            if on_chat is not None:
                on_chat("user", f"[determiner] {user_content}")
            session = backend.open_session(sid, options=opts)
            try:
                result = session.send_turn({"role": "user", "content": user_content})
                text = result.text or ""
                if on_chat is not None:
                    on_chat("assistant", f"[determiner] {text}")
                return text
            finally:
                session.close()
        return {
            "determiner_one_shot": _determiner_one_shot,
            "on_match_notify": self._on_match_notify or on_progress,
            "thinking_budget": thinking_budget,
        }


    def execute_action(
        self,
        decision: Decision,
        state: DialogState,
        backend: Any,
        *,
        on_progress: Any,
        on_chat: Any,
        ctx: dict[str, Any],
    ) -> ExecutorResult | None:
        """
        函数名: execute_action
        作用: 调用既有 toml executor（含 skip-interrupt 守卫），再同步 DialogState
        输入:
            decision (Decision): 本轮决策
            state (DialogState): 对话状态
            backend: LlmBackend
            on_progress / on_chat / ctx: 含 main_turn 与 determiner_one_shot
        输出:
            ExecutorResult: DialogState 兼容补丁 + 原 interrupt
        """
        result = execute(
            decision,
            self.workflow,
            backend,
            on_progress=on_progress,
            on_chat=on_chat,
            on_match_notify=ctx.get("on_match_notify"),
            main_turn=ctx.get("main_turn"),
            determiner_one_shot=ctx.get("determiner_one_shot"),
            thinking_budget=int(ctx.get("thinking_budget") or 512),
        )
        merge_state_patch(self.workflow, result.state_patch or {})
        self.sync_to_dialog(state)
        return ExecutorResult(
            ok=result.ok,
            messages=list(result.messages or []),
            state_patch=_dialog_patch(state),
            interrupt=result.interrupt,
            route_key=result.route_key,
        )


    def after_result(
        self,
        state: DialogState,
        decision: Decision,
        result: ExecutorResult,
        *,
        stub: bool = False,
    ) -> None:
        """
        函数名: after_result
        作用: stub 成功且未中断时推进游标；再同步一次袋
        输入:
            state (DialogState): 对话状态
            decision (Decision): 本轮决策
            result (ExecutorResult): 节点结果
            stub (bool): 是否 stub 路由
        输出: 无
        """
        if stub and result.ok and result.interrupt is None:
            self._stub_index += 1
        self.sync_to_dialog(state)


    def build_jobs(self, state: DialogState) -> list[SubagentJob]:
        """
        函数名: build_jobs
        作用: 描述向导子代理：determiner、ghost pass1/pass2、可选 sheet、可选 regex
        输入:
            state (DialogState): 对话状态（样本以 WorkflowState 袋为准）
        输出:
            list[SubagentJob]: 当前可分派的子任务
        """
        wf = self.workflow
        sample = str(wf.ghost_text_sample or state.facts.get("ghost_sample") or "")
        jobs: list[SubagentJob] = []
        if sample.strip() and not is_brace_json(sample.strip()):
            jobs.append(
                SubagentJob(
                    job_id="determiner",
                    system=DETERMINER_PROMPT,
                    user=f"## Input data\n\n```\n{sample[:4000]}\n```",
                    parse_json=False,
                    allow_thinking_retry=False,
                )
            )
        indexed = dict(wf.indexed_segments or {})
        seg_lines = "\n".join(f"{idx}: {value}" for idx, value in sorted(indexed.items()))
        labels = list(wf.planned_labels or wf.template_labels or [])
        for label in labels:
            draft = str((wf.user_draft or {}).get(label, "") or "").strip()
            if not draft:
                continue
            jobs.append(
                SubagentJob(
                    job_id=f"ghost_{label}",
                    system=STEP3_SYSTEM_PROMPT,
                    user=(
                        f"Input_label (hint only): {label}\n"
                        f"User-provided value (primary signal): {draft}\n"
                        f"Indexed segments:\n{seg_lines}\n"
                        "Find the index of the DATA VALUE for this field."
                    ),
                    parse_json=True,
                    allow_thinking_retry=True,
                )
            )
        if _has_google_source(wf) and list(wf.google_sheet_headers or []):
            headers = list(wf.google_sheet_headers or [])
            rows = list(wf.google_sheet_sample or [])
            for label in list(wf.template_labels or []):
                jobs.append(
                    SubagentJob(
                        job_id=f"sheet_{label}",
                        system=STEP4_SYSTEM_PROMPT,
                        user=f"Target Field: {label}\nHeaders: {headers}\nSample rows: {rows[:5]}",
                        parse_json=True,
                        allow_thinking_retry=True,
                    )
                )
        for label, fs in (wf.fields or {}).items():
            if not fs.needs_regex or str(fs.regex or "").strip():
                continue
            haystack = str((wf.indexed_segments or {}).get(fs.index, "") or sample)
            draft = str((wf.user_draft or {}).get(label, "") or "")
            jobs.append(
                SubagentJob(
                    job_id=f"regex_{label}",
                    system=STEP5_SYSTEM_PROMPT,
                    user=(
                        f"Input_label: {label}\n"
                        f"User-provided value (must be captured by group 1): {draft or '(none)'}\n"
                        f"Indexed segment text (haystack):\n{haystack}\n"
                        "Write a Python regex with one capture group. Output exactly one JSON object."
                    ),
                    parse_json=True,
                    allow_thinking_retry=True,
                )
            )
        return jobs
