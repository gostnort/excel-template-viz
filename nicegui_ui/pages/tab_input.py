import base64
from pathlib import Path
from datetime import datetime
from typing import Any

from nicegui import ui

from nicegui_ui.components.for_main import IdLookup
from nicegui_ui.components.general import SessionRegistry, list_export_files
from nicegui_ui.components.ocr_menu import open_camera_dialog, run_ocr


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
    if 'instance_k' in row:
        normalized['instance_k'] = row['instance_k']
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


def _clear_session_row_selection(session) -> None:
    session.selected_instance_k = None
    session.selected_instance_indices.clear()


def _load_session_row_into_draft(session, row_k: int) -> None:
    session.selected_instance_k = row_k
    idx = next((i for i, r in enumerate(session.session_rows) if r.get('instance_k', i) == row_k), None)
    if idx is not None:
        session.draft = session.session_rows[idx].copy()
        session.draft.pop('_index', None)
        session.suppress_id_search = True
        
        # update formula_mask based on the selected row
        if getattr(session, 'session_masks', None) and idx < len(session.session_masks):
            session.formula_mask = session.session_masks[idx].copy()
            
        render_dynamic_fields.refresh()
        render_session_table.refresh()


@ui.refreshable
def render_session_table(session, labels: list[str]) -> None:
    """本次已录入：HTML5 表格 + 勾选列 + 行点击载入 draft。"""
    checked = session.selected_instance_indices
    
    def toggle_sort(session, column: str) -> None:
        if getattr(session, 'sort_column', None) == column:
            if getattr(session, 'sort_descending', False):
                session.sort_column = None
                session.sort_descending = False
            else:
                session.sort_descending = True
        else:
            session.sort_column = column
            session.sort_descending = False
        render_session_table.refresh()
        
    with ui.element('div').classes('flex-1 overflow-y-auto w-full mt-2'):
        with ui.element('table').classes('records w-full'):
            with ui.element('thead').classes('sticky top-0 bg-gray-200 z-10 shadow-sm'):
                with ui.element('tr'):
                    with ui.element('th').classes('chkcol'):
                        ui.label('')
                    if not session.use_independent_db:
                        with ui.element('th'):
                            move_dir = getattr(session.cfg.input_section, 'move_to', 'down')
                            header_lbl = '列号' if move_dir in ['left', 'right'] else '行号'
                            ui.label(header_lbl)
                    for lbl in labels:
                        with ui.element('th').classes('cursor-pointer select-none').on('click', lambda _e=None, l=lbl: toggle_sort(session, l)):
                            suffix = " ▲" if getattr(session, 'sort_column', None) == lbl and not getattr(session, 'sort_descending', False) else (" ▼" if getattr(session, 'sort_column', None) == lbl else "")
                            ui.label(lbl + suffix)
            with ui.element('tbody'):
                if not session.session_rows:
                    with ui.element('tr'):
                        with ui.element('td').props(f'colspan={len(labels) + 2 if not session.use_independent_db else len(labels) + 1}'):
                            ui.label('（尚无录入行）').classes('text-gray-500')
                            
                displayed_rows = list(enumerate(session.session_rows))
                if getattr(session, 'sort_column', None):
                    col = session.sort_column
                    displayed_rows.sort(
                        key=lambda item: str(item[1].get(col, '') or ''),
                        reverse=getattr(session, 'sort_descending', False)
                    )
                    
                for idx, row in displayed_rows:
                    row_k = row.get('instance_k', idx)
                    row_class = 'selected' if session.selected_instance_k == row_k else ''
                    with ui.element('tr').classes(row_class):
                        with ui.element('td').classes('chkcol'):
                            def on_toggle(event, r_k: int = row_k) -> None:
                                if event.value:
                                    session.selected_instance_indices.add(r_k)
                                else:
                                    session.selected_instance_indices.discard(r_k)
                                render_session_table.refresh()
                            ui.checkbox(
                                value=row_k in checked,
                                on_change=on_toggle,
                            ).props('dense')
                        if not session.use_independent_db:
                            with ui.element('td').on('click', lambda _e=None, r_k=row_k: _load_session_row_into_draft(session, r_k)):
                                ui.label(str(row_k))
                        for lbl in labels:
                            with ui.element('td').on(
                                'click',
                                lambda _e=None, r_k=row_k: _load_session_row_into_draft(session, r_k),
                            ):
                                val_str = str(row.get(lbl, '') or '')
                                if val_str.endswith(' 00:00:00'):
                                    val_str = val_str.replace(' 00:00:00', '')
                                ui.label(val_str).classes('whitespace-pre-wrap')
                                
    
    if not session.use_independent_db and getattr(session, 'loaded_offset_k', 0) > 0:
        def load_next_batch():
            offset_k = max(0, session.loaded_offset_k - 50)
            limit = session.loaded_offset_k - offset_k
            session.loaded_offset_k = offset_k
            instances, masks = session.writer.read_instances(
                session.template_path, limit=limit, offset_k=offset_k + limit - 1, reverse=True
            )
            session.session_rows.extend(instances)
            session.session_masks.extend(masks)
            render_session_table.refresh()
            
        with ui.row().classes('justify-center w-full my-2'):
            ui.button(f'加载更多 (剩余 {session.loaded_offset_k} 行)', on_click=load_next_batch).props('flat dense')


