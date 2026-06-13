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
from app.services.import_history import (
    load_import_history, mark_as_processed, mark_as_trash, 
    get_import_stats, clear_history
)

logger = logging.getLogger(__name__)

MAX_FORM_FIELDS = 40
COLS_PER_ROW = 11


def resolve_default_sheet_name(
    template: TemplateConfig,
    workbook_sheets: list[str],
) -> str | None:
    """Prefer paste-config worksheet, then template default, then first sheet."""
    paste_config = load_paste_parse_config(template.id)
    preferred: list[str] = []
    if paste_config and paste_config.worksheet:
        preferred.append(paste_config.worksheet)
    if template.sheet_name:
        preferred.append(template.sheet_name)
    for name in preferred:
        target = name.strip().lower()
        for sheet in workbook_sheets:
            if sheet.strip().lower() == target:
                return sheet
    return workbook_sheets[0] if workbook_sheets else None


def get_form_field_headers(template_id: str) -> list[str]:
    """Load editable field names from paste parse config."""
    paste_config = load_paste_parse_config(template_id)
    if not paste_config:
        return []

    headers = [name for name in paste_config.field_rules if name.strip() != "order"]
    if paste_config.order:
        ordered: list[str] = []
        seen: set[str] = set()
        for item in paste_config.order:
            if not isinstance(item, dict):
                continue
            field_name = str(item.get("filed", "")).strip()
            if field_name and field_name in paste_config.field_rules and field_name not in seen:
                ordered.append(field_name)
                seen.add(field_name)
        for header in headers:
            if header not in seen:
                ordered.append(header)
        return ordered
    return headers


def read_area_form_values(
    workbook_path: Path,
    sheet_name: str,
    area_range: str,
    headers: list[str],
) -> dict[str, str]:
    """Read one template row from an Excel area and map values to field headers."""
    from openpyxl import load_workbook

    from app.services.excel_parser import format_cell_display, resolve_sheet_name
    from app.services.section_detector import parse_area_range

    coords = parse_area_range(area_range)
    resolved_sheet = resolve_sheet_name(workbook_path, sheet_name)
    wb = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        ws = wb[resolved_sheet]
        values: dict[str, str] = {}
        area_cols = coords.end_col - coords.start_col + 1
        area_rows = coords.end_row - coords.start_row + 1

        if len(headers) <= area_cols and area_rows == 1:
            for index, header in enumerate(headers):
                cell = ws.cell(coords.start_row, coords.start_col + index)
                values[header] = format_cell_display(cell.value)
            return values

        pos = 0
        for row_idx in range(coords.start_row, coords.end_row + 1):
            for col_idx in range(coords.start_col, coords.end_col + 1):
                if pos >= len(headers):
                    return values
                cell = ws.cell(row_idx, col_idx)
                values[headers[pos]] = format_cell_display(cell.value)
                pos += 1
        return values
    finally:
        wb.close()


def _empty_field_updates() -> list[gr.update]:
    return [gr.update(visible=False) for _ in range(MAX_FORM_FIELDS)]


def _build_field_updates(
    headers: list[str],
    row_values: dict[str, str],
) -> tuple[list[gr.update], gr.update]:
    updates: list[gr.update] = []
    for index in range(MAX_FORM_FIELDS):
        if index < len(headers):
            header = headers[index]
            updates.append(
                gr.update(
                    label=header,
                    value=row_values.get(header, ""),
                    visible=True,
                    interactive=True,
                )
            )
        else:
            updates.append(gr.update(visible=False))
    status = gr.update(
        value=f"已加载 {len(headers)} 个字段",
        visible=len(headers) == 0,
    )
    return updates, status


def _area_index_from_choice(area_choice: str | None) -> int:
    if not area_choice:
        return 0
    if area_choice.startswith("区域 "):
        try:
            return max(int(area_choice.split()[1]) - 1, 0)
        except (IndexError, ValueError):
            return 0
    return 0


def _inactive_form_refresh(form_data: list[dict[str, str]]) -> tuple:
    field_updates = _empty_field_updates()
    return (
        gr.update(visible=False),
        gr.update(visible=False),
        [],
        form_data,
        gr.update(choices=[], value=None),
        gr.update(value="请先选择模板和工作表", visible=True),
        *field_updates,
    )


