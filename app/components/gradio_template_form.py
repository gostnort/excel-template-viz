"""
Gradio Template Form Component

Handles dynamic form rendering, area selection, ID lookup, and bulk import.
"""
import gradio as gr
import logging
import polars as pl
from pathlib import Path
from typing import Any

from app.services.registry import TemplateConfig
from app.services.excel_parser import list_sheet_names, read_template_sheet
from app.services.paste_parse_config import (
    load_paste_parse_config,
    map_sheet_row_from_paste_config,
    parse_text_with_config,
    structural_order_col_offset,
    DEFAULT_FIELDS_PER_ROW,
)
from app.services.google_sheets import (
    fetch_all_rows,
    GoogleSheetsError,
    invalidate_sheet_cache,
    lookup_row_by_id,
)
from app.services.gemma4_field_matcher import create_field_matcher
from app.services.import_history import (
    load_import_history, mark_as_processed, mark_as_trash,
    unmark_ids, get_import_stats, clear_history,
)

logger = logging.getLogger(__name__)

MAX_FORM_FIELDS = 40
MAX_IMPORT_PREVIEW_ROWS = 1000
HIDE_PROGRESS = {"show_progress": "hidden"}


def _get_template_id(template: TemplateConfig | dict[str, Any] | None) -> str | None:
    """Resolve template id from TemplateConfig or Gradio state dict."""
    if template is None:
        return None
    if isinstance(template, dict):
        template_id = template.get("id")
        return str(template_id) if template_id else None
    return getattr(template, "id", None)


def _normalize_preview_rows(preview_data: Any) -> list[list[Any]]:
    """Convert Gradio Dataframe input (pandas, etc.) to list of row lists."""
    if preview_data is None:
        return []

    import pandas as pd

    if isinstance(preview_data, pd.DataFrame):
        return [] if preview_data.empty else preview_data.values.tolist()

    import numpy as np

    if isinstance(preview_data, np.ndarray):
        return [] if preview_data.size == 0 else preview_data.tolist()

    try:
        import polars as pl

        if isinstance(preview_data, pl.DataFrame):
            return [] if preview_data.is_empty() else preview_data.rows()
    except ImportError:
        pass

    if isinstance(preview_data, list):
        if not preview_data:
            return []
        if isinstance(preview_data[0], list):
            return preview_data
        return [preview_data]

    return []


