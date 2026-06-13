"""
Gradio Main Application Builder

Builds the main Gradio application layout with template selector and tabs.
"""
import gradio as gr
import logging
from typing import Any

from app.services.registry import load_templates, TemplateConfig

logger = logging.getLogger(__name__)


def build_app() -> gr.Blocks:
    """
    Build the main Gradio application
    
    Returns:
        gr.Blocks application instance
    """
    with gr.Blocks(
        title="Excel 模板可视化 - Gradio",
        theme=gr.themes.Soft(),
        css="""
        .template-selector { font-size: 1.1em !important; }
        .main-tabs { margin-top: 10px; }
        """
    ) as app:
        # Global state management
        current_template = gr.State(value=None)  # TemplateConfig
        credentials_state = gr.State(value=None)  # Google OAuth credentials
        form_data_state = gr.State(value=[])  # list[dict[str, str]]
        detected_areas_state = gr.State(value=[])  # list[DetectedArea]
        
        gr.Markdown("# Excel 模板可视化")
        
        with gr.Row():
            # Left sidebar: Template selector
            with gr.Column(scale=1, min_width=200):
                gr.Markdown("## 选择模板")
                
                template_selector = gr.Radio(
                    choices=[],
                    value=None,
                    label="模板列表",
                    elem_classes=["template-selector"]
                )
                
                gr.Markdown("---")
                
                shutdown_btn = gr.Button(
                    "关闭应用",
                    variant="secondary",
                    size="sm"
                )
            
            # Right main area: Tabs
            with gr.Column(scale=4):
                with gr.Tabs(elem_classes=["main-tabs"]) as tabs:
                    # Tab 1: Data Entry
                    with gr.TabItem("数据录入", id="data_entry"):
                        from app.components.gradio_template_form import build_form_tab
                        
                        form_components = build_form_tab(
                            current_template,
                            credentials_state,
                            form_data_state,
                            detected_areas_state
                        )
                    
                    # Tab 2: Data Source
                    with gr.TabItem("数据源", id="data_source"):
                        from app.components.gradio_data_source_settings import build_datasource_tab
                        
                        datasource_components = build_datasource_tab(
                            current_template,
                            credentials_state
                        )
                    
                    # Tab 3: Configuration
                    with gr.TabItem("参数配置", id="config"):
                        from app.components.gradio_config import build_config_tab
                        
                        config_components = build_config_tab(
                            current_template
                        )
        
        # Event: Load templates on startup
        app.load(
            fn=load_template_list,
            outputs=[template_selector]
        )
        
        # Event: Template selection changed
        template_selector.change(
            fn=on_template_change,
            inputs=[template_selector, current_template],
            outputs=[current_template, *form_components["update_on_template_change"]]
        )
        
        # Event: Shutdown button (placeholder - actual shutdown needs special handling)
        shutdown_btn.click(
            fn=lambda: gr.Info("请手动关闭浏览器窗口或按 Ctrl+C 停止服务器"),
            outputs=None
        )
    
    return app


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


def on_template_change(
    template_name: str | None,
    current_template: TemplateConfig | None
) -> tuple[Any, Any, Any, Any]:
    """
    Handle template selection change
    
    Returns: (current_template, form_container, sheet_selector, area_selector)
    """
    if not template_name:
        # Return 4 values for all outputs
        return (
            None,                           # current_template
            gr.update(visible=False),       # form_container
            gr.update(choices=[], value=None),  # sheet_selector
            gr.update(visible=False)        # area_selector
        )
    
    try:
        from app.services.excel_parser import list_sheet_names
        from pathlib import Path
        
        # Find template config
        templates = load_templates()
        template_dict = {t.display_name: t for t in templates}
        
        if template_name not in template_dict:
            gr.Warning(f"模板 '{template_name}' 未找到")
            return (
                None,
                gr.update(visible=False),
                gr.update(choices=[], value=None),
                gr.update(visible=False)
            )
        
        new_template = template_dict[template_name]
        logger.info(f"Switched to template: {new_template.id}")
        
        # Load sheet names from template
        try:
            sheet_names = list_sheet_names(Path(new_template.file_path))
            if not sheet_names:
                sheet_names = []
                logger.warning(f"No sheets found in template: {new_template.id}")
        except Exception as e:
            logger.error(f"Failed to load sheet names: {e}")
            sheet_names = []
        
        gr.Info(f"已切换到模板：{template_name}")
        
        # Return 4 values matching outputs
        return (
            new_template,                                  # current_template
            gr.update(visible=True),                       # form_container
            gr.update(choices=sheet_names, value=sheet_names[0] if sheet_names else None),  # sheet_selector
            gr.update(visible=False)                       # area_selector (hidden initially)
        )
        
    except Exception as e:
        logger.error(f"Failed to change template: {e}")
        gr.Warning(f"切换模板失败：{str(e)}")
        return (
            None,
            gr.update(visible=False),
            gr.update(choices=[], value=None),
            gr.update(visible=False)
        )