def refresh_data_entry_form(
    template: TemplateConfig | None,
    sheet_name: str | None,
    area_choice: str | None,
    form_data: list[dict[str, str]],
) -> tuple:
    """
    Detect areas and populate dynamic form fields from paste/sections config.

    Returns updates for:
    area_selector, form_container, detected_areas_state, form_data_state,
    row_selector, fields_status, *form_field_boxes
    """
    if not template or not sheet_name:
        return _inactive_form_refresh(form_data)

    headers = get_form_field_headers(template.id)
    if not headers:
        gr.Warning("未找到字段配置，请先在「参数配置」中保存 YAML 或区域配置")
        inactive = _inactive_form_refresh(form_data)
        return (
            inactive[0],
            gr.update(visible=True),
            inactive[2],
            inactive[3],
            inactive[4],
            gr.update(value="未找到字段配置，请先在「参数配置」中保存配置", visible=True),
            *inactive[6:],
        )

    paste_config = load_paste_parse_config(template.id)
    detected_areas = []
    area_selector_update = gr.update(visible=False)
    active_area_range: str | None = None

    if paste_config and paste_config.sections:
        sections = parse_sections_from_yaml({"sections": paste_config.sections})
        if sections:
            try:
                detected_areas = detect_multi_areas(
                    Path(template.file_path),
                    sheet_name,
                    sections[0],
                )
            except Exception as exc:
                logger.error(f"Area detection failed: {exc}")
                gr.Warning(f"区域检测失败：{exc}")

    if detected_areas:
        if len(detected_areas) > 1:
            area_choices = [f"区域 {area.index} ({area.area})" for area in detected_areas]
            selected_choice = area_choice if area_choice in area_choices else area_choices[0]
            area_selector_update = gr.update(
                choices=area_choices,
                value=selected_choice,
                visible=True,
            )
            area_index = _area_index_from_choice(selected_choice)
        else:
            area_selector_update = gr.update(visible=False)
            area_index = 0
        if 0 <= area_index < len(detected_areas):
            active_area_range = detected_areas[area_index].area
    elif paste_config and paste_config.sections:
        section = paste_config.sections[0]
        active_area_range = str(section.get("input_area", "")).strip() or None

    row_values: dict[str, str] = {header: "" for header in headers}
    if active_area_range:
        try:
            row_values = read_area_form_values(
                Path(template.file_path),
                sheet_name,
                active_area_range,
                headers,
            )
        except Exception as exc:
            logger.error(f"Failed to read area values: {exc}")
            gr.Warning(f"读取区域数据失败：{exc}")

    form_data = [row_values]
    field_updates, status_update = _build_field_updates(headers, row_values)
    return (
        area_selector_update,
        gr.update(visible=True),
        detected_areas,
        form_data,
        gr.update(choices=["Row 1"], value="Row 1"),
        status_update,
        *field_updates,
    )


