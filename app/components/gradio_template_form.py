"""
Gradio Template Form Component

Handles dynamic form rendering, area selection, ID lookup, and bulk import.
"""
import gradio as gr
import logging
from pathlib import Path
from typing import Any

from app.services.registry import TemplateConfig
from app.services.excel_parser import list_sheet_names, read_template_sheet
from app.services.section_detector import (
    detect_multi_areas, parse_sections_from_yaml, SectionConfig
)
from app.services.paste_parse_config import load_paste_parse_config
from app.services.google_sheets import fetch_row_by_id, fetch_all_rows, GoogleSheetsError
from app.services.phi4_field_matcher import create_field_matcher

logger = logging.getLogger(__name__)

# Global field matcher (lazy loaded)
_field_matcher = None


def get_field_matcher():
    """Get or create field matcher instance"""
    global _field_matcher
    if _field_matcher is None:
        _field_matcher = create_field_matcher()
    return _field_matcher


def build_form_tab(
    current_template: gr.State,
    credentials_state: gr.State,
    form_data_state: gr.State,
    detected_areas_state: gr.State
) -> dict:
    """
    Build the data entry tab
    
    Returns:
        Dict of component references for event binding
    """
    components = {}
    
    with gr.Column():
        # Sheet selector
        sheet_selector = gr.Dropdown(
            label="选择工作表",
            choices=[],
            value=None,
            interactive=True
        )
        components["sheet_selector"] = sheet_selector
        
        # Area selector (for multi-area templates)
        area_selector = gr.Dropdown(
            label="选择区域",
            choices=[],
            value=None,
            interactive=True,
            visible=False
        )
        components["area_selector"] = area_selector
        
        # Form container
        with gr.Column(visible=False) as form_container:
            gr.Markdown("### 表单数据")
            
            # Row selector
            row_selector = gr.Dropdown(
                label="选择行",
                choices=[],
                value=None
            )
            components["row_selector"] = row_selector
            
            # Dynamic form fields (will be populated dynamically)
            # For now, create placeholder fields
            form_fields = {}
            with gr.Column() as fields_container:
                # Placeholder - actual fields will be created dynamically
                placeholder_field = gr.Textbox(
                    label="字段加载中...",
                    interactive=False,
                    visible=True
                )
            
            components["form_fields"] = form_fields
            components["fields_container"] = fields_container
        
        components["form_container"] = form_container
        
        # Bulk import section
        with gr.Accordion("批量导入", open=False) as bulk_import_accordion:
            refresh_btn = gr.Button("🔄 从 Google Sheet 刷新数据")
            
            import_preview = gr.Dataframe(
                headers=["选择", "ID", "数据预览"],
                datatype=["bool", "str", "str"],
                interactive=True,
                wrap=True,
                visible=False
            )
            
            import_btn = gr.Button(
                "✅ 导入选中行",
                variant="primary",
                visible=False
            )
        
        components["refresh_btn"] = refresh_btn
        components["import_preview"] = import_preview
        components["import_btn"] = import_btn
        
        # Action buttons
        with gr.Row():
            export_btn = gr.Button("导出 Excel", variant="primary")
            print_btn = gr.Button("打印预览")
        
        components["export_btn"] = export_btn
        components["print_btn"] = print_btn
    
    # Event bindings
    
    # Sheet selector change
    sheet_selector.change(
        fn=on_sheet_change,
        inputs=[sheet_selector, current_template],
        outputs=[area_selector, form_container]
    )
    
    # Refresh button for bulk import
    refresh_btn.click(
        fn=handle_refresh_unrecorded,
        inputs=[current_template, credentials_state],
        outputs=[import_preview, import_btn]
    )
    
    # Import selected rows
    import_btn.click(
        fn=handle_import_selected,
        inputs=[import_preview, current_template, form_data_state],
        outputs=[form_data_state, row_selector]
    )
    
    # Export button
    export_btn.click(
        fn=handle_export,
        inputs=[current_template, form_data_state],
        outputs=[gr.File()]
    )
    
    # Components that need updating on template change
    components["update_on_template_change"] = [
        form_container,
        sheet_selector,
        area_selector
    ]
    
    return components


