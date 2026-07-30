"""TOML 智能向导进程内 UI：Tab 导航、步骤对话框、Shell FAB。"""

from __future__ import annotations

import re
from typing import Any, Callable

from nicegui import app, ui
from nicegui.client import Client

from nicegui_ui.components.buttons import AppBtn
from nicegui_ui.components.general import SessionRegistry
from nicegui_ui.components.model_runtime import is_gemma_loaded
from nicegui_ui.components.toml_wizard import get_toml_wizard


_shell_switch_tab: Callable[[str], None] | None = None
_refresh_chrome: Callable[[], None] | None = None
_refresh_sidebar: Callable[[], None] | None = None
_current_dialog: ui.dialog | None = None
_layout_input_area: Any = None
_layout_move_to: Any = None
_layout_offset: Any = None
_step7_db_id: str = ""
_step7_select: Any = None
_step7_saving: bool = False
# 步骤 7 可选「不指定主键」
_DB_ID_NONE = "None"
# 须在对话框内确认「下一步」的步骤（布局 / regex / 主键）
_DIALOG_NEXT_STEPS = frozenset({2, 6, 7})
# Excel 区域：单个 A1:B2；用于识别「A2:G2A2:F2」这类追加粘贴
_EXCEL_AREA_RE = re.compile(r"^[A-Za-z]+\d+:[A-Za-z]+\d+$")
_EXCEL_AREA_FIND_RE = re.compile(r"[A-Za-z]+\d+:[A-Za-z]+\d+")


