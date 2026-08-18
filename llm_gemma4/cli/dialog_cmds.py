"""对话 CLI：主会话 + 动态 intake 中断 + 子代理分派。不写 TOML。"""

from __future__ import annotations

from argparse import Namespace
from typing import Any

from llm_gemma4.cli.briefing import DEMO_FACTS, BriefingSpec
from llm_gemma4.dialog import ACTION_CATALOG, ACTION_HANDLERS, DialogOrchestrator, pending_needs
from llm_gemma4.dialog.spec import DialogSpec
from llm_gemma4.dialog.state import DialogState
from llm_gemma4.toml_config.spec import (
    TOML_DEMO_AUTO,
    TOML_DEMO_DRAFT,
    TOML_DEMO_GHOST,
    TOML_DEMO_GOAL,
    TOML_DEMO_LABELS,
    TomlGuideSpec,
)
from llm_gemma4.workflow.events import (
    EVENT_FINISHED,
    EVENT_INTERRUPT,
    EVENT_RESUME,
    EVENT_START,
    EVENT_STOP,
    WorkflowEvent,
)


def _print(msg: str) -> None:
    print(msg, flush=True)


def _spec_name(args: Namespace) -> str:
    """
    函数名: _spec_name
    作用: 读取 --spec，默认 briefing
    输入:
        args (Namespace): 可能含 spec
    输出:
        str: briefing 或 toml
    """
    name = str(getattr(args, "spec", None) or "briefing").strip().lower()
    if name in ("toml", "toml_guide", "wizard"):
        return "toml"
    return "briefing"


def _make_spec(args: Namespace) -> DialogSpec:
    """
    函数名: _make_spec
    作用: 按 --spec 构造 BriefingSpec 或 TomlGuideSpec
    输入:
        args (Namespace): spec / write_toml
    输出:
        DialogSpec: 域插件
    """
    if _spec_name(args) == "toml":
        return TomlGuideSpec(write_toml=bool(getattr(args, "write_toml", False)))
    return BriefingSpec()


def _make_backend(args: Namespace):
    """
    函数名: _make_backend
    作用: mock 脚本后端或真实 LiteRT 后端
    输入:
        args (Namespace): mock / force_thinking_retry
    输出:
        LlmBackend: 后端实例
    """
    if args.mock:
        from llm_gemma4.cli.mock_backend import ScriptedBackend
        return ScriptedBackend(force_thinking_retry=bool(args.force_thinking_retry))
    from llm_gemma4.__main__ import _get_backend
    return _get_backend()


def _make_orchestrator(args: Namespace) -> DialogOrchestrator:
    """
    函数名: _make_orchestrator
    作用: 绑定域 spec 与后端
    输入:
        args (Namespace): stub / mock / spec
    输出:
        DialogOrchestrator
    """
    backend = _make_backend(args)
    spec = _make_spec(args)
    return DialogOrchestrator(
        backend,
        spec,
        stub=bool(args.stub),
        thread_id=f"cli:{spec.name}",
        on_progress=lambda msg: _print(msg),
        on_chat=lambda role, text: _print(f"[{role}] {text[:400]}"),
    )


def _dump_state(orch: DialogOrchestrator) -> None:
    """
    函数名: _dump_state
    作用: 打印 facts / progress / artifacts 摘要
    输入:
        orch (DialogOrchestrator): 编排器
    输出: 无
    """
    state = orch.state
    _print(f"goal={state.goal!r}")
    _print(f"facts={state.facts}")
    _print(f"progress={state.progress}")
    pending = [item.key for item in pending_needs(state)]
    _print(f"pending={pending}")
    _print(f"artifacts={list(state.artifacts.keys())}")
    preview = state.artifacts.get("toml_preview")
    if preview:
        _print("--- toml_preview (dry-run, not written) ---")
        _print(str(preview)[:800])
    if state.last_summary:
        _print("--- summary ---")
        _print(state.last_summary)


def _prompt_fact(interrupt) -> dict[str, Any]:
    """
    函数名: _prompt_fact
    作用: 按 ask_fact 中断从 stdin 读一条事实
    输入:
        interrupt: InterruptPayload
    输出:
        dict: fact_key / fact_value
    """
    meta = dict(getattr(interrupt, "meta", None) or {})
    key = str(meta.get("key") or "fact")
    question = str(getattr(interrupt, "expected_input", None) or meta.get("question") or key)
    _print(f"need [{key}]: {question}")
    try:
        value = input("> ").strip()
    except EOFError:
        value = ""
    return {"fact_key": key, "fact_value": value}


