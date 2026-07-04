import base64
from pathlib import Path
from datetime import datetime
from typing import Any

from nicegui import ui

from nicegui_ui.components.for_main import IdLookup
from nicegui_ui.components.general import SessionRegistry, list_export_files


def ensure_exports_dir(template_id: str) -> Path:
    export_dir = Path('exports') / template_id
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def _resolve_print_areas(session, export_path: Path | None) -> list[dict[str, Any]]:
    if not session.writer or not export_path or not export_path.is_file():
        return []
    return session.writer.get_print_areas(export_path)


def _print_area_labels(areas: list[dict[str, Any]]) -> list[str]:
    if not areas:
        return ['（无打印区）']
    return [str(item.get('label') or item.get('area') or '打印区') for item in areas]


def _find_print_area_entry(areas: list[dict[str, Any]], selected_label: str) -> dict[str, Any] | None:
    for item in areas:
        if item.get('label') == selected_label:
            return item
    return None


def _open_print_preview(png_bytes: bytes, download_name: str) -> None:
    """内存 PNG → 预览对话框；浏览器 window.print 或 PNG 下载（不落盘）。"""
    data_url = 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')
    with ui.dialog() as dialog, ui.card().classes('excel-print-sheet w-full max-w-5xl'):
        ui.label('打印预览').classes('text-h6 no-print')
        ui.image(data_url).classes('w-full excel-print-image')
        with ui.row().classes('w-full justify-end gap-2 mt-2 no-print'):
            ui.label('关闭').classes('btn').on('click', dialog.close)
            ui.label('下载 PNG').classes('btn').on('click', lambda: ui.download(png_bytes, download_name))
            ui.label('打印').classes('btn excel').on('click', lambda: ui.run_javascript('window.print()'))
    dialog.open()


def _normalize_row_for_session(row: dict, labels: list[str]) -> dict[str, object]:
    """将 read_instances 的一行对齐到当前模板 Input_label 键。"""
    normalized: dict[str, object] = {}
    for lbl in labels:
        val = row.get(lbl)
        if val is None:
            normalized[lbl] = ''
        else:
            normalized[lbl] = val
    return normalized


def _reset_draft_after_session_change(session) -> None:
    session.draft.clear()
    if getattr(session, 'template_defaults', None):
        session.draft.update(session.template_defaults)


def _apply_loaded_rows(session, rows: list[dict], replace: bool) -> int:
    """
    将装载的行写入 session_rows；返回实际写入行数。
    replace=True 替换列表，False 追加；总量不超过 input_capacity。
    """
    labels = session.ui_provider.get_labels()
    cleaned = [_normalize_row_for_session(row, labels) for row in rows]
    if replace:
        allowed = cleaned[:session.input_capacity]
        session.session_rows = allowed
    else:
        remaining = max(0, session.input_capacity - len(session.session_rows))
        session.session_rows.extend(cleaned[:remaining])
        allowed = cleaned[:remaining]
    session.selected_session_index = None
    session.current_instance_index = len(session.session_rows)
    _reset_draft_after_session_change(session)
    return len(allowed)


