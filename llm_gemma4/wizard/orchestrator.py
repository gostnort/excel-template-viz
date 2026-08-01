"""TOML 向导状态机：主对话 + 字段子 agent 池（v8.1：Step2=layout，Step3=Ghost，Step4=匹配）。"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from llm_gemma4 import config
from llm_gemma4.backends.base import LlmBackend, SessionOptions
from llm_gemma4.wizard.context import build_main_turn_prefix, format_indexed_preview
from llm_gemma4.wizard.field_agent import (
    FieldAgentResult,
    _apply_ghost_payload,
    _apply_sheet_payload,
    run_field_agent,
)
from llm_gemma4.wizard.parse_field_json import ParseFieldError, parse_field_json
from llm_gemma4.wizard.prompts import (
    DETERMINER_PROMPT,
    MAIN_SYSTEM_PROMPT,
    PLAN_GHOST_TASKS_PROMPT,
    PLAN_SHEET_TASKS_PROMPT,
)
from llm_gemma4.wizard.sample_preprocess import build_indexed_segments
from llm_gemma4.wizard.state import FieldState, WizardState
from llm_gemma4.wizard.template_labels import list_template_labels
from llm_gemma4.wizard.toml_patcher import persist_wizard_toml


class WizardOrchestrator:
    """
    类名: WizardOrchestrator
    作用: 维护 8 步向导状态机，调度主对话与并发字段子 agent
    输入: 无（构造时可传 on_progress 回调）
    输出: 无
    """

    def __init__(
        self,
        backend: LlmBackend,
        on_progress: Callable[[str], None] | None = None,
        on_chat: Callable[[str, str], None] | None = None,
        on_match_notify: Callable[[str], None] | None = None,
    ):
        self._backend = backend
        self._on_progress = on_progress or (lambda _msg: None)
        self._on_chat = on_chat or (lambda _role, _text: None)
        self._on_match_notify = on_match_notify or (lambda _msg: None)
        self.state = WizardState()
        self._main_session_id = "wizard_main"
        self._main_opened = False
        self._semaphore = threading.Semaphore(2)
        self._thinking_budget_cached: int | None = None
        self._ui_lock = threading.Lock()

    def _progress(self, msg: str) -> None:
        with self._ui_lock:
            self._on_progress(msg)

    def _chat(self, role: str, text: str) -> None:
        with self._ui_lock:
            self._on_chat(role, text)

    def _match_notify(self, msg: str) -> None:
        """
        函数名: _match_notify
        作用: 字段匹配完成时触发轻量提醒回调（如 UI toast），与 chat 历史分离
        输入:
            msg (str): 提示文案
        输出: 无
        """
        with self._ui_lock:
            self._on_match_notify(msg)

    def _thinking_budget(self) -> int:
        if self._thinking_budget_cached is None:
            health = self._backend.health_check()
            self._thinking_budget_cached = config.load_thinking_budget(
                health.profile, litert_backend=health.litert_backend
            )
        return self._thinking_budget_cached

    def _summarize_field_errors(self, step_tag: str) -> None:
        """
        函数名: _summarize_field_errors
        作用: 步骤结束后汇总字段 error 并写入进度日志
        输入:
            step_tag (str): 步骤标签
        输出: 无
        """
        failed = [label for label, fs in self.state.fields.items() if fs.error]
        if failed:
            self._progress(f"{step_tag} done, {len(failed)} failed: {', '.join(failed)}")
        else:
            self._progress(f"{step_tag} done, all fields ok")


    def _persist_toml(self, step_tag: str) -> None:
        """
        函数名: _persist_toml
        作用: 将当前向导状态渐进写入 sidecar TOML 并打进度日志
        输入:
            step_tag (str): 步骤标签（如 [Step 2/8]）
        输出: 无
        """
        tid = (self.state.template_id or "").strip()
        if not tid:
            self._progress(f"{step_tag} TOML persist skipped: missing template_id")
            return
        try:
            path = persist_wizard_toml(self.state, tid)
        except Exception as exc:
            self._progress(f"{step_tag} TOML persist failed: {exc}")
            return
        self._progress(
            f"{step_tag} TOML persisted: {path} determiner={self.state.determiner!r}"
        )


    def _ensure_main_session(self) -> None:
        if not self._main_opened:
            self._backend.open_session(
                self._main_session_id,
                options=SessionOptions(system_message=MAIN_SYSTEM_PROMPT, thinking=False),
            )
            self._main_opened = True

    def _main_turn(self, user_body: str) -> str:
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
            str: 模型回复
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

    def _phase_preprocess(self) -> None:
        """
        函数名: _phase_preprocess
        作用: Step 4.1 构建 indexed_segments 与 determiner
        输入: 无
        输出: 无
        """
        result = build_indexed_segments(
            self.state.ghost_text_sample,
            one_shot=self._determiner_one_shot,
        )
        self.state.indexed_segments = dict(result.indexed_segments)
        self.state.determiner = result.determiner
        self.state.sample_kind = result.sample_kind
        self.state.preprocess_done = True
        preview = format_indexed_preview(self.state.indexed_segments)
        self._progress(
            f"[Step 4.1/8] preprocess done: {result.sample_kind}, "
            f"{len(result.indexed_segments)} tokens"
        )
        self._progress(f"[Step 4.1/8] determiner={result.determiner!r}")
        if result.cleaned_preview:
            self._progress(f"[Step 4.1/8] cleaned preview: {result.cleaned_preview[:200]}")
        self._progress(f"[Step 4.1/8] indexed preview:\n{preview}")
        # 预处理后立即落盘，确保 brace_json 空 determiner / plain list 写入 TOML
        self._persist_toml("[Step 4.1/8]")

    def _parse_planned_labels(self, reply: str, fallback: list[str]) -> list[str]:
        parsed = parse_field_json(reply)
        if isinstance(parsed, ParseFieldError):
            return list(fallback)
        labels_raw = parsed.get("labels")
        if not isinstance(labels_raw, list) or not labels_raw:
            return list(fallback)
        known = set(fallback)
        planned = [str(x) for x in labels_raw if str(x) in known]
        return planned if planned else list(fallback)

    def _labels_with_draft(self) -> list[str]:
        """
        函数名: _labels_with_draft
        作用: 返回 user_draft 非空的模板标签（空输入不送 Gemma）
        输入: 无
        输出:
            list[str]: 有源数据的 Input_label 列表
        """
        return [
            label for label in self.state.template_labels
            if str(self.state.user_draft.get(label) or "").strip()
        ]


    def _normalize_layout_area(self, raw: Any) -> str | list[str]:
        """
        函数名: _normalize_layout_area
        作用: 规范化步骤 2 的 input_area（单项字符串或多区域列表）
        输入:
            raw (Any): 表单 payload 中的 input_area
        输出:
            str | list[str]: 落盘用区域；非法则抛 ValueError
        """
        parts: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                text = str(item or "").strip().replace(" ", "")
                if text:
                    parts.append(text.upper())
        else:
            text = str(raw or "").strip().replace(" ", "")
            if text:
                parts.append(text.upper())
        if not parts:
            raise ValueError("input_area is required")
        return parts[0] if len(parts) == 1 else parts


    def _normalize_layout_move(self, raw: Any) -> str | list[str]:
        """
        函数名: _normalize_layout_move
        作用: 规范化步骤 2 的 move_to（1 或 2 个方向，顺序=主轴+次轴）
        输入:
            raw (Any): 表单 payload 中的 move_to
        输出:
            str | list[str]: 落盘用方向；非法则抛 ValueError
        """
        valid = ("up", "down", "left", "right")
        dirs: list[str] = []
        if isinstance(raw, list):
            for item in raw:
                direction = str(item or "").strip().lower()
                if not direction:
                    continue
                if direction not in valid:
                    raise ValueError("move_to must be one of up/down/left/right")
                if direction not in dirs:
                    dirs.append(direction)
        else:
            direction = str(raw or "").strip().lower()
            if direction:
                if direction not in valid:
                    raise ValueError("move_to must be one of up/down/left/right")
                dirs.append(direction)
        if not dirs or len(dirs) > 2:
            raise ValueError("move_to must select 1 or 2 directions")
        return dirs[0] if len(dirs) == 1 else dirs

    def _announce_match(
        self,
        label: str,
        *,
        match_type: str,
        index: int,
        content: str,
        reason: str,
    ) -> None:
        """
        函数名: _announce_match
        作用: 在对话区公布字段匹配结果（index / content / reason），并触发轻量提醒回调
        输入:
            label (str): Input_label
            match_type (str): exact|fuzzy|none
            index (int): 命中索引
            content (str): 对应段落内容
            reason (str): 匹配原因
        输出: 无
        """
        msg = (
            f"Matched [{label}]\n"
            f"match_type: {match_type}\n"
            f"index: {index}\n"
            f"content: {content}\n"
            f"reason: {reason}"
        )
        self._chat("assistant", msg)
        # 短提示用于弹窗，避免把 content/reason 完整段落塞进 toast
        short_content = content[:30] + ("…" if len(content) > 30 else "")
        short_reason = reason[:40] + ("…" if len(reason) > 40 else "")
        self._match_notify(
            f"已匹配 [{label}] index={index} content={short_content} reason={short_reason}"
        )

    def _phase_plan_ghost(self) -> None:
        """
        函数名: _phase_plan_ghost
        作用: Step 4.2 主对话规划 FieldTasks（空 draft 跳过；有 indexed 时必须走 wizard_main）
        输入: 无
        输出: 无
        """
        draft_labels = self._labels_with_draft()
        skipped = [l for l in self.state.template_labels if l not in set(draft_labels)]
        for label in skipped:
            fs = self.state.fields.get(label)
            if fs is not None:
                # 空 draft 跳过：本轮无文本框索引 → index=-1（向导结果全覆盖旧 TOML）
                fs.match_type = "none"
                fs.index = -1
                fs.error = ""
        if not self.state.indexed_segments:
            self._progress("[Step 4.2/8] no indexed_segments; draft-only labels without match")
            self.state.planned_labels = draft_labels
            self.state.field_tasks_planned = True
            if skipped:
                self._progress(f"[Step 4.2/8] skip empty draft: {', '.join(skipped)}")
            self._progress(f"[Step 4.2/8] FieldTasks planned: {len(draft_labels)} labels")
            return
        # 主对话确认 FieldTask 列表；空 draft 仅作过滤，不跳过 wizard_main
        indexed_lines = "\n".join(
            f"{idx}: {value}" for idx, value in sorted(self.state.indexed_segments.items())
        )
        draft_for_prompt = {
            label: str(self.state.user_draft.get(label) or "")
            for label in self.state.template_labels
        }
        plan_prompt = (
            f"{PLAN_GHOST_TASKS_PROMPT}\n\n"
            f"Indexed segments:\n{indexed_lines}\n"
            f"Template labels: {self.state.template_labels}\n"
            f"User draft (optional): {draft_for_prompt}\n\n"
            "List which labels need ghost index matching as FieldTasks."
        )
        plan_reply = self._main_turn(plan_prompt)
        # fallback 用非空 draft 标签，避免模型把空字段塞进 FieldTasks
        planned = self._parse_planned_labels(plan_reply, draft_labels)
        draft_set = set(draft_labels)
        planned = [label for label in planned if label in draft_set]
        if not planned and draft_labels:
            planned = list(draft_labels)
        self.state.planned_labels = planned
        self.state.field_tasks_planned = True
        if skipped:
            self._progress(f"[Step 4.2/8] skip empty draft (no Gemma): {', '.join(skipped)}")
        self._progress(f"[Step 4.2/8] FieldTasks planned: {len(self.state.planned_labels)} labels")

    def _phase_match_ghost(self, budget: int) -> None:
        """
        函数名: _phase_match_ghost
        作用: Step 4.3 子 agent 对已规划标签做 index 匹配（每字段必走 pass1/pass2，禁止 draft 短路）
        输入:
            budget (int): thinking_budget
        输出: 无
        """
        indexed = self.state.indexed_segments
        if not indexed:
            self._progress("[Step 4.3/8] indexed_segments empty; abort match")
            self._persist_toml("[Step 4/8]")
            self.state.current_step = 5
            return
        labels = [
            label for label in (self.state.planned_labels or self._labels_with_draft())
            if str(self.state.user_draft.get(label) or "").strip()
        ]
        total = len(labels)
        self._progress(f"[Step 4.3/8] matching {total} fields (non-empty draft only)")
        if total == 0:
            self._progress("[Step 4.3/8] nothing to match; all drafts empty")
            self._persist_toml("[Step 4/8]")
            self.state.current_step = 5
            return
        done_count = 0
        lock = threading.Lock()
        def _ghost_worker(label: str) -> tuple[str, FieldAgentResult]:
            nonlocal done_count
            draft_val = str(self.state.user_draft.get(label) or "").strip()
            fs = self.state.fields[label]
            # 每个字段都走子 agent；exact/fuzzy 由模型 + _apply_ghost_payload 硬校验
            res = run_field_agent(
                self._backend, "ghost", label,
                thinking_budget=budget,
                indexed_segments=indexed,
                draft_value=draft_val,
                on_chat=self._chat,
            )
            if not res.ok:
                fs.error = res.error or "ghost match failed"
                fs.match_type = "none"
                fs.index = -1
                with lock:
                    done_count += 1
                    count = done_count
                self._announce_match(
                    label,
                    match_type="none",
                    index=-1,
                    content="",
                    reason=fs.error,
                )
                self._progress(
                    f"[Step 4.3/8] matching [{label}] ({count}/{total}) "
                    f"→ none index=-1"
                )
                return label, res
            if res.payload:
                raw_idx = int(res.payload.get("index", -1))
                seg_text = str(indexed.get(raw_idx, "")) if raw_idx >= 0 else ""
                mt, idx, needs = _apply_ghost_payload(
                    res.payload, draft=draft_val, segment=seg_text,
                )
                fs.match_type = mt
                fs.index = idx
                fs.needs_regex = needs
                fs.used_thinking = res.used_thinking
                reason = str(res.payload.get("reason") or "")
                content = str(indexed.get(idx, "")) if idx >= 0 else ""
                if mt == "none":
                    fs.error = reason or "no match"
                else:
                    fs.error = ""
                with lock:
                    done_count += 1
                    count = done_count
                self._announce_match(
                    label,
                    match_type=mt,
                    index=idx,
                    content=content,
                    reason=reason or mt,
                )
                self._progress(
                    f"[Step 4.3/8] matching [{label}] ({count}/{total}) "
                    f"→ {fs.match_type} index={fs.index}"
                )
            else:
                with lock:
                    done_count += 1
                    count = done_count
                self._progress(
                    f"[Step 4.3/8] matching [{label}] ({count}/{total}) "
                    f"→ empty payload"
                )
            return label, res
        self._run_fields_parallel(labels, _ghost_worker)
        self._summarize_field_errors("[Step 4.3/8]")
        self._persist_toml("[Step 4/8]")
        self.state.current_step = 5

    def _run_fields_parallel(
        self,
        labels: list[str],
        worker: Callable[[str], tuple[str, FieldAgentResult]],
    ) -> None:
        total = len(labels)
        if total == 0:
            return
        def _guarded(label: str) -> tuple[str, FieldAgentResult]:
            with self._semaphore:
                return worker(label)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {pool.submit(_guarded, label): label for label in labels}
            for fut in as_completed(futures):
                label = futures[fut]
                try:
                    fut.result()
                except Exception as exc:
                    fs = self.state.fields.get(label)
                    if fs is not None:
                        fs.error = str(exc)
                    self._progress(f"field [{label}] exception: {exc}")

    def advance(self, step: int, payload: dict[str, Any]) -> WizardState:
        """
        函数名: advance
        作用: 执行指定步骤/阶段业务逻辑
        输入:
            step (int): 当前步骤 1–8
            payload (dict): UI 传入；step 3 须含 phase in preprocess|plan|match
        输出:
            WizardState: 更新后的向导状态
        """
        budget = self._thinking_budget()
        if step == 1:
            self.state.data_sources = list(payload.get("data_sources") or [])
            tid = str(payload.get("template_id") or "")
            tpath = payload.get("template_path")
            self.state.template_id = tid
            if tpath:
                self.state.template_path = Path(tpath)
            self._main_turn(f"Data sources configured: {self.state.data_sources}")
            self._progress(f"[Step 1/8] data sources recorded: {self.state.data_sources}")
            # 尽早校正 sidecar：无效 work_sheet（如 Input_sheet 不在 xlsx）在此写回真实表名
            self._persist_toml("[Step 1/8]")
            self.state.current_step = 2
        elif step == 2:
            # Google 之后、输入试填之前：写入 [[input_section]]（可多区域 / 多方向）
            if payload.get("template_id"):
                self.state.template_id = str(payload.get("template_id") or self.state.template_id)
            tpath = payload.get("template_path")
            if tpath:
                self.state.template_path = Path(tpath)
            input_area = self._normalize_layout_area(payload.get("input_area"))
            move_to = self._normalize_layout_move(payload.get("move_to"))
            offset_raw = payload.get("offset", 1)
            try:
                offset = int(offset_raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("offset must be int >= 1") from exc
            if offset < 1:
                raise ValueError("offset must be int >= 1")
            self.state.input_area = input_area
            self.state.move_to = move_to
            self.state.offset = offset
            area_n = len(input_area) if isinstance(input_area, list) else 1
            move_repr = move_to if isinstance(move_to, list) else [move_to]
            self._progress(
                f"[Step 2/8] input_section areas={area_n} "
                f"move_to={move_repr} offset={offset}"
            )
            self._persist_toml("[Step 2/8]")
            # generate_toml 已按 area 并集重建 fields；汇报保留标签
            kept = list(self.state.template_labels or [])
            self._progress(
                f"[Step 2/8] fields rebuilt for area: {len(kept)} labels"
                + (f" ({', '.join(kept)})" if kept else "")
            )
            self.state.current_step = 3
        elif step == 3:
            # 「输入」页试填后：捕获 Ghost / draft
            self.state.ghost_text_sample = str(payload.get("ghost_text_sample") or "")
            self.state.normalized_sample = self.state.ghost_text_sample
            draft = payload.get("user_draft") or {}
            self.state.user_draft = {
                str(k): str(v) for k, v in draft.items() if str(v or "").strip()
            }
            tid = str(payload.get("template_id") or self.state.template_id or "")
            tpath = payload.get("template_path")
            self.state.template_id = tid
            if tpath:
                self.state.template_path = Path(tpath)
            labels = list(payload.get("template_labels") or [])
            if not labels and self.state.template_path:
                labels = list_template_labels(self.state.template_path)
            self.state.template_labels = labels
            for label in labels:
                self.state.fields[label] = FieldState(input_label=label)
            self.state.indexed_segments = {}
            self.state.determiner = ""
            self.state.preprocess_done = False
            self.state.field_tasks_planned = False
            self.state.planned_labels = []
            self._main_turn(
                f"Sample captured ({len(self.state.ghost_text_sample)} chars), "
                f"{len(labels)} labels. No structure analysis yet."
            )
            self._progress(
                f"[Step 3/8] sample captured, {len(self.state.ghost_text_sample)} chars, "
                f"{len(labels)} labels"
            )
            self.state.current_step = 4
        elif step == 4:
            phase = str(payload.get("phase") or "").strip().lower()
            if phase == "preprocess":
                self._phase_preprocess()
            elif phase == "plan":
                if not self.state.preprocess_done:
                    self._phase_preprocess()
                self._phase_plan_ghost()
            elif phase == "match":
                if not self.state.preprocess_done:
                    self._phase_preprocess()
                if not self.state.field_tasks_planned:
                    self._phase_plan_ghost()
                self._phase_match_ghost(budget)
            else:
                self._progress(f"[Step 4/8] unknown phase={phase!r}; expected preprocess|plan|match")
        elif step == 5:
            headers = list(payload.get("google_sheet_headers") or self.state.google_sheet_headers)
            rows = list(payload.get("google_sheet_sample") or self.state.google_sheet_sample)
            self.state.google_sheet_headers = headers
            self.state.google_sheet_sample = rows
            has_sheet = any(
                ds.get("type") == "google_sheet" or ds.get("source1")
                for ds in self.state.data_sources
            )
            if not has_sheet or not headers:
                self._progress("[Step 5/8] no Google Sheet source, skip")
                self._persist_toml("[Step 5/8]")
                self.state.current_step = 6
                return self.state
            source_file = "source1"
            source_sheet = str(payload.get("source_sheet") or "Sheet1")
            plan_prompt = (
                f"{PLAN_SHEET_TASKS_PROMPT}\n\n"
                f"Headers: {headers}\n"
                f"Sample rows: {rows[:5]}\n"
                f"Template labels: {self.state.template_labels}"
            )
            plan_reply = self._main_turn(plan_prompt)
            labels = self._parse_planned_labels(plan_reply, self.state.template_labels)
            total = len(labels)
            self._progress(f"[Step 5/8] Sheet matching {total} fields")
            done_count = 0
            lock = threading.Lock()
            def _sheet_worker(label: str) -> tuple[str, FieldAgentResult]:
                nonlocal done_count
                res = run_field_agent(
                    self._backend, "sheet", label,
                    google_headers=headers, google_rows=rows,
                    thinking_budget=budget, on_chat=self._chat,
                )
                fs = self.state.fields[label]
                if not res.ok:
                    fs.error = res.error or "sheet match failed"
                elif res.payload:
                    mt, column, needs = _apply_sheet_payload(res.payload, label=label)
                    if column:
                        fs.column_name = column
                    fs.match_type = mt if mt != "unknown" else fs.match_type
                    fs.source_file = source_file
                    fs.source_sheet = source_sheet
                    fs.used_thinking = res.used_thinking
                    if needs:
                        fs.needs_regex = True
                    if mt == "none":
                        fs.error = str(res.payload.get("reason", "no column match"))
                    else:
                        fs.error = ""
                with lock:
                    done_count += 1
                    self._progress(f"[Step 5/8] matching [{label}] ({done_count}/{total})")
                return label, res
            self._run_fields_parallel(labels, _sheet_worker)
            self._summarize_field_errors("[Step 5/8]")
            self._persist_toml("[Step 5/8]")
            self.state.current_step = 6
        elif step == 6:
            regex_labels = [
                label for label in self.state.template_labels
                if self.state.fields[label].needs_regex
            ]
            total = len(regex_labels)
            self._progress(f"[Step 6/8] Regex for {total} fields")
            sample = self.state.ghost_text_sample
            indexed = self.state.indexed_segments
            done_count = 0
            lock = threading.Lock()
            def _regex_worker(label: str) -> tuple[str, FieldAgentResult]:
                nonlocal done_count
                fs = self.state.fields[label]
                draft_val = str(self.state.user_draft.get(label) or "").strip()
                # haystack = 该字段命中 index 的段文本；无 index 时回退整段样本
                segment = ""
                if fs.index >= 0 and indexed:
                    segment = str(indexed.get(fs.index, "") or "")
                haystack = segment.strip() or sample
                res = run_field_agent(
                    self._backend, "regex", label,
                    ghost_sample=sample,
                    raw_text_for_regex=haystack,
                    draft_value=draft_val,
                    thinking_budget=budget,
                    on_chat=self._chat,
                )
                if res.ok and res.payload:
                    fs.regex = str(res.payload.get("regex", ""))
                    fs.used_thinking = res.used_thinking
                    fs.error = ""
                    if res.used_thinking:
                        self._progress(f"[Step 6/8] [{label}] Thinking retry ok")
                elif not res.ok:
                    fs.error = res.error
                    fs.used_thinking = res.used_thinking
                    self._progress(f"[Step 6/8] [{label}] failed: {res.error}")
                with lock:
                    done_count += 1
                    self._progress(f"[Step 6/8] [{label}] ({done_count}/{total})")
                return label, res
            self._run_fields_parallel(regex_labels, _regex_worker)
            self._summarize_field_errors("[Step 6/8]")
            self._persist_toml("[Step 6/8]")
            self.state.current_step = 7
        elif step == 7:
            # 空 / "None" = 不指定主键（全部 id=false）；写盘后结束，不再试跑
            raw_id = str(payload.get("db_id") or "").strip()
            db_id = "" if raw_id in ("", "None") else raw_id
            self.state.db_id = db_id
            for fs in self.state.fields.values():
                fs.id = bool(db_id) and fs.input_label == db_id
            note = db_id if db_id else "(none)"
            self._main_turn(f"User selected db_id={note}")
            self._progress(f"[Step 7/8] db_id={note}; write TOML and finish (no trial)")
            self._persist_toml("[Step 7/8]")
            self.state.is_finished = True
            self.state.trial_ok = True
            self.state.trial_mismatches = []
            self.state.written_toml_path = self.state.written_toml_path or ""
            self.state.current_step = 7
        elif step == 8:
            # 试跑已取消：直接标记完成（兼容旧 UI 误入）
            self._progress("[Step 8/8] trial skipped; use step 7 save")
            self.state.is_finished = True
            self.state.trial_ok = True
            self.state.trial_mismatches = []
            self._persist_toml("[Step 8/8]")
        return self.state

    def close(self) -> None:
        """
        函数名: close
        作用: 关闭主对话 session
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
