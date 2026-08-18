"""通用动作：规划 intake、询问用户、分派子代理、主对话综合、结束。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from llm_gemma4.backends.base import LlmBackend
from llm_gemma4.dialog.spec import DialogSpec
from llm_gemma4.dialog.state import DialogState, pending_needs, upsert_intake
from llm_gemma4.dialog.subagent import run_subagent
from llm_gemma4.runtime.json_extract import extract_json_object
from llm_gemma4.workflow.parallel import map_run_sequential
from llm_gemma4.workflow.state import ExecutorResult, InterruptPayload


def _log(messages: list[str], on_progress, msg: str) -> None:
    """
    函数名: _log
    作用: 收集动作日志并即时推给 on_progress
    输入:
        messages (list[str]): 本动作日志缓冲
        on_progress: 进度回调，可为 None
        msg (str): 一行日志
    输出: 无
    """
    messages.append(msg)
    if on_progress is not None:
        try:
            on_progress(msg)
        except Exception:
            pass


def action_plan_intake(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """
    函数名: action_plan_intake
    作用: 主对话根据目标动态列出仍需采集的事实
    输入:
        state (DialogState): 对话状态
        spec (DialogSpec): 域插件
        backend (LlmBackend): 未直接使用；主对话走 ctx.main_turn
        on_progress: 进度回调
        on_chat: 对话回调
        ctx (dict): 含 main_turn
    输出:
        ExecutorResult: 更新 intake 后的补丁
    """
    messages: list[str] = []
    # 中文注释: 启动时已有 initial_intake；主对话可以追加 key，不能删掉已采集项
    upsert_intake(state, list(spec.initial_intake))
    main_turn = ctx.get("main_turn")
    captured = {k: v for k, v in state.facts.items() if str(v or "").strip()}
    body = (
        f"{spec.plan_intake_user}\n\n"
        f"goal: {state.goal or '(none)'}\n"
        f"already captured: {captured or '(none)'}\n"
        f"current intake keys: {[item.key for item in state.intake]}"
    )
    reply = ""
    if callable(main_turn):
        reply = main_turn(body) or ""
    payload, err = extract_json_object(reply) if reply else (None, "empty")
    extra = spec.parse_plan_needs(payload) if payload else []
    if extra:
        upsert_intake(state, extra)
        _log(messages, on_progress, f"[intake] planned extra keys: {[n.key for n in extra]}")
    elif err:
        _log(messages, on_progress, f"[intake] keep initial list ({err})")
    else:
        _log(messages, on_progress, "[intake] no extra keys from main session")
    state.intake_planned = True
    needs = [item.key for item in state.intake]
    _log(messages, on_progress, f"[intake] keys={needs}")
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={
            "intake_planned": True,
            "progress": dict(state.progress),
        },
        route_key="plan_intake",
    )


def action_ask_user(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """
    函数名: action_ask_user
    作用: 对下一个未采集 required key 发出中断；已齐则跳过
    输入:
        state / spec / backend / 回调 / ctx: 同其它 action
    输出:
        ExecutorResult: 中断或 already_have
    """
    messages: list[str] = []
    waiting = pending_needs(state)
    if not waiting:
        _log(messages, on_progress, "[ask] nothing pending")
        return ExecutorResult(ok=True, messages=messages, state_patch={}, route_key="already_have")
    item = waiting[0]
    _log(messages, on_progress, f"[ask] interrupt key={item.key}")
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={},
        interrupt=InterruptPayload(
            kind="ask_fact",
            expected_input=item.question,
            meta={"key": item.key, "question": item.question},
        ),
        route_key="ask_user",
    )


def action_dispatch_subagents(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """
    函数名: action_dispatch_subagents
    作用: 按 spec.build_jobs 顺序分派子代理（LiteRT 禁止线程池推理）
    输入:
        state / spec / backend / 回调 / ctx: ctx.thinking_budget
    输出:
        ExecutorResult: artifacts 补丁
    """
    messages: list[str] = []
    jobs = list(spec.build_jobs(state) or [])
    if not jobs:
        _log(messages, on_progress, "[subagent] spec produced no jobs")
        state.artifacts["(none)"] = {"ok": True, "note": "no jobs"}
        return ExecutorResult(
            ok=True,
            messages=messages,
            state_patch={"artifacts": dict(state.artifacts)},
            route_key="dispatch_subagents",
        )
    budget = int(ctx.get("thinking_budget") or 512)
    chat: Callable[[str, str], None] | None = on_chat if callable(on_chat) else None

    def _run_one(job_id: str):
        job = next(j for j in jobs if j.job_id == job_id)
        _log(messages, on_progress, f"[subagent] start {job.job_id}")
        result = run_subagent(
            backend,
            job_id=job.job_id,
            system=job.system,
            user=job.user,
            parse_json=job.parse_json,
            allow_thinking_retry=job.allow_thinking_retry,
            thinking_budget=budget,
            on_chat=chat,
        )
        note = "thinking-retry" if result.used_thinking else "pass1"
        status = "ok" if result.ok else f"fail:{result.error}"
        _log(messages, on_progress, f"[subagent] {job.job_id} {status} ({note})")
        return job.job_id, {
            "ok": result.ok,
            "text": result.text,
            "payload": result.payload,
            "error": result.error,
            "used_thinking": result.used_thinking,
            "session_ids": result.session_ids,
        }

    ordered_ids = [job.job_id for job in jobs]
    pairs = map_run_sequential(_run_one, ordered_ids)
    artifacts = dict(state.artifacts)
    for job_id, blob in pairs:
        artifacts[job_id] = blob
    state.artifacts = artifacts
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={"artifacts": artifacts},
        route_key="dispatch_subagents",
    )


def action_synthesize(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """
    函数名: action_synthesize
    作用: 主对话综合 facts + artifacts 写成最终答复
    输入:
        state / spec / backend / 回调 / ctx.main_turn
    输出:
        ExecutorResult: last_summary 补丁
    """
    messages: list[str] = []
    main_turn = ctx.get("main_turn")
    artifact_lines: list[str] = []
    for job_id, blob in state.artifacts.items():
        if not isinstance(blob, dict):
            artifact_lines.append(f"{job_id}: {blob}")
            continue
        payload = blob.get("payload")
        text = blob.get("text") or ""
        artifact_lines.append(f"{job_id} ok={blob.get('ok')} thinking={blob.get('used_thinking')}")
        if payload is not None:
            artifact_lines.append(str(payload)[:1500])
        elif text:
            artifact_lines.append(text[:1500])
    body = (
        f"{spec.synthesize_user}\n\n"
        f"goal: {state.goal}\n"
        f"facts: {state.facts}\n"
        f"sub-agent results:\n" + "\n".join(artifact_lines)
    )
    summary = ""
    if callable(main_turn):
        summary = main_turn(body) or ""
    state.last_summary = summary
    preview = summary.replace("\n", " ")[:160]
    _log(messages, on_progress, f"[synthesize] {preview}")
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={"last_summary": summary},
        route_key="synthesize",
    )


def action_finish(
    state: DialogState,
    spec: DialogSpec,
    backend: LlmBackend,
    *,
    on_progress,
    on_chat,
    ctx: dict[str, Any],
) -> ExecutorResult:
    """
    函数名: action_finish
    作用: 标记对话结束
    输入:
        state / spec / backend / 回调 / ctx
    输出:
        ExecutorResult: is_finished=True
    """
    messages: list[str] = []
    _log(messages, on_progress, "[finish] dialog complete")
    state.is_finished = True
    return ExecutorResult(
        ok=True,
        messages=messages,
        state_patch={"is_finished": True},
        route_key="finish",
    )


ACTION_HANDLERS: dict[str, Callable[..., ExecutorResult]] = {
    "plan_intake": action_plan_intake,
    "ask_user": action_ask_user,
    "dispatch_subagents": action_dispatch_subagents,
    "synthesize": action_synthesize,
    "finish": action_finish,
}
