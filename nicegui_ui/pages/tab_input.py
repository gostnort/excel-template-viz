import base64
from pathlib import Path
from datetime import datetime
from typing import Any

from nicegui import ui

from nicegui_ui.components.buttons import AppBtn
from nicegui_ui.components.for_main import IdLookup
from nicegui_ui.components.general import SessionRegistry, list_export_files
from nicegui_ui.components.ocr_menu import (
    GHOST_OCR_LABEL,
    add_image_pick_menu_items,
)
from app.core_toml import (
    add_button_label,
    is_scene2_section,
    move_to_directions,
    next_instance_idx_along,
)


_ghost_input: ui.textarea | None = None
_field_inputs: dict[str, Any] = {}


def read_ghost_sample() -> str:
    """
    函数名: read_ghost_sample
    作用: 读取「输入」页 Ghost 文本框当前值（blur 未触发时的回退）
    输入: 无
    输出:
        str: 去首尾空白后的文本
    """
    if _ghost_input is None:
        return ""
    return str(_ghost_input.value or "").strip()


def read_field_drafts(labels: list[str] | None = None) -> dict[str, str]:
    """
    函数名: read_field_drafts
    作用: 合并 session.draft 与字段控件当前值（向导步骤 3 不依赖 on_change/失焦）
    输入:
        labels (list[str] | None): 只读这些标签；None 时读全部已登记控件
    输出:
        dict[str, str]: Input_label → 文本（含空串）
    """
    session = SessionRegistry.for_current()
    merged: dict[str, str] = {
        str(key): str(value) if value is not None else ""
        for key, value in dict(session.draft or {}).items()
    }
    wanted = set(labels) if labels is not None else None
    for label, inp in list(_field_inputs.items()):
        if wanted is not None and label not in wanted:
            continue
        try:
            val = inp.value
        except Exception:
            continue
        merged[label] = "" if val is None else str(val)
    if wanted is not None:
        for label in wanted:
            merged.setdefault(label, "")
    return merged


def _sync_ghost_paste(session, raw: str) -> None:
    text = str(raw or "").strip()
    if text:
        session.last_ghost_paste = text


def ensure_exports_dir(template_id: str) -> Path:
    export_dir = Path("exports") / template_id
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _resolve_print_areas(session, export_path: Path | None) -> list[dict[str, Any]]:
    if not session.writer or not export_path or not export_path.is_file():
        return []
    return session.writer.get_print_areas(export_path)


def _print_area_labels(areas: list[dict[str, Any]]) -> list[str]:
    if not areas:
        return ["（无打印区）"]
    return [str(item.get("label") or item.get("area") or "打印区") for item in areas]


def _find_print_area_entry(
    areas: list[dict[str, Any]], selected_label: str
) -> dict[str, Any] | None:
    for item in areas:
        if item.get("label") == selected_label:
            return item
    return None


def _open_print_preview(png_bytes: bytes, download_name: str) -> None:
    """内存 PNG → 预览对话框；浏览器 window.print 或 PNG 下载（不落盘）。"""
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
    with ui.dialog() as dialog, ui.card().classes("excel-print-sheet w-full max-w-5xl"):
        ui.label("打印预览").classes("text-h6 no-print")
        ui.image(data_url).classes("w-full excel-print-image")
        with ui.row().classes("w-full justify-end gap-2 mt-2 no-print"):
            AppBtn("关闭", on_click=dialog.close)
            AppBtn("下载 PNG", on_click=lambda: ui.download(png_bytes, download_name))
            AppBtn(
                "打印",
                variant="excel",
                on_click=lambda: ui.run_javascript("window.print()"),
            )
    dialog.open()


def _normalize_row_for_session(row: dict, labels: list[str]) -> dict[str, object]:
    """将 read_instances 的一行对齐到当前模板 Input_label 键。"""
    normalized: dict[str, object] = {}
    if "instance_idx" in row:
        normalized["instance_idx"] = row["instance_idx"]
    for lbl in labels:
        val = row.get(lbl)
        if val is None:
            normalized[lbl] = ""
        else:
            normalized[lbl] = val
    return normalized


def _reset_draft_after_session_change(session) -> None:
    session.draft.clear()
    if getattr(session, "template_defaults", None):
        session.draft.update(session.template_defaults)


def _clear_session_row_selection(session) -> None:
    session.selected_instance_idx = None
    session.selected_instance_indices.clear()


def _is_edit_selected(session) -> bool:
    """
    函数名: _is_edit_selected
    作用: 是否处于勾选编辑（覆盖）模式
    输入:
        session: 当前会话
    输出:
        bool: 已勾选编辑目标时为 True
    """
    return getattr(session, "selected_instance_idx", None) is not None


