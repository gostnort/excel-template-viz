import subprocess
import sys

from nicegui import ui
from nicegui_ui.components.buttons import app_btn
from nicegui_ui.components.general import SessionRegistry


@ui.refreshable
def render_toml_tab():
    session = SessionRegistry.for_current()
    if not session.cfg:
        ui.label("请先从左侧选择模板").classes("text-gray-500 italic p-4")
        return

    with ui.element("div").classes("tab-scroll-container"):
        # 校验操作区域
        with ui.element("div").classes("section"):
            ui.label("校验与应用").classes("section-title")
            with ui.element("div").classes("section-body"):
                with ui.element("div").classes("form-row"):
                    app_btn(
                        "校验并应用配置",
                        primary=True,
                        on_click=lambda: trigger_toml_save(session),
                    )

                    if session.verify_report:
                        if session.verify_report.get("ok"):
                            ui.label("当前配置已校验通过").classes(
                                "ctrl wide status-ok"
                            )
                        else:
                            with (
                                ui.element("div")
                                .classes("ctrl wide status-warn")
                                .style(
                                    "flex-direction: column; align-items: flex-start; height: auto;"
                                )
                            ):
                                ui.label("配置校验失败").classes("font-bold text-red")
                                if session.verify_report.get("missing_labels"):
                                    ui.label(
                                        f"缺失标签: {', '.join(session.verify_report['missing_labels'])}"
                                    ).classes("text-sm")
                                if session.verify_report.get("duplicate_labels"):
                                    ui.label(
                                        f"重复标签: {', '.join(session.verify_report['duplicate_labels'])}"
                                    ).classes("text-sm")
                                if session.verify_report.get("out_of_area_labels"):
                                    ui.label(
                                        f"越界标签: {', '.join(session.verify_report['out_of_area_labels'])}"
                                    ).classes("text-sm")
                                if session.verify_report.get("errors"):
                                    for err in session.verify_report["errors"]:
                                        ui.label(f"- {err}").classes("text-sm text-red")

        # 高级（TOML 全文）
        with ui.element("div").classes("section"):
            ui.label("高级（TOML 全文）").classes("section-title")
            with ui.element("div").classes("section-body"):
                from app.core_toml import _core_toml_path

                toml_path = (
                    _core_toml_path(session.template_id)
                    if session.template_id
                    else None
                )
                try:
                    with open(toml_path, "r", encoding="utf-8") as f:
                        raw_toml = f.read()
                except Exception:
                    raw_toml = ""

                toml_editor = (
                    ui.textarea(value=raw_toml)
                    .classes("w-full font-mono text-sm")
                    .props('rows="25" outlined')
                    .style("border-radius: 0; border: 1px solid #000; padding: 4px;")
                )

                def save_raw_toml():
                    new_toml = toml_editor.value
                    if not toml_path:
                        return
                    try:
                        with open(toml_path, "w", encoding="utf-8") as f:
                            f.write(new_toml)
                        trigger_toml_save(session)
                    except Exception as e:
                        ui.notify(f"保存文件失败: {str(e)}", type="negative")

                with ui.element('div').classes('form-row').style('margin-top:8px'):
                    app_btn('保存', on_click=save_raw_toml)
                    app_btn('重置', on_click=render_toml_tab.refresh)


def trigger_toml_save(session):
    try:
        from app.core_toml import load_toml, verify_toml

        session.cfg = load_toml(session.template_id)
        session.verify_report = verify_toml(session.template_path, session.cfg)

        if session.verify_report.get("ok"):
            from app.core_store import SecureSQLite, default_db_path, UiProvider
            from app.core_transform import Template2DB, ExcelWriter

            session.located = session.verify_report.get("located", {})
            db_path = default_db_path(session.template_id)
            session.db_path = db_path

            if session.db:
                session.db.close()

            session.db = SecureSQLite(db_path)
            session.ui_provider = UiProvider(session.cfg, session.db)
            session.t2db = Template2DB(session.cfg)
            session.writer = ExcelWriter(session.cfg, session.located)

            session.input_capacity = session.writer.max_instance_count(
                session.template_path
            )
            if session.use_independent_db:
                session.session_rows.clear()
                session.current_instance_index = 0
                if hasattr(session, "field_images"):
                    session.field_images.clear()
                val, mask = (
                    session.writer.read_values(session.template_path, 0)
                    if session.template_path
                    else ({}, {})
                )
                session.template_defaults = val
                session.draft.clear()
                session.draft.update(val)
                session.formula_mask = mask
            else:
                if hasattr(session, "field_images"):
                    session.field_images.clear()
                instances, masks = (
                    session.writer.read_instances(session.template_path)
                    if session.template_path
                    else ([], [])
                )
                session.session_rows = instances
                session.session_masks = masks
                session.current_instance_index = len(instances)
                session.draft.clear()
                val, mask = (
                    session.writer.read_values(
                        session.template_path, session.current_instance_index
                    )
                    if session.template_path
                    else ({}, {})
                )
                session.draft.update(val)
                session.formula_mask = mask
            session.selected_instance_k = None
            session.selected_instance_indices.clear()

            ui.notify("配置保存并加载成功", type="positive")
        else:
            session.ui_provider = None
            session.writer = None
            session.t2db = None
            if session.db:
                session.db.close()
            session.db = None
            ui.notify("配置保存成功，但校验失败，工作区已锁定", type="warning")

        # Refresh tabs
        render_toml_tab.refresh()

        from nicegui_ui.pages.tab_input import render_input_tab

        render_input_tab.refresh()

    except Exception as e:
        ui.notify(f"应用失败: {str(e)}", type="negative")