def on_sheet_change(
    sheet_name: str | None,
    template: TemplateConfig | None
) -> tuple:
    """Handle sheet selection change"""
    if not sheet_name or not template:
        return gr.update(visible=False), gr.update(visible=False)
    
    try:
        # Load paste config to check for sections
        paste_config = load_paste_parse_config(template.id)
        
        if paste_config and paste_config.sections:
            # Multi-area template - detect areas
            sections = parse_sections_from_yaml({"sections": paste_config.sections})
            if sections:
                section_config = sections[0]  # Use first section config
                
                try:
                    detected_areas = detect_multi_areas(
                        Path(template.file_path),
                        sheet_name,
                        section_config
                    )
                    
                    if len(detected_areas) > 1:
                        # Show area selector
                        area_choices = [f"区域 {a.index}" for a in detected_areas]
                        return (
                            gr.update(choices=area_choices, value=area_choices[0], visible=True),
                            gr.update(visible=True)
                        )
                except Exception as e:
                    logger.error(f"Area detection failed: {e}")
                    gr.Warning(f"区域检测失败：{str(e)}")
        
        # Single area or detection failed - show form directly
        return (
            gr.update(visible=False),
            gr.update(visible=True)
        )
        
    except Exception as e:
        logger.error(f"Sheet change error: {e}")
        gr.Warning(f"切换工作表失败：{str(e)}")
        return gr.update(visible=False), gr.update(visible=False)


def handle_refresh_unrecorded(
    template: TemplateConfig | None,
    credentials: Any
) -> tuple:
    """
    Refresh unrecorded data from Google Sheet
    
    Returns:
        Updated preview dataframe and import button visibility
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源并连接 Google 账号")
        return gr.update(), gr.update(visible=False)
    
    try:
        # Load data source config
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return gr.update(), gr.update(visible=False)
        
        # Fetch all rows from sheet
        logger.info(f"Fetching all rows from sheet: {data_source.worksheet_name}")
        
        df = fetch_all_rows(
            credentials,
            data_source.sheet_url,
            data_source.worksheet_name
        )
        
        if df.height == 0:
            gr.Info("Sheet 中没有数据")
            return gr.update(), gr.update(visible=False)
        
        # Convert to preview format (with selection checkboxes)
        # For now, show first 3 columns as preview
        preview_data = []
        for i in range(df.height):
            row = df.row(i, named=True)
            # Get ID column value
            id_val = row.get(data_source.id_column, "")
            # Get preview of other values
            preview_vals = [str(v) for k, v in list(row.items())[:3]]
            preview_str = " | ".join(preview_vals)
            
            preview_data.append([False, str(id_val), preview_str])
        
        gr.Info(f"找到 {len(preview_data)} 行数据")
        
        return (
            gr.update(value=preview_data, visible=True),
            gr.update(visible=True)
        )
        
    except GoogleSheetsError as e:
        gr.Warning(f"获取 Sheet 数据失败：{e}")
        return gr.update(), gr.update(visible=False)
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        gr.Warning(f"刷新失败：{str(e)}")
        return gr.update(), gr.update(visible=False)


def handle_import_selected(
    preview_data: list[list[Any]],
    template: TemplateConfig | None,
    form_data: list[dict[str, str]]
) -> tuple:
    """
    Import selected rows from preview
    
    Returns:
        Updated form_data and row_selector
    """
    if not preview_data or not template:
        return form_data, gr.update()
    
    try:
        # Get selected rows (where first column is True)
        selected_rows = [row for row in preview_data if row[0]]
        
        if not selected_rows:
            gr.Warning("请勾选要导入的行")
            return form_data, gr.update()
        
        # TODO: Use Phi-4 field matcher to map Sheet data to template fields
        # For now, just show count
        gr.Info(f"已导入 {len(selected_rows)} 行数据")
        
        # Update form data
        new_form_data = form_data + []  # Add matched data
        
        # Update row selector
        row_choices = [f"Row {i+1}" for i in range(len(new_form_data))]
        
        return (
            new_form_data,
            gr.update(choices=row_choices, value=row_choices[0] if row_choices else None)
        )
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        gr.Warning(f"导入失败：{str(e)}")
        return form_data, gr.update()


def handle_export(
    template: TemplateConfig | None,
    form_data: list[dict[str, str]]
) -> gr.File:
    """
    Export form data to Excel
    
    Returns:
        File download
    """
    if not template:
        gr.Warning("请先选择模板")
        return None
    
    try:
        # TODO: Implement Excel export using excel_parser
        gr.Info("导出功能开发中...")
        return None
        
    except Exception as e:
        logger.error(f"Export failed: {e}")
        gr.Warning(f"导出失败：{str(e)}")
        return None