def handle_delete_checked_session_rows(session) -> None:
    """删除勾选的 session_rows 行（含空行/部分填写行）；仅内存列表，不写 DB。"""
    keys = list(session.selected_instance_indices)
    if not keys:
        ui.notify('请先勾选要删除的行', type='warning')
        return
    deleted = 0
    # map keys back to indices to pop
    indices_to_delete = []
    for idx, row in enumerate(session.session_rows):
        if row.get('instance_k', idx) in keys:
            indices_to_delete.append(idx)
            
    for idx in sorted(indices_to_delete, reverse=True):
        session.session_rows.pop(idx)
        if getattr(session, 'session_masks', None) and idx < len(session.session_masks):
            session.session_masks.pop(idx)
        deleted += 1
        
    _clear_session_row_selection(session)
    session.current_instance_index = len(session.session_rows)
    _reset_draft_after_session_change(session)
    render_input_tab.refresh()
    ui.notify(f'已删除 {deleted} 行', type='positive')


def _apply_loaded_rows(session, rows: list[dict], masks: list[dict], replace: bool) -> int:
    """
    将装载的行写入 session_rows；返回实际写入行数。
    replace=True 替换列表，False 追加；总量不超过 input_capacity。
    """
    labels = session.ui_provider.get_labels()
    cleaned = [_normalize_row_for_session(row, labels) for row in rows]
    if replace:
        allowed = cleaned[:session.input_capacity]
        allowed_masks = masks[:session.input_capacity]
        session.session_rows = allowed
        session.session_masks = allowed_masks
    else:
        remaining = max(0, session.input_capacity - len(session.session_rows))
        session.session_rows.extend(cleaned[:remaining])
        if hasattr(session, 'session_masks'):
            session.session_masks.extend(masks[:remaining])
        allowed = cleaned[:remaining]
    session.selected_instance_k = None
    session.selected_instance_indices.clear()
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
                    rows, masks = session.writer.read_instances(path)
                except Exception as exc:
                    ui.notify(f'读取失败: {exc}', type='negative')
                    return
                if not rows:
                    ui.notify('文件中未读到有效数据行', type='warning')
                    return
                replace = merge_mode is None or merge_mode.value == 'replace'
                loaded_count = _apply_loaded_rows(session, rows, masks, replace=replace)
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
    if hasattr(session, 'session_masks'):
        session.session_masks.clear()
    _clear_session_row_selection(session)
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
    
    with ui.element('div').classes('tab-flex-container'):
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
        ghost = ui.textarea().classes('ghost-input').props('borderless autogrow hide-bottom-space rows="1"')
        ghost.on('blur', on_ghost_blur)
        with ghost:
            with ui.context_menu():
                from nicegui_ui.components.ocr_menu import open_camera_dialog, run_ocr
                ui.menu_item('拍照', on_click=lambda: open_camera_dialog(session, '顶部粘贴'))
                ui.menu_item('OCR', on_click=lambda: run_ocr(session, '顶部粘贴', ghost))
        # 动态字段区（默认 3 列 field-grid）
        with ui.element('div').classes('field-grid shrink-0'):
            render_dynamic_fields(session, labels)
        
        # 本次已录入表格 / 模板已存数据
        with ui.element('div').classes('session-list flex-1 flex flex-col min-h-[150px] overflow-hidden'):
            if session.use_independent_db:
                ui.label('本次已录入（勾选后删除；点击数据格载入上方编辑）').classes('title shrink-0')
                ui.label(f'当前 {session.current_instance_index + 1} / 容量 {session.input_capacity}（到达容量上限时不再清空输入）').classes('ghost-note shrink-0')
            else:
                ui.label('模板已存数据（勾选后删除清空行；点击数据格载入上方编辑）').classes('title shrink-0')
                ui.label(f'当前将录入至第 {session.current_instance_index + 1} 行').classes('ghost-note shrink-0')
            render_session_table(session, labels)
            with ui.element('div').classes('list-btns shrink-0 mt-2'):
                with ui.element('div').classes('list-btns-start'):
                    ui.label('装载文件').classes('btn excel').on('click', lambda: open_load_file_dialog(session))
                with ui.element('div').classes('list-btns-end'):
                    ui.label('清空').classes('btn').on('click', lambda: handle_clear_session(session))
                    ui.label('删除选中').classes('btn').on(
                        'click',
                        lambda: handle_delete_checked_session_rows(session),
                    )

        ui.element('hr').classes('sep shrink-0')

        # 另存为 / 下一行
        with ui.element('div').classes('toolbar-row shrink-0'):
            save_as_cls = 'btn excel'
            next_row_cls = 'btn db'
            validation_ok = not (session.verify_report and not session.verify_report.get('ok', False))
            
            if not validation_ok:
                save_as_cls += ' disabled'
                next_row_cls += ' disabled'
                
            btn_save = ui.label('另存为').classes(save_as_cls)
            if validation_ok:
                btn_save.on('click', lambda: handle_save_as(session))
                
            btn_next = ui.label('下一行').classes(next_row_cls)
            if validation_ok:
                btn_next.on('click', lambda: handle_next_row(session))
                
        ui.element('div').classes('w-full shrink-0').style('height:1px; background:#000; margin: 10px 0;')

        # 打印文件 + 打印区域 + 打印（紧挨）
        with ui.element('div').classes('shrink-0'):
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
                
                use_db = getattr(session, 'use_independent_db', True)
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
                        ui.notify(f'已加载外部数据 ID {val}', type='info')
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
            
            with ui.row().classes('w-full no-wrap items-start gap-1 p-0 m-0'):
                inp = ui.textarea(
                    value=str(session.draft.get(lbl, '') or ''),
                    on_change=create_on_change(lbl),
                ).classes('input-box flex-1').props('autogrow dense borderless hide-bottom-space rows="1"')
                if getattr(session, 'formula_mask', {}).get(lbl):
                    inp.props('readonly')
                if is_pk:
                    inp.on('blur', create_on_blur(lbl))
                with inp:
                    with ui.context_menu():
                        ui.menu_item('拍照', on_click=lambda l=lbl: open_camera_dialog(session, l))
                        ui.menu_item('OCR', on_click=lambda l=lbl: run_ocr(session, l, inp))
                
                # 移动端菜单按钮
                btn = ui.button('···').classes('mobile-menu-btn p-0 m-0 min-w-[36px] min-h-[36px]').props('flat dense')
                with btn:
                    with ui.menu():
                        ui.menu_item('拍照', on_click=lambda l=lbl: open_camera_dialog(session, l))
                        ui.menu_item('OCR', on_click=lambda l=lbl: run_ocr(session, l, inp))

