from datetime import datetime

from nicegui import events, run, ui

from app.core_connect import (
    AutoConnect,
    ConnectGoogle,
    ConnectGoogleError,
    GoogleIdSheetTable,
    TemplateTrashHistory,
    load_trash_history,
    save_trash_history,
)
from app.core_store import _normalize_id
from nicegui_ui.components.for_main import IdLookup
from nicegui_ui.components.general import SessionRegistry


def _session_connect(session) -> ConnectGoogle:
    """Return per-session ConnectGoogle; create on first use."""
    conn = getattr(session, 'connect_google', None)
    if conn is None:
        conn = ConnectGoogle()
        session.connect_google = conn
    return conn


def _verify_ok(session) -> bool:
    """Whether current template passed verify_toml."""
    report = session.verify_report
    if not report:
        return False
    return bool(report.get('ok', False))


def _selected_ids(session) -> set[str]:
    """UI checkbox state for import."""
    ids = getattr(session, 'google_selected_ids', None)
    if ids is None:
        session.google_selected_ids = set()
        return session.google_selected_ids
    return ids


def _row_id(table: GoogleIdSheetTable, row: dict[str, str]) -> str:
    """Primary ID cell for one table row."""
    if table.id_column and table.id_column in row:
        return str(row[table.id_column]).strip()
    return ''


def _trash_id_set(session) -> set[str]:
    """Trash IDs from templates/{id}/{id}.history.json."""
    template_id = session.template_id
    if not template_id:
        return set()
    history = load_trash_history(template_id)
    return set(history.trash_ids)


def _id_in_database(session, row_id: str) -> bool:
    """True when primary ID already exists in SQLite or Template/Session."""
    if not row_id:
        return False
        
    try:
        rid = _normalize_id(row_id)
    except ValueError:
        rid = row_id
        
    use_db = getattr(session, 'use_independent_db', True)
    
    if not use_db:
        if getattr(session, 't2db', None) and session.t2db.fetch_row_by_id(rid):
            return True
        pk_label = next((rule.Input_label for rule in getattr(session.cfg, 'field_rules', []) if getattr(rule, 'id', False)), None)
        if pk_label:
            for row in getattr(session, 'session_rows', []):
                if str(row.get(pk_label, '')).strip() == str(row_id).strip():
                    return True
        return False
        
    if not session.db:
        return False
    return session.db.query_by_id(rid) is not None


def _row_visible(session, row_id: str) -> bool:
    """Hide trash IDs and rows already persisted in DB."""
    if not row_id:
        return False
    if row_id in _trash_id_set(session):
        return False
    return not _id_in_database(session, row_id)


def _template_defaults(session) -> dict:
    """Shallow copy of template default field values."""
    defaults = getattr(session, 'template_defaults', None) or {}
    return dict(defaults)


def _load_google_row_into_draft(session, row_id: str) -> None:
    """Merge template defaults + Google row into session.draft."""
    if not IdLookup.apply_source_to_draft(session, row_id):
        return
    from nicegui_ui.pages.tab_input import render_dynamic_fields
    render_dynamic_fields.refresh()


def _refresh_input_tab() -> None:
    """Refresh input tab after Google selection / import."""
    from nicegui_ui.pages.tab_input import render_input_tab
    render_input_tab.refresh()


def _render_sheet_table(session, table: GoogleIdSheetTable) -> None:
    """Paint HTML5 <table class=\"t\"> from session.google_table payload."""
    selected = _selected_ids(session)
    with ui.element('table').classes('t'):
        with ui.element('thead'):
            with ui.element('tr'):
                with ui.element('th').classes('chkcol'):
                    ui.label('')
                for column in table.columns:
                    with ui.element('th'):
                        ui.label(column)
        with ui.element('tbody'):
            visible_count = 0
            for row in table.rows:
                row_id = _row_id(table, row)
                if not _row_visible(session, row_id):
                    continue
                visible_count += 1
                row_class = 'selected' if row_id and row_id in selected else ''
                with ui.element('tr').classes(row_class):
                    with ui.element('td').classes('chkcol'):
                        if row_id:
                            def on_toggle(event, rid: str = row_id) -> None:
                                ids = _selected_ids(session)
                                if event.value:
                                    ids.add(rid)
                                    _load_google_row_into_draft(session, rid)
                                else:
                                    ids.discard(rid)
                                render_google_tab.refresh()
                            ui.checkbox(
                                value=row_id in selected,
                                on_change=on_toggle,
                            ).props('dense')
                        else:
                            ui.label('')
                    for column in table.columns:
                        with ui.element('td'):
                            ui.label(str(row.get(column, '')))
            if visible_count == 0:
                with ui.element('tr'):
                    with ui.element('td').props(f'colspan={len(table.columns) + 1}'):
                        ui.label('无可见行（已入库或已屏蔽）').classes('text-gray-500')