def _prompt_toml_interrupt(kind: str, interrupt) -> dict[str, Any]:
    """
    函数名: _prompt_toml_interrupt
    作用: 交互采集 ask_sources / ask_layout / ask_sample / ask_db_id
    输入:
        kind (str): 中断 kind
        interrupt: InterruptPayload
    输出:
        dict: 写入 TomlGuideSpec.merge_resume 的载荷
    """
    expected = str(getattr(interrupt, "expected_input", None) or kind)
    _print(f"need [{kind}]: {expected}")
    if kind == "ask_sources":
        _print("Enter skip to skip Google, or a source URL.")
        try:
            value = input("> ").strip()
        except EOFError:
            value = "skip"
        if value.lower() in ("", "skip", "none"):
            return {"data_sources_skipped": True}
        return {"data_sources": [{"type": "google_sheet", "source1": value}]}
    if kind == "ask_layout":
        _print("Format: input_area [move_to] [offset]  e.g. B2:F20 down 1")
        try:
            raw = input("> ").strip()
        except EOFError:
            raw = "B2:F20 down 1"
        parts = raw.split()
        area = parts[0] if parts else "B2:F20"
        move = parts[1] if len(parts) > 1 else "down"
        try:
            offset = int(parts[2]) if len(parts) > 2 else 1
        except ValueError:
            offset = 1
        return {"input_area": area, "move_to": move, "offset": offset}
    if kind == "ask_sample":
        _print("Paste ghost sample (one line). Drafts default to demo Ginger values if empty.")
        try:
            ghost = input("ghost> ").strip()
        except EOFError:
            ghost = ""
        return {
            "ghost_text_sample": ghost or TOML_DEMO_GHOST,
            "user_draft": dict(TOML_DEMO_DRAFT),
            "template_labels": list(TOML_DEMO_LABELS),
        }
    if kind == "ask_db_id":
        _print("Primary key label, or empty for none.")
        try:
            db_id = input("> ").strip()
        except EOFError:
            db_id = ""
        return {"db_id": db_id, "db_id_confirmed": True}
    return _prompt_fact(interrupt)


def _run_loop(
    orch: DialogOrchestrator,
    start_payload: dict[str, Any],
    *,
    auto_facts: dict[str, str] | None,
    auto_resumes: dict[str, dict[str, Any]] | None = None,
) -> int:
    """
    函数名: _run_loop
    作用: dispatch start，遇中断则采集事实并 resume，直到 finished/error/stop
    输入:
        orch (DialogOrchestrator): 编排器
        start_payload (dict): 启动载荷
        auto_facts (dict | None): briefing 非交互回放（fact_key）
        auto_resumes (dict | None): toml 中断 kind → resume 载荷
    输出:
        int: 退出码
    """
    remaining = dict(auto_facts or {})
    resumes = dict(auto_resumes or {})
    outbound = orch.dispatch(WorkflowEvent(type=EVENT_START, payload=dict(start_payload)))
    while True:
        if outbound.type == EVENT_FINISHED:
            _print("[event] finished")
            _dump_state(orch)
            orch.close()
            return 0
        if outbound.type == EVENT_STOP:
            _print("[event] stopped")
            return 0
        if outbound.type != EVENT_INTERRUPT:
            _print(f"[event] {outbound.type} {outbound.payload}")
            orch.close()
            return 1 if outbound.type != EVENT_FINISHED else 0
        interrupt = outbound.interrupt or orch.pending_interrupt
        kind = getattr(interrupt, "kind", "") if interrupt is not None else ""
        _print(f"[event] interrupt kind={kind}")
        payload: dict[str, Any] = {}
        if kind and kind in resumes:
            payload = dict(resumes[kind])
            _print(f"[auto] {kind} keys={list(payload.keys())}")
        elif kind == "ask_fact" and interrupt is not None:
            meta = dict(interrupt.meta or {})
            key = str(meta.get("key") or "")
            if key and key in remaining:
                payload = {"fact_key": key, "fact_value": remaining.pop(key)}
                _print(f"[auto] {key}={payload['fact_value'][:80]}")
            elif key and key in start_payload.get("facts", {}):
                payload = {"fact_key": key, "fact_value": str(start_payload["facts"][key])}
            else:
                payload = _prompt_fact(interrupt)
        elif kind in ("ask_sources", "ask_layout", "ask_sample", "ask_db_id") and interrupt is not None:
            payload = _prompt_toml_interrupt(kind, interrupt)
        else:
            payload = _prompt_fact(interrupt) if interrupt is not None else {}
        outbound = orch.dispatch(WorkflowEvent(type=EVENT_RESUME, payload=payload))