def update_import_stats(template: TemplateConfig | None) -> str:
    """
    Update import statistics display
    
    Returns:
        Markdown formatted stats
    """
    if not template:
        return "📊 导入统计：未选择模板"
    
    try:
        stats = get_import_stats(template.id)
        
        last_import = stats.get("last_import", "从未")
        if last_import != "从未":
            from datetime import datetime
            dt = datetime.fromisoformat(last_import)
            last_import = dt.strftime("%Y-%m-%d %H:%M")
        
        return (
            f"📊 **导入统计** | "
            f"已处理: **{stats['processed_count']}** | "
            f"垃圾数据: **{stats['trash_count']}** | "
            f"最后导入: {last_import}"
        )
    except Exception as e:
        logger.error(f"Failed to get import stats: {e}")
        return "📊 导入统计：加载失败"


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
            
            fields_status = gr.Markdown("字段加载中...", visible=True)
            components["fields_status"] = fields_status

            form_field_boxes: list[gr.Textbox] = []
            with gr.Column() as fields_container:
                for index in range(MAX_FORM_FIELDS):
                    field_box = gr.Textbox(
                        label=f"字段 {index + 1}",
                        visible=False,
                        interactive=True,
                    )
                    form_field_boxes.append(field_box)

            components["form_field_boxes"] = form_field_boxes
            components["fields_container"] = fields_container
        
        components["form_container"] = form_container
        
        # Bulk import section
        with gr.Accordion("批量导入", open=False) as bulk_import_accordion:
            # Import history stats
            with gr.Row():
                import_stats = gr.Markdown("📊 导入统计：加载中...")
            
            with gr.Row():
                refresh_btn = gr.Button("🔄 刷新未处理数据")
                show_processed_btn = gr.Button("📝 查看已处理", variant="secondary")
                show_trash_btn = gr.Button("🗑️ 查看垃圾数据", variant="secondary")
            
            import_preview = gr.Dataframe(
                headers=["选择", "ID", "状态", "数据预览"],
                datatype=["bool", "str", "str", "str"],
                interactive=True,
                wrap=True,
                visible=False
            )
            
            with gr.Row():
                import_btn = gr.Button(
                    "✅ 导入选中行",
                    variant="primary",
                    visible=False
                )
                
                mark_trash_btn = gr.Button(
                    "🗑️ 标记为垃圾",
                    variant="secondary",
                    visible=False
                )
                
                clear_history_btn = gr.Button(
                    "🧹 清空历史",
                    variant="stop",
                    visible=False,
                    size="sm"
                )
        
        components["import_stats"] = import_stats
        components["refresh_btn"] = refresh_btn
        components["show_processed_btn"] = show_processed_btn
        components["show_trash_btn"] = show_trash_btn
        components["import_preview"] = import_preview
        components["import_btn"] = import_btn
        components["mark_trash_btn"] = mark_trash_btn
        components["clear_history_btn"] = clear_history_btn
        
        # Action buttons
        with gr.Row():
            export_btn = gr.Button("导出 Excel", variant="primary")
            print_btn = gr.Button("打印预览")
        
        components["export_btn"] = export_btn
        components["print_btn"] = print_btn
    
    # Event bindings
    
    # Load import stats when template changes
    current_template.change(
        fn=update_import_stats,
        inputs=[current_template],
        outputs=[import_stats]
    )
    
    form_refresh_outputs = [
        area_selector,
        form_container,
        detected_areas_state,
        form_data_state,
        row_selector,
        fields_status,
        *form_field_boxes,
    ]

    sheet_selector.change(
        fn=refresh_data_entry_form,
        inputs=[current_template, sheet_selector, area_selector, form_data_state],
        outputs=form_refresh_outputs,
    )

    area_selector.change(
        fn=refresh_data_entry_form,
        inputs=[current_template, sheet_selector, area_selector, form_data_state],
        outputs=form_refresh_outputs,
    )
    
    # Refresh button for bulk import
    refresh_btn.click(
        fn=handle_refresh_unrecorded,
        inputs=[current_template, credentials_state, form_data_state],
        outputs=[import_preview, import_btn, mark_trash_btn, clear_history_btn, refresh_btn, import_stats]
    )
    
    # Show processed data
    show_processed_btn.click(
        fn=handle_show_processed,
        inputs=[current_template, credentials_state],
        outputs=[import_preview, import_btn, mark_trash_btn, clear_history_btn]
    )
    
    # Show trash data
    show_trash_btn.click(
        fn=handle_show_trash,
        inputs=[current_template, credentials_state],
        outputs=[import_preview, import_btn, mark_trash_btn, clear_history_btn]
    )
    
    # Import selected rows
    import_btn.click(
        fn=handle_import_selected,
        inputs=[import_preview, current_template, form_data_state, credentials_state, detected_areas_state],
        outputs=[form_data_state, row_selector, import_preview, import_btn, mark_trash_btn, import_stats]
    )
    
    # Mark as trash
    mark_trash_btn.click(
        fn=handle_mark_trash,
        inputs=[import_preview, current_template],
        outputs=[import_preview, mark_trash_btn, import_stats]
    )
    
    # Clear history
    clear_history_btn.click(
        fn=handle_clear_history,
        inputs=[current_template],
        outputs=[import_stats]
    )
    
    # Export button
    export_btn.click(
        fn=handle_export,
        inputs=[current_template, form_data_state],
        outputs=[gr.File()]
    )
    
    components["form_refresh_outputs"] = form_refresh_outputs
    components["update_on_template_change"] = [sheet_selector]

    return components