def _resolve_write_instance_idx(session) -> int:
    """
    函数名: _resolve_write_instance_idx
    作用: 写回目标 instance_idx——勾选编辑用选中行，否则用当前待录入 index（新建）
    输入:
        session: 当前会话
    输出:
        int: 0-based instance_idx
    """
    sel = getattr(session, "selected_instance_idx", None)
    if sel is not None:
        return int(sel)
    return int(session.current_instance_index or 0)


def _sync_draft_from_field_inputs(session) -> None:
    """
    函数名: _sync_draft_from_field_inputs
    作用: 保存/添加前把字段控件当前值合并进 session.draft
    输入:
        session: 当前会话
    输出: 无
    """
    labels = None
    if getattr(session, "ui_provider", None) is not None:
        try:
            labels = list(session.ui_provider.get_labels())
        except Exception:
            labels = None
    live = read_field_drafts(labels)
    session.draft.update(live)


def _load_session_row_into_draft(session, row_k: int) -> None:
    """
    函数名: _load_session_row_into_draft
    作用: 勾选/点击行时载入上方字段，并进入覆盖编辑模式
    输入:
        session: 当前会话
        row_k (int): 行 instance_idx
    输出: 无
    """
    session.selected_instance_idx = row_k
    # 非删除模式下勾选列与编辑选中同步为单选
    if not getattr(session, "delete_mode", False):
        session.selected_instance_indices = {row_k}
    idx = next(
        (
            row_idx
            for row_idx, row in enumerate(session.session_rows)
            if row.get("instance_idx", row_idx) == row_k
        ),
        None,
    )
    if idx is not None:
        session.draft = session.session_rows[idx].copy()
        session.draft.pop("_index", None)
        session.suppress_id_search = True
        # update formula_mask based on the selected row
        if getattr(session, "session_masks", None) and idx < len(session.session_masks):
            session.formula_mask = session.session_masks[idx].copy()
        # 刷新整页以同步提示文案与字段区
        render_input_tab.refresh()


def _unselect_edit_keep_draft(session, row_k: int) -> None:
    """
    函数名: _unselect_edit_keep_draft
    作用: 取消勾选编辑目标；先同步控件值进 draft，上方字段内容保留
    输入:
        session: 当前会话
        row_k (int): 被取消的 instance_idx
    输出: 无
    """
    # 取消前把上方已改内容写入 draft，避免整页 refresh 丢字
    _sync_draft_from_field_inputs(session)
    if session.selected_instance_idx == row_k:
        session.selected_instance_idx = None
    session.selected_instance_indices.discard(row_k)
    render_input_tab.refresh()


def _commit_draft_to_session_rows(
    session, write_k: int, *, overwrite: bool, record_id: int | None = None
) -> dict[str, Any]:
    """
    函数名: _commit_draft_to_session_rows
    作用: 把当前 draft 写入 session_rows（覆盖选中行或新建插入）
    输入:
        session: 当前会话
        write_k (int): 该条记录的 instance_idx
        overwrite (bool): True 覆盖同 instance_idx 行；False 头部插入新行
        record_id (int | None): 数据库 records.id；新建时写入，覆盖时保留旧 id
    输出:
        dict: 写入后的行副本
    """
    row_copy = session.draft.copy()
    row_copy.pop("_index", None)
    row_copy["instance_idx"] = write_k
    if overwrite:
        idx = next(
            (
                row_idx
                for row_idx, row in enumerate(session.session_rows)
                if row.get("instance_idx", row_idx) == write_k
            ),
            None,
        )
        if idx is not None:
            # 覆盖时保留 records.id，使删除仍能定位 DB 行
            old_id = session.session_rows[idx].get("id")
            if old_id is not None:
                row_copy["id"] = old_id
            session.session_rows[idx] = row_copy
        else:
            if record_id is not None:
                row_copy["id"] = record_id
            session.session_rows.insert(0, row_copy)
    else:
        if record_id is not None:
            row_copy["id"] = record_id
        session.session_rows.insert(0, row_copy)
    return row_copy


def _write_draft_to_excel(session, write_k: int) -> None:
    """
    函数名: _write_draft_to_excel
    作用: 把当前 draft 写回模板 xlsx 的指定 instance_idx
    输入:
        session: 当前会话
        write_k (int): 目标 instance
    输出: 无
    """
    if not session.writer or not session.template_path:
        return
    d = session.draft.copy()
    d.pop("_index", None)
    d.pop("instance_idx", None)
    session.writer.write_back(
        session.template_path, session.template_path, d, instance_idx=write_k
    )


