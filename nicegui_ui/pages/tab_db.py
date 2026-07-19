from nicegui import ui
from nicegui_ui.components.buttons import app_btn, app_btn_set_disabled
from nicegui_ui.components.general import SessionRegistry
from app.core_store import list_db_paths, allocate_next_db_path


def _select_db_row(session, row_id, is_independent: bool) -> None:
    """Remember selected DB row primary key or instance_k for overwrite."""
    if is_independent:
        session.selected_db_row_index = row_id
    else:
        session.selected_instance_k = row_id


@ui.refreshable
def render_db_tab():
    session = SessionRegistry.for_current()
    if not session.db or not session.ui_provider:
        ui.label("请先从左侧选择有效的模板配置").classes("text-gray-500 italic p-4")
        return
    pk_label = None
    for rule in session.cfg.field_rules:
        if getattr(rule, "id", False):
            pk_label = rule.Input_label
            break
    with ui.element("div").classes("tab-scroll-container"):
        # 当前数据库
        with ui.element("div").classes("section"):
            with ui.row().classes("w-full justify-between items-center section-title"):
                ui.label("当前数据库")

                def on_use_independent_db_change(e):
                    session.use_independent_db = e.value
                    if session.template_id:
                        session.cfg.use_independent_db = e.value
                        session.cfg.Save(session.template_id)
                    from nicegui_ui.components.for_main import ForMain

                    if session.template_id and session.template_path:
                        ForMain.load_template(
                            session.template_id, str(session.template_path)
                        )
                    render_db_tab.refresh()
                    from nicegui_ui.pages.tab_input import render_input_tab

                    render_input_tab.refresh()

                ui.checkbox(
                    "使用独立数据库",
                    value=session.use_independent_db,
                    on_change=on_use_independent_db_change,
                ).props("dense")
            with ui.element("div").classes("section-body"):
                with ui.element("div").classes("form-row"):
                    ui.label("使用库").classes("field-label")

                    paths = list_db_paths(session.template_id)
                    options = {str(p): p.name for p in paths}
                    current_db_str = str(session.db_path)

                    db_select = (
                        ui.select(options, value=current_db_str, label="")
                        .classes("dropdown narrow")
                        .props("dense borderless hide-bottom-space")
                    )
                    def on_switch():
                        if not session.use_independent_db:
                            return
                        new_path_str = db_select.value
                        if new_path_str == current_db_str:
                            return
                        from pathlib import Path
                        from app.core_store import SecureSQLite, UiProvider
                        session.db.close()
                        session.db_path = Path(new_path_str)
                        session.db = SecureSQLite(session.db_path)
                        session.ui_provider = UiProvider(session.cfg, session.db)
                        session.draft.clear()
                        session.session_rows.clear()
                        session.selected_instance_k = None
                        session.selected_instance_indices.clear()
                        session.sort_column = None
                        session.sort_descending = False
                        session.db_loaded_limit = 50
                        session.current_instance_index = 0
                        ui.notify("已切换数据库", type="positive")
                        render_db_tab.refresh()
                        from nicegui_ui.pages.tab_input import render_input_tab
                        render_input_tab.refresh()
                    switch_lbl = app_btn("切换", variant="db", disabled=True, on_click=on_switch)
                    if not session.use_independent_db:
                        db_select.props("disable")
                        app_btn_set_disabled(switch_lbl, True)
                    def on_db_select_change() -> None:
                        if (
                            db_select.value != current_db_str
                            and session.use_independent_db
                        ):
                            app_btn_set_disabled(switch_lbl, False)
                        else:
                            app_btn_set_disabled(switch_lbl, True)

                    db_select.on("update:model-value", lambda _e: on_db_select_change())

                    def on_new_db():
                        if not session.use_independent_db:
                            return
                        try:
                            new_path = allocate_next_db_path(session.template_id)
                            from app.core_store import SecureSQLite, UiProvider

                            session.db.close()
                            session.db_path = new_path
                            session.db = SecureSQLite(session.db_path)
                            session.ui_provider = UiProvider(session.cfg, session.db)

                            session.draft.clear()
                            session.session_rows.clear()
                            session.selected_instance_k = None
                            session.selected_instance_indices.clear()
                            session.sort_column = None
                            session.sort_descending = False
                            session.db_loaded_limit = 50
                            session.current_instance_index = 0

                            ui.notify(
                                f"已创建并切换到新库: {new_path.name}", type="positive"
                            )
                            render_db_tab.refresh()

                            from nicegui_ui.pages.tab_input import render_input_tab

                            render_input_tab.refresh()
                        except Exception as e:
                            ui.notify(f"创建失败: {str(e)}", type="negative")

                    new_db_btn = app_btn("新建库", variant="db", on_click=on_new_db)
                    if not session.use_independent_db:
                        app_btn_set_disabled(new_db_btn, True)

                ui.label(
                    "「切换」平时不可用；仅当 Dropdown 选中项 ≠ 当前使用库时才变为可点。"
                    if session.use_independent_db
                    else "未勾选独立数据库，数据将直接回写至模板本身。"
                ).classes("hint")

        # 全部数据
        with ui.element("div").classes("section"):
            table_title = (
                "全部数据（HTML5 自定义表格）"
                if session.use_independent_db
                else "数据表已存数据（从模板读取）"
            )
            ui.label(table_title).classes("section-title")
            with ui.element("div").classes("section-body"):
                if session.use_independent_db:
                    data = session.ui_provider.get_data()
                else:
                    data = session.session_rows

                if not data:
                    ui.label(
                        "当前库为空" if session.use_independent_db else "模板中无数据"
                    ).classes("hint")
                else:
                    labels = session.ui_provider.get_labels()
                    with ui.element("div").classes(
                        "overflow-y-auto max-h-[500px] border border-gray-300 w-full mt-2"
                    ):
                        with ui.element("table").classes("t records w-full"):
                            with ui.element("thead").classes(
                                "sticky top-0 bg-gray-200 z-10 shadow-sm"
                            ):
                                with ui.element("tr"):
                                    if not session.use_independent_db:
                                        with ui.element("th"):
                                            move_dir = getattr(
                                                session.cfg.input_section,
                                                "move_to",
                                                "down",
                                            )
                                            header_lbl = (
                                                "列号"
                                                if move_dir in ["left", "right"]
                                                else "行号"
                                            )
                                            ui.label(header_lbl)
                                    for lbl in labels:
                                        with ui.element("th"):
                                            ui.label(lbl)
                        with ui.element("tbody"):
                            if not session.use_independent_db:
                                displayed_data = data
                            else:
                                limit = getattr(session, "db_loaded_limit", 50)
                                displayed_data = data[:limit]

                            for row in displayed_data:
                                if session.use_independent_db:
                                    row_id = (
                                        row.get(pk_label) if pk_label else row.get("id")
                                    )
                                else:
                                    row_id = row.get("instance_k")
                                with (
                                    ui.element("tr")
                                    .classes("cursor-pointer")
                                    .on(
                                        "click",
                                        lambda _e=None, rid=row_id: _select_db_row(
                                            session, rid, session.use_independent_db
                                        ),
                                    )
                                ):
                                    if not session.use_independent_db:
                                        with ui.element("td"):
                                            ui.label(
                                                str(row_id)
                                                if row_id is not None
                                                else ""
                                            )
                                    for lbl in labels:
                                        with ui.element("td"):
                                            val_str = str(row.get(lbl, "") or "")
                                            if val_str.endswith(" 00:00:00"):
                                                val_str = val_str.replace(
                                                    " 00:00:00", ""
                                                )
                                            ui.label(val_str).classes(
                                                "whitespace-pre-wrap"
                                            )

                    if (
                        not session.use_independent_db
                        and getattr(session, "loaded_offset_k", 0) > 0
                    ):

                        def load_next_batch_excel():
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
                            render_db_tab.refresh()
                            from nicegui_ui.pages.tab_input import render_session_table

                            render_session_table.refresh()

                        with ui.row().classes("justify-center w-full my-2"):
                            ui.button(
                                f"加载更多 (剩余 {session.loaded_offset_k} 行)",
                                on_click=load_next_batch_excel,
                            ).props("flat dense")
                    elif session.use_independent_db and len(data) > getattr(
                        session, "db_loaded_limit", 50
                    ):

                        def load_next_batch_db():
                            session.db_loaded_limit = (
                                getattr(session, "db_loaded_limit", 50) + 50
                            )
                            render_db_tab.refresh()

                        with ui.row().classes("justify-center w-full my-2"):
                            ui.button(
                                "加载更多 (50行)", on_click=load_next_batch_db
                            ).props("flat dense")

        # 覆盖录入
        with ui.element("div").classes("section"):
            ui.label("覆盖录入（选中某行后，粘贴整段数据覆盖并保存）").classes(
                "section-title"
            )
            with ui.element("div").classes("section-body"):

                def on_overwrite(e):
                    if session.use_independent_db:
                        if session.selected_db_row_index is None:
                            ui.notify("请先从上面表格选中要覆盖的行", type="warning")
                            return
                    else:
                        if session.selected_instance_k is None:
                            ui.notify("请先从上面表格选中要覆盖的行", type="warning")
                            return

                    raw = overwrite_input.value
                    if not raw.strip():
                        return
                    try:
                        incoming = session.ui_provider.record_from_textbox(raw)
                        if session.use_independent_db:
                            incoming[pk_label] = session.selected_db_row_index
                            session.ui_provider.persist_fields(incoming)
                        else:
                            # 覆盖保存 -> merge paste into draft -> write_back updating the selected instance row
                            merged = dict(session.draft)
                            merged.update(incoming)
                            session.writer.write_back(
                                session.template_path,
                                session.template_path,
                                merged,
                                session.selected_instance_k,
                            )
                            from nicegui_ui.components.for_main import ForMain

                            ForMain.load_template(
                                session.template_id, str(session.template_path)
                            )
                        overwrite_input.value = ""
                        ui.notify("覆盖成功", type="positive")
                        render_db_tab.refresh()
                        from nicegui_ui.pages.tab_input import render_input_tab

                        render_input_tab.refresh()
                    except Exception as e:
                        ui.notify(f"覆盖失败: {str(e)}", type="negative")

                overwrite_input = (
                    ui.textarea()
                    .classes("ghost-input")
                    .props('borderless autogrow hide-bottom-space rows="1"')
                )
                with overwrite_input:
                    with ui.context_menu():
                        from nicegui_ui.components.ocr_menu import (
                            add_image_pick_menu_items,
                        )

                        add_image_pick_menu_items(session, "覆盖录入", overwrite_input)
                with ui.element("div").classes("form-row").style("margin-top:8px"):
                    app_btn("覆盖保存", variant="db", on_click=on_overwrite)
