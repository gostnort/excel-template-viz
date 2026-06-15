"""
Gradio Main Application Builder

Builds the main Gradio application layout with template selector and tabs.
"""
import gradio as gr
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.components.gradio_config import (
    build_config_tab,
    fetch_llm_test_columns,
    handle_sections_save,
    handle_yaml_load,
    load_llm_test_worksheets,
    refresh_llm_test_from_datasource_worksheet,
)
from app.components.gradio_data_source_settings import build_datasource_tab
from app.components.gradio_template_form import (
    build_form_tab,
    refresh_data_entry_form,
    resolve_default_sheet_name,
    try_template_select,
)
from app.services.excel_parser import list_sheet_names
from app.services.paste_parse_config import ensure_config_exists
from app.services.registry import load_templates, TemplateConfig

logger = logging.getLogger(__name__)

APP_THEME = gr.themes.Soft()
APP_CSS = """
        /* 模板选择器样式 */
        .template-selector { font-size: 1.1em !important; }
        .main-tabs { margin-top: 10px; }
        
        /* Radio 按钮容器：移除内边距，让选项占满宽度 */
        .template-selector .wrap.svelte-e4x47i {
            padding: 0 !important;
            gap: 2px !important;
        }
        
        /* Radio 按钮标签：占满宽度 */
        .template-selector .wrap.svelte-e4x47i > label {
            width: 100% !important;
            margin: 0 !important;
            padding: 10px 16px !important;
            box-shadow: none !important;
            border-radius: 4px !important;
            cursor: pointer;
            transition: all 0.15s ease;
            display: flex !important;
            align-items: center !important;
        }
        
        /* 未选中状态 */
        .template-selector .wrap.svelte-e4x47i > label:not(:has(input:checked)) {
            background: transparent !important;
        }
        
        /* 未选中状态悬停 */
        .template-selector .wrap.svelte-e4x47i > label:not(:has(input:checked)):hover {
            background: #f3f4f6 !important;
        }
        
        /* 选中状态：蓝色背景，占满宽度，无阴影 */
        .template-selector .wrap.svelte-e4x47i > label:has(input:checked) {
            background: #6366f1 !important;
            color: white !important;
            box-shadow: none !important;
        }
        
        /* Radio 圆点颜色调整 */
        .template-selector input[type="radio"]:checked {
            accent-color: white !important;
        }
        
        /* Toast 通知样式优化 */
        .toast-wrap.svelte-1qhecvt {
            animation-duration: 0.2s !important;
        }
        
        .toast-item.svelte-1qhecvt {
            padding: 4px 12px !important;
            min-height: 32px !important;
            max-height: 48px !important;
        }
        
        .toast-body.svelte-irmu64 {
            padding: 4px 8px !important;
            min-height: 28px !important;
        }
        
        .toast-message-item.svelte-irmu64 {
            padding: 2px 0 !important;
            line-height: 1.3 !important;
        }
        
        .toast-message-text.svelte-irmu64 {
            font-size: 0.9rem !important;
            padding: 0 !important;
            line-height: 1.3 !important;
        }
        
        /* 标签样式：添加冒号，移除背景色 */
        label.svelte-1gfkn6j::after {
            content: ":";
        }
        label.svelte-1gfkn6j {
            background: transparent !important;
            font-weight: 500;
            color: #374151;
        }
        
        /* 输入框默认样式：无背景，只有底部边框 */
        .wrap.svelte-1w1j06g,
        input.svelte-1w1j06g,
        textarea.svelte-1w1j06g,
        textarea.svelte-1hguek3,
        input[type="text"],
        textarea {
            background: transparent !important;
            border: none !important;
            border-bottom: 1px solid #d1d5db !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            transition: all 0.2s ease;
        }
        
        /* 下拉框和数字输入框 */
        .block.padded select,
        .block.padded input[type="number"] {
            background: transparent !important;
            border: none !important;
            border-bottom: 1px solid #d1d5db !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }
        
        /* 激活状态：深色阴影和下划线 */
        .wrap.svelte-1w1j06g:focus-within,
        input.svelte-1w1j06g:focus,
        textarea.svelte-1w1j06g:focus,
        textarea.svelte-1hguek3:focus,
        input[type="text"]:focus,
        textarea:focus,
        select:focus {
            border-bottom: 2px solid #4f46e5 !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15), 
                        0 2px 4px -1px rgba(0, 0, 0, 0.1) !important;
            outline: none !important;
        }
        
        /* Read-only LLM response JSON: Gradio sets overflow-y:hidden on disabled textareas */
        .llm-response-box textarea {
            overflow-y: auto !important;
        }
        
        /* 按钮激活状态 */
        button:focus {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15), 
                        0 2px 4px -1px rgba(0, 0, 0, 0.1) !important;
        }
        
        /* 代码编辑器激活状态 */
        .cm-editor.cm-focused {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15), 
                        0 2px 4px -1px rgba(0, 0, 0, 0.1) !important;
            outline: 2px solid #4f46e5 !important;
        }
        
        /* Checkbox 和 Radio 激活状态 */
        input[type="checkbox"]:focus,
        input[type="radio"]:focus {
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.2) !important;
        }
        
        /* 移除非激活状态的阴影 */
        .block.padded {
            box-shadow: none !important;
        }
        
        /* Accordion 激活状态 */
        .accordion.svelte-90oupt:focus-within {
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.15), 
                        0 2px 4px -1px rgba(0, 0, 0, 0.1) !important;
        }
        
        /* Toast 自动关闭时间控制 */
        @keyframes toast-fade-out {
            from { opacity: 1; }
            to { opacity: 0; }
        }
        
        .toast-item.svelte-1qhecvt {
            animation: toast-fade-out 0.3s ease-in-out 2s forwards !important;
        }
        
        /* 模板侧边栏折叠 */
        .template-sidebar {
            display: flex !important;
            flex-direction: column !important;
            transition: opacity 0.2s ease, max-width 0.25s ease, flex 0.25s ease, min-width 0.25s ease;
        }
        
        #template-sidebar.sidebar-collapsed {
            display: none !important;
            flex: 0 0 0 !important;
            width: 0 !important;
            min-width: 0 !important;
            max-width: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
            overflow: hidden !important;
            opacity: 0 !important;
        }
        
        #main-content.main-expanded {
            flex: 1 1 100% !important;
            max-width: 100% !important;
            width: 100% !important;
        }
        
        #app-body-row {
            align-items: stretch !important;
            min-height: calc(100vh - 88px) !important;
        }
        
        .template-nav-title p {
            margin: 0 0 4px 0 !important;
        }
        
        .template-list-scroll {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            overflow-y: auto !important;
            overflow-x: hidden !important;
        }
        
        .template-list-scroll .template-selector {
            min-height: 0 !important;
        }
        
        .sidebar-shutdown-footer {
            flex: 0 0 auto !important;
            margin-top: auto !important;
            padding-top: 12px !important;
            border-top: 1px solid #e5e7eb !important;
        }
        
        .sidebar-shutdown-footer .app-shutdown-btn {
            width: 100% !important;
            margin: 0 !important;
        }
        
        .sidebar-toggle-btn {
            min-width: 110px !important;
            width: fit-content !important;
            flex: 0 0 auto !important;
            margin: 12px 0 0 0 !important;
            align-self: flex-start !important;
        }
        
        .sidebar-show-btn {
            min-width: 110px !important;
            width: fit-content !important;
            margin-bottom: 4px !important;
        }
        
        /* App header: title left, shutdown right */
        .app-header-row {
            align-items: center !important;
            justify-content: space-between !important;
            flex-wrap: nowrap !important;
            gap: 12px !important;
            margin-bottom: 8px !important;
        }
        
        .app-header-row .app-title {
            flex: 1 1 0% !important;
            min-width: 0 !important;
            margin: 0 !important;
        }
        
        .app-header-row .app-title p,
        .app-header-row .app-title h1 {
            margin: 0 !important;
        }
        
        .app-header-row .app-title [data-testid="markdown-wrapper"],
        .app-header-row .app-title .prose {
            width: 100% !important;
        }
        
        .app-header-row .app-header-actions {
            display: flex !important;
            flex: 0 0 auto !important;
            width: fit-content !important;
            max-width: fit-content !important;
            align-items: center !important;
            gap: 8px !important;
            margin: 0 !important;
        }
        
        .app-header-row .sidebar-toggle-btn {
            margin: 0 !important;
        }
        
        .app-shutdown-btn button {
            font-size: 0.9rem !important;
            font-weight: normal !important;
            padding: 8px 16px !important;
            min-height: 36px !important;
            width: 100% !important;
            border: 2px solid #dc2626 !important;
            color: #dc2626 !important;
            background: #fef2f2 !important;
            box-shadow: 0 1px 3px rgba(220, 38, 38, 0.2) !important;
            transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease !important;
        }
        
        .app-shutdown-btn button:hover {
            background: #dc2626 !important;
            color: #ffffff !important;
            box-shadow: 0 2px 6px rgba(220, 38, 38, 0.35) !important;
        }
        
        /* Data entry form: next-area button aligned bottom-right */
        .form-next-row {
            justify-content: flex-end !important;
            margin-top: 8px !important;
        }
        
        /* Suppress Gradio default full-screen status tracker overlay */
        [data-testid="status-tracker"] {
            display: none !important;
        }
        """