@ui.refreshable
def render_session_table(session, labels: list[str]) -> None:
    """本次已录入：HTML5 表格 + 常驻勾选列（编辑单选 / 删除多选）+ 行点击载入。"""
    checked = session.selected_instance_indices
    delete_mode = getattr(session, "delete_mode", False)

    def toggle_sort(session, column: str) -> None:
        if getattr(session, "sort_column", None) == column:
            if getattr(session, "sort_descending", False):
                session.sort_column = None
                session.sort_descending = False
            else:
                session.sort_descending = True
        else:
            session.sort_column = column
            session.sort_descending = False
        render_session_table.refresh()

    with ui.element("div").classes(
        "flex-1 overflow-y-auto w-full mt-2 session-table-wrap"
    ):
        with ui.element("table").classes("records w-full"):
            with ui.element("thead").classes("sticky top-0 bg-gray-200 z-10 shadow-sm"):
                with ui.element("tr"):
                    # 常驻勾选列
                    with ui.element("th").classes("chkcol"):
                        ui.label("☐")
                    if not session.use_independent_db:
                        with ui.element("th"):
                            ui.label("#")
                    for lbl in labels:
                        with (
                            ui.element("th")
                            .classes("cursor-pointer select-none")
                            .on("click", lambda _e=None, l=lbl: toggle_sort(session, l))
                        ):
                            suffix = (
                                " ▲"
                                if getattr(session, "sort_column", None) == lbl
                                and not getattr(session, "sort_descending", False)
                                else (
                                    " ▼"
                                    if getattr(session, "sort_column", None) == lbl
                                    else ""
                                )
                            )
                            ui.label(lbl + suffix)
            with ui.element("tbody"):
                extra_cols = 1 + (0 if session.use_independent_db else 1)
                if not session.session_rows:
                    with ui.element("tr"):
                        with ui.element("td").props(
                            f"colspan={len(labels) + extra_cols}"
                        ):
                            ui.label("（尚无录入行）").classes("text-gray-500")

                displayed_rows = list(enumerate(session.session_rows))
                if getattr(session, "sort_column", None):
                    col = session.sort_column
                    displayed_rows.sort(
                        key=lambda item: str(item[1].get(col, "") or ""),
                        reverse=getattr(session, "sort_descending", False),
                    )

                for idx, row in displayed_rows:
                    row_k = row.get("instance_idx", idx)
                    is_edit = (
                        not delete_mode
                    ) and session.selected_instance_idx == row_k
                    row_class = "selected" if is_edit else ""
                    with ui.element("tr").classes(row_class):
                        with ui.element("td").classes("chkcol"):

                            def on_toggle(event, r_k: int = row_k) -> None:
                                if delete_mode:
                                    if event.value:
                                        session.selected_instance_indices.add(r_k)
                                    else:
                                        session.selected_instance_indices.discard(r_k)
                                    render_session_table.refresh()
                                    return
                                # 编辑模式：勾选=载入并单选；取消=保留上方字段
                                if event.value:
                                    _load_session_row_into_draft(session, r_k)
                                else:
                                    _unselect_edit_keep_draft(session, r_k)

                            box_val = (
                                row_k in checked
                                if delete_mode
                                else (session.selected_instance_idx == row_k)
                            )
                            ui.checkbox(
                                value=box_val,
                                on_change=on_toggle,
                            ).props("dense")
                        if not session.use_independent_db:
                            with ui.element("td").on(
                                "click",
                                lambda _e=None, r_k=row_k: _load_session_row_into_draft(
                                    session, r_k
                                ),
                            ):
                                ui.label(str(row_k))
                        for lbl in labels:
                            with ui.element("td").on(
                                "click",
                                lambda _e=None, r_k=row_k: _load_session_row_into_draft(
                                    session, r_k
                                ),
                            ):
                                val_str = str(row.get(lbl, "") or "")
                                if val_str.endswith(" 00:00:00"):
                                    val_str = val_str.replace(" 00:00:00", "")
                                ui.label(val_str).classes("whitespace-pre-wrap")

    if not session.use_independent_db and getattr(session, "loaded_offset_k", 0) > 0:

        def load_next_batch():
            offset_k = max(0, session.loaded_offset_k - 50)
            limit = session.loaded_offset_k - offset_k
            session.loaded_offset_k = offset_k
            instances, masks = session.writer.read_instances(
                session.template_path,
                limit=limit,
                offset_k=offset_k + limit - 1,
                reverse=True,
            )
            session.session_rows.extend(instances)
            session.session_masks.extend(masks)
            render_session_table.refresh()

        with ui.row().classes("justify-center w-full my-2"):
            ui.button(
                f"加载更多 (剩余 {session.loaded_offset_k} 行)",
                on_click=load_next_batch,
            ).props("flat dense")