def open_load_file_dialog(session) -> None:
    """弹出装载文件对话框：从 exports 选择 xlsx。"""
    if not session.writer:
        ui.notify('当前模板未就绪，无法装载文件', type='warning')
        return
    template_id = session.template_id or ''
    export_files = list_export_files(template_id)
    name_to_path = {p.name: p for p in export_files}
    with ui.dialog() as dialog, ui.card().classes('gap-2'):
        ui.label('装载文件').classes('text-lg font-bold')
        ui.label('从已导出文件中选择').classes('ghost-note')
        file_select = ui.select(
            options=list(name_to_path.keys()) if name_to_path else ['（无导出文件）'],
            value=next(iter(name_to_path), '（无导出文件）'),
            label='导出文件',
        ).classes('w-full').props('dense')
        if not name_to_path:
            file_select.props('disable')
        merge_mode = None
        if session.session_rows:
            merge_mode = ui.radio(
                {'replace': '替换当前列表', 'append': '追加到当前列表'},
                value='replace',
            ).props('inline')
        with ui.row().classes('w-full gap-2'):
            def on_confirm() -> None:
                selected_name = file_select.value
                if not selected_name or selected_name == '（无导出文件）':
                    ui.notify('请选择导出文件', type='warning')
                    return
                path = name_to_path.get(selected_name)
                if path is None or not path.is_file():
                    ui.notify('文件不存在', type='negative')
                    return
                try:
                    rows = session.writer.read_instances(path)
                except Exception as exc:
                    ui.notify(f'读取失败: {exc}', type='negative')
                    return
                if not rows:
                    ui.notify('文件中未读到有效数据行', type='warning')
                    return
                replace = merge_mode is None or merge_mode.value == 'replace'
                loaded_count = _apply_loaded_rows(session, rows, replace=replace)
                dialog.close()
                render_input_tab.refresh()
                if loaded_count < len(rows):
                    ui.notify(
                        f'已装载 {loaded_count} 行（已达容量 {session.input_capacity}，部分行未载入）',
                        type='warning',
                    )
                else:
                    action = '替换' if replace else '追加'
                    ui.notify(f'已{action}装载 {loaded_count} 行', type='positive')
            ui.label('装载').classes('btn excel primary').on('click', on_confirm)
            ui.label('取消').classes('btn').on('click', dialog.close)
    dialog.open()


def handle_clear_session(session) -> None:
    """清空本次已录入列表并重置草稿。"""
    if not session.session_rows:
        ui.notify('列表已为空', type='info')
        return
    session.session_rows.clear()
    session.selected_session_index = None
    session.current_instance_index = 0
    _reset_draft_after_session_change(session)
    render_input_tab.refresh()
    ui.notify('已清空本次已录入', type='positive')


@ui.refreshable
def render_print_row(session) -> None:
    # 打印文件 → 打印区域 → 打印（顺序与 HTML 蓝本一致）
    export_files = list_export_files(session.template_id or '')
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
    with ui.element('div').classes('print-row'):
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
                label='打印文件',
                on_change=on_file_change,
            ).classes('dropdown print-file').props('dense borderless hide-bottom-space')
        else:
            ui.select(
                options=['（空）'],
                value='（空）',
                label='打印文件',
            ).classes('dropdown print-file').props('dense borderless disable hide-bottom-space')
        selected_area = ui.select(
            print_labels,
            value=print_labels[0],
            label='打印区域',
        ).classes('dropdown narrow').props('dense borderless hide-bottom-space')
        ui.label('打印').classes('btn excel').on('click', lambda: handle_print(session, selected_area.value, selected_path))