def _render_empty_table() -> None:
    """Placeholder when not connected."""
    with ui.element('table').classes('t'):
        with ui.element('thead'):
            with ui.element('tr'):
                with ui.element('th').classes('chkcol'):
                    ui.label('')
                with ui.element('th'):
                    ui.label('—')
        with ui.element('tbody'):
            with ui.element('tr'):
                with ui.element('td').props('colspan=2'):
                    ui.label('尚未连接或无数据').classes('text-gray-500')


def _block_selected_rows(session) -> None:
    """Append checked visible primary IDs to templates/{id}/{id}.history.json trash_ids."""
    template_id = session.template_id
    if not template_id:
        ui.notify('请先选择模板', type='warning')
        return
    ids = list(_selected_ids(session))
    if not ids:
        ui.notify('请先勾选要屏蔽的行', type='warning')
        return
    # 仅屏蔽当前仍可见的行（未入库且未在 trash_ids 中）
    ids = [rid for rid in ids if _row_visible(session, rid)]
    if not ids:
        ui.notify('所选行已入库或已屏蔽', type='warning')
        return
    history = load_trash_history(template_id)
    existing = set(history.trash_ids)
    added = [rid for rid in ids if rid not in existing]
    if not added:
        ui.notify('所选 ID 已在屏蔽列表', type='info')
        return
    merged_trash = list(history.trash_ids) + added
    save_trash_history(
        TemplateTrashHistory(template_id, merged_trash, history.last_import),
    )
    session.google_selected_ids = set()
    ui.notify(f'已屏蔽 {len(added)} 行', type='positive')
    render_google_tab.refresh()