def handle_delete_checked_session_rows(session) -> None:
    """删除勾选的 session_rows 行（含空行/部分填写行）；仅内存列表，不写 DB。"""
    if not getattr(session, "delete_mode", False):
        session.delete_mode = True
        session.selected_instance_indices.clear()
        render_input_tab.refresh()
        return

    keys = list(session.selected_instance_indices)
    if not keys:
        ui.notify("已取消删除操作", type="info")
        session.delete_mode = False
        render_input_tab.refresh()
        return

    use_db = getattr(session, "use_independent_db", True)
    deleted = 0
    # map keys back to indices to pop
    indices_to_delete = []
    for idx, row in enumerate(session.session_rows):
        if row.get("instance_idx", idx) in keys:
            indices_to_delete.append(idx)

    for idx in sorted(indices_to_delete, reverse=True):
        row = session.session_rows[idx]
        # 独立库模式下同时从 DB 删除，避免重载后死灰复燃
        if use_db and session.db:
            rid = row.get("id")
            if rid is not None:
                try:
                    session.db.delete_record(rid)
                except Exception:
                    pass
        session.session_rows.pop(idx)
        if getattr(session, "session_masks", None) and idx < len(session.session_masks):
            session.session_masks.pop(idx)
        deleted += 1

    _clear_session_row_selection(session)
    session.delete_mode = False
    session.current_instance_index = len(session.session_rows)
    _reset_draft_after_session_change(session)
    render_input_tab.refresh()
    ui.notify(f"已删除 {deleted} 行", type="positive")


@ui.refreshable
def render_print_row(session) -> None:
    # 打印文件 → 打印区域 → 打印（顺序与 HTML 蓝本一致）
    export_files = list_export_files(session.template_id or "")
    session.exported_files = export_files
    if export_files:
        resolved = {p.resolve(): p for p in export_files}
        last = session.last_export_path.resolve() if session.last_export_path else None
        if last and last in resolved:
            selected_path = resolved[last]
        else:
            selected_path = export_files[0]
            session.last_export_path = selected_path
    else:
        selected_path = None
        session.last_export_path = None
    print_areas = _resolve_print_areas(session, selected_path)
    print_labels = _print_area_labels(print_areas)
    name_to_path = {p.name: p for p in export_files}
    with ui.element("div").classes("print-row"):
        if export_files and selected_path is not None:

            def on_file_change(event) -> None:
                path = name_to_path.get(event.value)
                if path is None:
                    return
                session.last_export_path = path
                render_print_row.refresh()

            ui.select(
                options=list(name_to_path.keys()),
                value=selected_path.name,
                label="打印文件",
                on_change=on_file_change,
            ).classes("dropdown print-file").props("dense borderless hide-bottom-space")
        else:
            ui.select(
                options=["（空）"],
                value="（空）",
                label="打印文件",
            ).classes("dropdown print-file").props(
                "dense borderless disable hide-bottom-space"
            )
        selected_area = (
            ui.select(
                print_labels,
                value=print_labels[0],
                label="打印区域",
            )
            .classes("dropdown narrow")
            .props("dense borderless hide-bottom-space")
        )
        AppBtn(
            "打印",
            variant="excel",
            on_click=lambda: handle_print(session, selected_area.value, selected_path),
        )


