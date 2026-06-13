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


def _find_id_field_key(template_id: str) -> str | None:
    """
    Find the ID field key from paste config
    
    Args:
        template_id: Template identifier
        
    Returns:
        ID field key if found, None otherwise
    """
    paste_config = load_paste_parse_config(template_id)
    if not paste_config:
        return None
    
    for field_key, field_config in paste_config.to_dict().items():
        if isinstance(field_config, list):
            for rule in field_config:
                if isinstance(rule, dict) and rule.get('ID'):
                    return field_key
    
    return None


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
        outputs=[area_selector, form_container, detected_areas_state]
    )
    
    # Refresh button for bulk import
    refresh_btn.click(
        fn=handle_refresh_unrecorded,
        inputs=[current_template, credentials_state, form_data_state],
        outputs=[import_preview, import_btn, refresh_btn]
    )
    
    # Import selected rows
    import_btn.click(
        fn=handle_import_selected,
        inputs=[import_preview, current_template, form_data_state, credentials_state, detected_areas_state],
        outputs=[form_data_state, row_selector, import_preview, import_btn]
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
    """
    Handle sheet selection change
    
    Returns: (area_selector, form_container, detected_areas_state)
    """
    if not sheet_name or not template:
        return gr.update(visible=False), gr.update(visible=False), []
    
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
                        # Show area selector and return detected areas
                        area_choices = [f"区域 {a.index} ({a.area_range})" for a in detected_areas]
                        return (
                            gr.update(choices=area_choices, value=area_choices[0], visible=True),
                            gr.update(visible=True),
                            detected_areas  # Update state with detected areas
                        )
                    else:
                        # Single area detected
                        return (
                            gr.update(visible=False),
                            gr.update(visible=True),
                            detected_areas if detected_areas else []
                        )
                except Exception as e:
                    logger.error(f"Area detection failed: {e}")
                    gr.Warning(f"区域检测失败：{str(e)}")
        
        # Single area or detection failed - show form directly
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            []  # No detected areas
        )
        
    except Exception as e:
        logger.error(f"Sheet change error: {e}")
        gr.Warning(f"切换工作表失败：{str(e)}")
        return gr.update(visible=False), gr.update(visible=False), []


def handle_refresh_unrecorded(
    template: TemplateConfig | None,
    credentials: Any,
    form_data: list[dict[str, str]]
) -> tuple:
    """
    Refresh unrecorded data from Google Sheet
    Filters out IDs that are already in form_data
    
    Returns:
        (import_preview, import_btn, refresh_btn)
    """
    MAX_ROWS = 1000  # Limit to prevent memory issues
    
    if not template or not credentials:
        gr.Warning("请先配置数据源并连接 Google 账号")
        return gr.update(), gr.update(visible=False), gr.update(interactive=True)
    
    try:
        # Load data source config
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return gr.update(), gr.update(visible=False), gr.update(interactive=True)
        
        # Fetch all rows from sheet
        logger.info(f"Fetching all rows from sheet: {data_source.worksheet_name}")
        
        df = fetch_all_rows(
            credentials,
            data_source.sheet_url,
            data_source.worksheet_name
        )
        
        if df.height == 0:
            gr.Info("Sheet 中没有数据")
            return gr.update(), gr.update(visible=False), gr.update(interactive=True)
        
        # Check for large data and warn user
        if df.height > MAX_ROWS:
            gr.Warning(f"数据量过大（{df.height} 行），仅显示前 {MAX_ROWS} 行未录入数据")
        
        # Get list of already-recorded IDs
        recorded_ids = set()
        id_field_key = _find_id_field_key(template.id)
        
        # Extract recorded IDs from form_data
        if id_field_key:
            for row_data in form_data:
                if id_field_key in row_data:
                    recorded_ids.add(str(row_data[id_field_key]))
        
        # Filter unrecorded rows (with limit)
        unrecorded_rows = []
        for i in range(min(df.height, MAX_ROWS * 2)):  # Check up to 2x MAX_ROWS
            if len(unrecorded_rows) >= MAX_ROWS:
                break
                
            row = df.row(i, named=True)
            id_val = str(row.get(data_source.id_column, ""))
            
            if id_val not in recorded_ids:
                # Get preview of values
                preview_vals = [str(v) for k, v in list(row.items())[:3]]
                preview_str = " | ".join(preview_vals)
                
                unrecorded_rows.append([False, id_val, preview_str])
        
        if not unrecorded_rows:
            gr.Info("所有数据均已录入")
            return gr.update(), gr.update(visible=False), gr.update(interactive=True)
        
        info_msg = f"找到 {len(unrecorded_rows)} 行未录入数据"
        if len(unrecorded_rows) >= MAX_ROWS:
            info_msg += f"（已达到显示上限 {MAX_ROWS} 行）"
        gr.Info(info_msg)
        
        return (
            gr.update(value=unrecorded_rows, visible=True),
            gr.update(visible=True),
            gr.update(interactive=True)  # Re-enable refresh button
        )
        
    except GoogleSheetsError as e:
        gr.Warning(f"获取 Sheet 数据失败：{e}")
        return gr.update(), gr.update(visible=False), gr.update(interactive=True)
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        gr.Warning(f"刷新失败：{str(e)}")
        return gr.update(), gr.update(visible=False), gr.update(interactive=True)