@ui.refreshable
def render_google_tab():
    """
    函数名: render_google_tab
    作用: Google 连接 Tab — 授权三按钮 + HTML5 主 ID 表（仅渲染，无 gspread 逻辑）
    输入:
        无
    输出:
        None
    """
    session = SessionRegistry.for_current()
    if not session.ui_provider:
        ui.label('请先从左侧选择有效的模板配置').classes('text-gray-500 italic p-4')
        return
    conn = _session_connect(session)
    client_ready = conn.has_oauth_client()
    with ui.element('div').classes('tab-scroll-container'):
        # 授权与连接
        with ui.element('div').classes('section'):
            ui.label('授权与连接').classes('section-title')
            with ui.element('div').classes('section-body'):
                async def handle_oauth_upload(event: events.UploadEventArguments) -> None:
                    """
                    函数名: handle_oauth_upload
                    作用: 选择授权文件 → 写入 credentials/oauth_client.json
                    """
                    try:
                        content = await event.file.read()
                        conn.save_oauth_client(content)
                        ui.notify('授权文件已保存', type='positive')
                        render_google_tab.refresh()
                    except Exception as exc:
                        ui.notify(f'保存失败: {exc}', type='negative')
                upload = ui.upload(
                    on_upload=handle_oauth_upload,
                    auto_upload=True,
                    max_files=1,
                ).props('accept=".json" no-thumbnails auto-hide-upload-progress').style(
                    'position:fixed;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden'
                )
                with ui.element('div').classes('form-row'):
                    ui.label('选择授权文件').classes('btn google').on(
                        'click',
                        lambda: upload.run_method('pickFiles'),
                    )
                    connect_cls = 'btn google primary' if client_ready else 'btn google primary disabled'
                    if client_ready:
                        async def handle_connect() -> None:
                            """
                            函数名: handle_connect
                            作用: authorize → AutoConnect.run → 刷新表
                            """
                            if not session.cfg:
                                ui.notify('当前无模板配置', type='warning')
                                return
                            try:
                                await run.io_bound(conn.authorize)
                                activator = AutoConnect(conn)
                                bundle = await run.io_bound(
                                    activator.run,
                                    session.cfg,
                                    verify_ok=_verify_ok(session),
                                )
                                AutoConnect.apply_bundle(session, bundle)
                                if bundle.status.connected:
                                    ui.notify('连接成功', type='positive')
                                elif bundle.status.error:
                                    ui.notify(bundle.status.error, type='negative')
                                else:
                                    ui.notify(bundle.status.status_text, type='warning')
                                render_google_tab.refresh()
                            except ConnectGoogleError as exc:
                                ui.notify(str(exc), type='negative')
                            except Exception as exc:
                                ui.notify(f'连接失败: {exc}', type='negative')
                        ui.label('连接').classes(connect_cls).on('click', handle_connect)
                    else:
                        ui.label('连接').classes(connect_cls)
                    def handle_delete() -> None:
                        """
                        函数名: handle_delete
                        作用: cancel_auth 并清空 session Google 载荷
                        """
                        conn.cancel_auth()
                        AutoConnect.apply_bundle(
                            session,
                            AutoConnect(conn).run(session.cfg, verify_ok=False),
                        )
                        ui.notify('已删除授权并断开连接', type='info')
                        render_google_tab.refresh()
                    delete_cls = 'btn google' if client_ready else 'btn google disabled'
                    if client_ready:
                        ui.label('删除').classes(delete_cls).on('click', handle_delete)
                    else:
                        ui.label('删除').classes(delete_cls)
                ui.label(
                    '选择授权文件后「连接」可用；模板激活且已授权时由 AutoConnect 自动连接。'
                ).classes('hint')
        # 主 ID 工作表
        with ui.element('div').classes('section'):
            ui.label('主 ID 工作表').classes('section-title')
            with ui.element('div').classes('section-body sheet-panel'):
                with ui.element('div').classes('sheet-table-scroll'):
                    table = getattr(session, 'google_table', None)
                    if table and table.rows is not None:
                        _render_sheet_table(session, table)
                    else:
                        _render_empty_table()
                with ui.element('div').classes('sheet-toolbar-bar'):
                    with ui.element('div').classes('toolbar-main'):
                        def handle_select_all() -> None:
                            """全选当前可见 ID 行。"""
                            current = getattr(session, 'google_table', None)
                            if not current:
                                return
                            ids: set[str] = set()
                            for row in current.rows:
                                rid = _row_id(current, row)
                                if rid and _row_visible(session, rid):
                                    ids.add(rid)
                            session.google_selected_ids = ids
                            if ids:
                                last_id = sorted(ids)[-1]
                                _load_google_row_into_draft(session, last_id)
                            render_google_tab.refresh()
                        def handle_deselect_all() -> None:
                            """取消全部勾选。"""
                            session.google_selected_ids = set()
                            render_google_tab.refresh()
                        def handle_import() -> None:
                            """
                            函数名: handle_import
                            作用: build_import_rows + template_defaults → persist_fields
                            """
                            if not getattr(session, 'google_op', None) or not session.google_connected:
                                ui.notify('请先连接 Google', type='warning')
                                return
                            ids = list(_selected_ids(session))
                            if not ids:
                                ui.notify('请先勾选要导入的行', type='warning')
                                return
                                
                            use_db = getattr(session, 'use_independent_db', True)
                            
                            if use_db and not session.ui_provider:
                                ui.notify('数据库未就绪', type='negative')
                                return
                            try:
                                defaults = _template_defaults(session)
                                rows = session.google_op.build_import_rows(ids)
                                for incoming in rows:
                                    merged = {**defaults, **incoming}
                                    if use_db:
                                        session.ui_provider.persist_fields(merged)
                                    session.session_rows.append(dict(merged))
                                if session.template_id:
                                    history = load_trash_history(session.template_id)
                                    history.last_import = datetime.now().isoformat()
                                    save_trash_history(history)
                                ui.notify(f'已导入 {len(rows)} 行', type='positive')
                                session.google_selected_ids = set()
                                
                                # switch to input tab
                                from nicegui import app
                                if hasattr(app.storage, 'user'):
                                    app.storage.user['active_tab'] = '输入'
                                ui.run_javascript("Array.from(document.querySelectorAll('.tabs .tab')).find(el => el.textContent === '输入')?.click();")
                                
                                _refresh_input_tab()
                                render_google_tab.refresh()
                            except Exception as exc:
                                ui.notify(f'导入失败: {exc}', type='negative')
                        ui.label('全选').classes('btn').on('click', handle_select_all)
                        ui.label('取消全选').classes('btn').on('click', handle_deselect_all)
                        ui.label('导入选中行').classes('btn google primary').on('click', handle_import)
                    ui.label('屏蔽所选数据').classes('btn toolbar-trash-anchor').on(
                        'click',
                        lambda: _block_selected_rows(session),
                    )
                ui.label(
                    '已入库行由 db.query_by_id 隐藏；屏蔽 ID 写入 history.json 后不再显示。'
                ).classes('hint')