@ui.refreshable
def render_input_tab():
    session = SessionRegistry.for_current()

    if not session.template_id:
        ui.label("请从左侧选择模板。").classes("text-red text-lg font-bold")
        return
    if session.verify_report and not session.verify_report.get("ok", False):
        ui.label("配置校验未通过，部分功能可能不可用。").classes(
            "text-orange text-sm mb-2"
        )

    ui_provider = session.ui_provider
    if not ui_provider:
        ui.label("引擎未就绪，请打开 [输入配置] 检查 TOML。").classes("text-red")
        return

    labels = ui_provider.get_labels()

    with ui.element("div").classes("tab-flex-container"):
        # 幽灵输入框
        def on_ghost_blur(event) -> None:
            raw = event.sender.value or ""
            if not str(raw).strip():
                return
            _sync_ghost_paste(session, str(raw))
            from nicegui_ui.components.wizard_ui import is_wizard_active

            # 配置向导步骤 2：仅缓存样本，不触发自动拆分填入字段
            if is_wizard_active():
                return
            try:
                incoming = ui_provider.record_from_textbox(str(raw))
                session.draft.update(incoming)
                session.suppress_id_search = True
                event.sender.value = ""
                render_dynamic_fields.refresh()
                if raw.strip().startswith("{"):
                    ui.notify("已从 OCR 结果解析并填入各字段", type="positive")
                else:
                    ui.notify("已从粘贴板解析数据", type="positive")
            except Exception as ex:
                ui.notify(f"解析失败: {str(ex)}", type="negative")

        ghost = (
            ui.textarea()
            .classes("ghost-input")
            .props('borderless autogrow hide-bottom-space rows="1"')
        )

        def on_ghost_change(_event) -> None:
            # OCR 设值或用户输入时同步服务端，不依赖 blur 回传
            _sync_ghost_paste(session, ghost.value or "")

        ghost.on("blur", on_ghost_blur)
        ghost.on("update:model-value", on_ghost_change)
        global _ghost_input
        _ghost_input = ghost
        with ghost:
            with ui.context_menu():
                add_image_pick_menu_items(session, GHOST_OCR_LABEL, ghost)
        # 动态字段区（默认 3 列 field-grid）
        with ui.element("div").classes("field-grid shrink-0"):
            render_dynamic_fields(session, labels)

        # 本次已录入表格 / 模板已存数据
        with ui.element("div").classes(
            "session-panel session-list flex-1 flex flex-col min-h-[150px] overflow-hidden"
        ):
            if session.use_independent_db:
                if getattr(session, "delete_mode", False):
                    lbl_hint = "（请勾选要删除的行）"
                elif _is_edit_selected(session):
                    lbl_hint = "（已勾选：保存/方向按钮将覆盖该条；取消勾选不清空上方）"
                else:
                    lbl_hint = "（勾选载入上方；未勾选时保存/方向=新建）"
                ui.label(f"本次已录入 {lbl_hint}").classes("title shrink-0")
                ui.label(
                    f"当前 {session.current_instance_index + 1} / 容量 {session.input_capacity}（到达容量上限时不再清空输入）"
                ).classes("ghost-note shrink-0")
            else:
                if getattr(session, "delete_mode", False):
                    lbl_hint = "（请勾选要删除的行）"
                elif _is_edit_selected(session):
                    lbl_hint = (
                        "（已勾选：保存/方向按钮将覆盖该 instance；取消勾选不清空上方）"
                    )
                else:
                    lbl_hint = "（勾选载入上方；未勾选时保存/方向=新建写入）"
                ui.label(f"模板已存数据 {lbl_hint}").classes("title shrink-0")
                ui.label(
                    f"当前将录入至 instance {session.current_instance_index}"
                ).classes("ghost-note shrink-0")
            render_session_table(session, labels)
        ui.element("hr").classes("sep shrink-0")

        # 保存 / 添加 / 刷新 / 删除数据
        with ui.element("div").classes("toolbar-row shrink-0 w-full"):
            validation_ok = not (
                session.verify_report and not session.verify_report.get("ok", False)
            )

            with ui.row().classes("gap-2 items-center"):
                if validation_ok:
                    AppBtn(
                        "保存",
                        variant="excel",
                        on_click=lambda: handle_save_as(session),
                    )
                else:
                    AppBtn("保存", variant="excel", disabled=True)

                def on_refresh():
                    from nicegui_ui.components.for_main import ForMain

                    ForMain.refresh_session_from_source(session)
                    render_input_tab.refresh()

                AppBtn("刷新数据", variant="excel", on_click=on_refresh)
                if getattr(session, "delete_mode", False):
                    AppBtn(
                        "确认删除",
                        variant="danger",
                        on_click=lambda: handle_delete_checked_session_rows(session),
                    )
                else:
                    AppBtn(
                        "删除选中",
                        on_click=lambda: handle_delete_checked_session_rows(session),
                    )
            with ui.row().classes("gap-2 items-center"):
                # 按 move_to 绘制一或两个方向添加按钮
                move_to = "down"
                scene2 = False
                if session.cfg is not None and getattr(
                    session.cfg, "input_section", None
                ):
                    move_to = session.cfg.input_section.move_to
                    scene2 = is_scene2_section(session.cfg.input_section)
                directions = move_to_directions(move_to)
                primary_span = int(getattr(session, "primary_span", 0) or 0)
                write_k = _resolve_write_instance_idx(session)
                use_db = getattr(session, "use_independent_db", True)
                for direction in directions:
                    label = add_button_label(direction)
                    next_k = next_instance_idx_along(
                        write_k, direction, move_to, primary_span, scene2=scene2
                    )
                    # 独立库模式还需受自然容量限制；模板即库模式只受方向本身限制
                    disabled = (
                        not validation_ok
                        or next_k is None
                        or (use_db and next_k >= session.input_capacity)
                    )
                    AppBtn(
                        label,
                        variant="db",
                        disabled=disabled,
                        on_click=lambda _e=None, d=direction: handle_next_row(
                            session, d
                        ),
                    )

        ui.element("div").classes("w-full shrink-0").style(
            "height:1px; background:#000; margin: 10px 0;"
        )

        # 打印文件 + 打印区域 + 打印（紧挨）
        with ui.element("div").classes("shrink-0"):
            render_print_row(session)