def handle_import_selected(
    preview_data: list[list[Any]],
    template: TemplateConfig | None,
    form_data: list[dict[str, str]],
    credentials: Any,
    detected_areas: list
) -> tuple:
    """
    Import selected rows from preview using Phi-4 field matching
    
    Returns:
        (form_data_state, row_selector, import_preview, import_btn)
    """
    if not preview_data or not template:
        return form_data, gr.update(), gr.update(), gr.update(interactive=True)
    
    try:
        # Get selected rows (where first column is True)
        selected_rows = [row for row in preview_data if row[0]]
        
        if not selected_rows:
            gr.Warning("请勾选要导入的行")
            return form_data, gr.update(), gr.update(), gr.update(interactive=True)
        
        # Load data source config and paste config
        from app.services.data_source import load_template_data_source
        from app.services.google_sheets import fetch_row_by_id
        
        data_source = load_template_data_source(template.id)
        if not data_source or not credentials:
            gr.Warning("请先配置数据源")
            return form_data, gr.update(), gr.update(), gr.update(interactive=True)
        
        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            gr.Warning("模板配置加载失败")
            return form_data, gr.update(), gr.update(), gr.update(interactive=True)
        
        # Get field matcher (create new instance each time)
        try:
            field_matcher = create_field_matcher()
        except Exception as e:
            logger.error(f"Failed to create field matcher: {e}")
            gr.Warning(f"字段匹配器加载失败：{str(e)}")
            return form_data, gr.update(), gr.update(), gr.update(interactive=True)
        
        imported_count = 0
        
        # Process each selected row
        for row in selected_rows:
            id_value = str(row[1])  # Second column is ID
            
            # Fetch full row data from Sheet
            sheet_row = fetch_row_by_id(
                credentials,
                data_source.sheet_url,
                data_source.worksheet_name,
                data_source.id_column,
                id_value
            )
            
            if not sheet_row:
                logger.warning(f"Row not found for ID: {id_value}")
                continue
            
            # Use Phi-4 to match fields
            matched_fields = field_matcher.match_sheet_fields_to_yaml(
                sheet_row,
                paste_config.to_dict()
            )
            
            if matched_fields:
                form_data.append(matched_fields)
                imported_count += 1
        
        if imported_count > 0:
            gr.Info(f"✅ 成功导入 {imported_count} 行数据")
        else:
            gr.Warning("未能导入任何数据，请检查配置")
        
        # Update row selector
        row_choices = [f"Row {i+1}" for i in range(len(form_data))]
        
        return (
            form_data,
            gr.update(choices=row_choices, value=row_choices[0] if row_choices else None),
            gr.update(visible=False),  # Hide import preview after import
            gr.update(interactive=True)  # Re-enable import button
        )
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        gr.Warning(f"导入失败：{str(e)}")
        return form_data, gr.update(), gr.update(), gr.update(interactive=True)


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