# 步骤对应的默认 Tab
# 1 Google → 2 input_section 布局 → 3 输入试填/Ghost → 4 匹配 → 5 Sheet 列 → 6 regex → 7 保存(db_id)
_STEP_TABS: dict[int, str] = {
    1: "Google 连接",
    2: "输入配置",
    3: "输入",
    4: "输入配置",
    5: "Google 连接",
    6: "输入配置",
    7: "输入配置",
    8: "输入配置",
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
        refresh_chrome: 刷新右下角向导 FAB
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



def _schedule_chrome_refresh(client: Client | None = None) -> None:
    resolved = _resolve_client(client)
    if resolved is None:
        _refresh_chrome_safe()
        return
    with resolved:
        ui.timer(0.05, _refresh_chrome_safe, once=True)



def _schedule_sidebar_refresh(client: Client | None = None) -> None:
    if _refresh_sidebar is None:
        return
    resolved = _resolve_client(client)
    if resolved is None:
        _refresh_sidebar()
        return
    with resolved:
        ui.timer(0.05, _refresh_sidebar, once=True)



def _resolve_ghost_sample(session) -> str:
    """
    函数名: _resolve_ghost_sample
    作用: 步骤 2 校验前合并 session 缓存与 Ghost 控件当前值
    输入:
        session: SessionRegistry 当前会话
    输出:
        str: 非空样本文本
    """
    stored = (session.last_ghost_paste or "").strip()
    if stored:
        return stored
    from nicegui_ui.pages.tab_input import read_ghost_sample
    live = read_ghost_sample()
    if live:
        session.last_ghost_paste = live
    return live



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



def _set_wizard_active(active: bool) -> None:
    if hasattr(app.storage, "user"):
        app.storage.user["wizard_active"] = active



def is_wizard_active() -> bool:
    """
    函数名: is_wizard_active
    作用: 当前会话是否处于 TOML 向导模式
    输入: 无
    输出:
        bool: 向导进行中为 True
    """
    if not hasattr(app.storage, "user"):
        return False
    return bool(app.storage.user.get("wizard_active"))



def _orchestrator_has_google(ctrl) -> bool:
    if ctrl.orchestrator is None:
        return False
    sources = ctrl.orchestrator.state.data_sources
    return any(ds.get("type") == "google_sheet" or ds.get("source1") for ds in sources)



def _show_step_dialog(step: int, *, client: Client | None = None) -> None:
    """
    函数名: _show_step_dialog
    作用: 按步骤弹出说明对话框（半模态，不阻挡目标 Tab 操作）
    输入:
        step (int): UI 步骤 1–8
        client (Client | None): 提前捕获的 client，避免在已删除 slot 内建 dialog
    输出: 无
    """
    global _current_dialog
    global _layout_input_area, _layout_move_to, _layout_offset
    global _step7_select, _step7_db_id
    _close_dialog()
    ctrl = get_toml_wizard()
    resolved = _resolve_client(client)
    ctx = resolved if resolved is not None else ui.context.client
    with ctx:
        with ui.dialog() as dialog, ui.card().classes("wizard-step-dialog w-11/12 max-w-4xl"):
            ui.label(f"配置向导 · 步骤 {step}/8").classes("text-lg font-bold mb-2")
            if step == 1:
                ui.label(
                    "请在当前「Google 连接」页配置 OAuth 与 Sheet（可选）。"
                    "若不需要 Google 数据源可直接点右下角「下一步配置」。"
                ).classes("text-sm")
            elif step == 2:
                ui.label(
                    "请打开当前 Excel 模板，准备回答 [[input_section]] 三项（见 toml_config_design）："
                    "1) 每次变化的填写值区域 input_area；"
                    "2) 下一组平移方向 move_to；"
                    "3) 平移步长 offset。"
                    "确认后点本对话框内「下一步配置」：写入 TOML、加载新规则，并进入「输入」页填写测试数据。"
                ).classes("text-sm mb-2")
                # 提示来自本模板 xlsx 推导；用户可改任意区域，落盘时按区域重建 fields
                from llm_gemma4.wizard.toml_patcher import layout_hints_for_template
                hints = {"input_area": "", "move_to": "down", "offset": 1}
                if ctrl.orchestrator is not None:
                    st = ctrl.orchestrator.state
                    # 步骤 1 已写入 template_id/path 时可取 xlsx 推导提示
                    try:
                        hints = layout_hints_for_template(st)
                    except Exception:
                        pass
                    if (st.input_area or "").strip():
                        hints["input_area"] = st.input_area.strip()
                    if (st.move_to or "").strip() in ("up", "down", "left", "right"):
                        hints["move_to"] = st.move_to.strip()
                    if isinstance(st.offset, int) and st.offset >= 1:
                        hints["offset"] = st.offset
                default_area = str(hints.get("input_area") or "")
                default_move = str(hints.get("move_to") or "down")
                default_offset = int(hints.get("offset") or 1)
                # 若上次布局校验失败，在对话框内展示原因（勿直接跳到步骤 3）
                session = SessionRegistry.for_current()
                report = session.verify_report or {}
                if report and not report.get("ok"):
                    ui.label(
                        "上次布局校验未通过，工作区已锁定；请确认区域后重试"
                        "（系统会按区域重建 fields）："
                    ).classes("text-sm text-negative font-bold mb-1")
                    if report.get("out_of_area_labels"):
                        ui.label(
                            f"越界标签: {', '.join(report['out_of_area_labels'])}"
                        ).classes("text-sm text-negative mb-1")
                    if report.get("missing_labels"):
                        ui.label(
                            f"缺失标签: {', '.join(report['missing_labels'])}"
                        ).classes("text-sm text-negative mb-1")
                    if report.get("errors"):
                        for err in report["errors"]:
                            ui.label(f"- {err}").classes("text-sm text-negative")
                _layout_input_area = ui.input(
                    label="1. 每次变化的填写值区域 input_area（对照本模板 Excel）",
                    placeholder=default_area or "由本模板推导，请对照 Excel 确认",
                    value=default_area,
                ).classes("w-full").props("clearable")
                # 聚焦全选，避免在旧值后追加（如 A2:G2A2:F2）
                def _select_area_text(_e=None) -> None:
                    if _layout_input_area is not None:
                        try:
                            _layout_input_area.run_method("select")
                        except Exception:
                            pass
                _layout_input_area.on("focus", _select_area_text)
                ui.label("2. 下一组填写值平移方向 move_to").classes("text-sm mt-2")
                _layout_move_to = ui.radio(
                    ["up", "down", "left", "right"],
                    value=default_move if default_move in ("up", "down", "left", "right") else "down",
                ).props("inline")
                _layout_offset = ui.number(
                    label="3. 平移步长 offset（行/列数，≥1）",
                    value=default_offset if default_offset >= 1 else 1,
                    min=1,
                    precision=0,
                ).classes("w-full")
            elif step == 3:
                ui.label(
                    "TOML 布局已应用。请在「输入」页填写/粘贴测试数据（Ghost 样本或字段草稿），"
                    "完成后点右下角「下一步配置」。"
                ).classes("text-sm")
            elif step == 4:
                ui.label(
                    "将依次执行：4.1 预处理建 index 字典 → 4.2 规划字段任务 → 4.3 逐字段匹配。"
                    "点「下一步配置」自动串行三阶段并刷新日志。"
                ).classes("text-sm mb-2")
                log_box = ui.log().classes("w-full h-56 wizard-step-log")
                ctrl.bind_log(log_box)
            elif step == 5:
                ui.label("将 Google Sheet 列与模板字段配对。点「下一步配置」开始匹配。").classes("text-sm mb-2")
                log_box = ui.log().classes("w-full h-56 wizard-step-log")
                ctrl.bind_log(log_box)
            elif step == 6:
                ui.label(
                    "为模糊匹配字段推理 Python 正则。"
                    "确认后点本对话框内「下一步配置」开始推理。"
                ).classes("text-sm mb-2")
                log_box = ui.log().classes("w-full h-56 wizard-step-log")
                ctrl.bind_log(log_box)
            elif step == 7:
                ui.label(
                    "请选择主键 db_id（Input_label）。默认 None：不指定主键（所有字段 id=false）。"
                    "确认后点本对话框内「保存配置文件」写入 TOML 并结束向导（不再试跑）。"
                ).classes("text-sm mb-2")
                labels = ctrl.template_labels()
                options = [_DB_ID_NONE] + list(labels)
                # 默认 None，用户可主动拒绝指定主键；无需先点开下拉也可保存
                prev = ""
                if ctrl.orchestrator is not None:
                    prev = str(ctrl.orchestrator.state.db_id or "").strip()
                default = prev if prev in labels else _DB_ID_NONE
                _step7_db_id = "" if default == _DB_ID_NONE else default
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
            elif step == 8:
                # 已取消试跑；若误入本步，提示返回步骤 7 保存
                ui.label(
                    "试跑已取消。请关闭后打开步骤 7，点「保存配置文件」写入 TOML。"
                ).classes("text-sm mb-2")
            # 步骤 2 / 6：对话框内「下一步配置」；步骤 7：保存并退出
            if step in _DIALOG_NEXT_STEPS:
                with ui.row().classes("mt-4 w-full items-center justify-between gap-2"):
                    ui.button("关闭说明", on_click=dialog.close).props("flat")
                    # 步骤 7 默认 None 即可保存，按钮不因 is_busy 误禁用
                    cta = "保存配置文件" if step == 7 else "下一步配置"
                    AppBtn(
                        cta,
                        variant="danger",
                        disabled=False if step == 7 else ctrl.is_busy,
                        on_click=on_next_click,
                    )
            else:
                with ui.row().classes("mt-4 justify-end"):
                    ui.button("关闭说明", on_click=dialog.close).props("flat")
        _current_dialog = dialog
        dialog.open()



def _schedule_step_dialog(step: int, client: Client | None = None) -> None:
    resolved = _resolve_client(client)
    if resolved is None:
        _show_step_dialog(step)
        return
    with resolved:
        ui.timer(0.15, lambda s=step, c=resolved: _show_step_dialog(s, client=c), once=True)



def enter_step(step: int, *, client: Client | None = None) -> None:
    """
    函数名: enter_step
    作用: 进入指定 UI 步骤：切 Tab 并延迟弹出说明对话框
    输入:
        step (int): 步骤 1–8
    输出: 无
    """
    ctrl = get_toml_wizard()
    ctrl.ui_step = step
    resolved = _resolve_client(client)
    # 步骤 5（Sheet 列匹配）无 Google 时跳到步骤 6（regex）
    if step == 5 and not _orchestrator_has_google(ctrl):
        if ctrl.orchestrator is not None:
            ctrl.orchestrator.state.current_step = 6
        enter_step(6, client=resolved)
        return
    tab = _STEP_TABS.get(step, "输入配置")
    _switch_tab(tab)
    _schedule_chrome_refresh(resolved)
    _schedule_step_dialog(step, resolved)



def _normalize_input_area(raw: str) -> tuple[str, str]:
    """
    函数名: _normalize_input_area
    作用: 规范化并校验 Excel 区域字符串；拒绝追加粘贴产生的双区域
    输入:
        raw (str): 用户输入的 input_area
    输出:
        tuple[str, str]: (规范化区域, 错误文案)；成功时错误文案为空串
    """
    s = (raw or "").strip().replace(" ", "")
    if not s:
        return "", "请填写本模板的 input_area（对照 Excel 填写值区域）"
    # 识别 A2:G2A2:F2 这类未全选就改写导致的拼接
    found = _EXCEL_AREA_FIND_RE.findall(s)
    if len(found) > 1 and "".join(found) == s:
        return "", f"input_area 疑似重复粘贴（{raw.strip()}），请清空后只填一个区域"
    if not _EXCEL_AREA_RE.match(s):
        return "", f"input_area 格式无效: {raw.strip()}（例 A2:G2）"
    return s.upper(), ""


def _read_layout_payload() -> dict[str, Any]:
    """
    函数名: _read_layout_payload
    作用: 从步骤 2（Google 之后、输入试填之前）对话框读取 input_section 表单值
    输入: 无
    输出:
        dict[str, Any]: 含 input_area / move_to / offset / area_error
    """
    area = ""
    area_error = ""
    if _layout_input_area is not None:
        area, area_error = _normalize_input_area(str(_layout_input_area.value or ""))
    move_to = "down"
    if _layout_move_to is not None:
        move_to = str(_layout_move_to.value or "down").strip().lower() or "down"
    offset = 1
    if _layout_offset is not None:
        try:
            offset = int(_layout_offset.value)
        except (TypeError, ValueError):
            offset = 1
    return {
        "input_area": area,
        "move_to": move_to,
        "offset": offset,
        "area_error": area_error,
    }



async def stop_wizard(reason: str | None = None) -> None:
    """
    函数名: stop_wizard
    作用: 结束向导模式并释放 Gemma
    输入:
        reason (str | None): 可选提示文案
    输出: 无
    """
    client = _resolve_client(None)
    _close_dialog()
    get_toml_wizard().stop()
    _set_wizard_active(False)
    _schedule_chrome_refresh(client)
    _schedule_sidebar_refresh(client)
    if reason:
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify(reason, type="info")
        else:
            ui.notify(reason, type="info")



async def on_next_click() -> None:
    """
    函数名: on_next_click
    作用: 右下角「下一步配置」FAB 回调，校验并执行当前步骤
    输入: 无
    输出: 无
    """
    ctrl = get_toml_wizard()
    if not is_wizard_active() or ctrl.is_busy or not ctrl.started:
        return
    client = _resolve_client(None)
    step = ctrl.ui_step
    session = SessionRegistry.for_current()
    def _refresh_toml_tab() -> None:
        # 渐进写盘后刷新 TOML 全文编辑区（从磁盘重读）；不触发 engines 重建
        try:
            from nicegui_ui.pages.tab_toml import render_toml_tab
            render_toml_tab.refresh()
        except Exception:
            pass
    try:
        if step == 1:
            payload = {**ctrl.session_payload_base(), "data_sources": ctrl.build_data_sources()}
            await ctrl.run_step(1, payload)
            enter_step(2, client=client)
        elif step == 2:
            # Google 之后、输入试填之前：回答 input_section，写 TOML，再进「输入」页
            layout = _read_layout_payload()
            area_error = str(layout.get("area_error") or "")
            if area_error:
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify(area_error, type="warning")
                return
            if not layout["input_area"]:
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify("请填写本模板的 input_area（对照 Excel 填写值区域）", type="warning")
                return
            if layout["move_to"] not in ("up", "down", "left", "right"):
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify("move_to 须为 up/down/left/right", type="warning")
                return
            if int(layout["offset"]) < 1:
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify("offset 须为 ≥1 的整数", type="warning")
                return
            await ctrl.run_step(
                2,
                {
                    **ctrl.session_payload_base(),
                    "input_area": layout["input_area"],
                    "move_to": layout["move_to"],
                    "offset": layout["offset"],
                },
            )
            from nicegui_ui.pages.tab_toml import trigger_toml_save
            trigger_toml_save(session)
            _refresh_toml_tab()
            report = session.verify_report or {}
            # 校验失败则停在步骤 2，避免「输入」页因工作区锁定无法继续
            if not report.get("ok"):
                ctrl.ui_step = 2
                if ctrl.orchestrator is not None:
                    ctrl.orchestrator.state.current_step = 2
                _switch_tab("输入配置")
                _schedule_chrome_refresh(client)
                _schedule_step_dialog(2, client)
                parts: list[str] = []
                if report.get("out_of_area_labels"):
                    parts.append("越界标签: " + ", ".join(report["out_of_area_labels"]))
                if report.get("missing_labels"):
                    parts.append("缺失标签: " + ", ".join(report["missing_labels"]))
                detail = "；".join(parts) if parts else "请检查 input_area 是否覆盖全部填写值列"
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify(f"布局校验失败，未进入下一步。{detail}", type="warning")
                return
            # 进入步骤 3：在「输入」页填测试数据 / Ghost
            ctrl.ui_step = 3
            if ctrl.orchestrator is not None:
                ctrl.orchestrator.state.current_step = 3
            _switch_tab("输入")
            _schedule_chrome_refresh(client)
            _schedule_step_dialog(3, client)
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("TOML 已保存并应用，请在「输入」页填写测试数据后继续", type="positive")
        elif step == 3:
            ghost = _resolve_ghost_sample(session)
            has_google = ctrl.has_google_sheet_source() or _orchestrator_has_google(ctrl)
            if not ghost and not has_google:
                await stop_wizard("无样本且无 Google 数据源，向导已结束")
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify("需要 Ghost 样本或 Google 数据源才能继续", type="warning")
                return
            labels = ctrl.template_labels()
            # 从字段控件读当前值（不依赖 on_change/失焦是否已写入 session.draft）
            from nicegui_ui.pages.tab_input import read_field_drafts
            user_draft = read_field_drafts(labels)
            session.draft.update(user_draft)
            payload = {
                **ctrl.session_payload_base(),
                "ghost_text_sample": ghost,
                "template_labels": labels,
                "user_draft": user_draft,
            }
            await ctrl.run_step(3, payload)
            enter_step(4, client=client)
        elif step == 4:
            # sidebar 对话通过 bind_chat 原地更新；此处不重建 sidebar，避免打断自动滚动
            await ctrl.run_step(4, {"phase": "preprocess"})
            _schedule_chrome_refresh(client)
            await ctrl.run_step(4, {"phase": "plan"})
            _schedule_chrome_refresh(client)
            await ctrl.run_step(4, {"phase": "match"})
            _refresh_toml_tab()
            enter_step(5, client=client)
        elif step == 5:
            await ctrl.run_step(5, ctrl.google_payload())
            _refresh_toml_tab()
            enter_step(6, client=client)
        elif step == 6:
            await ctrl.run_step(6, {})
            _refresh_toml_tab()
            enter_step(7, client=client)
        elif step == 7:
            # 一次点击即关闭对话框并保存退出（防双击 / select 失焦吞第一次点击）
            global _step7_saving
            if _step7_saving or ctrl.is_busy:
                return
            _step7_saving = True
            _close_dialog()
            try:
                # 默认 None 即可保存；未触碰下拉时 value 可能仍为 None，按不指定主键处理
                db_id = _step7_db_id
                if _step7_select is not None:
                    raw = str(_step7_select.value or _DB_ID_NONE).strip() or _DB_ID_NONE
                    db_id = "" if raw == _DB_ID_NONE else raw
                elif not db_id:
                    db_id = ""
                await ctrl.run_step(7, {"db_id": db_id, **ctrl.session_payload_base()})
                from nicegui_ui.pages.tab_toml import trigger_toml_save
                trigger_toml_save(session)
                _refresh_toml_tab()
                resolved = _resolve_client(client)
                if resolved is not None:
                    with resolved:
                        ui.notify("TOML 已保存并应用", type="positive")
                await stop_wizard("配置向导已完成")
            finally:
                _step7_saving = False
        elif step == 8:
            # 试跑已取消；若仍进入本步则直接结束
            resolved = _resolve_client(client)
            if resolved is not None:
                with resolved:
                    ui.notify("试跑已取消，请使用步骤 7「保存配置文件」", type="info")
            await stop_wizard("配置向导已结束（未试跑）")
    except Exception:
        resolved = _resolve_client(client)
        if resolved is not None:
            with resolved:
                ui.notify("向导步骤执行失败，请查看日志", type="negative")
    finally:
        _schedule_chrome_refresh(client)
        _schedule_sidebar_refresh(client)



async def start_wizard() -> None:
    """
    函数名: start_wizard
    作用: 从「输入配置」启动进程内向导：加载 Gemma 并进入步骤 1
    输入: 无
    输出: 无
    """
    session = SessionRegistry.for_current()
    if not session.template_id or not session.template_path:
        ui.notify("请先选择模板", type="warning")
        return
    ctrl = get_toml_wizard()
    if ctrl.is_busy:
        return
    client = ui.context.client
    if is_wizard_active() and ctrl.started:
        # 再次点启动：清空对话后从步骤 1 重开（不重新加载模型）
        from llm_gemma4.wizard.state import WizardState
        ctrl.clear_histories()
        ctrl.ui_step = 1
        if ctrl.orchestrator is not None:
            ctrl.orchestrator.state = WizardState()
        with client:
            ui.timer(0.05, lambda c=client: enter_step(1, client=c), once=True)
            ui.notify("向导已重置，对话已清空", type="info")
        _schedule_chrome_refresh(client)
        _schedule_sidebar_refresh(client)
        return
    progress = None
    if not is_gemma_loaded():
        with client:
            progress = ui.notification("正在加载 Gemma4…", spinner=True, type="ongoing")
    _refresh_chrome_safe()
    try:
        ok = await ctrl.start(client=client)
    finally:
        if progress is not None:
            with client:
                from nicegui_ui.components.model_runtime import _dismiss_notification
                _dismiss_notification(progress)
    if not ok:
        with client:
            ui.notify("Gemma 模型加载失败，请检查 llm_gemma4 环境", type="negative")
        return
    _set_wizard_active(True)
    ctrl.ui_step = 1
    _schedule_chrome_refresh(client)
    _schedule_sidebar_refresh(client)
    with client:
        ui.timer(0.05, lambda c=client: enter_step(1, client=c), once=True)
        ui.notify("配置向导已启动", type="positive")
    from nicegui_ui.components.model_runtime import sync_model_runtime_ui
    sync_model_runtime_ui(client)



def render_wizard_sidebar_chat() -> None:
    """
    函数名: render_wizard_sidebar_chat
    作用: 向导进行中在 sidebar 展示程序与 Gemma 的对话记录
    输入: 无
    输出: 无
    """
    if not is_wizard_active():
        return
    ctrl = get_toml_wizard()
    with ui.element("div").classes("wizard-sidebar-chat"):
        ui.label("Gemma 对话").classes("wizard-sidebar-chat-title")
        chat_area = (
            ui.textarea(value=ctrl.chat_text)
            .classes("wizard-sidebar-chat-log w-full")
            .props("readonly outlined dense")
            .style("min-width:0;max-width:100%;")
        )
        ctrl.bind_chat(chat_area)



def render_wizard_fab() -> None:
    """
    函数名: render_wizard_fab
    作用: 渲染 Shell 右下角向导 FAB（仅 wizard_active 时）
    输入: 无
    输出: 无
    """
    if not is_wizard_active():
        return
    ctrl = get_toml_wizard()
    with ui.element("div").classes("wizard-fab-anchor"):
        async def _exit():
            await stop_wizard("已退出配置向导")
        AppBtn("退出向导", variant="default", on_click=_exit)
        # 步骤 2 / 6 / 7：下一步在对话框内；FAB 仅提供重新打开说明
        if ctrl.ui_step in _DIALOG_NEXT_STEPS:
            def _reopen():
                _schedule_step_dialog(ctrl.ui_step, _resolve_client(None))
            AppBtn("打开步骤说明", variant="default", on_click=_reopen)
        else:
            next_btn = AppBtn(
                "下一步配置",
                variant="danger",
                disabled=ctrl.is_busy,
                on_click=on_next_click,
            )
            if ctrl.is_busy:
                next_btn.props("loading")