@ui.refreshable
def render_dynamic_fields(session, labels: list[str]):
    global _field_inputs
    # refresh 会重建控件，先清空登记再按当前标签重绑
    _field_inputs = {}
    select_options = {}
    if session.verify_report:
        select_options = dict(session.verify_report.get("select_options") or {})
    rules_by_label = {}
    if session.cfg is not None:
        for rule in session.cfg.field_rules or []:
            rules_by_label[rule.Input_label] = rule
    for lbl in labels:
        is_pk = False
        rule = rules_by_label.get(lbl)
        if rule is not None and getattr(rule, "id", False):
            is_pk = True
        ui_widget = getattr(rule, "ui_widget", "text") if rule else "text"
        cell_role = getattr(rule, "cell_role", "input") if rule else "input"
        is_readonly = (
            bool(getattr(session, "formula_mask", {}).get(lbl))
            or cell_role == "formula"
            or ui_widget == "readonly"
        )

        def create_on_change(label: str):
            def on_change(event) -> None:
                session.draft[label] = event.value

            return on_change

        def create_on_blur(label: str):
            def on_id_blur(event) -> None:
                if session.suppress_id_search:
                    session.suppress_id_search = False
                    return
                # blur 常早于 change；优先读控件当前值，再回退 draft
                sender_val = getattr(event.sender, "value", None)
                val = (
                    sender_val
                    if sender_val not in (None, "")
                    else session.draft.get(label)
                )
                if not val or not str(val).strip():
                    return
                val = str(val).strip()
                session.draft[label] = val

                use_db = getattr(session, "use_independent_db", True)
                existing = None

                from app.core_store import _normalize_id

                try:
                    rid = _normalize_id(val)
                except ValueError:
                    rid = val

                if use_db and session.db:
                    existing = session.db.query_by_id(rid) if rid is not None else None

                if existing:
                    with ui.dialog() as dialog, ui.card():
                        ui.label(f"发现已存在的记录 (ID: {val})")

                        def refetch_from_source() -> None:
                            dialog.close()
                            if IdLookup.apply_source_to_draft(session, val):
                                render_dynamic_fields.refresh()
                                ui.notify(f"已从数据源重新读取 ID {val}", type="info")
                            else:
                                ui.notify(f"数据源中未找到 ID {val}", type="warning")

                        with ui.row().classes("gap-2"):
                            AppBtn("从数据源重新读取", on_click=refetch_from_source)
                            AppBtn(
                                "从数据库读取",
                                on_click=lambda: load_and_close(dialog, existing),
                            )
                    dialog.open()
                else:
                    if IdLookup.apply_source_to_draft(session, val):
                        render_dynamic_fields.refresh()
                        ui.notify(f"已加载外部数据 ID {val}", type="info")
                    elif not getattr(session, "google_connected", False):
                        ui.notify(
                            "尚未连接 Google Sheet，无法按主键查源", type="warning"
                        )

            return on_id_blur

        def create_sync_blur(label: str):
            def on_blur(event) -> None:
                # 非主键：失焦时把控件值写入 draft（不依赖 on_change 是否已触发）
                sender_val = getattr(event.sender, "value", None)
                if sender_val is not None:
                    session.draft[label] = str(sender_val)

            return on_blur

        def load_and_close(dialog, existing_row) -> None:
            dialog.close()
            session.draft.update(existing_row)
            session.suppress_id_search = True
            render_dynamic_fields.refresh()

        with ui.element("div").classes(
            "field-cell id-field" if is_pk else "field-cell"
        ):
            ui.label(lbl).classes("field-label primary" if is_pk else "field-label")

            with ui.element("div").classes("field-input-row"):
                draft_val = session.draft.get(lbl, "")
                draft_str = "" if draft_val is None else str(draft_val)
                if ui_widget == "select" and not is_readonly:
                    opts = list(select_options.get(lbl) or [])
                    cur = draft_str if draft_str in opts else (draft_str or None)
                    inp = (
                        ui.select(
                            options=opts,
                            value=cur,
                            on_change=create_on_change(lbl),
                            with_input=True,
                        )
                        .classes("input-box")
                        .props("dense borderless hide-bottom-space")
                    )
                else:
                    inp = (
                        ui.textarea(
                            value=draft_str,
                            on_change=create_on_change(lbl),
                        )
                        .classes("input-box")
                        .props('autogrow dense borderless hide-bottom-space rows="1"')
                    )
                if is_readonly:
                    inp.props("readonly")
                if is_pk:
                    inp.on("blur", create_on_blur(lbl))
                else:
                    inp.on("blur", create_sync_blur(lbl))
                # 向导步骤 3 可直接读控件当前值
                _field_inputs[lbl] = inp
                if not is_readonly and ui_widget != "select":
                    with inp:
                        with ui.context_menu():
                            add_image_pick_menu_items(session, lbl, inp)
                    btn = (
                        ui.button("···").classes("mobile-menu-btn").props("flat dense")
                    )
                    with btn:
                        with ui.menu():
                            add_image_pick_menu_items(session, lbl, inp)


