from pathlib import Path

from nicegui import ui
from typing import Any
from nicegui_ui.components.general import SessionRegistry, list_export_files

from app.core_connect import AutoConnect, ConnectGoogle
from app.core_toml import _core_toml_path, load_toml, verify_toml, ensure_exists
from app.core_store import SecureSQLite, default_db_path, UiProvider
from app.core_transform import Template2DB, ExcelWriter
from app.core_store import _normalize_id


class ForMain:
    @staticmethod
    def _ensure_connect_google(state) -> ConnectGoogle:
        conn = getattr(state, 'connect_google', None)
        if conn is None:
            conn = ConnectGoogle()
            state.connect_google = conn
        return conn

    @staticmethod
    def _clear_engines(state) -> None:
        state.ui_provider = None
        state.writer = None
        state.t2db = None
        state.located = {}
        if state.db:
            state.db.close()
        state.db = None
        state.db_path = None

    @staticmethod
    def load_template(template_id: str, template_path: str) -> None:
        """
        切换侧栏模板：始终写入 session 并刷新 UI，不因校验失败而阻断。
        """
        state = SessionRegistry.for_current()
        xlsx_path = Path(template_path)
        if not xlsx_path.is_file():
            ui.notify(f"模板文件不存在: {template_path}", type='negative')
            return
        state.template_id = template_id
        state.template_path = xlsx_path
        
        from nicegui import app
        if hasattr(app.storage, 'user'):
            state.use_independent_db = app.storage.user.get(f'use_independent_db_{template_id}', True)
        state.current_instance_index = 0
        state.draft.clear()
        state.session_rows.clear()
        state.selected_instance_k = None
        state.selected_instance_indices.clear()
        state.sort_column = None
        state.sort_descending = False
        state.total_instance_count = 0
        state.loaded_offset_k = 0
        state.db_loaded_limit = 50
        state.exported_files = []
        state.last_export_path = None
        ForMain._clear_engines(state)
        try:
            created = not _core_toml_path(template_id).exists() or load_toml(template_id) is None
            ensure_exists(template_id, xlsx_path)
            if created:
                ui.notify(f'已生成默认 TOML: {template_id}', type='info')
        except Exception as exc:
            ui.notify(f'TOML 准备失败: {exc}', type='warning')
        try:
            cfg = load_toml(template_id)
        except Exception as exc:
            ui.notify(f'TOML 读取失败: {exc}', type='warning')
            cfg = None
        state.cfg = cfg
        if cfg is None:
            state.verify_report = {'ok': False, 'errors': ['TOML 无法解析']}
            return
        report = verify_toml(xlsx_path, cfg)
        state.verify_report = report
        state.located = report.get('located', {}) or {}
        if not report.get('ok', False):
            ui.notify(
                f'模板 {template_id} 校验未通过，可在 [输入配置] 中修改',
                type='warning',
            )
        try:
            db_path = default_db_path(template_id)
            state.db_path = db_path
            state.db = SecureSQLite(db_path)
            state.ui_provider = UiProvider(cfg, state.db)
            state.t2db = Template2DB(cfg)
            state.writer = ExcelWriter(cfg, state.located)
            state.input_capacity = state.writer.max_instance_count(xlsx_path)
            # 初始化 Session 状态
            if state.use_independent_db:
                state.session_rows.clear()
                state.current_instance_index = 0
                state.field_images.clear()
                val, mask = state.writer.read_values(xlsx_path, 0)
                state.template_defaults = val
                state.draft.clear()
                state.draft.update(val)
                state.formula_mask = mask
            else:
                state.field_images.clear()
                total = state.writer.get_total_instance_count(xlsx_path)
                state.total_instance_count = total
                state.loaded_offset_k = max(0, total - 50)
                instances, masks = state.writer.read_instances(xlsx_path, limit=50, reverse=True)
                state.session_rows = instances
                state.session_masks = masks
                state.current_instance_index = total
                state.draft.clear()
                val, mask = state.writer.read_values(xlsx_path, state.current_instance_index)
                state.draft.update(val)
                state.formula_mask = mask
            state.selected_instance_k = None
            state.selected_instance_indices.clear()
            conn = ForMain._ensure_connect_google(state)
            bundle = AutoConnect(conn).run(cfg, verify_ok=bool(report.get('ok')))
            AutoConnect.apply_bundle(state, bundle)
            export_files = list_export_files(template_id)
            state.exported_files = export_files
            state.last_export_path = export_files[0] if export_files else None
        except Exception as exc:
            ui.notify(f'引擎初始化部分失败: {exc}', type='warning')

    @staticmethod
    def activate_template(template_id: str, template_path: str) -> bool:
        """兼容旧调用；始终尝试加载，返回是否已有 cfg。"""
        ForMain.load_template(template_id, template_path)
        state = SessionRegistry.for_current()
        return state.cfg is not None



class IdLookup:
    @staticmethod
    def fetch_from_source(session, id_value: str) -> dict[str, Any] | None:
        """
        按 id=true 字段输入值从外部数据源取行。
        Google 已连接时用 SheetOperation；否则回退 Template2DB（本地 xlsx）。
        """
        raw = str(id_value).strip()
        if not raw:
            return None
        google_op = getattr(session, 'google_op', None)
        if google_op and getattr(session, 'google_connected', False):
            rows = google_op.build_import_rows([raw])
            if rows:
                merged = dict(getattr(session, 'template_defaults', None) or {})
                merged.update(rows[0])
                return merged
        t2db = getattr(session, 't2db', None)
        if not t2db:
            return None
        try:
            lookup_key = _normalize_id(raw)
        except ValueError:
            lookup_key = raw
        fetched = t2db.fetch_row_by_id(lookup_key)
        if not fetched:
            return None
        merged = dict(getattr(session, 'template_defaults', None) or {})
        merged.update(fetched)
        return merged

    @staticmethod
    def apply_source_to_draft(session, id_value: str) -> bool:
        """拉取数据源行并写入 session.draft；成功返回 True。"""
        merged = IdLookup.fetch_from_source(session, id_value)
        if not merged:
            return False
        session.draft.clear()
        session.draft.update(merged)
        session.suppress_id_search = True
        return True