def handle_next_row(session):
    use_db = getattr(session, 'use_independent_db', True)
    
    if use_db and session.current_instance_index >= session.input_capacity:
        ui.notify("容量已满，无法录入下一行", type='warning')
        return
        
    if use_db:
        record_id = session.ui_provider.persist_fields(session.draft)
        
        if getattr(session, 'field_images', None):
            for label, img_data in list(session.field_images.items()):
                res = session.db.save_image(
                    cfg=session.cfg,
                    template_id=session.template_id,
                    record_id=record_id,
                    input_label=label,
                    image_bytes=img_data['bytes'],
                    mime=img_data['mime']
                )
                if res.get('ok'):
                    image_id = res['image_id']
                    ocr_text = img_data.get('ocr_text')
                    ocr_status = img_data.get('ocr_status')
                    if ocr_text or ocr_status:
                        session.db.update_image_ocr(
                            image_id=image_id,
                            ocr_text=ocr_text,
                            ocr_status=ocr_status
                        )
                del session.field_images[label]
                
        row_copy = session.draft.copy()
        row_copy.pop('_index', None)
        
        if getattr(session, 'selected_instance_k', None) is not None:
            idx = next((i for i, r in enumerate(session.session_rows) if r.get('instance_k', i) == session.selected_instance_k), None)
            if idx is not None:
                session.session_rows[idx] = row_copy
            session.selected_instance_k = None
            session.current_instance_index = len(session.session_rows)
        else:
            if session.current_instance_index < len(session.session_rows):
                # When reading bottom-up, session_rows[0] is the newest.
                # However, for independent DB, session_rows are just "what we entered this session"
                session.session_rows.insert(0, row_copy)
            else:
                session.session_rows.insert(0, row_copy)
            session.current_instance_index += 1
            
        session.draft.clear()
        if getattr(session, 'template_defaults', None):
            session.draft.update(session.template_defaults)
    else:
        if getattr(session, 'field_images', None):
            session.field_images.clear()
            
        row_copy = session.draft.copy()
        row_copy.pop('_index', None)
        k = session.current_instance_index
        try:
            session.writer.write_back(session.template_path, session.template_path, row_copy, instance_k=k)
            from nicegui_ui.components.for_main import ForMain
            ForMain.load_template(session.template_id, str(session.template_path))
            from nicegui_ui.pages.tab_db import render_db_tab
            render_db_tab.refresh()
        except Exception as e:
            ui.notify(f"写入模板失败: {str(e)}", type='negative')
            return
            
    render_input_tab.refresh()
    ui.notify("已记录", type='positive')

