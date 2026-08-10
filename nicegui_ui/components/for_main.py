from pathlib import Path

from nicegui import ui
from typing import Any
from nicegui_ui.components.general import SessionRegistry, list_export_files

from app.core_connect import AutoConnect, ConnectGoogle
from app.core_toml import _core_toml_path, load_toml, verify_toml, ensure_exists
from app.core_store import SecureSQLite, default_db_path, UiProvider
from app.core_transform import Template2DB, ExcelWriter, recompute_formula_draft_fields
from app.core_store import _normalize_id


class ForMain:
    @staticmethod
    def _ensure_connect_google(state) -> ConnectGoogle:
        conn = getattr(state, "connect_google", None)
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
            ui.notify(f"模板文件不存在: {template_path}", type="negative")
            return
        state.template_id = template_id
        state.template_path = xlsx_path

        state.current_instance_index = 0
        state.draft.clear()
        state.session_rows.clear()
        state.selected_instance_idx = None
        state.selected_instance_indices.clear()
        state.sort_column = None
        state.sort_descending = False
        state.total_instance_count = 0
        state.loaded_offset_k = 0
        state.db_loaded_limit = 50
        state.delete_mode = False
        state.exported_files = []
        state.last_export_path = None
        ForMain._clear_engines(state)
        try:
            toml_path = _core_toml_path(template_id)
            created = not toml_path.exists()
            ok = ensure_exists(template_id, xlsx_path)
            if created and ok:
                ui.notify(f"已生成默认 TOML: {template_id}", type="info")
            elif created and not ok:
                ui.notify(f"默认 TOML 生成失败: {template_id}", type="negative")
        except Exception as exc:
            ui.notify(f"TOML 准备失败: {exc}", type="warning")
        try:
            cfg = load_toml(template_id)
        except Exception as exc:
            ui.notify(f"TOML 读取失败: {exc}", type="warning")
            cfg = None
        state.cfg = cfg
        if cfg is None:
            state.verify_report = {"ok": False, "errors": ["TOML 无法解析"]}
            return
        state.use_independent_db = cfg.use_independent_db
        report = verify_toml(xlsx_path, cfg)
        state.verify_report = report
        state.located = report.get("located", {}) or {}
        if not report.get("ok", False):
            ui.notify(
                f"模板 {template_id} 校验未通过，可在 [输入配置] 中修改",
                type="warning",
            )
        try:
            db_path = default_db_path(template_id)
            state.db_path = db_path
            state.db = SecureSQLite(db_path)
            state.ui_provider = UiProvider(cfg, state.db)
            state.t2db = Template2DB(cfg)
            state.writer = ExcelWriter(
                cfg,
                state.located,
                formula_cells=report.get("formula_cells") or {},
            )
            state.input_capacity = state.writer.max_instance_count(xlsx_path)
            state.primary_span = int(getattr(state.writer, "primary_span", 0) or 0)
            # 初始化 Session 状态
            if state.use_independent_db:
                state.field_images.clear()
                # 从 DB 加载已存记录，按 instance_idx 回填到 session_rows
                db_records = state.ui_provider.get_data()
                state.session_rows = [
                    {
                        "instance_idx": int(r.get("instance_idx", 0) or 0),
                        "id": r.get("id"),
                        **{
                            lbl: r.get(lbl, "")
                            for lbl in state.ui_provider.get_labels()
                        },
                    }
                    for r in db_records
                ]
                # 按 instance_idx 降序展示，最新的在最上方
                state.session_rows.sort(
                    key=lambda r: r.get("instance_idx", 0), reverse=True
                )
                state.session_masks = []
                # 下一条待录入 instance_idx：已有最大 instance_idx 的下一槽；无记录则从 0 开始
                max_k = max(
                    (r.get("instance_idx", 0) for r in state.session_rows), default=-1
                )
                state.current_instance_index = max_k + 1
                if state.current_instance_index >= state.input_capacity:
                    state.current_instance_index = max(0, state.input_capacity - 1)
                val, mask = state.writer.read_values(xlsx_path, 0)
                state.template_defaults = val
                state.draft.clear()
                state.draft.update(val)
                state.formula_mask = mask
                recompute_formula_draft_fields(
                    state.draft,
                    report.get("formula_cells") or {},
                    state.located,
                )
            else:
                state.field_images.clear()
                total = state.writer.get_total_instance_count(xlsx_path)
                state.total_instance_count = total
                state.loaded_offset_k = max(0, total - 50)
                instances, masks = state.writer.read_instances(
                    xlsx_path, limit=50, reverse=True
                )
                state.session_rows = instances
                state.session_masks = masks
                state.current_instance_index = total
                state.draft.clear()
                val, mask = state.writer.read_values(
                    xlsx_path, state.current_instance_index
                )
                state.draft.update(val)
                state.formula_mask = mask
            state.selected_instance_idx = None
            state.selected_instance_indices.clear()
            state.delete_mode = False
            conn = ForMain._ensure_connect_google(state)
            bundle = AutoConnect(conn).run(cfg, verify_ok=bool(report.get("ok")))
            AutoConnect.apply_bundle(state, bundle)
            export_files = list_export_files(template_id)
            state.exported_files = export_files
            state.last_export_path = export_files[0] if export_files else None
        except Exception as exc:
            ui.notify(f"引擎初始化部分失败: {exc}", type="warning")

    @staticmethod
    def activate_template(template_id: str, template_path: str) -> bool:
        """兼容旧调用；始终尝试加载，返回是否已有 cfg。"""
        ForMain.load_template(template_id, template_path)
        state = SessionRegistry.for_current()
        return state.cfg is not None

    @staticmethod
    def refresh_session_from_source(session, *, notify: bool = True) -> None:
        """
        函数名: refresh_session_from_source
        作用: 刷新会话：重跑 verify_toml 更新校验报告，重建 ExcelWriter，模板即库模式下重载 instance 数据
        输入:
            session: 当前会话对象
            notify (bool): 是否弹出提示通知；默认 True
        输出: 无
        """
        from nicegui import ui
        if not session.cfg or not session.template_path:
            if notify:
                ui.notify("当前没有可刷新的模板", type="warning")
            return
        try:
            # 重新执行 verify_toml，获取最新下拉选项/公式格/坐标
            report = verify_toml(session.template_path, session.cfg)
            session.verify_report = report
            session.located = report.get("located", {}) or {}
            # 用新的 located/formula_cells 重建 writer
            session.writer = ExcelWriter(
                session.cfg,
                session.located,
                formula_cells=report.get("formula_cells") or {},
            )
            session.input_capacity = session.writer.max_instance_count(
                session.template_path
            )
            session.primary_span = int(
                getattr(session.writer, "primary_span", 0) or 0
            )
            # 独立库模式：保留内存列表，只同步配置变化
            if session.use_independent_db:
                if notify:
                    ui.notify(
                        "独立库模式：配置已刷新，保留当前内存列表", type="info"
                    )
                return
            # 模板即库模式：重载 instance 数据
            instances, masks = session.writer.read_instances(
                session.template_path, limit=session.db_loaded_limit, reverse=True
            )
            session.session_rows = instances
            session.session_masks = masks
            total = session.writer.get_total_instance_count(session.template_path)
            session.total_instance_count = total
            session.current_instance_index = total
            session.loaded_offset_k = max(0, total - session.db_loaded_limit)
            session.draft.clear()
            val, mask = session.writer.read_values(
                session.template_path, session.current_instance_index
            )
            session.draft.update(val)
            session.formula_mask = mask
            # 按最新公式格重算 draft；UI 未就绪时回退到核心重算函数
            try:
                from nicegui_ui.pages.tab_input import _refresh_formula_draft
                _refresh_formula_draft(session)
            except Exception:
                recompute_formula_draft_fields(
                    session.draft,
                    report.get("formula_cells") or {},
                    session.located,
                )
            session.delete_mode = False
            session.selected_instance_idx = None
            session.selected_instance_indices.clear()
            if notify:
                ui.notify("数据已刷新", type="positive")
        except Exception as e:
            ui.notify(f"刷新失败: {str(e)}", type="negative")


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
        google_op = getattr(session, "google_op", None)
        if google_op and getattr(session, "google_connected", False):
            rows = google_op.build_import_rows([raw])
            if rows:
                merged = dict(getattr(session, "template_defaults", None) or {})
                merged.update(rows[0])
                return merged
        t2db = getattr(session, "t2db", None)
        if not t2db:
            return None
        try:
            lookup_key = _normalize_id(raw)
        except ValueError:
            lookup_key = raw
        fetched = t2db.fetch_row_by_id(lookup_key)
        if not fetched:
            return None
        merged = dict(getattr(session, "template_defaults", None) or {})
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
        formula_cells = (getattr(session, "verify_report", None) or {}).get(
            "formula_cells"
        ) or {}
        located = getattr(session, "located", None) or {}
        recompute_formula_draft_fields(session.draft, formula_cells, located)
        session.suppress_id_search = True
        return True
