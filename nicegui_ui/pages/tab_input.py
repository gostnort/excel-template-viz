from nicegui import ui
from nicegui_ui.components.session import SessionRegistry
import os

def ensure_exports_dir(template_id: str):
    p = os.path.join('exports', template_id)
    os.makedirs(p, exist_ok=True)
    return p

@ui.refreshable
def render_input_tab():
    session = SessionRegistry.for_current()
    
    if not session.verify_report or not session.verify_report.get('ok', False):
        ui.label('请先选择有效模板并确保配置校验通过。').classes('text-red text-lg font-bold')
        return

    ui_provider = session.ui_provider
    if not ui_provider:
        return
        
    labels = ui_provider.get_labels()
    
    with ui.element('div'):
        # 幽灵输入框
        def on_ghost_blur(e):
            raw = e.sender.value
            if not raw.strip(): return
            try:
                incoming = ui_provider.record_from_textbox(raw)
                session.draft.update(incoming)
                session.suppress_id_search = True
                e.sender.value = "" # 清空
                render_dynamic_fields.refresh()
                ui.notify("已从粘贴板解析数据", type='positive')
            except Exception as ex:
                ui.notify(f"解析失败: {str(ex)}", type='negative')

        ui.element('input').classes('ghost-input').props('placeholder="粘贴整行数据..."').on('blur', on_ghost_blur)
        ui.label('隐藏样式输入框：切换焦点后按分隔符拆分，自动填入下方各项').classes('ghost-note')
        
        # 动态字段区
        render_dynamic_fields(session, labels)
        
        # 本次已录入表格
        with ui.element('div').classes('session-list'):
            ui.label(f'当前 {session.current_instance_index + 1} / 容量 {session.input_capacity}（容量 = writer.max_instance_count(模板)，到达上界时不再清空输入）').classes('ghost-note')
            columns = [{'name': lbl, 'label': lbl, 'field': lbl} for lbl in labels]
            for i, row in enumerate(session.session_rows):
                row['_index'] = i
                
            def on_table_select(e):
                if e.selection:
                    sel = e.selection[0]
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

            # We use NiceGUI's ui.table but apply custom classes if needed. 
            # Or we can use q-table but strip its shadow.
            table = ui.table(columns=columns, rows=session.session_rows, row_key='_index', selection='single').classes('w-full').style('border-radius: 0; box-shadow: none; border: 1px solid #000;')
            table.on('selection', on_table_select)
            
            with ui.element('div').classes('list-btns'):
                ui.label('清空').classes('btn')  # Mock btn
                
                def on_delete_selected():
                    if session.selected_session_index is not None:
                        session.session_rows.pop(session.selected_session_index)
                        session.selected_session_index = None
                        session.current_instance_index = len(session.session_rows)
                        render_input_tab.refresh()
                delete_btn = ui.label('删除').classes('btn').on('click', on_delete_selected)

        ui.element('hr').classes('sep')

        # 另存为 / 下一行
        with ui.element('div').classes('toolbar-row'):
            ui.label('另存为').classes('btn').on('click', lambda: handle_save_as(session))
            ui.label('下一行').classes('btn').on('click', lambda: handle_next_row(session))
        ui.element('div').classes('w-full').style('height:1px; background:#000; margin: 10px 0;')

        # 打印文件 + 打印区域 + 打印（紧挨）
        with ui.element('div').classes('print-row'):
            print_areas = session.writer.get_print_areas(session.last_export_path) if session.writer and session.last_export_path and os.path.exists(session.last_export_path) else ['默认打印区']
            if not print_areas:
                print_areas = ['默认打印区']
                
            selected_area = ui.select(print_areas, value=print_areas[0], label='').classes('dropdown narrow').props('dense borderless')
            # 打印文件
            ui.label(f"打印文件 ▼  {os.path.basename(session.last_export_path).classes('dropdown') if session.last_export_path else '（空）'}")
            ui.label('打印').classes('btn').on('click', lambda: handle_print(session, selected_area.value))

@ui.refreshable
def render_dynamic_fields(session, labels: list[str]):
    for lbl in labels:
        is_pk = False
        for rule in session.cfg.field_rules:
            if rule.Input_label == lbl and getattr(rule, 'id', False):
                is_pk = True
                break
                
        def create_on_change(label):
            def on_change(e):
                session.draft[label] = e.sender.value
            return on_change

        def create_on_blur(label):
            def on_id_blur(e):
                if session.suppress_id_search:
                    session.suppress_id_search = False
                    return
                
                val = e.sender.value
                if not val:
                    return
                
                from app.services.core_store import _normalize_id
                try:
                    rid = _normalize_id(val)
                except ValueError:
                    return
                    
                existing = session.db.query_by_id(rid)
                if existing:
                    with ui.dialog() as dialog, ui.card():
                        ui.label(f"发现已存在的记录 (ID: {rid})")
                        with ui.row():
                            ui.button("从数据源重新读取", on_click=lambda: dialog.close()) # placeholder
                            ui.button("从数据库读取", on_click=lambda: load_and_close(dialog, existing))
                    dialog.open()
                else:
                    fetched = session.t2db.fetch_row_by_id(rid)
                    if fetched:
                        session.draft.update(fetched)
                        session.suppress_id_search = True
                        render_dynamic_fields.refresh()
                        ui.notify(f"已自动拉取 ID {rid} 的数据", type='info')
                        
            return on_id_blur
            
        def load_and_close(dialog, existing_row):
            dialog.close()
            session.draft.update(existing_row)
            session.suppress_id_search = True
            render_dynamic_fields.refresh()

        with ui.element('div').classes('field-row'):
            ui.label(lbl).classes('field-label primary' if is_pk else 'field-label')
            inp = ui.element('input').classes('input-box').props(f'value="{session.draft.get(lbl, "")}"').on('input', create_on_change(lbl))
            
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
        
    from datetime import datetime
    from app.services.core_store import _read_active_suffix_token
    suffix = _read_active_suffix_token(session.template_id) or "0000"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{session.template_id}_{suffix}_{ts}.xlsx"
    export_dir = ensure_exports_dir(session.template_id)
    out_path = os.path.join(export_dir, filename)
    
    try:
        session.writer.write_back(session.template_path, out_path, rows_to_write, instance_k=0)
        session.exported_files.append(out_path)
        session.last_export_path = out_path
        ui.notify(f"成功另存为: {filename}", type='positive')
        render_input_tab.refresh()
    except Exception as e:
        ui.notify(f"保存失败: {str(e)}", type='negative')

def handle_print(session, selected_area):
    if not session.last_export_path or not os.path.exists(session.last_export_path):
        ui.notify("请先成功执行【另存为】", type='warning')
        return
        
    path = session.last_export_path
    
    if os.name == 'nt':
        try:
            os.startfile(path, 'print')
            ui.notify("已发送到打印机", type='info')
        except Exception as e:
            ui.download(path)
            ui.notify(f"打印调用失败，已转为下载: {str(e)}", type='warning')
    else:
        ui.download(path)
        ui.notify("非 Windows 系统，文件已下载", type='info')