def handle_save_as(session):
    if not session.session_rows and not any(str(v).strip() for v in session.draft.values() if v is not None):
        ui.notify("没有数据可以保存", type='warning')
        return
        
    use_db = getattr(session, 'use_independent_db', True)
        
    rows_to_write = session.session_rows.copy()
    for r in rows_to_write:
        r.pop('_index', None)
        
    is_draft_active = any(str(v).strip() for v in session.draft.values() if v is not None)
    if is_draft_active and getattr(session, 'selected_instance_k', None) is None:
        d = session.draft.copy()
        d.pop('_index', None)
        if not use_db:
            d['instance_k'] = session.current_instance_index
        rows_to_write.append(d)
        
    from app.core_store import _read_active_suffix_token
    suffix = _read_active_suffix_token(session.template_id) or "0000"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{session.template_id}_{suffix}_{ts}.xlsx"
    export_dir = ensure_exports_dir(session.template_id)
    out_path = export_dir / filename
    
    try:
        if use_db:
            for row in rows_to_write:
                # We skip persisting to DB here for draft, handle_next_row already does it,
                # but if draft is active it wasn't persisted yet, let's persist it?
                # Actually, in existing code it persists rows_to_write... wait, they are already persisted?
                # The existing code did persist_fields(row). It's fine.
                record_id = session.ui_provider.persist_fields(row)
                if row == rows_to_write[-1] and getattr(session, 'field_images', None):
                    for label, img_data in list(session.field_images.items()):
                        res = session.db.save_image(
                            cfg=session.cfg, template_id=session.template_id,
                            record_id=record_id, input_label=label,
                            image_bytes=img_data['bytes'], mime=img_data['mime']
                        )
                        if res.get('ok'):
                            image_id = res['image_id']
                            ocr_text, ocr_status = img_data.get('ocr_text'), img_data.get('ocr_status')
                            if ocr_text or ocr_status:
                                session.db.update_image_ocr(image_id, ocr_text, ocr_status)
                    session.field_images.clear()
        else:
            if getattr(session, 'field_images', None):
                session.field_images.clear()
            # In template mode, we just write the whole dataset into the export file.
            # Write back to template first for the draft
            if is_draft_active and getattr(session, 'selected_instance_k', None) is None:
                d = session.draft.copy()
                d.pop('_index', None)
                session.writer.write_back(session.template_path, session.template_path, d, instance_k=session.current_instance_index)
                from nicegui_ui.components.for_main import ForMain
                ForMain.load_template(session.template_id, str(session.template_path))
                # Update rows_to_write from the fresh session_rows
                rows_to_write = session.session_rows.copy()
                
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
        
    import os
    if os.name == 'nt':
        try:
            os.startfile(str(path), 'print')
            ui.notify('已发送至本地打印机', type='positive')
        except Exception as e:
            ui.notify(f'打印失败: {str(e)}', type='negative')
    else:
        ui.notify('自动打印仅支持 Windows 系统', type='warning')