def handle_refresh_unrecorded(
    template: TemplateConfig | None,
    credentials: Any,
    form_data: list[dict[str, str]]
) -> tuple:
    """
    Refresh unrecorded data from Google Sheet
    Filters out processed IDs and trash IDs
    
    Returns:
        (import_preview, import_btn, mark_trash_btn, clear_history_btn, refresh_btn, import_stats)
    """
    MAX_ROWS = 1000  # Limit to prevent memory issues
    
    if not template or not credentials:
        gr.Warning("请先配置数据源并连接 Google 账号")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template)
        )
    
    try:
        # Load data source config and import history
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        # Load import history
        history = load_import_history(template.id)
        
        # Fetch all rows from sheet
        logger.info(f"Fetching all rows from sheet: {data_source.worksheet_name}")
        
        df = fetch_all_rows(
            credentials,
            data_source.sheet_url,
            data_source.worksheet_name
        )
        
        if df.height == 0:
            gr.Info("Sheet 中没有数据")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        # Check for large data and warn user
        if df.height > MAX_ROWS:
            gr.Warning(f"数据量过大（{df.height} 行），仅显示前 {MAX_ROWS} 行未录入数据")
        
        # Filter unrecorded rows (exclude processed and trash)
        unrecorded_rows = []
        for i in range(min(df.height, MAX_ROWS * 2)):
            if len(unrecorded_rows) >= MAX_ROWS:
                break
                
            row = df.row(i, named=True)
            id_val = str(row.get(data_source.id_column, ""))
            
            # Skip if processed or trash
            if id_val in history.processed_ids:
                continue
            if id_val in history.trash_ids:
                continue
            
            # Get preview of values
            preview_vals = [str(v) for k, v in list(row.items())[:3]]
            preview_str = " | ".join(preview_vals)
            
            unrecorded_rows.append([False, id_val, "新数据", preview_str])
        
        if not unrecorded_rows:
            gr.Info("所有数据均已处理或标记")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        info_msg = f"找到 {len(unrecorded_rows)} 行未处理数据"
        if len(unrecorded_rows) >= MAX_ROWS:
            info_msg += f"（已达到显示上限 {MAX_ROWS} 行）"
        gr.Info(info_msg)
        
        return (
            gr.update(value=unrecorded_rows, visible=True),
            gr.update(visible=True),  # import_btn
            gr.update(visible=True),  # mark_trash_btn
            gr.update(visible=True),  # clear_history_btn
            gr.update(interactive=True),  # refresh_btn
            update_import_stats(template)
        )
        
    except GoogleSheetsError as e:
        gr.Warning(f"获取 Sheet 数据失败：{e}")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template)
        )
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        gr.Warning(f"刷新失败：{str(e)}")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template)
        )


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
        (form_data_state, row_selector, import_preview, import_btn, mark_trash_btn, import_stats)
    """
    if not preview_data or not template:
        return (
            form_data, 
            gr.update(), 
            gr.update(), 
            gr.update(interactive=True), 
            gr.update(interactive=True),
            update_import_stats(template)
        )
    
    try:
        # Get selected rows (where first column is True)
        selected_rows = [row for row in preview_data if row[0]]
        
        if not selected_rows:
            gr.Warning("请勾选要导入的行")
            return (
                form_data, 
                gr.update(), 
                gr.update(), 
                gr.update(interactive=True), 
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        # Load data source config and paste config
        from app.services.data_source import load_template_data_source
        from app.services.google_sheets import fetch_row_by_id
        
        data_source = load_template_data_source(template.id)
        if not data_source or not credentials:
            gr.Warning("请先配置数据源")
            return (
                form_data, 
                gr.update(), 
                gr.update(), 
                gr.update(interactive=True), 
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            gr.Warning("模板配置加载失败")
            return (
                form_data, 
                gr.update(), 
                gr.update(), 
                gr.update(interactive=True), 
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        # Get field matcher (create new instance each time)
        try:
            field_matcher = create_field_matcher()
        except Exception as e:
            logger.error(f"Failed to create field matcher: {e}")
            gr.Warning(f"字段匹配器加载失败：{str(e)}")
            return (
                form_data, 
                gr.update(), 
                gr.update(), 
                gr.update(interactive=True), 
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        imported_count = 0
        imported_ids = []
        
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
                imported_ids.append(id_value)
                imported_count += 1
        
        # Mark imported IDs as processed
        if imported_ids:
            mark_as_processed(template.id, imported_ids)
        
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
            gr.update(interactive=True),  # Re-enable import button
            gr.update(interactive=True),  # Re-enable mark trash button
            update_import_stats(template)
        )
        
    except Exception as e:
        logger.error(f"Import failed: {e}")
        gr.Warning(f"导入失败：{str(e)}")
        return (
            form_data, 
            gr.update(), 
            gr.update(), 
            gr.update(interactive=True), 
            gr.update(interactive=True),
            update_import_stats(template)
        )


def handle_show_processed(
    template: TemplateConfig | None,
    credentials: Any
) -> tuple:
    """
    Show processed data
    
    Returns:
        (import_preview, import_btn, mark_trash_btn, clear_history_btn)
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源")
        return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
    
    try:
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
        
        history = load_import_history(template.id)
        
        if not history.processed_ids:
            gr.Info("没有已处理的数据")
            return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
        
        # Fetch processed rows
        df = fetch_all_rows(credentials, data_source.sheet_url, data_source.worksheet_name)
        
        processed_rows = []
        for i in range(df.height):
            row = df.row(i, named=True)
            id_val = str(row.get(data_source.id_column, ""))
            
            if id_val in history.processed_ids:
                preview_vals = [str(v) for k, v in list(row.items())[:3]]
                preview_str = " | ".join(preview_vals)
                processed_rows.append([False, id_val, "已处理", preview_str])
        
        gr.Info(f"找到 {len(processed_rows)} 行已处理数据")
        
        return (
            gr.update(value=processed_rows, visible=True),
            gr.update(visible=False),  # Hide import button
            gr.update(visible=False),  # Hide mark trash button
            gr.update(visible=True)    # Show clear history button
        )
    except Exception as e:
        logger.error(f"Show processed failed: {e}")
        gr.Warning(f"加载失败：{str(e)}")
        return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)