@ui.refreshable
def render_input_tab():
    session = SessionRegistry.for_current()
    
    if not session.template_id:
        ui.label('请从左侧选择模板。').classes('text-red text-lg font-bold')
        return
    if session.verify_report and not session.verify_report.get('ok', False):
        ui.label('配置校验未通过，部分功能可能不可用。').classes('text-orange text-sm mb-2')

    ui_provider = session.ui_provider
    if not ui_provider:
        ui.label('引擎未就绪，请打开 [输入配置] 检查 TOML。').classes('text-red')
        return
        
    labels = ui_provider.get_labels()
    
    with ui.element('div'):
        # 幽灵输入框
        def on_ghost_blur(event) -> None:
            raw = event.sender.value or ''
            if not str(raw).strip():
                return
            try:
                incoming = ui_provider.record_from_textbox(str(raw))
                session.draft.update(incoming)
                session.suppress_id_search = True
                event.sender.value = ''
                render_dynamic_fields.refresh()
                ui.notify('已从粘贴板解析数据', type='positive')
            except Exception as ex:
                ui.notify(f'解析失败: {str(ex)}', type='negative')
        ghost = ui.input(placeholder='粘贴整行数据…').classes('ghost-input').props('borderless dense hide-bottom-space')
        ghost.on('blur', on_ghost_blur)
        # 动态字段区（默认 3 列 field-grid）
        with ui.element('div').classes('field-grid'):
            render_dynamic_fields(session, labels)
        
        # 本次已录入表格
        with ui.element('div').classes('session-list'):
            ui.label(f'当前 {session.current_instance_index + 1} / 容量 {session.input_capacity}（容量 = writer.max_instance_count(模板)，到达上界时不再清空输入）').classes('ghost-note')
            columns = [{'name': lbl, 'label': lbl, 'field': lbl} for lbl in labels]
            for i, row in enumerate(session.session_rows):
                row['_index'] = i
                
            def on_table_select(event) -> None:
                if event.selection:
                    sel = event.selection[0]
                    idx = sel['_index']
                    session.selected_session_index = idx
                    session.draft = session.session_rows[idx].copy()
                    session.draft.pop('_index', None)
                    session.suppress_id_search = True
                    render_dynamic_fields.refresh()
                else:
                    session.selected_session_index = None
                    session.draft.clear()
                    if getattr(session, 'template_defaults', None):
                        session.draft.update(session.template_defaults)
                    render_dynamic_fields.refresh()
            table = ui.table(
                columns=columns,
                rows=session.session_rows,
                row_key='_index',
                selection='single',
            ).classes('w-full').style('border-radius: 0; box-shadow: none; border: 1px solid #000;')
            table.on_select(on_table_select)
            
            with ui.element('div').classes('list-btns'):
                with ui.element('div').classes('list-btns-start'):
                    ui.label('装载文件').classes('btn excel').on('click', lambda: open_load_file_dialog(session))
                with ui.element('div').classes('list-btns-end'):
                    ui.label('清空').classes('btn').on('click', lambda: handle_clear_session(session))
                    def on_delete_selected():
                        if session.selected_session_index is not None:
                            session.session_rows.pop(session.selected_session_index)
                            session.selected_session_index = None
                            session.current_instance_index = len(session.session_rows)
                            render_input_tab.refresh()
                        else:
                            ui.notify('请先选择要删除的行', type='warning')
                    ui.label('单个删除').classes('btn').on('click', on_delete_selected)

        ui.element('hr').classes('sep')

        # 另存为 / 下一行
        with ui.element('div').classes('toolbar-row'):
            ui.label('另存为').classes('btn excel').on('click', lambda: handle_save_as(session))
            ui.label('下一行').classes('btn db').on('click', lambda: handle_next_row(session))
        ui.element('div').classes('w-full').style('height:1px; background:#000; margin: 10px 0;')

        # 打印文件 + 打印区域 + 打印（紧挨）
        render_print_row(session)

@ui.refreshable
def render_dynamic_fields(session, labels: list[str]):
    for lbl in labels:
        is_pk = False
        for rule in session.cfg.field_rules:
            if rule.Input_label == lbl and getattr(rule, 'id', False):
                is_pk = True
                break
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
                sender_val = getattr(event.sender, 'value', None)
                val = sender_val if sender_val not in (None, '') else session.draft.get(label)
                if not val or not str(val).strip():
                    return
                val = str(val).strip()
                session.draft[label] = val
                from app.core_store import _normalize_id
                try:
                    rid = _normalize_id(val)
                except ValueError:
                    rid = None
                existing = session.db.query_by_id(rid) if rid is not None else None
                if existing:
                    with ui.dialog() as dialog, ui.card():
                        ui.label(f'发现已存在的记录 (ID: {val})')
                        def refetch_from_source() -> None:
                            dialog.close()
                            if IdLookup.apply_source_to_draft(session, val):
                                render_dynamic_fields.refresh()
                                ui.notify(f'已从数据源重新读取 ID {val}', type='info')
                            else:
                                ui.notify(f'数据源中未找到 ID {val}', type='warning')
                        with ui.row().classes('gap-2'):
                            ui.label('从数据源重新读取').classes('btn').on('click', refetch_from_source)
                            ui.label('从数据库读取').classes('btn').on(
                                'click',
                                lambda: load_and_close(dialog, existing),
                            )
                    dialog.open()
                else:
                    if IdLookup.apply_source_to_draft(session, val):
                        render_dynamic_fields.refresh()
                        ui.notify(f'已自动拉取 ID {val} 的数据', type='info')
                    elif not getattr(session, 'google_connected', False):
                        ui.notify('尚未连接 Google Sheet，无法按主键查源', type='warning')
            return on_id_blur
        def load_and_close(dialog, existing_row) -> None:
            dialog.close()
            session.draft.update(existing_row)
            session.suppress_id_search = True
            render_dynamic_fields.refresh()
        with ui.element('div').classes('field-cell id-field' if is_pk else 'field-cell'):
            ui.label(lbl).classes('field-label primary' if is_pk else 'field-label')
            inp = ui.input(
                value=str(session.draft.get(lbl, '') or ''),
                on_change=create_on_change(lbl),
            ).classes('input-box').props('dense borderless hide-bottom-space')
            if is_pk:
                inp.on('blur', create_on_blur(lbl))