def cmd_catalog(args: Namespace) -> int:
    """
    函数名: cmd_catalog
    作用: 打印当前 spec 的动作表与 intake（briefing 为通用五动作，toml 为九动作）
    输入:
        args (Namespace): spec
    输出:
        int: 0
    """
    spec = _make_spec(args)
    catalog = spec.get_decision_catalog() or ACTION_CATALOG
    handlers = spec.get_action_handlers() or ACTION_HANDLERS
    _print(f"spec={spec.name}")
    if spec.name == "toml":
        _print("domain actions (TomlGuideSpec weights; runtime is llm_gemma4.dialog):")
    else:
        _print("runtime actions (llm_gemma4.dialog, not toml_config):")
    _print(catalog)
    _print("handlers: " + ", ".join(sorted(handlers)))
    _print("interrupt kinds: " + ", ".join(sorted(spec.get_interrupt_kinds())))
    _print("initial intake:")
    for item in spec.initial_intake:
        _print(f"  - {item.key}: {item.question} required={item.required}")
    jobs = spec.build_jobs(DialogState())
    job_ids = ", ".join(job.job_id for job in jobs) or "(none)"
    _print(f"build_jobs on empty state: {job_ids}")
    if spec.name == "toml":
        _print("job kinds: determiner; ghost_{label} (thinking on pass2); sheet_{label}; regex_{label}")
    _print("sessions: dialog_main (thinking=False); dialog_decision_* / wizard_decision_* (thinking=False);")
    _print("          wizard_determiner_* (thinking=False); field_{label}_pass1 (False); field_{label}_pass2 (True)")
    return 0


def cmd_dialog_run(args: Namespace) -> int:
    """
    函数名: cmd_dialog_run
    作用: 交互或预填后跑 briefing / toml 对话
    输入:
        args (Namespace): spec / goal / material / stub / mock / demo / write_toml
    输出:
        int: 退出码
    """
    orch = _make_orchestrator(args)
    auto_resumes: dict[str, dict[str, Any]] | None = None
    if _spec_name(args) == "toml":
        payload: dict[str, Any] = {
            "goal": args.goal or TOML_DEMO_GOAL,
            "template_id": "cli_toml_demo",
            "template_labels": list(TOML_DEMO_LABELS),
        }
        if args.demo or args.non_interactive:
            auto_resumes = {kind: dict(blob) for kind, blob in TOML_DEMO_AUTO.items()}
        try:
            return _run_loop(orch, payload, auto_facts=None, auto_resumes=auto_resumes)
        finally:
            orch.close()
            if (not args.mock) and args.release:
                from llm_gemma4.__main__ import EndGemma
                EndGemma()
    facts: dict[str, str] = {}
    if args.demo:
        facts.update(DEMO_FACTS)
    if args.goal:
        facts["goal"] = args.goal
    if args.material:
        facts["material"] = args.material
    if args.constraints:
        facts["constraints"] = args.constraints
    if args.output_shape:
        facts["output_shape"] = args.output_shape
    payload = {"facts": dict(facts)}
    if facts.get("goal"):
        payload["goal"] = facts["goal"]
    auto = dict(facts) if (args.demo or args.non_interactive) else None
    try:
        return _run_loop(orch, payload, auto_facts=auto)
    finally:
        orch.close()
        if (not args.mock) and args.release:
            from llm_gemma4.__main__ import EndGemma
            EndGemma()


def cmd_dialog_demo(args: Namespace) -> int:
    """
    函数名: cmd_dialog_demo
    作用: 用内置材料非交互跑完整 briefing（默认 mock+stub）
    输入:
        args (Namespace): live 时用真模型
    输出:
        int: 退出码
    """
    if not args.live:
        args.mock = True
        args.stub = True
    args.demo = True
    args.non_interactive = True
    args.goal = args.goal or ""
    args.material = args.material or ""
    args.constraints = args.constraints or ""
    args.output_shape = args.output_shape or ""
    return cmd_dialog_run(args)
