from nicegui import ui
from nicegui_ui.components.general import SessionRegistry
from app.core_store import list_db_paths, allocate_next_db_path


def _select_db_row(session, row_id) -> None:
    """Remember selected DB row primary key for overwrite."""
    session.selected_db_row_index = row_id


@ui.refreshable
def render_db_tab():
    session = SessionRegistry.for_current()
    if not session.db or not session.ui_provider:
        ui.label('请先从左侧选择有效的模板配置').classes('text-gray-500 italic p-4')
        return
    pk_label = None
    for rule in session.cfg.field_rules:
        if getattr(rule, 'id', False):
            pk_label = rule.Input_label
            break
    with ui.element('div'):
        # 当前数据库
        with ui.element('div').classes('section'):
            with ui.row().classes('w-full justify-between items-center section-title'):
                ui.label('当前数据库')
                
                from nicegui import app
                if session.template_id:
                    session.use_independent_db = app.storage.user.get(f'use_independent_db_{session.template_id}', True)
                    
                def on_use_independent_db_change(e):
                    session.use_independent_db = e.value
                    if session.template_id:
                        app.storage.user[f'use_independent_db_{session.template_id}'] = e.value
                    render_db_tab.refresh()
                ui.checkbox('使用独立数据库', value=session.use_independent_db, on_change=on_use_independent_db_change).props('dense')
            with ui.element('div').classes('section-body'):
                with ui.element('div').classes('form-row'):
                    ui.label('使用库').classes('field-label')
                    
                    paths = list_db_paths(session.template_id)
                    options = {str(p): p.name for p in paths}
                    current_db_str = str(session.db_path)
                    
                    db_select = ui.select(options, value=current_db_str, label='').classes('dropdown narrow').props('dense borderless hide-bottom-space')
                    
                    switch_cls = 'btn db disabled'
                    switch_lbl = ui.label('切换').classes(switch_cls)
                    
                    if not session.use_independent_db:
                        db_select.props('disable')
                        switch_lbl.classes('disabled')
                        
                    def on_switch():
                        if not session.use_independent_db: return
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
                        session.selected_session_index = None
                        session.selected_session_indices.clear()
                        session.current_instance_index = 0
                        ui.notify('已切换数据库', type='positive')
                        render_db_tab.refresh()
                        from nicegui_ui.pages.tab_input import render_input_tab
                        render_input_tab.refresh()
                    switch_lbl.on('click', on_switch)
                    def on_db_select_change() -> None:
                        if db_select.value != current_db_str and session.use_independent_db:
                            switch_lbl.classes('btn db', remove='disabled')
                        else:
                            switch_lbl.classes('btn db disabled')
                    db_select.on('update:model-value', lambda _e: on_db_select_change())
                    
                    def on_new_db():
                        if not session.use_independent_db: return
                        try:
                            new_path = allocate_next_db_path(session.template_id)
                            from app.core_store import SecureSQLite, UiProvider
                            session.db.close()
                            session.db_path = new_path
                            session.db = SecureSQLite(session.db_path)
                            session.ui_provider = UiProvider(session.cfg, session.db)
                            
                            session.draft.clear()
                            session.session_rows.clear()
                            session.selected_session_index = None
                            session.selected_session_indices.clear()
                            session.current_instance_index = 0
                            
                            ui.notify(f'已创建并切换到新库: {new_path.name}', type='positive')
                            render_db_tab.refresh()
                            
                            from nicegui_ui.pages.tab_input import render_input_tab
                            render_input_tab.refresh()
                        except Exception as e:
                            ui.notify(f'创建失败: {str(e)}', type='negative')
                            
                    new_db_btn = ui.label('新建库').classes('btn db').on('click', on_new_db)
                    if not session.use_independent_db:
                        new_db_btn.classes('disabled')
                    
                ui.label('「切换」平时不可用；仅当 Dropdown 选中项 ≠ 当前使用库时才变为可点。' if session.use_independent_db else '未勾选独立数据库，数据将直接回写至模板本身。').classes('hint')
        
        # 全部数据
        with ui.element('div').classes('section'):
            table_title = '全部数据（HTML5 自定义表格）' if session.use_independent_db else '数据表已存数据（从模板读取）'
            ui.label(table_title).classes('section-title')
            with ui.element('div').classes('section-body'):
                if session.use_independent_db:
                    data = session.ui_provider.get_data()
                else:
                    try:
                        data = session.writer.read_instances(session.template_path, limit=session.input_capacity) if session.writer else []
                    except Exception as e:
                        data = []
                        ui.notify(f'读取模板失败: {str(e)}', type='negative')
                        
                if not data:
                    ui.label('当前库为空' if session.use_independent_db else '模板中无数据').classes('hint')
                else:
                    labels = session.ui_provider.get_labels()
                    with ui.element('table').classes('t records'):
                        with ui.element('thead'):
                            with ui.element('tr'):
                                for lbl in labels:
                                    with ui.element('th'):
                                        ui.label(lbl)
                        with ui.element('tbody'):
                            for row in data:
                                row_id = row.get(pk_label) if pk_label else row.get('id')
                                with ui.element('tr').classes('cursor-pointer').on(
                                    'click',
                                    lambda _e=None, rid=row_id: _select_db_row(session, rid),
                                ):
                                    for lbl in labels:
                                        with ui.element('td'):
                                            ui.label(str(row.get(lbl, '') or ''))

        # 覆盖录入
        with ui.element('div').classes('section'):
            ui.label('覆盖录入（选中某行后，粘贴整段数据覆盖并保存）').classes('section-title')
            with ui.element('div').classes('section-body'):
                if not session.use_independent_db:
                    ui.label('非独立数据库模式下不可用覆盖录入。').classes('hint')
                else:
                    def on_overwrite(e):
                        if session.selected_db_row_index is None:
                            ui.notify('请先从上面表格选中要覆盖的行', type='warning')
                            return
                        raw = overwrite_input.value
                        if not raw.strip():
                            return
                        try:
                            incoming = session.ui_provider.record_from_textbox(raw)
                            incoming[pk_label] = session.selected_db_row_index
                            session.ui_provider.persist_fields(incoming)
                            overwrite_input.value = ""
                            ui.notify('覆盖成功', type='positive')
                            render_db_tab.refresh()
                        except Exception as e:
                            ui.notify(f'覆盖失败: {str(e)}', type='negative')
    
                    overwrite_input = ui.textarea().classes('ghost-input').props('borderless autogrow hide-bottom-space rows="1"')
                    with overwrite_input:
                        with ui.context_menu():
                            from nicegui_ui.components.ocr_menu import open_camera_dialog, run_ocr
                            ui.menu_item('拍照', on_click=lambda: open_camera_dialog(session, '覆盖录入'))
                            ui.menu_item('OCR', on_click=lambda: run_ocr(session, '覆盖录入', overwrite_input))
                    with ui.element('div').classes('form-row').style('margin-top:8px'):
                        ui.label('覆盖保存').classes('btn db').on('click', on_overwrite)