def handle_next_row(session):
    if session.current_instance_index >= session.input_capacity:
        ui.notify("容量已满，无法录入下一行", type='warning')
        return
        
    session.ui_provider.persist_fields(session.draft)
    
    row_copy = session.draft.copy()
    row_copy.pop('_index', None)
    
    if session.selected_session_index is not None:
        session.session_rows[session.selected_session_index] = row_copy
        session.selected_session_index = None
        session.current_instance_index = len(session.session_rows)
    else:
        if session.current_instance_index < len(session.session_rows):
            session.session_rows[session.current_instance_index] = row_copy
        else:
            session.session_rows.append(row_copy)
        session.current_instance_index += 1
        
    session.draft.clear()
    if getattr(session, 'template_defaults', None):
        session.draft.update(session.template_defaults)
    
    render_input_tab.refresh()
    ui.notify("已记录", type='positive')

def handle_save_as(session):
    if not session.session_rows and not any(str(v).strip() for v in session.draft.values() if v is not None):
        ui.notify("没有数据可以保存", type='warning')
        return
        
    rows_to_write = session.session_rows.copy()
    for r in rows_to_write:
        r.pop('_index', None)
        
    if any(str(v).strip() for v in session.draft.values() if v is not None) and session.selected_session_index is None:
        d = session.draft.copy()
        d.pop('_index', None)
        rows_to_write.append(d)
        
    from app.core_store import _read_active_suffix_token
    suffix = _read_active_suffix_token(session.template_id) or "0000"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{session.template_id}_{suffix}_{ts}.xlsx"
    export_dir = ensure_exports_dir(session.template_id)
    out_path = export_dir / filename
    
    try:
        for row in rows_to_write:
            session.ui_provider.persist_fields(row)
        session.writer.write_back(session.template_path, out_path, rows_to_write, instance_k=0)
        session.exported_files.append(out_path)
        session.last_export_path = out_path
        ui.notify(f"成功另存为: {filename}", type='positive')
        render_input_tab.refresh()
        from nicegui_ui.pages.tab_db import render_db_tab
        render_db_tab.refresh()
    except Exception as e:
        ui.notify(f"保存失败: {str(e)}", type='negative')

def handle_print(session, selected_label, export_path: Path | None = None) -> None:
    path = Path(export_path) if export_path else None
    if path is None and session.last_export_path:
        path = Path(session.last_export_path)
    if path is None or not path.is_file():
        ui.notify('请先成功执行【另存为】', type='warning')
        return
    areas = _resolve_print_areas(session, path)
    area_entry = _find_print_area_entry(areas, selected_label)
    if area_entry is None or not area_entry.get('area') or not area_entry.get('sheet'):
        ui.notify('请选择有效打印区域', type='warning')
        return
    if not session.writer:
        ui.notify('模板引擎未就绪', type='warning')
        return
    try:
        png_bytes = session.writer.render_print_area_png_bytes(
            path,
            str(area_entry['sheet']),
            str(area_entry['area']),
        )
    except Exception as exc:
        ui.notify(f'渲染打印区失败: {exc}', type='negative')
        return
    _open_print_preview(png_bytes, f'{path.stem}_print.png')