def build_app() -> gr.Blocks:
    """
    Build the main Gradio application
    
    Returns:
        gr.Blocks application instance
    """
    with gr.Blocks(title="Excel 模板可视化 - Gradio") as app:
        # Global state management
        current_template = gr.State(value=None)  # TemplateConfig
        credentials_state = gr.State(value=None)  # Google OAuth credentials
        form_data_state = gr.State(value=[])  # list[dict[str, str]]
        detected_areas_state = gr.State(value=[])  # list[DetectedArea]
        sidebar_visible = gr.State(value=True)
        
        with gr.Row(elem_classes=["app-header-row"]):
            gr.Markdown(
                "# Excel 模板可视化",
                elem_classes=["app-title"],
            )
            with gr.Row(elem_classes=["app-header-actions"]):
                sidebar_toggle_btn = gr.Button(
                    "◀ 隐藏模板",
                    variant="secondary",
                    size="sm",
                    elem_classes=["sidebar-toggle-btn"],
                )
        
        with gr.Row(elem_id="app-body-row"):
            # Left sidebar: Template selector
            with gr.Column(
                scale=1,
                min_width=200,
                elem_id="template-sidebar",
                elem_classes=["template-sidebar"],
            ) as sidebar_column:
                gr.Markdown(
                    "## 选择模板",
                    elem_classes=["template-nav-title", "template-nav-header"],
                )
                with gr.Column(elem_classes=["template-list-scroll"]):
                    template_selector = gr.Radio(
                        choices=[],
                        value=None,
                        show_label=False,
                        elem_classes=["template-selector"]
                    )
                with gr.Column(elem_classes=["sidebar-shutdown-footer"]):
                    shutdown_btn = gr.Button(
                        "关闭应用",
                        variant="stop",
                        size="sm",
                        elem_classes=["app-shutdown-btn"],
                    )
            
            # Right main area: Tabs
            with gr.Column(scale=4, elem_id="main-content", elem_classes=["main-content"]) as main_column:
                sidebar_show_btn = gr.Button(
                    "▶ 显示模板",
                    variant="secondary",
                    size="sm",
                    visible=False,
                    elem_classes=["sidebar-show-btn"],
                )
                
                with gr.Tabs(elem_classes=["main-tabs"]) as tabs:
                    # Tab 1: Data Entry
                    with gr.TabItem("数据录入", id="data_entry"):
                        form_components = build_form_tab(
                            current_template,
                            credentials_state,
                            form_data_state,
                            detected_areas_state,
                            template_selector,
                        )
                    
                    # Tab 2: Data Source
                    with gr.TabItem("数据源", id="data_source"):
                        datasource_components = build_datasource_tab(
                            current_template,
                            credentials_state
                        )
                    
                    # Tab 3: Configuration
                    with gr.TabItem("参数配置", id="config"):
                        config_components = build_config_tab(
                            current_template,
                            credentials_state
                        )
        
        # Event: Load templates on startup, then select default template and refresh form
        app.load(
            fn=load_template_list,
            outputs=[template_selector],
        ).then(
            fn=apply_template_and_refresh_form,
            inputs=[
                template_selector,
                current_template,
                form_data_state,
                form_components["entry_mode_state"],
                form_components["committed_template_name_state"],
                detected_areas_state,
                form_components["form_session_state"],
                form_components["committed_sheet_state"],
                form_components["import_selection_state"],
                form_components["import_preview_active_state"],
                form_components["import_sheet_cache_state"],
                form_components["import_view_state"],
                form_components["import_preview"],
            ],
            outputs=form_components["guarded_template_outputs"],
            show_progress="hidden",
        )
        
        # Event: Template selection changed
        template_selector.change(
            fn=apply_template_and_refresh_form,
            inputs=[
                template_selector,
                current_template,
                form_data_state,
                form_components["entry_mode_state"],
                form_components["committed_template_name_state"],
                detected_areas_state,
                form_components["form_session_state"],
                form_components["committed_sheet_state"],
                form_components["import_selection_state"],
                form_components["import_preview_active_state"],
                form_components["import_sheet_cache_state"],
                form_components["import_view_state"],
                form_components["import_preview"],
            ],
            outputs=form_components["guarded_template_outputs"],
            show_progress="hidden",
        )

        config_components["sections_save_btn"].click(
            fn=handle_sections_save,
            inputs=[
                current_template,
                config_components["input_area"],
                config_components["move_direction"],
                config_components["offset_value"],
            ],
            outputs=[config_components["sections_status"]],
        ).then(
            fn=handle_yaml_load,
            inputs=[current_template],
            outputs=[
                config_components["yaml_editor"],
            ],
        ).then(
            fn=refresh_data_entry_form,
            inputs=[
                current_template,
                form_components["sheet_selector"],
                form_data_state,
                form_components["entry_mode_state"],
            ],
            outputs=form_components["form_refresh_outputs"],
            show_progress="hidden",
        )
        
        datasource_components["connect_btn"].click(
            fn=load_llm_test_worksheets,
            inputs=[current_template, credentials_state],
            outputs=[config_components["llm_test_worksheet"]],
        ).then(
            fn=fetch_llm_test_columns,
            inputs=[
                current_template,
                credentials_state,
                config_components["llm_test_worksheet"],
            ],
            outputs=[config_components["test_sheet_cols"]],
        )

        # Cross-tab event: sync LLM test sheet/columns when data-source worksheet changes
        datasource_components["worksheet_dropdown"].change(
            fn=refresh_llm_test_from_datasource_worksheet,
            inputs=[
                current_template,
                credentials_state,
                datasource_components["worksheet_dropdown"],
            ],
            outputs=[
                config_components["llm_test_worksheet"],
                config_components["test_sheet_cols"],
            ],
        )
        
        # Event: Sidebar toggle (hide in sidebar, show in main area when collapsed)
        sidebar_toggle_outputs = [
            sidebar_column,
            sidebar_visible,
            sidebar_show_btn,
            main_column,
        ]
        sidebar_toggle_btn.click(
            fn=toggle_sidebar_visibility,
            inputs=[sidebar_visible],
            outputs=sidebar_toggle_outputs,
        )
        sidebar_show_btn.click(
            fn=toggle_sidebar_visibility,
            inputs=[sidebar_visible],
            outputs=sidebar_toggle_outputs,
        )
        
        # Event: Shutdown button
        shutdown_btn.click(
            fn=handle_shutdown,
            outputs=None
        )
    
    return app