def handle_show_trash(
    template: TemplateConfig | None,
    credentials: Any
) -> tuple:
    """
    Show trash data
    
    Returns:
        (import_preview, import_btn, mark_trash_btn, clear_history_btn)
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源")
        return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
    
    try:
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
        
        history = load_import_history(template.id)
        
        if not history.trash_ids:
            gr.Info("没有垃圾数据")
            return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
        
        # Fetch trash rows
        df = fetch_all_rows(credentials, data_source.sheet_url, data_source.worksheet_name)
        
        trash_rows = []
        for i in range(df.height):
            row = df.row(i, named=True)
            id_val = str(row.get(data_source.id_column, ""))
            
            if id_val in history.trash_ids:
                preview_vals = [str(v) for k, v in list(row.items())[:3]]
                preview_str = " | ".join(preview_vals)
                trash_rows.append([False, id_val, "垃圾", preview_str])
        
        gr.Info(f"找到 {len(trash_rows)} 行垃圾数据")
        
        return (
            gr.update(value=trash_rows, visible=True),
            gr.update(visible=False),  # Hide import button
            gr.update(visible=False),  # Hide mark trash button
            gr.update(visible=True)    # Show clear history button
        )
    except Exception as e:
        logger.error(f"Show trash failed: {e}")
        gr.Warning(f"加载失败：{str(e)}")
        return gr.update(), gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)


def handle_mark_trash(
    preview_data: list[list[Any]],
    template: TemplateConfig | None
) -> tuple:
    """
    Mark selected rows as trash
    
    Returns:
        (import_preview, mark_trash_btn, import_stats)
    """
    if not preview_data or not template:
        return gr.update(), gr.update(interactive=True), update_import_stats(template)
    
    try:
        # Get selected rows
        selected_rows = [row for row in preview_data if row[0]]
        
        if not selected_rows:
            gr.Warning("请勾选要标记的行")
            return gr.update(), gr.update(interactive=True), update_import_stats(template)
        
        # Extract IDs
        ids_to_mark = [str(row[1]) for row in selected_rows]
        
        # Mark as trash
        if mark_as_trash(template.id, ids_to_mark):
            gr.Info(f"✅ 已标记 {len(ids_to_mark)} 行为垃圾数据")
            
            # Remove marked rows from preview
            remaining_rows = [row for row in preview_data if row[1] not in ids_to_mark]
            
            return (
                gr.update(value=remaining_rows, visible=len(remaining_rows) > 0),
                gr.update(interactive=True),
                update_import_stats(template)
            )
        else:
            gr.Warning("标记失败")
            return gr.update(), gr.update(interactive=True), update_import_stats(template)
            
    except Exception as e:
        logger.error(f"Mark trash failed: {e}")
        gr.Warning(f"标记失败：{str(e)}")
        return gr.update(), gr.update(interactive=True), update_import_stats(template)


def handle_clear_history(template: TemplateConfig | None) -> str:
    """
    Clear import history
    
    Returns:
        Updated stats markdown
    """
    if not template:
        return "📊 导入统计：未选择模板"
    
    try:
        if clear_history(template.id):
            gr.Info("✅ 已清空导入历史")
        else:
            gr.Warning("清空失败")
        
        return update_import_stats(template)
    except Exception as e:
        logger.error(f"Clear history failed: {e}")
        gr.Warning(f"清空失败：{str(e)}")
        return update_import_stats(template)


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
