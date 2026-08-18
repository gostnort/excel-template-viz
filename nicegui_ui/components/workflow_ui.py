"""TOML 工作流进程内 UI：interrupt + progress 驱动，无固定 8 步状态机。"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Callable

from nicegui import app, ui
from nicegui.client import Client

from llm_gemma4.workflow.events import (
    EVENT_ERROR,
    EVENT_FINISHED,
    EVENT_INTERRUPT,
    EVENT_RESUME,
    EVENT_START,
    EVENT_STOP,
    WorkflowEvent,
)
from llm_gemma4.workflow.state import WorkflowState
from nicegui_ui.components.buttons import AppBtn
from nicegui_ui.components.general import SessionRegistry
from nicegui_ui.components.model_runtime import is_gemma_loaded
from nicegui_ui.components.toml_wizard import get_toml_wizard


_shell_switch_tab: Callable[[str], None] | None = None
_refresh_chrome: Callable[[], None] | None = None
_refresh_sidebar: Callable[[], None] | None = None
_current_dialog: ui.dialog | None = None
_layout_area_inputs: list[Any] = []
_layout_area_values: list[str] = []
_layout_move_order: list[str] = []
_layout_move_checks: dict[str, Any] = {}
_layout_move_order_label: Any = None
_layout_offset: Any = None
_step7_db_id: str = ""
_step7_select: Any = None
_step7_saving: bool = False
_DB_ID_NONE = "None"
_VALID_MOVE_TO = ("up", "down", "left", "right")
_EXCEL_AREA_RE = re.compile(r"^[A-Za-z]+\d+(?::[A-Za-z]+\d+)?$")
_EXCEL_AREA_FIND_RE = re.compile(r"[A-Za-z]+\d+(?::[A-Za-z]+\d+)?")
# 对话框内自带确认按钮的中断类型
_DIALOG_CONFIRM_INTERRUPTS = frozenset({"ask_layout", "ask_db_id"})
_INTERRUPT_TABS: dict[str, str] = {
    "ask_sources": "Google 连接",
    "ask_layout": "输入配置",
    "ask_sample": "输入",
    "ask_db_id": "输入配置",
}
_INTERRUPT_FAB_LABELS: dict[str, str] = {
    "ask_sources": "下一步",
    "ask_layout": "下一步",
    "ask_sample": "下一步",
    "ask_db_id": "下一步",
}


def register_shell(
    *,
    switch_tab: Callable[[str], None],
    refresh_chrome: Callable[[], None],
    refresh_sidebar: Callable[[], None] | None = None,
) -> None:
    """
    函数名: register_shell
    作用: 由 main.render_shell 注入 Tab 切换与 FAB 刷新回调
    输入:
        switch_tab: 切换顶栏 Tab 并刷新面板
        refresh_chrome: 刷新左下角工作流 FAB
        refresh_sidebar: 刷新 sidebar 内 Gemma 对话区
    输出: 无
    """
    global _shell_switch_tab, _refresh_chrome, _refresh_sidebar
    _shell_switch_tab = switch_tab
    _refresh_chrome = refresh_chrome
    _refresh_sidebar = refresh_sidebar


def _refresh_chrome_safe() -> None:
    if _refresh_chrome is not None:
        _refresh_chrome()


def _resolve_client(client: Client | None = None) -> Client | None:
    """
    函数名: _resolve_client
    作用: 解析 NiceGUI Client；FAB 刷新后 slot 失效时须提前捕获
    输入:
        client (Client | None): 调用方已捕获的 client
    输出:
        Client | None: 可用 client，无上下文时为 None
    """
    if client is not None:
        return client
    try:
        return ui.context.client
    except RuntimeError:
        return None


def _schedule_deferred(seconds: float, callback: Callable[[], None]) -> None:
    """
    函数名: _schedule_deferred
    作用: 用 asyncio 延迟回调，避免 ui.timer 挂在会被 refresh 销毁的 slot 上
    输入:
        seconds (float): 延迟秒数
        callback (Callable[[], None]): 到期后执行的同步回调
    输出: 无
    """
    async def _run() -> None:
        await asyncio.sleep(seconds)
        callback()
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        callback()


def _schedule_chrome_refresh(client: Client | None = None) -> None:
    _ = client
    _schedule_deferred(0.05, _refresh_chrome_safe)


def _schedule_sidebar_refresh(client: Client | None = None) -> None:
    if _refresh_sidebar is None:
        return
    _ = client
    _schedule_deferred(0.05, _refresh_sidebar)


def _user_storage() -> dict[str, Any] | None:
  # 读取 app.storage.user 前先探测会话是否已初始化（hasattr 会触发断言）
    try:
        return app.storage.user
    except (AssertionError, RuntimeError):
        return None


def _set_workflow_active(active: bool) -> None:
    store = _user_storage()
    if store is None:
        return
    store["workflow_active"] = active
    store["wizard_active"] = active
    _sync_workflow_shell_class(active)


def _sync_workflow_shell_class(active: bool | None = None) -> None:
    """
    函数名: _sync_workflow_shell_class
    作用: 按工作流开关同步 .shell.is-workflow-active（侧栏铺满对话 / 主区留白）
    输入:
        active (bool | None): 显式开关；None 时读 storage
    输出: 无
    """
    on = is_workflow_active() if active is None else bool(active)
    try:
        if on:
            ui.query(".shell").classes(add="is-workflow-active")
        else:
            ui.query(".shell").classes(remove="is-workflow-active")
    except Exception:
        return


def is_workflow_active() -> bool:
    """
    函数名: is_workflow_active
    作用: 当前会话是否处于 TOML 工作流模式
    输入: 无
    输出:
        bool: 工作流进行中为 True
    """
    store = _user_storage()
    if store is None:
        return False
    return bool(store.get("workflow_active") or store.get("wizard_active"))


def is_wizard_active() -> bool:
    """
    函数名: is_wizard_active
    作用: is_workflow_active 的向后兼容别名
    输入: 无
    输出:
        bool: 工作流进行中为 True
    """
    return is_workflow_active()


def render_progress_summary(state: WorkflowState) -> str:
    """
    函数名: render_progress_summary
    作用: 从 progress + history 生成用户可见进度文本
    输入:
        state (WorkflowState): 工作流状态
    输出:
        str: 多行进度摘要
    """
    lines: list[str] = []
    for key in sorted((state.progress or {}).keys()):
        status = state.progress.get(key, "pending")
        lines.append(f"[{status}] {key}")
    reasons: list[str] = []
    for entry in (state.history or [])[-6:]:
        dec = entry.get("decision") if isinstance(entry, dict) else None
        if isinstance(dec, dict) and dec.get("reason"):
            reasons.append(str(dec["reason"]))
    if reasons:
        lines.append("--- recent decisions ---")
        lines.extend(reasons[-3:])
    return "\n".join(lines)


def _switch_tab(tab_name: str) -> None:
    if _shell_switch_tab is not None:
        _shell_switch_tab(tab_name)
        return
    if hasattr(app.storage, "user"):
        if app.storage.user.get("active_tab") == tab_name:
            return
        app.storage.user["active_tab"] = tab_name


def _close_dialog() -> None:
    global _current_dialog
    if _current_dialog is not None:
        try:
            _current_dialog.close()
        except Exception:
            pass
        _current_dialog = None


def _resolve_ghost_sample(session) -> str:
    """
    函数名: _resolve_ghost_sample
    作用: 优先读取 Ghost 控件当前值；控件未挂载时回退 session 缓存
    输入:
        session: SessionRegistry 当前会话
    输出:
        str: 样本文本
    """
    from nicegui_ui.pages.tab_input import is_ghost_input_bound, read_ghost_sample
    if is_ghost_input_bound():
        live = read_ghost_sample()
        session.last_ghost_paste = live
        return live
    return (session.last_ghost_paste or "").strip()


def _orchestrator_has_google(ctrl) -> bool:
    if ctrl.orchestrator is None:
        return False
    sources = ctrl.orchestrator.state.data_sources
    return any(ds.get("type") == "google_sheet" or ds.get("source1") for ds in sources)


def _initial_tick_payload(ctrl) -> dict[str, Any]:
    sources = ctrl.build_data_sources()
    orch = ctrl.orchestrator
    if not sources and orch is not None:
        if orch.state.data_sources:
            sources = list(orch.state.data_sources)
        else:
            from llm_gemma4.toml_config.intake_seed import sidecar_data_sources
            tid = str(orch.state.template_id or "")
            if tid:
                sources = sidecar_data_sources(tid)
                if sources:
                    orch.state.data_sources = sources
    payload: dict[str, Any] = {
        **ctrl.session_payload_base(),
        "template_labels": ctrl.template_labels(),
    }
    if sources:
        payload["data_sources"] = sources
    return payload


def _fab_label(ctrl) -> str:
    if ctrl.is_busy:
        return "处理中…"
    orch = ctrl.orchestrator
    if orch is not None and orch.state.is_finished and not orch.is_interrupted():
        return "已完成"
    if orch is not None and orch.is_interrupted():
        kind = _pending_interrupt_kind(ctrl)
        if kind in _INTERRUPT_FAB_LABELS:
            return _INTERRUPT_FAB_LABELS[kind]
        pending = orch.pending_interrupt
        if pending is not None and pending.expected_input:
            text = str(pending.expected_input).strip()
            if text:
                return text[:48] + ("…" if len(text) > 48 else "")
        return "继续配置"
    return "下一步"


def _pending_interrupt_kind(ctrl) -> str | None:
    orch = ctrl.orchestrator
    if orch is None or not orch.is_interrupted():
        return None
    pending = orch.pending_interrupt
    return pending.kind if pending is not None else None


def _sync_area_values_from_inputs() -> None:
    global _layout_area_values
    synced: list[str] = []
    for inp in _layout_area_inputs:
        try:
            synced.append(str(inp.value or ""))
        except Exception:
            synced.append("")
    if synced:
        _layout_area_values = synced
    elif not _layout_area_values:
        _layout_area_values = [""]


def _refresh_move_order_label() -> None:
    if _layout_move_order_label is None:
        return
    if not _layout_move_order:
        _layout_move_order_label.set_text("尚未选择方向（须选 1～2 个）")
    elif len(_layout_move_order) == 1:
        _layout_move_order_label.set_text(f"当前：主轴 {_layout_move_order[0]}（单轴）")
    else:
        _layout_move_order_label.set_text(
            f"当前：主轴 {_layout_move_order[0]} · 次轴 {_layout_move_order[1]}"
        )


def _normalize_one_input_area(raw: str) -> tuple[str, str]:
    s = (raw or "").strip().replace(" ", "")
    if not s:
        return "", ""
    found = _EXCEL_AREA_FIND_RE.findall(s)
    if len(found) > 1 and "".join(found) == s:
        return "", f"input_area 疑似重复粘贴（{raw.strip()}），请拆成多行区域"
    if not _EXCEL_AREA_RE.match(s):
        return "", f"input_area 格式无效: {raw.strip()}（例 A2:G2 或 A2）"
    return s.upper(), ""


def _read_layout_payload() -> dict[str, Any]:
    _sync_area_values_from_inputs()
    areas: list[str] = []
    area_error = ""
    for raw in _layout_area_values:
        normalized, err = _normalize_one_input_area(str(raw or ""))
        if err:
            area_error = err
            break
        if normalized:
            areas.append(normalized)
    if not area_error and not areas:
        area_error = "请至少填写一个 input_area（可添加多个区域）"
    input_area: str | list[str] = areas[0] if len(areas) == 1 else areas
    move_error = ""
    move_dirs = [d for d in _layout_move_order if d in _VALID_MOVE_TO]
    if not move_dirs:
        move_error = "请至少勾选 1 个 move_to 方向"
        move_to: str | list[str] = "down"
    elif len(move_dirs) > 2:
        move_error = "move_to 最多勾选 2 个方向（主轴+次轴）"
        move_to = move_dirs[:2]
    else:
        move_to = move_dirs[0] if len(move_dirs) == 1 else move_dirs
    offset = 1
    if _layout_offset is not None:
        try:
            offset = int(_layout_offset.value)
        except (TypeError, ValueError):
            offset = 1
    return {
        "input_area": input_area,
        "move_to": move_to,
        "offset": offset,
        "area_error": area_error,
        "move_error": move_error,
    }


def _refresh_toml_tab() -> None:
    try:
        from nicegui_ui.pages.tab_toml import render_toml_tab
        render_toml_tab.refresh()
    except Exception:
        pass


async def _collect_resume_payload(ctrl, client: Client | None) -> dict[str, Any] | None:
    """
    函数名: _collect_resume_payload
    作用: 根据 pending_interrupt 从 UI 收集恢复 tick 的 payload
    输入:
        ctrl: TomlWizardController
        client (Client | None): NiceGUI client
    输出:
        dict | None: payload；校验失败时为 None
    """
    kind = _pending_interrupt_kind(ctrl)
    session = SessionRegistry.for_current()
    if kind is None:
        return {}
    if kind == "ask_sources":
        sources = ctrl.build_data_sources()
        payload = {
            **ctrl.session_payload_base(),
            "data_sources": sources,
            "template_labels": ctrl.template_labels(),
            **ctrl.google_payload(),
        }
        if not sources:
            payload["data_sources_skipped"] = True
        return payload
    if kind == "ask_layout":
        layout = _read_layout_payload()
        area_error = str(layout.get("area_error") or "")
        if area_error:
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify(area_error, type="warning")
            return None
        move_error = str(layout.get("move_error") or "")
        if move_error:
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify(move_error, type="warning")
            return None
        if not layout["input_area"]:
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("请至少填写一个 input_area", type="warning")
            return None
        if int(layout["offset"]) < 1:
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("offset 须为 ≥1 的整数", type="warning")
            return None
        return {
            **ctrl.session_payload_base(),
            "input_area": layout["input_area"],
            "move_to": layout["move_to"],
            "offset": layout["offset"],
        }
    if kind == "ask_sample":
        ghost = _resolve_ghost_sample(session)
        has_google = ctrl.has_google_sheet_source() or _orchestrator_has_google(ctrl)
        if not ghost and not has_google:
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("需要 Ghost 样本或 Google 数据源才能继续", type="warning")
            return None
        labels = ctrl.template_labels()
        from nicegui_ui.pages.tab_input import read_field_drafts
        user_draft = read_field_drafts(labels)
        session.draft.update(user_draft)
        return {
            **ctrl.session_payload_base(),
            "ghost_text_sample": ghost,
            "template_labels": labels,
            "user_draft": user_draft,
        }
    if kind == "ask_db_id":
        db_id = _step7_db_id
        if _step7_select is not None:
            raw = str(_step7_select.value or _DB_ID_NONE).strip() or _DB_ID_NONE
            db_id = "" if raw == _DB_ID_NONE else raw
        elif not db_id:
            db_id = ""
        return {"db_id": db_id, **ctrl.session_payload_base()}
    return dict(ctrl.session_payload_base())


async def _after_layout_resume(ctrl, client: Client | None) -> bool:
    """布局恢复后触发 TOML 保存并校验；失败时保留中断。"""
    session = SessionRegistry.for_current()
    from nicegui_ui.pages.tab_toml import trigger_toml_save
    trigger_toml_save(session)
    _refresh_toml_tab()
    report = session.verify_report or {}
    if report.get("ok"):
        from nicegui_ui.pages.tab_input import clear_field_drafts
        clear_field_drafts(session, ctrl.template_labels(), refresh_ui=True)
        _switch_tab("输入")
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify("TOML 已保存并应用，请在「输入」页填写测试数据后继续", type="positive")
        return True
    parts: list[str] = []
    if report.get("out_of_area_labels"):
        parts.append("越界标签: " + ", ".join(report["out_of_area_labels"]))
    if report.get("missing_labels"):
        parts.append("缺失标签: " + ", ".join(report["missing_labels"]))
    detail = "；".join(parts) if parts else "请检查 input_area 是否覆盖全部填写值列"
    resolved = _resolve_client(client)
    if resolved is not None:
        with resolved:
            ui.notify(f"布局校验失败。{detail}", type="warning")
    return False


async def _handle_outbound(ctrl, client: Client | None, outbound: WorkflowEvent | None) -> None:
    """
    函数名: _handle_outbound
    作用: 根据 Graph 出站事件刷新 UI：完成则停止，中断则弹窗，错误则通知
    输入:
        ctrl: TomlWizardController
        client (Client | None): NiceGUI client
        outbound (WorkflowEvent | None): dispatch 返回值
    输出: 无
    """
    if outbound is None or not is_workflow_active() or ctrl.is_stopping:
        return
    if outbound.type == EVENT_FINISHED:
        await stop_wizard("配置向导已完成")
        return
    if outbound.type == EVENT_ERROR:
        reason = str((outbound.payload or {}).get("reason") or "工作流错误")
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify(reason, type="negative")
        else:
            ui.notify(reason, type="negative")
        _schedule_chrome_refresh(client)
        _schedule_sidebar_refresh(client)
        return
    if ctrl.orchestrator is None:
        return
    kind = _pending_interrupt_kind(ctrl)
    if kind or outbound.type == EVENT_INTERRUPT:
        if not kind and outbound.interrupt is not None:
            kind = outbound.interrupt.kind
        tab = _INTERRUPT_TABS.get(kind or "")
        if tab:
            _switch_tab(tab)
        if kind:
            _schedule_interrupt_dialog(kind, client)
    _schedule_chrome_refresh(client)
    _schedule_sidebar_refresh(client)


def _show_interrupt_dialog(kind: str, *, client: Client | None = None) -> None:
    global _current_dialog
    global _layout_area_inputs, _layout_area_values
    global _layout_move_order, _layout_move_checks, _layout_move_order_label
    global _layout_offset
    global _step7_select, _step7_db_id
    _close_dialog()
    ctrl = get_toml_wizard()
    resolved = _resolve_client(client)
    ctx = resolved if resolved is not None else ui.context.client
    title_map = {
        "ask_sources": "数据源",
        "ask_layout": "布局 input_section",
        "ask_sample": "样本与字段草稿",
        "ask_db_id": "主键 db_id",
    }
    with ctx:
        with ui.dialog() as dialog, ui.card().classes("wizard-step-dialog w-11/12 max-w-4xl"):
            ui.label(f"配置向导 · {title_map.get(kind, kind)}").classes("text-lg font-bold mb-2")
            if kind == "ask_sources":
                ui.label(
                    "请在当前「Google 连接」页配置 OAuth 与 Sheet（可选）。"
                    "若不需要 Google 数据源可点「跳过 Google」或左下角继续。"
                ).classes("text-sm")
                async def _skip_google() -> None:
                    ctrl_local = get_toml_wizard()
                    if ctrl_local.is_busy:
                        return
                    client_local = _resolve_client(client)
                    payload = {
                        **ctrl_local.session_payload_base(),
                        "data_sources": [],
                        "data_sources_skipped": True,
                        "template_labels": ctrl_local.template_labels(),
                    }
                    _close_dialog()
                    outbound = await ctrl_local.dispatch(
                        WorkflowEvent(type=EVENT_RESUME, payload=payload)
                    )
                    await _handle_outbound(ctrl_local, client_local, outbound)
                with ui.row().classes("mt-2"):
                    AppBtn("跳过 Google", variant="default", on_click=_skip_google)
            elif kind == "ask_layout":
                _render_layout_dialog_body(ctrl)
            elif kind == "ask_sample":
                ui.label(
                    "请在「输入」页填写/粘贴测试数据（Ghost 样本或字段草稿），"
                    "完成后点左下角继续。"
                ).classes("text-sm")
            elif kind == "ask_db_id":
                _render_db_id_dialog_body(ctrl)
            else:
                ui.label(f"等待输入: {kind}").classes("text-sm")
            if kind in _DIALOG_CONFIRM_INTERRUPTS:
                with ui.row().classes("mt-4 w-full items-center justify-between gap-2"):
                    ui.button("关闭说明", on_click=dialog.close).props("flat")
                    cta = "保存配置文件" if kind == "ask_db_id" else "确认并继续"
                    AppBtn(
                        cta,
                        variant="danger",
                        disabled=False if kind == "ask_db_id" else ctrl.is_busy,
                        on_click=on_fab_click,
                    )
            else:
                with ui.row().classes("mt-4 justify-end"):
                    ui.button("关闭说明", on_click=dialog.close).props("flat")
        _current_dialog = dialog
        dialog.open()


def _render_layout_dialog_body(ctrl) -> None:
    global _layout_area_inputs, _layout_area_values
    global _layout_move_order, _layout_move_checks, _layout_move_order_label
    global _layout_offset
    ui.label(
        "请配置 [[input_section]]：多个 input_area（并集）、move_to（1～2 个方向）、offset。"
    ).classes("text-sm mb-2")
    from llm_gemma4.toml_config.toml_patcher import (
        _areas_as_list,
        _layout_area_is_set,
        _moves_as_list,
        layout_hints_for_template,
    )
    hints = {"input_area": "", "move_to": "down", "offset": 1}
    if ctrl.orchestrator is not None:
        st = ctrl.orchestrator.state
        try:
            hints = layout_hints_for_template(st)
        except Exception:
            pass
        if _layout_area_is_set(st.input_area):
            hints["input_area"] = st.input_area
        if isinstance(st.move_to, list) or (
            isinstance(st.move_to, str) and st.move_to.strip()
        ):
            hints["move_to"] = st.move_to
        if isinstance(st.offset, int) and st.offset >= 1:
            hints["offset"] = st.offset
    default_areas = _areas_as_list(hints.get("input_area"))
    if not default_areas:
        default_areas = [""]
    default_moves = _moves_as_list(hints.get("move_to"))
    default_offset = int(hints.get("offset") or 1)
    session = SessionRegistry.for_current()
    report = session.verify_report or {}
    if report and not report.get("ok"):
        ui.label("上次布局校验未通过，请修正后重试：").classes("text-sm text-negative font-bold mb-1")
        if report.get("out_of_area_labels"):
            ui.label(
                f"越界标签: {', '.join(report['out_of_area_labels'])}"
            ).classes("text-sm text-negative mb-1")
    _layout_area_values = list(default_areas)

    @ui.refreshable
    def _render_area_rows() -> None:
        global _layout_area_inputs
        _layout_area_inputs = []
        for idx, val in enumerate(_layout_area_values):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                inp = (
                    ui.input(
                        label=f"区域 {idx + 1}",
                        placeholder="例 A2:G2 或单格 A2",
                        value=val,
                    )
                    .classes("flex-grow")
                    .props("clearable dense")
                )
                _layout_area_inputs.append(inp)

                def _remove_area(i: int = idx) -> None:
                    _sync_area_values_from_inputs()
                    if len(_layout_area_values) <= 1:
                        _layout_area_values[0] = ""
                    else:
                        _layout_area_values.pop(i)
                    _render_area_rows.refresh()

                AppBtn("删除", variant="danger", on_click=_remove_area)

        def _add_area() -> None:
            _sync_area_values_from_inputs()
            _layout_area_values.append("")
            _render_area_rows.refresh()

        with ui.row().classes("w-full mt-1"):
            AppBtn("添加区域", variant="excel", on_click=_add_area)

    _render_area_rows()
    ui.label("move_to — 勾选顺序：第 1 个=主轴，第 2 个=次轴").classes("text-sm font-bold mt-3")
    _layout_move_order = [d for d in default_moves if d in _VALID_MOVE_TO][:2]
    if not _layout_move_order:
        _layout_move_order = ["down"]
    _layout_move_checks = {}
    with ui.row().classes("w-full items-center gap-3 flex-wrap"):
        for direction in _VALID_MOVE_TO:

            def _on_move_toggle(e, d: str = direction) -> None:
                checked = bool(getattr(e, "value", False))
                if checked:
                    if d not in _layout_move_order:
                        if len(_layout_move_order) >= 2:
                            box = _layout_move_checks.get(d)
                            if box is not None:
                                box.value = False
                            ui.notify("最多选择 2 个方向（主轴+次轴）", type="warning")
                            return
                        _layout_move_order.append(d)
                elif d in _layout_move_order:
                    _layout_move_order.remove(d)
                _refresh_move_order_label()

            box = ui.checkbox(
                direction,
                value=direction in _layout_move_order,
                on_change=_on_move_toggle,
            )
            _layout_move_checks[direction] = box
    _layout_move_order_label = ui.label("").classes("text-sm mt-1")
    _refresh_move_order_label()
    _layout_offset = ui.number(
        label="offset — 每一轴平移步长（≥1）",
        value=default_offset if default_offset >= 1 else 1,
        min=1,
        precision=0,
    ).classes("w-full mt-2")


def _render_db_id_dialog_body(ctrl) -> None:
    global _step7_select, _step7_db_id
    ui.label(
        "请选择主键 db_id（Input_label）。None 表示不指定主键。"
    ).classes("text-sm mb-2")
    labels = ctrl.template_labels()
    options = [_DB_ID_NONE] + list(labels)
    default = _DB_ID_NONE
    _step7_db_id = ""
    _step7_select = ui.select(
        options,
        label="db_id（None = 不指定）",
        value=default,
    ).classes("w-full")

    def _on_db_change(_e):
        global _step7_db_id
        raw = str(_step7_select.value or _DB_ID_NONE).strip() or _DB_ID_NONE
        _step7_db_id = "" if raw == _DB_ID_NONE else raw

    _step7_select.on("update:model-value", _on_db_change)


def _schedule_interrupt_dialog(kind: str, client: Client | None = None) -> None:
    resolved = _resolve_client(client)
    def _open() -> None:
        _show_interrupt_dialog(kind, client=resolved)
    _schedule_deferred(0.15, _open)


async def on_fab_click() -> None:
    """
    函数名: on_fab_click
    作用: 工作流 FAB 主入口：收集中断恢复 payload 或推进 compute，并 auto-chain
    输入: 无
    输出: 无
    """
    ctrl = get_toml_wizard()
    if not is_workflow_active() or ctrl.is_busy or ctrl.is_stopping or not ctrl.started:
        return
    client = _resolve_client(None)
    kind_before = _pending_interrupt_kind(ctrl)
    try:
        if kind_before == "ask_db_id":
            global _step7_saving
            if _step7_saving:
                return
            _step7_saving = True
            _close_dialog()
        payload = await _collect_resume_payload(ctrl, client)
        if payload is None:
            return
        outbound = await ctrl.dispatch(WorkflowEvent(type=EVENT_RESUME, payload=payload))
        if kind_before == "ask_layout":
            ok = await _after_layout_resume(ctrl, client)
            if not ok:
                return
        if kind_before == "ask_db_id":
            session = SessionRegistry.for_current()
            from nicegui_ui.pages.tab_toml import trigger_toml_save
            trigger_toml_save(session)
            _refresh_toml_tab()
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("TOML 已保存并应用", type="positive")
            if outbound is not None and outbound.type == EVENT_FINISHED:
                await stop_wizard("配置向导已完成")
                return
            if ctrl.orchestrator is not None and ctrl.orchestrator.state.is_finished:
                await stop_wizard("配置向导已完成")
                return
        if not is_workflow_active() or ctrl.is_stopping:
            return
        await _handle_outbound(ctrl, client, outbound)
    except Exception:
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify("工作流执行失败，请查看日志", type="negative")
    finally:
        if kind_before == "ask_db_id":
            _step7_saving = False
        _schedule_chrome_refresh(client)
        _schedule_sidebar_refresh(client)


async def stop_wizard(reason: str | None = None) -> None:
    """
    函数名: stop_wizard
    作用: 结束工作流并释放 Gemma
    输入:
        reason (str | None): 可选提示文案
    输出: 无
    """
    client = _resolve_client(None)
    ctrl = get_toml_wizard()
    if ctrl.orchestrator is not None and not ctrl.is_busy:
        await ctrl.dispatch(WorkflowEvent(type=EVENT_STOP))
    _close_dialog()
    _set_workflow_active(False)
    from nicegui_ui.pages.tab_input import clear_ghost_cache
    clear_ghost_cache(SessionRegistry.for_current())
    await get_toml_wizard().stop_async()
    _schedule_chrome_refresh(client)
    _schedule_sidebar_refresh(client)
    if reason:
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify(reason, type="info")
        else:
            ui.notify(reason, type="info")


async def start_wizard() -> None:
    """
    函数名: start_wizard
    作用: 启动 TOML 配置工作流（Gemma + 首次 Graph start）
    输入: 无
    输出: 无
    """
    session = SessionRegistry.for_current()
    if not session.template_id or not session.template_path:
        ui.notify("请先选择模板", type="warning")
        return
    from nicegui_ui.pages.tab_input import clear_field_drafts, clear_ghost_cache
    clear_ghost_cache(session)
    ctrl = get_toml_wizard()
    draft_labels = ctrl.template_labels() if ctrl.started else None
    if not draft_labels and session.ui_provider:
        try:
            draft_labels = list(session.ui_provider.get_labels())
        except Exception:
            draft_labels = None
    clear_field_drafts(session, draft_labels, refresh_ui=True)
    if ctrl.is_busy:
        return
    client = ui.context.client
    if is_workflow_active() and ctrl.started:
        clear_field_drafts(session, ctrl.template_labels(), refresh_ui=True)
        ctrl.clear_histories()
        if ctrl.orchestrator is not None:
            ctrl.orchestrator.reset_state()
        with client:
            ui.notify("工作流已重置，对话已清空", type="info")
        outbound = await ctrl.dispatch(
            WorkflowEvent(type=EVENT_START, payload=_initial_tick_payload(ctrl))
        )
        await _handle_outbound(ctrl, client, outbound)
        _schedule_chrome_refresh(client)
        _schedule_sidebar_refresh(client)
        return
    progress = None
    if not is_gemma_loaded():
        with client:
            progress = ui.notification("正在加载 Gemma4…", spinner=True, type="ongoing")
    _set_workflow_active(True)
    try:
        ok = await ctrl.start(client=client)
    finally:
        if progress is not None:
            from nicegui_ui.components.model_runtime import _dismiss_notification
            _dismiss_notification(progress)
    if not ok:
        _set_workflow_active(False)
        with client:
            ui.notify("Gemma 模型加载失败，请检查 llm_gemma4 环境", type="negative")
        return
    _schedule_chrome_refresh(client)
    _schedule_sidebar_refresh(client)
    with client:
        ui.notify("配置向导已启动", type="positive")
    outbound = await ctrl.dispatch(
        WorkflowEvent(type=EVENT_START, payload=_initial_tick_payload(ctrl))
    )
    await _handle_outbound(ctrl, client, outbound)
    from nicegui_ui.components.model_runtime import sync_model_runtime_ui
    sync_model_runtime_ui(client)


def render_wizard_sidebar_chat() -> None:
    """
    函数名: render_wizard_sidebar_chat
    作用: 工作流进行中铺满左侧 sidebar，覆盖模板列表并展示 Gemma 对话
    输入: 无
    输出: 无
    """
    if not is_workflow_active():
        _sync_workflow_shell_class(False)
        return
    _sync_workflow_shell_class(True)
    ctrl = get_toml_wizard()
    with ui.element("div").classes("wizard-sidebar-chat"):
        ui.label("Gemma 对话").classes("wizard-sidebar-chat-title")
        chat_area = (
            ui.textarea(value=ctrl.sidebar_feed_text)
            .classes("wizard-sidebar-chat-log w-full")
            .props("readonly outlined dense")
        )
        ctrl.bind_chat(chat_area)


def render_wizard_fab() -> None:
    """
    函数名: render_wizard_fab
    作用: 渲染 Shell 左下角工作流 FAB（仅 workflow_active 时）
    输入: 无
    输出: 无
    """
    if not is_workflow_active():
        _sync_workflow_shell_class(False)
        return
    _sync_workflow_shell_class(True)
    ctrl = get_toml_wizard()
    with ui.element("div").classes("wizard-fab-anchor"):
        async def _exit():
            await stop_wizard("已退出配置向导")
        AppBtn("退出向导", variant="default", on_click=_exit)
        kind = _pending_interrupt_kind(ctrl)
        if kind in _DIALOG_CONFIRM_INTERRUPTS:
            def _reopen():
                _schedule_interrupt_dialog(kind, _resolve_client(None))
            AppBtn("打开说明", variant="default", on_click=_reopen)
        else:
            label = _fab_label(ctrl)
            next_btn = AppBtn(
                label,
                variant="danger",
                disabled=ctrl.is_busy,
                on_click=on_fab_click,
            )
            if ctrl.is_busy:
                next_btn.props("loading")