def handle_next_row(session, direction: str = "down"):
    """
    函数名: handle_next_row
    作用: 提交当前 draft（勾选=覆盖，未勾选=新建），写入 DB/Excel，再沿方向推进
    输入:
        session: 当前会话
        direction (str): 用户点击的方向（up/down/left/right）
    输出: 无
    """
    use_db = getattr(session, "use_independent_db", True)
    _sync_draft_from_field_inputs(session)
    move_to = "down"
    scene2 = False
    if session.cfg is not None and getattr(session.cfg, "input_section", None):
        move_to = session.cfg.input_section.move_to
        scene2 = is_scene2_section(session.cfg.input_section)
    primary_span = int(getattr(session, "primary_span", 0) or 0)
    overwrite = _is_edit_selected(session)
    write_k = _resolve_write_instance_idx(session)
    next_k = next_instance_idx_along(
        write_k, direction, move_to, primary_span, scene2=scene2
    )
    # 独立库模式：下一步将超出自然容量时阻断；模板即库模式不限
    if use_db and next_k is not None and next_k >= session.input_capacity:
        ui.notify("容量已满，无法继续添加", type="warning")
        return
    if next_k is None:
        ui.notify("该方向已无空位，请改用另一方向或检查版式", type="warning")
        return
    if getattr(session, "field_images", None) and not use_db:
        session.field_images.clear()
    try:
        if use_db:
            record_id = session.ui_provider.persist_fields(
                session.draft, instance_idx=write_k
            )
            if getattr(session, "field_images", None):
                for label, img_data in list(session.field_images.items()):
                    res = session.db.save_image(
                        cfg=session.cfg,
                        template_id=session.template_id,
                        record_id=record_id,
                        input_label=label,
                        image_bytes=img_data["bytes"],
                        mime=img_data["mime"],
                    )
                    if res.get("ok"):
                        image_id = res["image_id"]
                        ocr_text = img_data.get("ocr_text")
                        ocr_status = img_data.get("ocr_status")
                        if ocr_text or ocr_status:
                            session.db.update_image_ocr(
                                image_id=image_id,
                                ocr_text=ocr_text,
                                ocr_status=ocr_status,
                            )
                    del session.field_images[label]
            _commit_draft_to_session_rows(
                session, write_k, overwrite=overwrite, record_id=record_id
            )
            # 方向按钮：覆盖或新建后都写入 excel
            _write_draft_to_excel(session, write_k)
        else:
            # 模板即库：写回当前 write_k
            _write_draft_to_excel(session, write_k)
            from nicegui_ui.components.for_main import ForMain

            ForMain.refresh_session_from_source(session, notify=False)
            from nicegui_ui.pages.tab_db import render_db_tab

            render_db_tab.refresh()
        session.current_instance_index = next_k
        session.selected_instance_idx = None
        session.selected_instance_indices.clear()
        # 载入推进后的格（模板即库）或清空为默认（独立库）
        if use_db:
            session.draft.clear()
            if getattr(session, "template_defaults", None):
                session.draft.update(session.template_defaults)
        else:
            if session.writer and session.template_path:
                val, mask = session.writer.read_values(
                    session.template_path, session.current_instance_index
                )
                session.draft.clear()
                session.draft.update(val)
                session.formula_mask = mask
    except Exception as e:
        ui.notify(f"写入失败: {str(e)}", type="negative")
        return
    render_input_tab.refresh()
    mode = "已覆盖" if overwrite else "已新建"
    ui.notify(f"{mode}并写入 Excel，已推进", type="positive")


