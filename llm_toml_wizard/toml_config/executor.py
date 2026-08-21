"""动作执行器：将 Decision.action_id 映射到具体业务逻辑。

Phase A: 从 wizard/orchestrator.py 逐步骤 lift，每个 action 独立调用对应子代理或同步操作。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from llm_lmstudio.backend import LlmBackend
from llm_toml_wizard.toml_config.field_agent import (
    _draft_haystack_compatible,
    _resolve_ghost_index,
    _segment_matches_draft,
    run_field_agent,
)
from llm_toml_wizard.toml_config.intake_plan import already_captured, intake_key_for_action
from llm_toml_wizard.toml_config.sample_preprocess import build_indexed_segments
from llm_toml_wizard.toml_config.toml_patcher import persist_wizard_toml
from llm_toml_wizard.workflow.parallel import map_run_sequential
from llm_toml_wizard.workflow.state import (
    Decision,
    ExecutorResult,
    FieldState,
    InterruptPayload,
    WorkflowState,
    ensure_field_states,
)


def _progress_patch(state: WorkflowState, *keys: str, status: str = "done") -> dict[str, Any]:
    """
    函数名: _progress_patch
    作用: 将 intake progress 键标记为 done/skip 并返回 state_patch 片段
    输入:
        state (WorkflowState): 当前状态
        keys (str): progress 键名
        status (str): done 或 skip
    输出:
        dict[str, Any]: 含 progress 的补丁
    """
    progress = dict(state.progress or {})
    for key in keys:
        progress[key] = status
    return {"progress": progress}


def _persist_message(state: WorkflowState, prefix: str) -> str:
    """
    函数名: _persist_message
    作用: dry-run 时标明未写 sidecar，否则报告落盘路径
    输入:
        state (WorkflowState): 含 write_toml / written_toml_path
        prefix (str): 日志前缀，如 [db_id]
    输出:
        str: 一行进度日志
    """
    if state.user_inputs.get("write_toml") is False:
        return f"{prefix} TOML preview (dry-run, not written)"
    path = str(state.written_toml_path or "").strip()
    if path:
        return f"{prefix} TOML persisted: {path}"
    return f"{prefix} TOML persisted"


def _resolve_draft_index(
    indexed: dict[int, str],
    draft_val: str,
    preferred_idx: int = -1,
    *,
    label: str = "",
) -> tuple[int, str]:
    """
    函数名: _resolve_draft_index
    作用: 在 index 字典中定位 draft 值段；Gemma 误选标签 index 时回退到值段
    输入:
        indexed (dict[int, str]): 预处理段字典
        draft_val (str): 用户草稿值
        preferred_idx (int): Gemma 返回的候选 index
        label (str): Input_label（用于 label→value 邻接纠正）
    输出:
        tuple[int, str]: (index, segment_text)
    """
    resolved = _resolve_ghost_index(
        preferred_idx,
        label=label,
        draft=draft_val,
        indexed_segments=indexed,
    )
    if resolved >= 0:
        return resolved, str(indexed.get(resolved, "") or "")
    return -1, ""


def _should_skip_interrupt(state: WorkflowState, action_id: str) -> bool:
    key = intake_key_for_action(action_id)
    if not key:
        return False
    if key == "ghost_sample":
        return (
            already_captured(state, "ghost_sample")
            and already_captured(state, "field_drafts")
        )
    return already_captured(state, key)


def _executor_ctx(
    *,
    main_turn: Callable[[str], str] | None,
    determiner_one_shot: Callable[[str], str] | None,
    thinking_budget: int,
) -> dict[str, Any]:
    return {
        "main_turn": main_turn,
        "determiner_one_shot": determiner_one_shot,
        "thinking_budget": thinking_budget,
    }


def _action_capture_sources(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 0：采集数据源（Google 可选）或显式跳过。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    if already_captured(state, "data_sources"):
        _log("[data_sources] already captured or skipped")
        patch = _progress_patch(state, "data_sources")
        return ExecutorResult(
            ok=True,
            messages=messages,
            state_patch=patch,
            route_key="already_have",
        )
    has_sources = bool(state.data_sources)
    skipped = bool(state.user_inputs.get("data_sources_skipped"))
    if not has_sources and not skipped:
        return ExecutorResult(
            ok=True,
            messages=["capture_sources interrupted: configure Google or skip"],
            state_patch={},
            interrupt=InterruptPayload(
                kind="ask_sources",
                expected_input="Configure Google Sheet or skip data sources",
            ),
            route_key="capture_sources",
        )
    if skipped and not has_sources:
        _log("[data_sources] user skipped Google source")
    else:
        _log(f"[data_sources] sources ready: {state.data_sources}")
    patch = _progress_patch(state, "data_sources")
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        route_key="capture_sources",
    )


def _action_record_sources(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 1：记录数据源配置。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    data_sources = list(state.data_sources or [])
    tid = str(state.template_id or "")
    if not already_captured(state, "data_sources"):
        return ExecutorResult(
            ok=True,
            messages=["record_sources blocked: data_sources not captured"],
            state_patch={},
            interrupt=InterruptPayload(
                kind="ask_sources",
                expected_input="Complete data source step before record_sources",
            ),
            route_key="capture_sources",
        )
    _log(f"[data_sources] data sources recorded: {data_sources}")
    main_turn = ctx.get("main_turn")
    if callable(main_turn):
        main_turn(f"Data sources configured: {data_sources}")
    # 尽早校正 sidecar：无效 work_sheet（如 Input_sheet 不在 xlsx）在此写回真实表名
    try:
        persist_wizard_toml(state, tid)
        _log(_persist_message(state, "[data_sources]"))
    except Exception as exc:
        _log(f"[data_sources] TOML persist failed: {exc}")

    state.current_step = 2
    patch = {"current_step": 2}
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        route_key="record_sources",
    )


def _action_capture_layout(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 2：捕获 input_section 布局。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    if already_captured(state, "input_section"):
        _log("[input_section] already captured")
        patch = _progress_patch(state, "input_section")
        return ExecutorResult(
            ok=True,
            messages=messages,
            state_patch=patch,
            route_key="already_have",
        )

    input_area = state.input_area if isinstance(state.input_area, (str, list)) else ""
    move_to = state.move_to if isinstance(state.move_to, (str, list)) else ""
    offset_raw = state.offset if isinstance(state.offset, int) and state.offset >= 1 else 1

    # 规范化输入
    parts: list[str] = []
    if isinstance(input_area, list):
        for item in input_area:
            text = str(item or "").strip().replace(" ", "")
            if text:
                parts.append(text.upper())
    elif input_area:
        parts.append(str(input_area).upper())

    valid = ("up", "down", "left", "right")
    move_dirs: list[str] = []
    if isinstance(move_to, list):
        for item in move_to:
            direction = str(item or "").strip().lower()
            if not direction:
                continue
            if direction not in valid:
                raise ValueError("move_to must be one of up/down/left/right")
            if direction not in move_dirs:
                move_dirs.append(direction)
    elif move_to:
        direction = str(move_to).strip().lower()
        if direction and direction in valid:
            move_dirs.append(direction)

    if not parts:
        # 无 input_area：中断等待用户，不抛异常（Phase A interrupt 模式）
        return ExecutorResult(
            ok=False,
            messages=["capture_layout interrupted: input_area is required"],
            state_patch={},
            interrupt=InterruptPayload(kind="ask_layout", expected_input="please provide at least one input_area"),
            route_key="capture_layout",
        )
    area_val = parts[0] if len(parts) == 1 else parts
    if len(move_dirs) == 0:
        move_val = "down"
    elif len(move_dirs) > 2:
        move_val = move_dirs[:2]
    else:
        move_val = move_dirs[0] if len(move_dirs) == 1 else move_dirs

    offset = int(offset_raw) if isinstance(offset_raw, str) else offset_raw
    if offset < 1:
        raise ValueError("offset must be int >= 1")

    state.input_area = area_val
    state.move_to = move_val
    state.offset = offset

    area_n = len(area_val) if isinstance(area_val, list) else 1
    move_repr = move_val if isinstance(move_val, list) else [move_val]
    _log(
        f"[input_section] input_section areas={area_n} "
        f"move_to={move_repr} offset={offset}"
    )

    # generate_toml 已按 area 并集重建 fields；汇报保留标签
    kept = list(state.template_labels or [])
    _log(f"[input_section] fields rebuilt for area: {len(kept)} labels" + (f" ({', '.join(kept)})" if kept else ""))

    # 写入 TOML
    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
    except Exception as exc:
        _log(f"[input_section] TOML persist failed: {exc}")

    state.current_step = 3
    patch = {
        "current_step": 3,
        "input_area": area_val,
        "move_to": move_val,
        "offset": offset,
    }
    patch.update(_progress_patch(state, "input_section"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="capture_layout",
    )


def _action_capture_sample(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 3：捕获 Ghost 样本 + draft。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    ghost_text_sample = str(state.ghost_text_sample or "")
    draft = state.user_draft or {}
    labels = list(state.template_labels or [])
    if not ghost_text_sample.strip():
        return ExecutorResult(
            ok=False,
            messages=["capture_sample interrupted: ghost sample required"],
            state_patch={},
            interrupt=InterruptPayload(
                kind="ask_sample",
                expected_input="请在「输入」页粘贴 Ghost 样本并填写字段草稿后点「下一步」",
            ),
            route_key="capture_sample",
        )
    ensure_field_states(state, labels)
    # 重置预处理状态，准备重新处理
    state.indexed_segments = {}
    state.determiner = ""
    state.preprocess_done = False
    state.field_tasks_planned = False
    state.planned_labels = []

    _log(
        f"[ghost_sample] sample captured ({len(ghost_text_sample)} chars), "
        f"{len(labels)} labels"
    )
    _log(f"[ghost_sample] user_draft: {list(draft.keys())}")
    main_turn = ctx.get("main_turn")
    if callable(main_turn):
        main_turn(
            f"Sample captured ({len(ghost_text_sample)} chars), "
            f"{len(labels)} labels. No structure analysis yet."
        )

    state.current_step = 4
    state.user_inputs["field_drafts_captured"] = True
    patch = {
        "current_step": 4,
        "ghost_text_sample": ghost_text_sample,
        "user_draft": draft,
        "template_labels": labels,
    }
    patch.update(_progress_patch(state, "ghost_sample", "field_drafts"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="capture_sample",
    )


def _action_preprocess_sample(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 4.1：预处理 — 构建 indexed_segments + determiner。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    # plain text：独立 determiner 会话（禁止走 wizard_main）
    one_shot = ctx.get("determiner_one_shot")
    if not callable(one_shot):
        def _determiner_fallback(sample_excerpt: str) -> str:
            return "\t"
        one_shot = _determiner_fallback
    result = build_indexed_segments(state.ghost_text_sample, one_shot=one_shot)
    state.indexed_segments = dict(result.indexed_segments)
    state.determiner = result.determiner
    state.sample_kind = result.sample_kind
    state.preprocess_done = True

    preview_lines: list[str] = []
    for idx, value in sorted(state.indexed_segments.items()):
        preview_lines.append(f"{idx}: {value}")

    _log(
        f"[ghost_preprocess] preprocess done: {result.sample_kind}, "
        f"{len(result.indexed_segments)} tokens"
    )
    _log(f"[ghost_preprocess] determiner={result.determiner!r}")
    if result.cleaned_preview:
        _log(f"[ghost_preprocess] cleaned preview: {result.cleaned_preview[:200]}")
    preview_text = "\n".join(preview_lines)
    _log(f"[ghost_preprocess] indexed preview:\n{preview_text}")

    # 预处理后立即落盘，确保 brace_json 空 determiner / plain list 写入 TOML
    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
        _log(_persist_message(state, "[ghost_preprocess]"))
    except Exception as exc:
        _log(f"[ghost_preprocess] TOML persist failed: {exc}")

    patch = {
        "current_step": 5,
        "indexed_segments": dict(state.indexed_segments),
        "determiner": result.determiner,
        "sample_kind": result.sample_kind,
        "preprocess_done": True,
    }
    patch.update(_progress_patch(state, "ghost_preprocess"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="preprocess_sample",
    )


def _action_plan_ghost_tasks(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 4.2：规划 Ghost 字段任务列表。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    # 空 draft：不送 Gemma，直接跳过
    draft_labels = [
        label for label in state.template_labels
        if str(state.user_draft.get(label, "") or "").strip()
    ]
    skipped = [l for l in state.template_labels if l not in set(draft_labels)]

    if not state.indexed_segments:
        _log("[field_match] no indexed_segments; draft-only labels without match")
        state.planned_labels = draft_labels
        state.field_tasks_planned = True
        for label in skipped:
            fs = state.fields.get(label)
            if fs is not None:
                fs.match_type = "none"
                fs.index = -1
                fs.error = ""
        _log(f"[field_match] skip empty draft (no Gemma): {', '.join(skipped)}")
        _log(f"[field_match] FieldTasks planned: {len(draft_labels)} labels")

        try:
            persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
        except Exception as exc:
            _log(f"[field_match] TOML persist failed: {exc}")

        return ExecutorResult(
            ok=True,
            messages=messages,
            state_patch={
                "current_step": 5,
                "planned_labels": draft_labels,
                "field_tasks_planned": True,
            },
            interrupt=None,
            route_key="plan_ghost_tasks",
        )

    # 有 indexed_segments：按非空 draft 规划 FieldTasks（不经过 wizard_main，避免误答「请粘贴样本」）
    planned = list(draft_labels)
    _log(
        f"[field_match] plan from drafts ({len(planned)}): "
        + (", ".join(planned) if planned else "(none)")
    )

    state.planned_labels = planned
    state.field_tasks_planned = True
    _log(f"[field_match] FieldTasks planned: {len(state.planned_labels or [])} labels")

    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
    except Exception as exc:
        _log(f"[field_match] TOML persist failed: {exc}")

    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={
            "current_step": 5,
            "planned_labels": planned,
            "field_tasks_planned": True,
        },
        interrupt=None,
        route_key="plan_ghost_tasks",
    )


def _action_match_ghost_fields(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 4.3：子代理对已规划标签做 index 匹配。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    def _chat(role: str, text: str) -> None:
        _log(f"[{role}] {text}")

    indexed = state.indexed_segments
    if not indexed:
        _log("[field_match] indexed_segments empty; abort match")
        try:
            persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
        except Exception as exc:
            _log(f"[field_match] TOML persist failed: {exc}")

    labels = [
        label for label in (state.planned_labels or state.template_labels)
        if str(state.user_draft.get(label, "") or "").strip()
    ]
    total = len(labels)
    _log(
    f"[field_match] matching {total} fields "
    + (f"(ghost: {len(state.user_draft)})" if state.user_draft else "(no ghost)")
)

    budget: int = int(ctx.get("thinking_budget") or 512)
    lock = threading.Lock()
    done_count = 0

    def _ghost_worker(label: str) -> None:
        nonlocal done_count
        draft_val = str(state.user_draft.get(label, "") or "").strip()
        ensure_field_states(state, [label])
        fs = state.fields[label]
        # 每个字段都走子代理；exact/fuzzy 由模型 + _apply_ghost_payload 硬校验
        res = run_field_agent(
            backend, "ghost", label,
            thinking_budget=budget,
            indexed_segments=indexed,
            draft_value=draft_val,
            on_chat=_chat,
        )
        if not res.ok:
            fs.error = res.error or "ghost match failed"
            fs.match_type = "none"
            fs.index = -1
            with lock:
                done_count += 1
            progress_key = f"field:{label}"
            if state.progress is not None:
                state.progress[progress_key] = "done"
            _log(f"[field_match] matching [{label}] ({done_count}/{total}) -> none index=-1")
        elif res.payload:
            raw_idx = int(res.payload.get("index", -1))
            raw_idx, seg_text = _resolve_draft_index(
                indexed, draft_val, raw_idx, label=label,
            )
            field_payload = dict(res.payload)
            field_payload["index"] = raw_idx
            from llm_toml_wizard.toml_config.field_agent import _apply_ghost_payload
            mt, idx, needs = _apply_ghost_payload(
                field_payload, draft=draft_val, segment=seg_text,
            )
            fs.match_type = mt
            fs.index = idx
            fs.needs_regex = needs
            fs.used_thinking = res.used_thinking
            reason = str(res.payload.get("reason") or "")
            content = str(indexed.get(idx, "")) if idx >= 0 else ""
            with lock:
                done_count += 1
            progress_key = f"field:{label}"
            if state.progress is not None:
                state.progress[progress_key] = "done"
            _log(
                f"[field_match] matching [{label}] ({done_count}/{total}) "
                f"-> {fs.match_type} index={fs.index}"
            )

    if total > 0:
        map_run_sequential(_ghost_worker, labels)

    # 汇总错误
    failed = [label for label, fs in state.fields.items() if fs.error]
    if failed:
        _log(f"[field_match] done, {len(failed)} failed: {', '.join(failed)}")
    else:
        _log("[field_match] done, all fields ok")

    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
    except Exception as exc:
        _log(f"[field_match] TOML persist failed: {exc}")

    patch = {"current_step": 5}
    patch.update(_progress_patch(state, "field_match"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="match_ghost_fields",
    )


def _action_match_sheet_columns(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 5：Google Sheet 列匹配（跳过无 Google 源时）。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    def _chat(role: str, text: str) -> None:
        _log(f"[{role}] {text}")

    has_sheet = any(
        ds.get("type") == "google_sheet" or ds.get("source1")
        for ds in state.data_sources
    )
    if not has_sheet or not state.google_sheet_headers:
        _log("[sheet_match] skipped — no Google source")
        try:
            persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
        except Exception as exc:
            _log(f"[sheet_match] TOML persist failed: {exc}")
        patch = {"current_step": 6}
        patch.update(_progress_patch(state, "sheet_match", status="skip"))
        return ExecutorResult(
            ok=True,
            messages=messages,
            state_patch=patch,
            interrupt=None,
            route_key="skip_sheet",
        )

    headers = list(state.google_sheet_headers)
    rows = list(state.google_sheet_sample)
    source_file = "source1"
    source_sheet = str(state.google_sheet_sample[0][0].split("\n")[0]) if rows and rows[0] else ""

    labels_to_match: list[str] = []
    for label in state.template_labels or []:
        fs = state.fields.get(label)
        if not fs or fs.column_name:
            continue
        labels_to_match.append(label)

    total = len(labels_to_match)
    budget: int = int(ctx.get("thinking_budget") or 512)
    lock = threading.Lock()
    done_count = 0

    def _sheet_worker(label: str) -> None:
        nonlocal done_count
        res = run_field_agent(
            backend, "sheet", label,
            google_headers=headers, google_rows=rows,
            thinking_budget=budget, on_chat=_chat,
        )
        fs = state.fields[label] if label in state.fields else None
        if not fs:
            return
        if not res.ok:
            fs.error = res.error or "sheet match failed"
        elif res.payload:
            from llm_toml_wizard.toml_config.field_agent import _apply_sheet_payload
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

    if total > 0:
        map_run_sequential(_sheet_worker, labels_to_match)

    failed = [label for label, fs in state.fields.items() if fs.error and label not in set(state.template_labels)]
    # 在已知标签范围内汇总
    known_failed = [l for l in failed if l in (state.planned_labels or state.template_labels)]
    if known_failed:
        _log(f"[sheet_match] done, {len(known_failed)} failed: {', '.join(known_failed)}")
    else:
        _log("[sheet_match] done, all fields ok")

    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
    except Exception as exc:
        _log(f"[sheet_match] TOML persist failed: {exc}")

    patch = {
        "current_step": 6,
        "google_sheet_headers": headers,
        "google_sheet_sample": rows,
    }
    patch.update(_progress_patch(state, "sheet_match"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="match_sheet_columns",
    )


def _action_infer_regex(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 6：为模糊匹配字段推理 Python 正则。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    def _chat(role: str, text: str) -> None:
        _log(f"[{role}] {text}")

    regex_labels = [
        label for label in state.template_labels
        if state.fields[label].needs_regex
    ]
    total = len(regex_labels)
    _log(f"[regex_infer] Regex for {total} fields")
    sample = state.ghost_text_sample
    indexed = state.indexed_segments
    budget: int = int(ctx.get("thinking_budget") or 512)
    lock = threading.Lock()
    done_count = 0

    def _regex_worker(label: str) -> None:
        nonlocal done_count
        fs = state.fields[label]
        draft_val = str(state.user_draft.get(label, "") or "").strip()
        # haystack = 该字段命中 index 的段文本；draft 不在段内时按值重定位 index
        resolved_idx, segment = _resolve_draft_index(
            indexed, draft_val, fs.index, label=label,
        )
        if resolved_idx >= 0:
            fs.index = resolved_idx
        haystack = segment.strip() or sample
        # 段文本与 draft 全等时无需 regex
        if draft_val and segment.strip() == draft_val:
            fs.needs_regex = False
            fs.match_type = "exact"
            fs.regex = ""
            fs.error = ""
            _log(f"[regex_infer] [{label}] skip — exact value at index={fs.index}")
            with lock:
                done_count += 1
            return
        # haystack 不含 draft 或格式不兼容时跳过 LLM，避免 label-only 段死循环
        if draft_val and haystack and not _draft_haystack_compatible(haystack, draft_val):
            fs.needs_regex = False
            fs.error = f"segment at index={fs.index} lacks draft value"
            _log(f"[regex_infer] [{label}] skip — haystack lacks draft")
            with lock:
                done_count += 1
            return
        if not fs.needs_regex:
            _log(f"[regex_infer] [{label}] skip — needs_regex=False")
            with lock:
                done_count += 1
            return

        res = run_field_agent(
            backend, "regex", label,
            ghost_sample=sample,
            raw_text_for_regex=haystack,
            draft_value=draft_val,
            thinking_budget=budget,
            on_chat=_chat,
        )
        if res.ok and res.payload:
            fs.regex = str(res.payload.get("regex", ""))
            fs.used_thinking = res.used_thinking
            fs.error = ""
            fs.needs_regex = False
            _log(f"[regex_infer] [{label}] Thinking retry ok")
        elif not res.ok:
            fs.error = res.error
            fs.used_thinking = res.used_thinking
            fs.needs_regex = False
            _log(f"[regex_infer] [{label}] failed: {res.error}")
        with lock:
            done_count += 1

    if total > 0:
        map_run_sequential(_regex_worker, regex_labels)

    failed = [label for label, fs in state.fields.items() if fs.error and label not in set(state.template_labels)]
    known_failed = [l for l in failed if l in (state.planned_labels or state.template_labels)]
    if known_failed:
        _log(f"[regex_infer] done, {len(known_failed)} failed: {', '.join(known_failed)}")
    else:
        _log("[regex_infer] done, all fields ok")

    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
    except Exception as exc:
        _log(f"[regex_infer] TOML persist failed: {exc}")

    patch = {"current_step": 7}
    patch.update(_progress_patch(state, "regex_infer"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="infer_regex",
    )


def _action_finalize_toml(
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """步骤 7：最终化 TOML — db_id + 写入。"""
    messages: list[str] = []

    def _log(msg: str) -> None:
        messages.append(msg)
        if on_progress is not None:
            try:
                on_progress(msg)
            except Exception:
                pass

    if not state.user_inputs.get("db_id_confirmed"):
        return ExecutorResult(
            ok=False,
            messages=["finalize_toml interrupted: db_id selection required"],
            state_patch={},
            interrupt=InterruptPayload(
                kind="ask_db_id",
                expected_input="db_id",
            ),
            route_key="finalize_toml",
        )
    raw_id = str(state.db_id or "").strip()
    db_id = "" if raw_id in ("", "None") else raw_id
    for fs in state.fields.values():
        fs.id = bool(db_id) and fs.input_label == db_id
    note = db_id if db_id else "(none)"
    _log(f"[db_id] db_id={note}; write TOML and finish (no trial)")
    main_turn = ctx.get("main_turn")
    if callable(main_turn):
        main_turn(f"User selected db_id={note}")

    try:
        persist_wizard_toml(state, str(state.template_id or "") if state.template_id else "")
        _log(_persist_message(state, "[db_id]"))
    except Exception as exc:
        _log(f"[db_id] TOML persist failed: {exc}")

    state.is_finished = True
    patch = {
        "current_step": 7,
        "db_id": db_id,
        "is_finished": True,
    }
    patch.update(_progress_patch(state, "db_id"))
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch=patch,
        interrupt=None,
        route_key="finalize_toml",
    )


# --- Action handler registry ---

ACTION_HANDLERS: dict[str, Callable] = {
    "capture_sources": _action_capture_sources,
    "record_sources": _action_record_sources,
    "capture_layout": _action_capture_layout,
    "capture_sample": _action_capture_sample,
    "preprocess_sample": _action_preprocess_sample,
    "plan_ghost_tasks": _action_plan_ghost_tasks,
    "match_ghost_fields": _action_match_ghost_fields,
    "match_sheet_columns": _action_match_sheet_columns,
    "infer_regex": _action_infer_regex,
    "finalize_toml": _action_finalize_toml,
}


def execute(
    decision: Decision,
    state: WorkflowState,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    on_match_notify,
    main_turn: Callable[[str], str] | None = None,
    determiner_one_shot: Callable[[str], str] | None = None,
    thinking_budget: int = 512,
) -> ExecutorResult:
    """
    函数名: execute
    作用: 根据 Decision.action_id 调用对应 action handler
    输入:
        decision (Decision): 决策结果（含 action_id）
        state (WorkflowState): 当前工作流状态
        backend (LlmBackend): LLM 后端
        on_progress (Callable): 进度日志回调
        on_chat (Callable): 聊天日志回调
        on_match_notify (Callable): 匹配提醒回调
        main_turn (Callable | None): 持久 wizard_main 对话轮次
        determiner_one_shot (Callable | None): plain-text determiner 一次性会话
        thinking_budget (int): field agent thinking token 预算
    输出:
        ExecutorResult: 执行结果（含 state_patch / interrupt）
    """
    handler = ACTION_HANDLERS.get(decision.action_id)
    if handler is None:
        return ExecutorResult(
            ok=False,
            messages=[f"unknown action_id: {decision.action_id}"],
            state_patch={},
            route_key=decision.route_key or decision.action_id,
        )

    ctx = _executor_ctx(
        main_turn=main_turn,
        determiner_one_shot=determiner_one_shot,
        thinking_budget=thinking_budget,
    )
    try:
        result = handler(
            state,
            backend,
            on_progress=on_progress,
            on_chat=on_chat,
            on_match_notify=on_match_notify,
            ctx=ctx,
        )
    except ValueError as exc:
        return ExecutorResult(
            ok=False,
            messages=[str(exc)],
            state_patch={},
            route_key=decision.route_key or decision.action_id,
        )

    # 检查中断：各 action 可能在 state.state_pending_interrupt 中设置 payload
    interrupt = None
    if isinstance(result, ExecutorResult):
        interrupt = result.interrupt
        messages = result.messages
        patch = result.state_patch
        route_key = result.route_key
    else:
        # fallback: 从结果中提取 info（兼容旧签名）
        try:
            if hasattr(result, "state"):
                state.update(result.state)
            return ExecutorResult(ok=True, messages=[], state_patch={}, interrupt=None)
        except Exception as exc:
            return ExecutorResult(
                ok=False,
                messages=[str(exc)],
                state_patch={},
                route_key=decision.route_key or decision.action_id,
            )

    if interrupt is not None and _should_skip_interrupt(state, decision.action_id):
        key = intake_key_for_action(decision.action_id) or decision.action_id
        return ExecutorResult(
            ok=True,
            messages=[f"skip ask {key}, already captured"],
            state_patch=patch or {},
            interrupt=None,
            route_key="already_have",
        )

    if interrupt is not None and on_match_notify is not None:
        try:
            on_match_notify(f"Workflow interrupted: {interrupt.kind}")
        except Exception:
            pass

    return ExecutorResult(
        ok=True if interrupt is not None else bool(result.ok),
        messages=messages if isinstance(messages, list) else [str(messages)],
        state_patch=patch or {},
        interrupt=interrupt,
        route_key=route_key or decision.route_key,
    )