def toggle_sidebar_visibility(is_visible: bool) -> tuple[Any, bool, Any, Any]:
    """Toggle template selector sidebar visibility."""
    new_visible = not is_visible
    sidebar_classes = ["template-sidebar"] if new_visible else ["template-sidebar", "sidebar-collapsed"]
    main_classes = ["main-content"] if new_visible else ["main-content", "main-expanded"]
    return (
        gr.update(
            visible=new_visible,
            scale=1 if new_visible else 0,
            min_width=200 if new_visible else 0,
            elem_classes=sidebar_classes,
        ),
        new_visible,
        gr.update(visible=not new_visible),
        gr.update(
            scale=4 if new_visible else 1,
            elem_classes=main_classes,
        ),
    )


def load_template_list() -> gr.Dropdown:
    """Load available templates"""
    try:
        templates = load_templates()
        choices = [t.display_name for t in templates]
        
        if not choices:
            logger.warning("No templates found")
            return gr.Radio(choices=[], value=None)
        
        logger.info(f"Loaded {len(choices)} templates")
        return gr.Radio(
            choices=choices,
            value=choices[0] if choices else None
        )
    except Exception as e:
        logger.error(f"Failed to load templates: {e}")
        return gr.Radio(choices=[], value=None)


def handle_shutdown():
    """
    Shutdown the application and backend service
    """
    logger.info("Shutdown requested by user")
    gr.Info("正在关闭应用...")
    
    # Schedule shutdown after a short delay to allow response to be sent
    def delayed_shutdown():
        time.sleep(1)  # Wait 1 second for response to be sent
        logger.info("Shutting down Gradio server...")
        
        try:
            gr.close_all()
        except Exception as e:
            logger.error("Error closing Gradio: %s", e)
        sys.exit(0)
    
    shutdown_thread = threading.Thread(target=delayed_shutdown, daemon=True)
    shutdown_thread.start()
    
    return None