def handle_save_as(session):
    """
    函数名: handle_save_as
    作用: 勾选时覆盖 DB/会话行；未勾选时新增。独立库另导出 xlsx；模板即库写回模板。
    输入:
        session: 当前会话
    输出: 无
    """
    _sync_draft_from_field_inputs(session)
    if not session.session_rows and not any(
        str(v).strip() for v in session.draft.values() if v is not None
    ):
        ui.notify("没有数据可以保存", type="warning")
        return

    use_db = getattr(session, "use_independent_db", True)
    overwrite = _is_edit_selected(session)
    write_k = _resolve_write_instance_idx(session)
    is_draft_active = any(
        str(v).strip() for v in session.draft.values() if v is not None
    )

    try:
        if use_db:
            if is_draft_active:
                if use_db and (not overwrite) and write_k >= session.input_capacity:
                    ui.notify("容量已满，无法新建", type="warning")
                    return
                record_id = session.ui_provider.persist_fields(
                    session.draft, instance_idx=write_k
                )
                if getattr(session, "field_images", None):
                    for label, img_data in list(session.field_images.items()):
                        res = session.db.save_image(
                            cfg=session.cfg,
                            template_id=session.template_id,
                            record_id=record_id,
                            input_label=label,
                            image_bytes=img_data["bytes"],
                            mime=img_data["mime"],
                        )
                        if res.get("ok"):
                            image_id = res["image_id"]
                            ocr_text, ocr_status = (
                                img_data.get("ocr_text"),
                                img_data.get("ocr_status"),
                            )
                            if ocr_text or ocr_status:
                                session.db.update_image_ocr(
                                    image_id, ocr_text, ocr_status
                                )
                        del session.field_images[label]
                _commit_draft_to_session_rows(
                    session, write_k, overwrite=overwrite, record_id=record_id
                )
                if not overwrite:
                    # 新建后推进待录入指针，便于连续录入
                    session.current_instance_index = write_k + 1
                # 保存后退出勾选覆盖模式，draft 保留便于继续改或再新建
                session.selected_instance_idx = None
                session.selected_instance_indices.clear()
            # 导出全部会话行到 exports/
            rows_to_write = [dict(r) for r in session.session_rows]
            for r in rows_to_write:
                r.pop("_index", None)
            if not rows_to_write:
                ui.notify("没有数据可以导出", type="warning")
                return
            from app.core_store import _read_active_suffix_token

            suffix = _read_active_suffix_token(session.template_id) or "0000"
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{session.template_id}_{suffix}_{ts}.xlsx"
            export_dir = ensure_exports_dir(session.template_id)
            out_path = export_dir / filename
            session.writer.write_back(
                session.template_path, out_path, rows_to_write, instance_idx=0
            )
            session.exported_files.append(out_path)
            session.last_export_path = out_path
            mode = "已覆盖数据库" if overwrite else "已新增记录"
            ui.notify(f"{mode}并导出: {filename}", type="positive")
        else:
            # 模板即库：保存 = 按 instance_idx 写回模板（勾选覆盖 / 未勾选新建槽）
            if getattr(session, "field_images", None):
                session.field_images.clear()
            if not is_draft_active:
                ui.notify("没有可写入模板的编辑内容", type="warning")
                return
            _write_draft_to_excel(session, write_k)
            from nicegui_ui.components.for_main import ForMain

            ForMain.refresh_session_from_source(session, notify=False)
            session.selected_instance_idx = None
            session.selected_instance_indices.clear()
            mode = "已覆盖" if overwrite else "已新建写入"
            ui.notify(f"{mode}模板 instance {write_k}", type="positive")
        render_input_tab.refresh()
        from nicegui_ui.pages.tab_db import render_db_tab

        render_db_tab.refresh()
    except Exception as e:
        ui.notify(f"保存失败: {str(e)}", type="negative")


def handle_print(session, selected_label, export_path: Path | None = None) -> None:
    path = Path(export_path) if export_path else None
    if path is None and session.last_export_path:
        path = Path(session.last_export_path)
    if path is None or not path.is_file():
        ui.notify("请先成功执行【保存】", type="warning")
        return

    import os

    if os.name == "nt":
        try:
            os.startfile(str(path), "print")
            ui.notify("已发送至本地打印机", type="positive")
        except Exception as e:
            ui.notify(f"打印失败: {str(e)}", type="negative")
    else:
        ui.notify("自动打印仅支持 Windows 系统", type="warning")