def _is_row_selected(row: list[Any]) -> bool:
    """Check whether the first column (checkbox) is selected."""
    if not row:
        return False
    value = row[0]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _format_last_import(last_import: Any) -> str:
    """Format last_import timestamp for display, falling back on parse errors."""
    if not last_import:
        return "从未"
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(str(last_import).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(last_import)


def _field_row_count(fields_per_row: int = DEFAULT_FIELDS_PER_ROW) -> int:
    return (MAX_FORM_FIELDS + fields_per_row - 1) // fields_per_row


# UI row layout is fixed at build time; row updates must use the same grouping.
FORM_LAYOUT_FIELDS_PER_ROW = DEFAULT_FIELDS_PER_ROW
FORM_ROW_COUNT = _field_row_count(FORM_LAYOUT_FIELDS_PER_ROW)
_NO_CHANGE_FIELD_UPDATES = tuple(gr.update() for _ in range(MAX_FORM_FIELDS))


def form_refresh_output_count() -> int:
    """Expected tuple length for refresh_data_entry_form / form_refresh_outputs."""
    return 6 + FORM_ROW_COUNT + MAX_FORM_FIELDS


def get_fields_per_row(template_id: str) -> int:
    """Load fields-per-row layout from paste config (default 7)."""
    paste_config = load_paste_parse_config(template_id)
    if paste_config is None:
        return DEFAULT_FIELDS_PER_ROW
    return paste_config.fields_per_row


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


def _resolve_field_header_name(
    filed: str,
    field_rules: dict[str, list],
) -> str | None:
    """Map a paste-config filed value to the form header name."""
    filed_stripped = filed.strip()
    if not filed_stripped or filed_stripped == "?":
        return None
    if filed_stripped in field_rules:
        return filed_stripped
    filed_lower = filed_stripped.lower()
    for field_name, rules in field_rules.items():
        for rule in rules:
            rule_filed = str(rule.filed).strip()
            if rule_filed == filed_stripped or rule_filed.lower() == filed_lower:
                return field_name
    return filed_stripped


def get_form_field_headers(template_id: str) -> list[str]:
    """Load form field names from paste parse config, including structural ``order`` when configured."""
    paste_config = load_paste_parse_config(template_id)
    if not paste_config:
        return []
    headers = list(paste_config.field_rules.keys())
    if structural_order_col_offset(paste_config.order) == 1:
        return ["order", *headers]
    return headers


def read_area_form_values(
    workbook_path: Path,
    sheet_name: str,
    area_range: str,
    headers: list[str],
    *,
    col_offset: int = 0,
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
                cell = ws.cell(coords.start_row, coords.start_col + col_offset + index)
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


def _empty_row_updates() -> list[gr.update]:
    return [gr.update(visible=False) for _ in range(FORM_ROW_COUNT)]


def _build_row_updates(headers: list[str]) -> list[gr.update]:
    """Show gr.Row containers when any child field slot in that row is active."""
    updates: list[gr.update] = []
    for row_idx in range(FORM_ROW_COUNT):
        row_start = row_idx * FORM_LAYOUT_FIELDS_PER_ROW
        row_end = min(row_start + FORM_LAYOUT_FIELDS_PER_ROW, MAX_FORM_FIELDS)
        has_visible = any(index < len(headers) for index in range(row_start, row_end))
        updates.append(gr.update(visible=has_visible))
    return updates


def _resolve_row_index(row_selector_value: str | None, form_data_len: int) -> int:
    if form_data_len <= 0:
        return 0
    if row_selector_value and row_selector_value.startswith("Row "):
        try:
            return max(0, min(form_data_len - 1, int(row_selector_value[4:].strip()) - 1))
        except ValueError:
            pass
    return 0


def _row_values_for_headers(headers: list[str], row_dict: dict[str, str]) -> dict[str, str]:
    return {header: row_dict.get(header, "") for header in headers}


def _field_updates_for_row(headers: list[str], row_values: dict[str, str]) -> list[gr.update]:
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
    return updates


def _paste_input_update(headers: list[str], *, interactive: bool = True) -> gr.update:
    count = len(headers)
    placeholder = "粘贴 Tab 分隔的一行（可从 Excel 复制）"
    if count:
        placeholder += "；填入「选择行」当前行，未选则第 1 行"
    return gr.update(
        value="",
        visible=count > 0,
        interactive=interactive,
        placeholder=placeholder,
        label=f"粘贴数据（已配置 {count} 个字段）" if count else "粘贴数据",
    )


def _should_parse_paste(paste_text: str) -> bool:
    stripped = (paste_text or "").strip()
    if not stripped:
        return False
    return "\t" in stripped or "\n" in stripped


def _build_field_updates(
    headers: list[str],
    row_values: dict[str, str],
) -> tuple[list[gr.update], list[gr.update], gr.update]:
    updates = _field_updates_for_row(headers, row_values)
    row_updates = _build_row_updates(headers)
    paste_update = _paste_input_update(headers)
    return updates, row_updates, paste_update


def _inactive_form_refresh(form_data: list[dict[str, str]]) -> tuple:
    field_updates = _empty_field_updates()
    row_updates = _empty_row_updates()
    return (
        gr.update(visible=False),
        [],
        form_data,
        gr.update(choices=[], value=None),
        gr.update(value="", visible=False, interactive=True),
        gr.update(visible=False),
        *row_updates,
        *field_updates,
    )


def refresh_data_entry_form(
    template: TemplateConfig | None,
    sheet_name: str | None,
    form_data: list[dict[str, str]],
) -> tuple:
    """
    Detect areas and populate dynamic form fields from paste/sections config.

    Returns updates for:
    form_container, detected_areas_state, form_data_state,
    row_selector, paste_input, fields_container, *field_rows, *form_field_boxes
    """
    if not template or not sheet_name:
        return _inactive_form_refresh(form_data)

    headers = get_form_field_headers(template.id)
    if not headers:
        gr.Warning("未找到字段配置，请先在「参数配置」中保存 YAML 或区域配置")
        inactive = _inactive_form_refresh(form_data)
        return (
            gr.update(visible=True),
            inactive[1],
            inactive[2],
            inactive[3],
            gr.update(value="", visible=False, interactive=True),
            gr.update(visible=False),
            *inactive[6:],
        )

    paste_config = load_paste_parse_config(template.id)
    detected_areas = []
    active_area_range: str | None = None

    if paste_config and paste_config.sections:
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
    field_updates, row_updates, status_update = _build_field_updates(headers, row_values)
    return (
        gr.update(visible=True),
        detected_areas,
        form_data,
        gr.update(choices=["Row 1"], value="Row 1"),
        status_update,
        gr.update(visible=True),
        *row_updates,
        *field_updates,
    )


def _begin_paste_parse() -> gr.update:
    return gr.update(interactive=False)


def apply_pasted_form_data(
    template: TemplateConfig | None,
    paste_text: str,
    form_data: list[dict[str, str]],
    row_selector_value: str | None,
) -> tuple:
    """Parse tab-separated paste text and fill form rows using paste YAML index rules."""
    headers = get_form_field_headers(template.id) if template else []
    if not template:
        gr.Warning("请先选择模板")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    if not headers:
        gr.Warning("未找到字段配置")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    if not _should_parse_paste(paste_text):
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    paste_config = load_paste_parse_config(template.id)
    if not paste_config:
        gr.Warning("模板粘贴配置加载失败")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    try:
        parsed_rows = parse_text_with_config(paste_text.strip(), paste_config)
    except ValueError as exc:
        gr.Warning(f"解析失败：{exc}")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    if not parsed_rows:
        gr.Warning("未能解析粘贴数据")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    has_values = any(
        value
        for row in parsed_rows
        for key, value in row.items()
        if key != "order" and str(value).strip()
    )
    if not has_values:
        gr.Warning("粘贴数据未匹配任何字段，请检查 YAML index 配置")
        return form_data, gr.update(), gr.update(interactive=True), *_NO_CHANGE_FIELD_UPDATES
    if not form_data:
        form_data = [{header: "" for header in headers}]
    target_idx = _resolve_row_index(row_selector_value, len(form_data))
    for offset, parsed in enumerate(parsed_rows):
        row_idx = target_idx + offset
        while len(form_data) <= row_idx:
            form_data.append({header: "" for header in headers})
        form_data[row_idx] = _row_values_for_headers(headers, parsed)
    row_choices = [f"Row {index + 1}" for index in range(len(form_data))]
    selected_row = f"Row {target_idx + 1}"
    field_updates = _field_updates_for_row(headers, form_data[target_idx])
    gr.Info(f"已填充 {len(parsed_rows)} 行数据到表单")
    return (
        form_data,
        gr.update(choices=row_choices, value=selected_row),
        gr.update(value="", interactive=True),
        *field_updates,
    )


def sync_form_fields_to_row(
    template: TemplateConfig | None,
    row_selector_value: str | None,
    form_data: list[dict[str, str]],
) -> tuple:
    """Show the selected form row in field textboxes."""
    if not template:
        return _empty_field_updates()
    headers = get_form_field_headers(template.id)
    if not headers:
        return _empty_field_updates()
    if not form_data:
        return tuple(_field_updates_for_row(headers, {header: "" for header in headers}))
    target_idx = _resolve_row_index(row_selector_value, len(form_data))
    row_values = _row_values_for_headers(headers, form_data[target_idx])
    return tuple(_field_updates_for_row(headers, row_values))


def update_import_stats(template: TemplateConfig | dict[str, Any] | None) -> str:
    """
    Update import statistics display
    
    Returns:
        Markdown formatted stats
    """
    template_id = _get_template_id(template)
    if not template_id:
        return "📊 导入统计：未选择模板"
    
    try:
        stats = get_import_stats(template_id)
        last_import = _format_last_import(stats.get("last_import"))
        
        return (
            f"📊 **导入统计** | "
            f"已处理: **{stats['processed_count']}** | "
            f"垃圾数据: **{stats['trash_count']}** | "
            f"最后导入: {last_import}"
        )
    except Exception as e:
        logger.error(f"Failed to get import stats: {e}")
        return "📊 导入统计：加载失败"


def _begin_bulk_refresh() -> tuple[Any, str]:
    """Fast UI feedback before a Google Sheet fetch."""
    return (
        gr.update(interactive=False),
        "📊 **导入统计** | 正在从 Google Sheet 加载数据...",
    )


def _preview_columns(df: pl.DataFrame, id_column: str, limit: int = 3) -> list[str]:
    return [column for column in df.columns if column != id_column][:limit]


def _build_import_preview_rows(
    df: pl.DataFrame,
    id_column: str,
    include_ids: set[str] | None,
    exclude_ids: set[str] | None,
    status_label: str,
    max_rows: int,
) -> list[list[Any]]:
    if df.height == 0 or id_column not in df.columns:
        return []

    id_expr = pl.col(id_column).cast(pl.Utf8).str.strip_chars()
    filtered = df
    if include_ids is not None:
        filtered = filtered.filter(id_expr.is_in(list(include_ids)))
    if exclude_ids:
        filtered = filtered.filter(~id_expr.is_in(list(exclude_ids)))

    preview_cols = _preview_columns(df, id_column)
    rows: list[list[Any]] = []
    for record in filtered.head(max_rows).iter_rows(named=True):
        id_val = str(record.get(id_column, ""))
        preview_vals = [str(record.get(column, "")) for column in preview_cols]
        rows.append([False, id_val, status_label, " | ".join(preview_vals)])
    return rows


def _load_template_sheet_df(
    credentials: Any,
    data_source: Any,
    *,
    force_refresh: bool = False,
) -> pl.DataFrame:
    return fetch_all_rows(
        credentials,
        data_source.sheet_url,
        data_source.worksheet_name,
        force_refresh=force_refresh,
    )


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
    import_view_state = gr.State("unprocessed")
    components["import_view_state"] = import_view_state
    
    with gr.Column():
        # Sheet selector
        sheet_selector = gr.Dropdown(
            label="选择工作表",
            choices=[],
            value=None,
            interactive=True
        )
        components["sheet_selector"] = sheet_selector
        
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
            
            paste_input = gr.Textbox(
                label="粘贴数据",
                placeholder="粘贴 Tab 分隔的一行（可从 Excel 复制）；填入「选择行」当前行，未选则第 1 行",
                lines=2,
                max_lines=6,
                visible=False,
                interactive=True,
            )
            components["paste_input"] = paste_input

            form_field_boxes: list[gr.Textbox] = []
            field_rows: list[gr.Row] = []
            # Row/column shells stay visible; only textbox slots toggle via refresh updates.
            with gr.Column(visible=True) as fields_container:
                for row_start in range(0, MAX_FORM_FIELDS, FORM_LAYOUT_FIELDS_PER_ROW):
                    with gr.Row(visible=True) as field_row:
                        field_rows.append(field_row)
                        row_end = min(row_start + FORM_LAYOUT_FIELDS_PER_ROW, MAX_FORM_FIELDS)
                        for index in range(row_start, row_end):
                            field_box = gr.Textbox(
                                label=f"字段 {index + 1}",
                                visible=False,
                                interactive=True,
                                scale=1,
                                min_width=100,
                            )
                            form_field_boxes.append(field_box)

            components["form_field_boxes"] = form_field_boxes
            components["field_rows"] = field_rows
            components["fields_container"] = fields_container
        
        components["form_container"] = form_container
        
        # Action buttons
        with gr.Row():
            export_btn = gr.Button("导出 Excel", variant="primary")
            print_btn = gr.Button("打印预览")
        
        components["export_btn"] = export_btn
        components["print_btn"] = print_btn
        
        # Bulk import section (always visible; no gr.Group — avoids Gradio panel background)
        gr.Markdown("## 批量导入")
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
            
            restore_btn = gr.Button(
                "↩️ 恢复为未处理",
                variant="secondary",
                visible=False,
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
        components["restore_btn"] = restore_btn
        components["clear_history_btn"] = clear_history_btn
    
    # Event bindings
    
    # Load import stats when template changes
    current_template.change(
        fn=update_import_stats,
        inputs=[current_template],
        outputs=[import_stats],
        **HIDE_PROGRESS,
    )
    
    form_refresh_outputs = [
        form_container,
        detected_areas_state,
        form_data_state,
        row_selector,
        paste_input,
        fields_container,
        *field_rows,
        *form_field_boxes,
    ]

    sheet_selector.change(
        fn=refresh_data_entry_form,
        inputs=[current_template, sheet_selector, form_data_state],
        outputs=form_refresh_outputs,
        **HIDE_PROGRESS,
    )

    paste_apply_outputs = [form_data_state, row_selector, paste_input, *form_field_boxes]

    row_selector.change(
        fn=sync_form_fields_to_row,
        inputs=[current_template, row_selector, form_data_state],
        outputs=form_field_boxes,
        **HIDE_PROGRESS,
    )

    paste_input.submit(
        fn=_begin_paste_parse,
        outputs=[paste_input],
        **HIDE_PROGRESS,
    ).then(
        fn=apply_pasted_form_data,
        inputs=[current_template, paste_input, form_data_state, row_selector],
        outputs=paste_apply_outputs,
        **HIDE_PROGRESS,
    )

    paste_input.change(
        fn=_begin_paste_parse,
        outputs=[paste_input],
        **HIDE_PROGRESS,
    ).then(
        fn=apply_pasted_form_data,
        inputs=[current_template, paste_input, form_data_state, row_selector],
        outputs=paste_apply_outputs,
        **HIDE_PROGRESS,
    )
    
    # Refresh button for bulk import: fast UI feedback, then sheet fetch
    refresh_btn.click(
        fn=_begin_bulk_refresh,
        outputs=[refresh_btn, import_stats],
        **HIDE_PROGRESS,
    ).then(
        fn=handle_refresh_unrecorded,
        inputs=[current_template, credentials_state, form_data_state],
        outputs=[
            import_preview, import_btn, mark_trash_btn, restore_btn,
            clear_history_btn, refresh_btn, import_stats, import_view_state,
        ],
        **HIDE_PROGRESS,
    )
    
    # Show processed data
    show_processed_btn.click(
        fn=handle_show_processed,
        inputs=[current_template, credentials_state],
        outputs=[
            import_preview, import_btn, mark_trash_btn, restore_btn,
            clear_history_btn, import_view_state,
        ],
        **HIDE_PROGRESS,
    )
    
    # Show trash data
    show_trash_btn.click(
        fn=handle_show_trash,
        inputs=[current_template, credentials_state],
        outputs=[
            import_preview, import_btn, mark_trash_btn, restore_btn,
            clear_history_btn, import_view_state,
        ],
        **HIDE_PROGRESS,
    )
    
    # Import selected rows
    import_btn.click(
        fn=handle_import_selected,
        inputs=[import_preview, current_template, form_data_state, credentials_state, detected_areas_state],
        outputs=[form_data_state, row_selector, import_preview, import_btn, mark_trash_btn, import_stats],
        **HIDE_PROGRESS,
    )
    
    # Mark as trash
    mark_trash_btn.click(
        fn=handle_mark_trash,
        inputs=[import_preview, current_template],
        outputs=[import_preview, mark_trash_btn, import_stats],
        **HIDE_PROGRESS,
    )
    
    # Restore selected rows to unprocessed
    restore_btn.click(
        fn=handle_restore_selected,
        inputs=[import_preview, current_template],
        outputs=[import_preview, restore_btn, import_stats],
        **HIDE_PROGRESS,
    )
    
    # Clear history
    clear_history_btn.click(
        fn=handle_clear_history,
        inputs=[current_template],
        outputs=[import_stats]
    )
    
    # Export button (no File output until export is implemented)
    export_btn.click(
        fn=handle_export,
        inputs=[current_template, form_data_state],
    )
    
    components["form_refresh_outputs"] = form_refresh_outputs
    components["update_on_template_change"] = [sheet_selector]

    return components


def handle_refresh_unrecorded(
    template: TemplateConfig | None,
    credentials: Any,
    form_data: list[dict[str, str]],
) -> tuple:
    """
    Refresh unrecorded data from Google Sheet
    Filters out processed IDs and trash IDs
    
    Returns:
        (import_preview, import_btn, mark_trash_btn, restore_btn,
         clear_history_btn, refresh_btn, import_stats, import_view_state)
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源并连接 Google 账号")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template),
            "unprocessed",
        )
    
    try:
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template),
                "unprocessed",
            )
        
        history = load_import_history(template.id)
        exclude_ids = history.processed_ids | history.trash_ids

        logger.info(f"Fetching all rows from sheet: {data_source.worksheet_name}")
        invalidate_sheet_cache(data_source.sheet_url, data_source.worksheet_name)
        df = _load_template_sheet_df(credentials, data_source, force_refresh=True)
        
        if df.height == 0:
            gr.Info("Sheet 中没有数据")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template),
                "unprocessed",
            )
        
        if df.height > MAX_IMPORT_PREVIEW_ROWS:
            gr.Warning(
                f"数据量过大（{df.height} 行），仅显示前 {MAX_IMPORT_PREVIEW_ROWS} 行未录入数据"
            )

        unrecorded_rows = _build_import_preview_rows(
            df,
            data_source.id_column,
            include_ids=None,
            exclude_ids=exclude_ids,
            status_label="新数据",
            max_rows=MAX_IMPORT_PREVIEW_ROWS,
        )
        
        if not unrecorded_rows:
            gr.Info("所有数据均已处理或标记")
            return (
                gr.update(), 
                gr.update(visible=False), 
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(interactive=True),
                update_import_stats(template),
                "unprocessed",
            )
        
        info_msg = f"找到 {len(unrecorded_rows)} 行未处理数据"
        if len(unrecorded_rows) >= MAX_IMPORT_PREVIEW_ROWS:
            info_msg += f"（已达到显示上限 {MAX_IMPORT_PREVIEW_ROWS} 行）"
        gr.Info(info_msg)
        
        return (
            gr.update(value=unrecorded_rows, visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(interactive=True),
            update_import_stats(template),
            "unprocessed",
        )
        
    except GoogleSheetsError as e:
        gr.Warning(f"获取 Sheet 数据失败：{e}")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template),
            "unprocessed",
        )
    except Exception as e:
        logger.error(f"Refresh failed: {e}")
        gr.Warning(f"刷新失败：{str(e)}")
        return (
            gr.update(), 
            gr.update(visible=False), 
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(interactive=True),
            update_import_stats(template),
            "unprocessed",
        )


def handle_import_selected(
    preview_data: list[list[Any]],
    template: TemplateConfig | None,
    form_data: list[dict[str, str]],
    credentials: Any,
    detected_areas: list
) -> tuple:
    """
    Import selected rows from preview using Gemma 4 field matching
    
    Returns:
        (form_data_state, row_selector, import_preview, import_btn, mark_trash_btn, import_stats)
    """
    preview_rows = _normalize_preview_rows(preview_data)
    template_id = _get_template_id(template)
    if not preview_rows or not template_id:
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
        selected_rows = [row for row in preview_rows if _is_row_selected(row)]
        
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
        
        data_source = load_template_data_source(template_id)
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
        
        paste_config = load_paste_parse_config(template_id)
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
        
        # Get field matcher (optional — fall back to rule-based mapping)
        field_matcher = create_field_matcher()
        if field_matcher is None:
            gr.Warning("LLM 模型未加载，使用规则匹配")
        
        sheet_df = _load_template_sheet_df(credentials, data_source)
        imported_count = 0
        imported_ids = []
        
        # Process each selected row
        for row in selected_rows:
            id_value = str(row[1])  # Second column is ID
            
            sheet_row = lookup_row_by_id(
                sheet_df,
                data_source.id_column,
                id_value,
            )
            
            if not sheet_row:
                logger.warning(f"Row not found for ID: {id_value}")
                continue
            
            if field_matcher is not None:
                matched_fields = field_matcher.match_sheet_fields_to_yaml(
                    sheet_row,
                    paste_config.to_dict()
                )
            else:
                matched_fields = map_sheet_row_from_paste_config(sheet_row, paste_config)
            
            if matched_fields:
                form_data.append(matched_fields)
                imported_ids.append(id_value)
                imported_count += 1
        
        # Mark imported IDs as processed
        if imported_ids:
            mark_as_processed(template_id, imported_ids)
        
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
        (import_preview, import_btn, mark_trash_btn, restore_btn,
         clear_history_btn, import_view_state)
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源")
        return (
            gr.update(), gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False), "unprocessed",
        )
    
    try:
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return (
                gr.update(), gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "unprocessed",
            )
        
        history = load_import_history(template.id)
        
        if not history.processed_ids:
            gr.Info("没有已处理的数据")
            return (
                gr.update(), gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "unprocessed",
            )
        
        df = _load_template_sheet_df(credentials, data_source)
        processed_rows = _build_import_preview_rows(
            df,
            data_source.id_column,
            include_ids=history.processed_ids,
            exclude_ids=None,
            status_label="已处理",
            max_rows=MAX_IMPORT_PREVIEW_ROWS,
        )
        
        gr.Info(f"找到 {len(processed_rows)} 行已处理数据")
        
        return (
            gr.update(value=processed_rows, visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=True),
            "processed",
        )
    except Exception as e:
        logger.error(f"Show processed failed: {e}")
        gr.Warning(f"加载失败：{str(e)}")
        return (
            gr.update(), gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False), "unprocessed",
        )


def handle_show_trash(
    template: TemplateConfig | None,
    credentials: Any
) -> tuple:
    """
    Show trash data
    
    Returns:
        (import_preview, import_btn, mark_trash_btn, restore_btn,
         clear_history_btn, import_view_state)
    """
    if not template or not credentials:
        gr.Warning("请先配置数据源")
        return (
            gr.update(), gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False), "unprocessed",
        )
    
    try:
        from app.services.data_source import load_template_data_source
        
        data_source = load_template_data_source(template.id)
        if not data_source:
            gr.Warning("模板未配置数据源")
            return (
                gr.update(), gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "unprocessed",
            )
        
        history = load_import_history(template.id)
        
        if not history.trash_ids:
            gr.Info("没有垃圾数据")
            return (
                gr.update(), gr.update(visible=False), gr.update(visible=False),
                gr.update(visible=False), gr.update(visible=False), "unprocessed",
            )
        
        df = _load_template_sheet_df(credentials, data_source)
        trash_rows = _build_import_preview_rows(
            df,
            data_source.id_column,
            include_ids=history.trash_ids,
            exclude_ids=None,
            status_label="垃圾",
            max_rows=MAX_IMPORT_PREVIEW_ROWS,
        )
        
        gr.Info(f"找到 {len(trash_rows)} 行垃圾数据")
        
        return (
            gr.update(value=trash_rows, visible=True),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
            gr.update(visible=True),
            "trash",
        )
    except Exception as e:
        logger.error(f"Show trash failed: {e}")
        gr.Warning(f"加载失败：{str(e)}")
        return (
            gr.update(), gr.update(visible=False), gr.update(visible=False),
            gr.update(visible=False), gr.update(visible=False), "unprocessed",
        )


def handle_mark_trash(
    preview_data: Any,
    template: TemplateConfig | dict[str, Any] | None
) -> tuple:
    """
    Mark selected rows as trash
    
    Returns:
        (import_preview, mark_trash_btn, import_stats)
    """
    preview_rows = _normalize_preview_rows(preview_data)
    template_id = _get_template_id(template)
    if not preview_rows or not template_id:
        return gr.update(), gr.update(interactive=True), update_import_stats(template)
    
    try:
        selected_rows = [row for row in preview_rows if _is_row_selected(row)]
        
        if not selected_rows:
            gr.Warning("请勾选要标记的行")
            return gr.update(), gr.update(interactive=True), update_import_stats(template)
        
        ids_to_mark = [str(row[1]) for row in selected_rows]
        
        if mark_as_trash(template_id, ids_to_mark):
            remaining_rows = [row for row in preview_rows if str(row[1]) not in ids_to_mark]
            try:
                gr.Info(f"已标记 {len(ids_to_mark)} 行为垃圾数据")
            except Exception as notify_err:
                logger.debug("Notification failed: %s", notify_err)
            return (
                gr.update(value=remaining_rows, visible=len(remaining_rows) > 0),
                gr.update(interactive=True),
                update_import_stats(template)
            )
        
        gr.Warning("标记失败")
        return gr.update(), gr.update(interactive=True), update_import_stats(template)
            
    except Exception as e:
        logger.error(f"Mark trash failed: {e}")
        gr.Warning(f"标记失败：{str(e)}")
        return gr.update(), gr.update(interactive=True), update_import_stats(template)


def handle_restore_selected(
    preview_data: Any,
    template: TemplateConfig | dict[str, Any] | None,
) -> tuple:
    """
    Restore selected rows from processed/trash back to unprocessed state
    
    Returns:
        (import_preview, restore_btn, import_stats)
    """
    preview_rows = _normalize_preview_rows(preview_data)
    template_id = _get_template_id(template)
    if not preview_rows or not template_id:
        return gr.update(), gr.update(interactive=True), update_import_stats(template)
    
    try:
        selected_rows = [row for row in preview_rows if _is_row_selected(row)]
        
        if not selected_rows:
            gr.Warning("请勾选要恢复的行")
            return gr.update(), gr.update(interactive=True), update_import_stats(template)
        
        ids_to_restore = [str(row[1]) for row in selected_rows]
        
        if unmark_ids(template_id, ids_to_restore):
            remaining_rows = [
                row for row in preview_rows if str(row[1]) not in ids_to_restore
            ]
            gr.Info(f"已恢复 {len(ids_to_restore)} 行为未处理状态")
            return (
                gr.update(value=remaining_rows, visible=len(remaining_rows) > 0),
                gr.update(interactive=True),
                update_import_stats(template),
            )
        
        gr.Warning("恢复失败")
        return gr.update(), gr.update(interactive=True), update_import_stats(template)
            
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        gr.Warning(f"恢复失败：{str(e)}")
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
) -> None:
    """Export form data to Excel (not yet implemented)."""
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