def on_template_change(
    template_name: str | None,
    current_template: TemplateConfig | None,
) -> tuple[TemplateConfig | None, Any, str | None]:
    """
    Handle template selection change

    Returns: (current_template, sheet_selector, default_sheet_name)
    """
    if not template_name:
        return None, gr.update(choices=[], value=None), None

    try:
        templates = load_templates()
        template_dict = {t.display_name: t for t in templates}

        if template_name not in template_dict:
            gr.Warning(f"模板 '{template_name}' 未找到")
            return None, gr.update(choices=[], value=None), None

        new_template = template_dict[template_name]
        logger.info(f"Switched to template: {new_template.id}")
        ensure_config_exists(new_template.id, Path(new_template.file_path))

        try:
            sheet_names = list_sheet_names(Path(new_template.file_path))
            if not sheet_names:
                sheet_names = []
                logger.warning(f"No sheets found in template: {new_template.id}")
        except Exception as e:
            logger.error(f"Failed to load sheet names: {e}")
            sheet_names = []

        default_sheet = resolve_default_sheet_name(new_template, sheet_names)
        gr.Info(f"已切换到模板：{template_name}")

        return (
            new_template,
            gr.update(choices=sheet_names, value=default_sheet),
            default_sheet,
        )

    except Exception as e:
        logger.error(f"Failed to change template: {e}")
        gr.Warning(f"切换模板失败：{str(e)}")
        return None, gr.update(choices=[], value=None), None


def apply_template_and_refresh_form(
    template_name: str | None,
    current_template: TemplateConfig | None,
    form_data: list[dict[str, str]],
    entry_mode: str,
    committed_template_name: str | None,
    detected_areas: list,
    session: dict,
    committed_sheet: str | None,
    import_selection: dict,
    import_preview_active: bool,
    sheet_cache: dict,
    import_view: str,
    import_preview: Any,
) -> tuple:
    """Select template with unsaved-change guard and refresh the data entry form."""
    return try_template_select(
        template_name,
        current_template,
        committed_template_name,
        form_data,
        detected_areas,
        entry_mode,
        session,
        committed_sheet,
        import_selection,
        import_preview_active,
        sheet_cache,
        import_view,
        import_preview,
    )
