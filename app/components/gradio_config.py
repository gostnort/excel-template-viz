"""
Gradio Config Tab Component

Handles YAML configuration editing, LLM settings, and template parameters.
"""
import gradio as gr
import logging
import sys
import threading
import time
from pathlib import Path
from typing import Any

from app.services.registry import TemplateConfig
from app.services.paste_parse_config import (
    PasteParseConfig,
    PasteParseRule,
    UNMAPPED_INDEX,
    _default_order_entry,
    _default_unmapped_rule,
    _order_entry_to_dict,
    build_order_entries_from_mappings,
    config_to_yaml,
    config_from_dict,
    create_default_config_from_template,
    ensure_config_exists,
    load_paste_parse_config,
    paste_config_path,
    resolve_sheet_header,
)
from app.services.gemma4_field_matcher import (
    ModelDownloadError,
    build_batch_field_mapping_prompt,
    ensure_model_downloaded,
    find_model_file,
    get_last_load_error,
    get_or_create_field_matcher,
    _collect_yaml_fields,
    prepare_batch_input,
)

logger = logging.getLogger(__name__)


def on_template_change_load_config(template: TemplateConfig | None) -> tuple:
    """
    Load configuration when template changes
    
    Returns:
        (sections_enabled, sections_config_panel, input_area, move_direction, offset_value, sections_status)
    """
    if not template:
        return (
            gr.update(value=False),
            gr.update(visible=False),
            gr.update(value=""),
            gr.update(value="down"),
            gr.update(value=1),
            "未配置多区域"
        )
    
    try:
        from pathlib import Path
        
        # Ensure config exists (create default if not)
        template_path = Path(template.file_path)
        ensure_config_exists(template.id, template_path)
        
        # Load config
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            # Create default config
            default_config = create_default_config_from_template(template_path)
            sections = default_config.sections
        else:
            sections = paste_config.sections
        
        # If no sections, try to create default
        if not sections:
            try:
                default_config = create_default_config_from_template(template_path)
                sections = default_config.sections
            except Exception as e:
                logger.error(f"Failed to create default sections: {e}")
                sections = None
        
        if sections and len(sections) > 0:
            section = sections[0]
            return (
                gr.update(value=True),
                gr.update(visible=True),
                gr.update(value=section.get("input_area", "")),
                gr.update(value=section.get("move_to", "down")),
                gr.update(value=section.get("offset", 1)),
                f"✓ 已加载区域配置：{section.get('input_area', '')}"
            )
        else:
            return (
                gr.update(value=False),
                gr.update(visible=False),
                gr.update(value=""),
                gr.update(value="down"),
                gr.update(value=1),
                "未检测到区域配置"
            )
    
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return (
            gr.update(value=False),
            gr.update(visible=False),
            gr.update(value=""),
            gr.update(value="down"),
            gr.update(value=1),
            f"❌ 加载失败：{str(e)}"
        )


def load_llm_test_worksheets(
    template: TemplateConfig | None,
    credentials: Any,
) -> gr.Dropdown:
    """
    Populate LLM test worksheet dropdown from the template's connected Google Sheet.

    Returns:
        gr.update with worksheet choices (defaults to saved data-source worksheet)
    """
    if not template:
        return gr.update(
            choices=[],
            value=None,
            interactive=False,
            info='请先在"数据源"标签页连接 Google Sheet',
        )
    try:
        from app.services.data_source import load_template_data_source
        from app.services.google_sheets import list_worksheets

        data_source = load_template_data_source(template.id)
        if not data_source:
            return gr.update(
                choices=[],
                value=None,
                interactive=False,
                info='⚠️ 未配置数据源，请先在"数据源"标签页连接 Google Sheet',
            )
        if not credentials:
            return gr.update(
                choices=[],
                value=None,
                interactive=False,
                info='⚠️ 未授权，请先在"数据源"标签页授权 Google 账号',
            )
        worksheets = list_worksheets(credentials, data_source.sheet_url)
        if not worksheets:
            return gr.update(
                choices=[],
                value=None,
                interactive=False,
                info="⚠️ 未找到工作表",
            )
        default = (
            data_source.worksheet_name
            if data_source.worksheet_name in worksheets
            else worksheets[0]
        )
        return gr.update(
            choices=worksheets,
            value=default,
            interactive=True,
            info=f"✓ 共 {len(worksheets)} 个工作表",
        )
    except Exception as exc:
        logger.error("Failed to list worksheets for LLM test: %s", exc)
        return gr.update(
            choices=[],
            value=None,
            interactive=False,
            info=f"⚠️ 加载工作表列表失败：{exc}",
        )


def fetch_llm_test_columns(
    template: TemplateConfig | None,
    credentials: Any,
    worksheet_name: str | None,
) -> gr.Dropdown:
    """
    Update LLM test column multiselect for the selected worksheet.

    Returns:
        gr.update with column choices
    """
    if not template:
        return gr.update(
            choices=[],
            value=None,
            interactive=True,
            info='从已连接的 Google Sheet 中选择列（如未显示选项，请先在"数据源"标签页连接 Sheet）',
        )
    if not worksheet_name:
        return gr.update(
            choices=[],
            value=None,
            interactive=True,
            info="⚠️ 请先选择工作表",
        )
    try:
        from app.services.data_source import load_template_data_source
        from app.services.google_sheets import fetch_sheet_preview

        data_source = load_template_data_source(template.id)
        if not data_source:
            return gr.update(
                choices=[],
                value=None,
                interactive=True,
                info='⚠️ 未配置数据源，请先在"数据源"标签页连接 Google Sheet',
            )
        if not credentials:
            return gr.update(
                choices=[],
                value=None,
                interactive=True,
                info='⚠️ 未授权，请先在"数据源"标签页授权 Google 账号',
            )
        df, _ = fetch_sheet_preview(
            credentials,
            data_source.sheet_url,
            worksheet_name,
        )
        if df.height == 0:
            columns = list(df.columns)
            if not columns:
                return gr.update(
                    choices=[],
                    value=None,
                    interactive=True,
                    info=f"⚠️ 工作表「{worksheet_name}」为空",
                )
            return gr.update(
                choices=columns,
                value=None,
                interactive=True,
                info=f"✓ 已加载 {len(columns)} 列（来自 {worksheet_name}）",
            )
        columns = list(df.columns)
        return gr.update(
            choices=columns,
            value=None,
            interactive=True,
            info=f"✓ 已加载 {len(columns)} 列（来自 {worksheet_name}）",
        )
    except Exception as exc:
        logger.error("Failed to load columns for LLM test: %s", exc)
        return gr.update(
            choices=[],
            value=None,
            interactive=True,
            info=f"⚠️ 加载列失败：{exc}",
        )


def _disable_llm_test_columns() -> gr.Dropdown:
    """Disable column multiselect while column data is loading."""
    return gr.update(interactive=False)


def refresh_llm_test_from_datasource_worksheet(
    template: TemplateConfig | None,
    credentials: Any,
    worksheet_name: str | None,
) -> tuple[gr.Dropdown, gr.Dropdown]:
    """
    Sync LLM tab worksheet + columns when the data-source tab worksheet changes.
    """
    worksheet_update = load_llm_test_worksheets(template, credentials)
    if worksheet_name and isinstance(worksheet_update, dict):
        choices = worksheet_update.get("choices") or []
        if worksheet_name in choices:
            worksheet_update = {
                **worksheet_update,
                "value": worksheet_name,
            }
    columns_update = fetch_llm_test_columns(template, credentials, worksheet_name)
    return worksheet_update, columns_update


def build_config_tab(
    current_template: gr.State,
    credentials_state: gr.State
) -> dict:
    """
    Build the configuration tab with YAML editor and LLM settings
    
    Returns:
        Dict of component references for event binding
    """
    components = {}
    
    with gr.Column():
        gr.Markdown("## 参数配置")
        
        with gr.Tabs() as config_tabs:
            # Sub-tab 1: Sections Configuration (for multi-area templates)
            with gr.TabItem("区域配置"):
                gr.Markdown("配置多区域检测（适用于重复区域模板）")
                
                sections_enabled = gr.Checkbox(
                    label="启用多区域检测",
                    value=False
                )
                
                with gr.Column(visible=False) as sections_config_panel:
                    input_area = gr.Textbox(
                        label="输入区域 (如: B2:F10)",
                        placeholder="B2:F10"
                    )
                    
                    move_direction = gr.Radio(
                        label="移动方向",
                        choices=["down", "right"],
                        value="down"
                    )
                    
                    offset_value = gr.Number(
                        label="偏移量（行数或列数）",
                        value=1,
                        minimum=1
                    )
                    
                    sections_save_btn = gr.Button("💾 保存区域配置", variant="primary")
                
                sections_status = gr.Markdown("未配置多区域")
                
                components["sections_enabled"] = sections_enabled
                components["sections_config_panel"] = sections_config_panel
                components["input_area"] = input_area
                components["move_direction"] = move_direction
                components["offset_value"] = offset_value
                components["sections_save_btn"] = sections_save_btn
                components["sections_status"] = sections_status
            
            # Sub-tab 2: YAML Configuration
            with gr.TabItem("YAML 配置"):
                gr.Markdown("编辑模板的字段映射配置")
                
                yaml_editor = gr.Code(
                    label="YAML 配置内容",
                    language="yaml",
                    lines=20,
                    value="",
                    interactive=True
                )
                
                with gr.Row():
                    auto_config_btn = gr.Button("🤖 自动配置", variant="secondary")
                    yaml_save_btn = gr.Button("💾 保存配置", variant="primary")
                    yaml_validate_btn = gr.Button("✓ 验证语法", variant="secondary")
                
                yaml_status = gr.Markdown("等待操作...")
                
                components["yaml_editor"] = yaml_editor
                components["auto_config_btn"] = auto_config_btn
                components["yaml_save_btn"] = yaml_save_btn
                components["yaml_validate_btn"] = yaml_validate_btn
                components["yaml_status"] = yaml_status
            
            # Sub-tab 3: LLM Settings
            with gr.TabItem("LLM 字段匹配"):
                gr.Markdown("使用 Gemma 4 模型智能匹配字段（首次使用会自动下载）")
                
                # Test LLM matching
                with gr.Row():
                    llm_test_worksheet = gr.Dropdown(
                        label="测试工作表",
                        choices=[],
                        value=None,
                        interactive=False,
                        info='从已连接的 Google Sheet 中选择工作表（如未显示选项，请先在"数据源"标签页连接 Sheet）',
                    )
                with gr.Row():
                    test_sheet_cols = gr.Dropdown(
                        label="测试 Sheet 列名",
                        choices=[],
                        value=None,
                        multiselect=True,
                        interactive=True,
                        info="选择工作表后将自动加载列名",
                    )
                
                llm_test_cancel = gr.State({"cancelled": False})
                llm_test_start_time = gr.State(0.0)
                llm_test_prepared_state = gr.State(None)

                with gr.Row():
                    test_llm_btn = gr.Button("🧪 测试 LLM 匹配", variant="primary")
                    stop_llm_btn = gr.Button("⏹ 停止测试", variant="stop", interactive=False)
                    llm_test_elapsed = gr.Markdown("已用时: —")
                
                with gr.Accordion("📝 LLM Prompt", open=False):
                    prompt_display = gr.Textbox(
                        show_label=False,
                        lines=10,
                        interactive=False,
                        placeholder="点击测试后将显示 prompt..."
                    )
                
                with gr.Accordion("🤖 LLM 响应", open=False):
                    llm_response = gr.Textbox(
                        show_label=False,
                        lines=5,
                        max_lines=20,
                        interactive=False,
                        autoscroll=False,
                        elem_classes=["llm-response-box"],
                        placeholder="等待 LLM 响应..."
                    )
                
                with gr.Accordion("✅ 匹配结果", open=True):
                    test_result_yaml = gr.Code(
                        label="可复制 YAML 片段（粘贴到「YAML 配置」标签页或 .paste.yaml）",
                        language="yaml",
                        lines=18,
                        value="",
                        interactive=False,
                    )
                
                components["llm_test_worksheet"] = llm_test_worksheet
                components["test_sheet_cols"] = test_sheet_cols
                components["llm_test_cancel"] = llm_test_cancel
                components["llm_test_start_time"] = llm_test_start_time
                components["llm_test_prepared_state"] = llm_test_prepared_state
                components["test_llm_btn"] = test_llm_btn
                components["stop_llm_btn"] = stop_llm_btn
                components["llm_test_elapsed"] = llm_test_elapsed
                components["prompt_display"] = prompt_display
                components["llm_response"] = llm_response
                components["test_result_yaml"] = test_result_yaml
    
    components["config_tabs"] = config_tabs

    # Event bindings
    
    # Update worksheet list + columns when template changes or data source connects
    current_template.change(
        fn=load_llm_test_worksheets,
        inputs=[current_template, credentials_state],
        outputs=[llm_test_worksheet],
    ).then(
        fn=fetch_llm_test_columns,
        inputs=[current_template, credentials_state, llm_test_worksheet],
        outputs=[test_sheet_cols],
    )

    llm_test_worksheet.change(
        fn=_disable_llm_test_columns,
        outputs=[test_sheet_cols],
    ).then(
        fn=fetch_llm_test_columns,
        inputs=[current_template, credentials_state, llm_test_worksheet],
        outputs=[test_sheet_cols],
    )
    
    # Load sections + YAML when template changes
    current_template.change(
        fn=on_template_change_load_config,
        inputs=[current_template],
        outputs=[
            sections_enabled,
            sections_config_panel,
            input_area,
            move_direction,
            offset_value,
            sections_status
        ]
    ).then(
        fn=handle_yaml_load,
        inputs=[current_template],
        outputs=[yaml_editor, yaml_status]
    )
    
    # Auto-load YAML when user opens the YAML sub-tab
    config_tabs.select(
        fn=on_yaml_tab_select,
        inputs=[current_template],
        outputs=[yaml_editor, yaml_status]
    )
    
    # YAML tab events
    auto_config_btn.click(
        fn=lambda: gr.update(interactive=False),
        outputs=[auto_config_btn],
    ).then(
        fn=handle_yaml_auto_config,
        inputs=[current_template, credentials_state],
        outputs=[yaml_editor, yaml_status],
    ).then(
        fn=lambda: gr.update(interactive=True),
        outputs=[auto_config_btn],
    )
    
    yaml_save_btn.click(
        fn=handle_yaml_save,
        inputs=[current_template, yaml_editor],
        outputs=[yaml_status]
    )
    
    yaml_validate_btn.click(
        fn=handle_yaml_validate,
        inputs=[yaml_editor],
        outputs=[yaml_status]
    )
    
    llm_test_event = test_llm_btn.click(
        fn=_begin_llm_test,
        outputs=[test_llm_btn, stop_llm_btn, llm_test_cancel, llm_test_start_time, llm_test_elapsed],
    ).then(
        fn=prepare_llm_test_prompt,
        inputs=[
            current_template,
            test_sheet_cols,
            llm_test_worksheet,
            credentials_state,
            llm_test_start_time,
        ],
        outputs=[
            llm_test_prepared_state,
            prompt_display,
            llm_response,
            llm_test_elapsed,
        ],
    ).then(
        fn=run_llm_test_generation,
        inputs=[
            current_template,
            llm_test_prepared_state,
            llm_test_cancel,
            llm_test_start_time,
        ],
        outputs=[prompt_display, llm_response, test_result_yaml, llm_test_elapsed],
    ).then(
        fn=_end_llm_test,
        inputs=[llm_test_start_time],
        outputs=[test_llm_btn, stop_llm_btn, llm_test_cancel, llm_test_elapsed],
    )

    stop_llm_btn.click(
        fn=_on_llm_test_stop,
        inputs=[llm_test_cancel, llm_test_start_time],
        outputs=[llm_test_cancel, test_llm_btn, stop_llm_btn, llm_test_elapsed],
        cancels=[llm_test_event],
    )
    
    # Sections tab events
    sections_enabled.change(
        fn=lambda enabled: gr.update(visible=enabled),
        inputs=[sections_enabled],
        outputs=[sections_config_panel]
    )

    return components


def on_yaml_tab_select(
    evt: gr.SelectData,
    template: TemplateConfig | None,
) -> tuple:
    """Load YAML into the editor when the YAML sub-tab is selected."""
    if evt.selected and str(evt.value).strip() == "YAML 配置":
        return handle_yaml_load(template)
    return gr.skip(), gr.skip()


def handle_yaml_load(
    template: TemplateConfig | None
) -> tuple:
    """
    Load YAML configuration for current template
    
    Returns:
        (yaml_editor, yaml_status)
    """
    if not template:
        return "", "❌ 请先选择模板"
    
    try:
        # Ensure config exists (create default if not)
        from pathlib import Path
        from app.services.paste_parse_config import ensure_config_exists
        
        template_path = Path(template.file_path)
        ensure_config_exists(template.id, template_path)
        
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            return "", f"❌ 未找到模板 '{template.id}' 的配置文件"
        
        # Convert config to YAML string
        yaml_str = config_to_yaml(paste_config.to_dict())
        
        return yaml_str, f"✓ 已加载配置文件（{len(yaml_str.split(chr(10)))} 行）"
        
    except Exception as e:
        logger.error(f"Failed to load YAML: {e}")
        return "", f"❌ 加载失败：{str(e)}"


def handle_yaml_save(
    template: TemplateConfig | None,
    yaml_content: str
) -> str:
    """
    Save YAML configuration
    
    Returns:
        Status message
    """
    if not template:
        return "❌ 请先选择模板"
    
    if not yaml_content or not yaml_content.strip():
        return "❌ YAML 内容为空"
    
    try:
        import yaml
        from pathlib import Path
        
        # Parse YAML to validate
        yaml_dict = yaml.safe_load(yaml_content)
        
        if not isinstance(yaml_dict, dict):
            return "❌ YAML 格式错误：根节点必须是字典"
        
        # Convert back to config
        paste_config = config_from_dict(yaml_dict)
        
        # Save to file
        config_path = Path(f"templates/{template.id}/{template.id}.paste.yaml")
        
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        logger.info(f"Saved YAML config for template: {template.id}")
        
        return f"✓ 配置已保存到 {config_path}"
        
    except yaml.YAMLError as e:
        return f"❌ YAML 语法错误：{str(e)}"
    except Exception as e:
        logger.error(f"Failed to save YAML: {e}")
        return f"❌ 保存失败：{str(e)}"


def handle_yaml_validate(
    yaml_content: str
) -> str:
    """
    Validate YAML syntax
    
    Returns:
        Status message
    """
    if not yaml_content or not yaml_content.strip():
        return "❌ YAML 内容为空"
    
    try:
        import yaml
        
        yaml_dict = yaml.safe_load(yaml_content)
        
        if not isinstance(yaml_dict, dict):
            return "❌ YAML 格式错误：根节点必须是字典"
        
        # Basic validation
        field_count = len([k for k in yaml_dict.keys() if not k.startswith('_')])
        
        return f"✓ YAML 语法正确（{field_count} 个字段）"
        
    except yaml.YAMLError as e:
        return f"❌ YAML 语法错误：{str(e)}"
    except Exception as e:
        return f"❌ 验证失败：{str(e)}"


def _fetch_sheet_columns_and_samples(
    template: TemplateConfig,
    credentials: Any,
    worksheet_name: str | None = None,
) -> tuple[list[str], list[dict[str, str]], str | None]:
    """Load sheet columns and sample rows from the connected data source."""
    from app.services.data_source import load_template_data_source
    from app.services.google_sheets import fetch_sheet_preview

    data_source = load_template_data_source(template.id)
    if not data_source:
        return [], {}, '请先在"数据源"标签页连接 Google Sheet'

    if not credentials:
        return [], {}, '请先在"数据源"标签页授权 Google 账号'

    ws_name = worksheet_name or data_source.worksheet_name
    if not ws_name:
        return [], {}, "请先选择工作表"

    try:
        df, _ = fetch_sheet_preview(
            credentials,
            data_source.sheet_url,
            ws_name,
        )
    except Exception as exc:
        logger.error("Failed to fetch sheet preview: %s", exc)
        return [], {}, f"加载 Sheet 列失败：{exc}"

    if df.height == 0:
        columns = list(df.columns)
        if not columns:
            return [], [], "工作表为空，无法获取列名"
        return columns, [], None

    columns = list(df.columns)
    sample_rows: list[dict[str, str]] = []
    sample_count = min(df.height, 20)
    for row_index in range(sample_count):
        row = df.row(row_index, named=True)
        sample_rows.append({col: str(row.get(col, "") or "") for col in columns})
    return columns, sample_rows, None


def _exact_match_columns(
    template_fields: list[str],
    sheet_columns: list[str],
    filed_hints: dict[str, str] | None = None,
) -> dict[str, str | None]:
    """Map template fields to sheet columns via case-insensitive name matching."""
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    hints = filed_hints or {}

    for field_name in template_fields:
        candidates = [c for c in sheet_columns if c not in used]
        matched: str | None = None

        hint = hints.get(field_name, field_name)
        if hint and hint != "?":
            matched = resolve_sheet_header(hint, candidates)

        if matched is None:
            matched = resolve_sheet_header(field_name, candidates)

        if matched:
            used.add(matched)
        mapping[field_name] = matched

    return mapping


def _resolve_column_map_entry(
    mapping_entry: str | None | dict[str, Any],
    col_index: dict[str, int] | None = None,
) -> str | None:
    """Return matched sheet column name, or None when unmapped or unknown."""
    if isinstance(mapping_entry, dict):
        matched_col = str(mapping_entry.get("filed", "?") or "?")
        if matched_col == "?":
            return None
    elif mapping_entry:
        matched_col = str(mapping_entry)
    else:
        return None
    if col_index is not None and matched_col not in col_index:
        return None
    return matched_col


def _build_llm_test_yaml_from_mappings(
    paste_config: PasteParseConfig,
    column_map: dict[str, str | None] | dict[str, dict[str, Any]],
    sheet_columns: list[str],
    id_sheet_col: str | None = None,
) -> str:
    """Build copy-ready .paste.yaml text from batch mapping results."""
    updated_config = _apply_column_mapping_to_config(
        paste_config,
        column_map,
        sheet_columns,
        id_sheet_col,
        include_unmapped=False,
    )
    return config_to_yaml(updated_config.to_dict(), omit_unmapped_fields=True)


def _apply_column_mapping_to_config(
    paste_config: PasteParseConfig,
    column_map: dict[str, str | None] | dict[str, dict[str, Any]],
    sheet_columns: list[str],
    id_sheet_col: str | None,
    *,
    include_unmapped: bool = True,
) -> PasteParseConfig:
    """Update field_rules and order entries from a template-field -> sheet-column map."""
    col_index = {col: idx for idx, col in enumerate(sheet_columns)}

    new_field_rules: dict[str, list[PasteParseRule]] = {}
    for field_name, rules in paste_config.field_rules.items():
        mapping_entry = column_map.get(field_name)
        matched_col = _resolve_column_map_entry(mapping_entry, col_index)
        new_rules: list[PasteParseRule] = []
        inferred_regex: str | None = None
        for rule in rules:
            if matched_col:
                idx = col_index[matched_col]
                id_flag = rule.id_flag
                if id_sheet_col and matched_col == id_sheet_col:
                    id_flag = True
                if isinstance(mapping_entry, dict):
                    raw_regex = mapping_entry.get("regex")
                    if raw_regex not in (None, "None", ""):
                        inferred_regex = str(raw_regex)
                rule_regex = inferred_regex if inferred_regex else rule.regex
                new_rules.append(
                    PasteParseRule(
                        filed=matched_col,
                        index=idx,
                        regex=rule_regex,
                        id_flag=id_flag,
                    )
                )
            elif include_unmapped:
                new_rules.append(_default_unmapped_rule(id_flag=rule.id_flag))
        if new_rules:
            new_field_rules[field_name] = new_rules

    mapped_columns: set[str] = set()
    for field_name in paste_config.field_rules:
        mapping_entry = column_map.get(field_name)
        matched_col = _resolve_column_map_entry(mapping_entry, col_index)
        if matched_col:
            mapped_columns.add(matched_col)
    new_order = build_order_entries_from_mappings(
        sheet_columns,
        mapped_columns,
        include_unmapped=include_unmapped,
    )

    return PasteParseConfig(
        determiner=paste_config.determiner,
        field_rules=new_field_rules,
        order=new_order,
        worksheet=paste_config.worksheet,
        sections=paste_config.sections,
        fields_per_row=paste_config.fields_per_row,
    )


def handle_yaml_auto_config(
    template: TemplateConfig | None,
    credentials: Any,
    progress: gr.Progress = gr.Progress(),
):
    """
    Auto-fill YAML field mappings using sheet columns and Gemma 4 matching.

    Args:
        template: Current template
        credentials: Google OAuth credentials
        progress: Gradio Progress component

    Yields incremental (yaml_editor, yaml_status) updates while matching.
    """
    if not template:
        yield "", "❌ 请先选择模板"
        return

    progress(0, desc="⏳ 正在读取 Sheet 样本数据…")
    yield gr.skip(), "⏳ 正在读取 Sheet 样本数据…"
    columns, sample_rows, fetch_error = _fetch_sheet_columns_and_samples(template, credentials)
    if fetch_error:
        gr.Warning(fetch_error)
        yield gr.skip(), f"⚠️ {fetch_error}"
        return

    gr.Info(f"已读取 Sheet：{len(columns)} 列，{len(sample_rows)} 行样本")
    if len(sample_rows) < 5:
        gr.Warning(f"仅有 {len(sample_rows)} 行样本，建议至少 5 行以提高匹配准确率")

    try:
        template_path = Path(template.file_path)
        ensure_config_exists(template.id, template_path)
        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            yield "", f"❌ 未找到模板 '{template.id}' 的配置文件"
            return

        template_fields = list(paste_config.field_rules.keys())
        if not template_fields:
            yield "", "❌ 模板没有可映射的字段"
            return

        filed_hints: dict[str, str] = {}
        for field_name, rules in paste_config.field_rules.items():
            if rules and rules[0].filed and rules[0].filed != "?" and rules[0].index >= 0:
                filed_hints[field_name] = rules[0].filed
        fallback_column_map = _exact_match_columns(template_fields, columns, filed_hints)

        if not find_model_file():
            gr.Info("正在下载 Gemma 4 模型…")
            progress(0.2, desc="⏳ 正在下载 Gemma 4 模型…")
            yield gr.skip(), "⏳ 正在下载 Gemma 4 模型…"

            def download_progress(stage, current, total, msg):
                progress(0.2 + 0.2 * (current / total), desc=msg)

            try:
                ensure_model_downloaded(on_progress=download_progress)
                gr.Info("模型下载完成")
            except ModelDownloadError as exc:
                logger.error("Model download failed: %s", exc)
                gr.Warning(f"LLM 不可用（{exc}），已回退到精确名称匹配")
            except Exception as exc:
                logger.error("Download failed: %s", exc)
                gr.Warning(f"LLM 不可用（{exc}），已回退到精确名称匹配")

        progress(0.4, desc="⏳ 正在加载 Gemma 4…")
        yield gr.skip(), "⏳ 正在加载 Gemma 4…"

        def load_progress(stage, current, total, msg):
            progress(0.4 + 0.2 * (current / total), desc=f"⏳ {msg}")

        matcher = get_or_create_field_matcher(on_progress=load_progress)
        batch_mappings: dict[str, dict[str, Any]] = {}
        llm_used = False

        if matcher and sample_rows and columns:
            usable_rows = sample_rows[: max(5, min(len(sample_rows), 10))]
            if len(usable_rows) >= 5:
                source_data = prepare_batch_input(columns, usable_rows, min_rows=5)
            else:
                # Fallback when sample rows are insufficient
                source_data = [
                    {
                        "index": idx,
                        "header": col,
                        "data": [str(row.get(col, "") or "") for row in usable_rows],
                    }
                    for idx, col in enumerate(columns)
                ]
            batch_prompt = build_batch_field_mapping_prompt(source_data, template_fields)
            preview = batch_prompt if len(batch_prompt) <= 800 else batch_prompt[:800] + "\n…（已截断）"
            gr.Info(f"Prompt 已构建（{len(batch_prompt)} 字符），开始 LLM 推理…")
            progress(0.62, desc="⏳ Prompt 已就绪，LLM 推理中…")
            yield gr.skip(), (
                f"⏳ Prompt 已构建（{len(batch_prompt)} 字符），LLM 推理中…\n\n"
                f"```\n{preview}\n```"
            )
            batch_mappings, _, _ = matcher.batch_match_all_fields(
                source_data,
                template_fields,
                prompt=batch_prompt,
            )
            llm_used = True
            usable_for_transform = sample_rows[: max(5, min(len(sample_rows), 10))]
            if batch_mappings and usable_for_transform:
                progress(0.75, desc="⏳ 检测格式不匹配并推断转换…")
                yield gr.skip(), "⏳ 批量映射完成，正在推断列转换规则…"
                try:
                    _, batch_mappings = matcher.enrich_mappings_with_transformations(
                        batch_mappings,
                        usable_for_transform,
                    )
                except Exception as transform_exc:
                    logger.warning("Transformation pass failed: %s", transform_exc)
        else:
            detail = get_last_load_error()
            if detail:
                gr.Warning(f"Gemma 4 模型不可用（{detail}），已回退到精确名称匹配")
            else:
                gr.Warning("Gemma 4 模型不可用，已回退到精确名称匹配")

        if llm_used and batch_mappings:
            column_map: dict[str, dict[str, Any]] = {}
            for field_name in template_fields:
                llm_item = batch_mappings.get(field_name, {"filed": "?", "index": -1})
                if llm_item.get("filed") == "?" and fallback_column_map.get(field_name):
                    fallback_col = fallback_column_map[field_name]
                    if fallback_col:
                        llm_item = {"filed": fallback_col, "index": columns.index(fallback_col)}
                column_map[field_name] = llm_item
        else:
            column_map = {
                field: (
                    {"filed": col, "index": columns.index(col)}
                    if col else
                    {"filed": "?", "index": -1}
                )
                for field, col in fallback_column_map.items()
            }

        from app.services.data_source import load_template_data_source

        data_source = load_template_data_source(template.id)
        id_sheet_col = data_source.id_column if data_source else None

        progress(0.9, desc="⏳ 生成 YAML 配置…")
        updated_config = _apply_column_mapping_to_config(
            paste_config,
            column_map,
            columns,
            id_sheet_col,
        )
        yaml_str = config_to_yaml(updated_config.to_dict())

        matched_count = sum(
            1
            for mapping in column_map.values()
            if isinstance(mapping, dict) and mapping.get("filed") not in {None, "?"}
        )
        unmapped_count = len(template_fields) - matched_count
        method = "批量 Gemma 4 + 精确回退" if llm_used else "精确名称匹配"
        
        # Write to YAML file
        try:
            import yaml
            yaml_path = Path(f"templates/{template.id}/{template.id}.paste.yaml")
            
            # Ensure directory exists
            yaml_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write YAML file
            with open(yaml_path, 'w', encoding='utf-8') as f:
                f.write(yaml_str)
            
            logger.info(f"Saved auto-config to {yaml_path}: {matched_count}/{len(template_fields)} fields matched")
            
            status = f"✓ 自动配置完成并已保存（{method}）：{matched_count}/{len(template_fields)} 个字段已匹配"
            if unmapped_count:
                status += f"，{unmapped_count} 个未映射（filed=\"?\", index=-1）"
            
        except Exception as write_exc:
            logger.error(f"Failed to write YAML: {write_exc}")
            status = f"✓ 自动配置完成（{method}）：{matched_count}/{len(template_fields)} 个字段已匹配"
            if unmapped_count:
                status += f"，{unmapped_count} 个未映射"
            status += f"\n⚠️ 但写入文件失败：{write_exc}"

        progress(1.0, desc="✓ 配置完成")
        yield yaml_str, status

    except Exception as exc:
        logger.error("Auto config failed: %s", exc)
        yield "", f"❌ 自动配置失败：{exc}"


def _format_elapsed_seconds(total_seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS / S."""
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _running_elapsed_label(start_time: float) -> str:
    if not start_time:
        return "已用时: —"
    elapsed = time.monotonic() - start_time
    return f"已用时: {_format_elapsed_seconds(elapsed)}"


def _final_elapsed_label(start_time: float, *, stopped: bool = False) -> str:
    if not start_time:
        return "用时: —"
    elapsed = time.monotonic() - start_time
    prefix = "已停止 · " if stopped else ""
    return f"{prefix}用时: {_format_elapsed_seconds(elapsed)}"


def _begin_llm_test() -> tuple[Any, Any, dict[str, bool], float, str]:
    """Reset cancel flag, record start time, and toggle test/stop button interactivity."""
    start_time = time.monotonic()
    return (
        gr.update(interactive=False),
        gr.update(interactive=True),
        {"cancelled": False},
        start_time,
        _running_elapsed_label(start_time),
    )


def _end_llm_test(start_time: float) -> tuple[Any, Any, dict[str, bool], str]:
    """Restore test/stop button interactivity and show final elapsed time."""
    return (
        gr.update(interactive=True),
        gr.update(interactive=False),
        {"cancelled": False},
        _final_elapsed_label(start_time),
    )


def _on_llm_test_stop(
    cancel_state: dict[str, bool],
    start_time: float,
) -> tuple[dict[str, bool], Any, Any, str]:
    """Request cancellation, restore button states, and freeze elapsed time."""
    gr.Info("已停止测试")
    cancel_state["cancelled"] = True
    return (
        cancel_state,
        gr.update(interactive=True),
        gr.update(interactive=False),
        _final_elapsed_label(start_time, stopped=True),
    )


def _is_llm_test_cancelled(cancel_state: dict[str, bool] | None) -> bool:
    return bool(cancel_state and cancel_state.get("cancelled"))


LLM_TEST_TICK_INTERVAL_S = 2.0


def _format_transformation_summary(
    transformations: dict[str, list[dict[str, Any]]],
) -> str:
    """Summarize second-pass transformation rules for LLM test response display."""
    if not transformations:
        return ""
    lines = ["\n\n--- Transformation pass ---"]
    for source_column, rules in transformations.items():
        lines.append(f"\nSource column: {source_column}")
        for rule in rules:
            lines.append(
                f"  {rule.get('target_field')}: "
                f"{rule.get('extraction_method')} "
                f"pattern={rule.get('pattern')!r} "
                f"({rule.get('explanation', '')})"
            )
    return "\n".join(lines)


def _gather_llm_test_sheet_data(
    template: TemplateConfig,
    test_cols: list | None,
    worksheet_name: str | None,
    credentials: Any,
) -> tuple[list[str], list[dict[str, str]], bool, str | None]:
    """Return (columns, sample_rows, using_manual_cols, fetch_error)."""
    columns, fetched_rows, fetch_error = _fetch_sheet_columns_and_samples(
        template,
        credentials,
        worksheet_name,
    )
    if fetch_error:
        if not test_cols:
            return [], [], False, fetch_error
        sheet_columns = list(test_cols)
        sample_rows = [
            {col: f"测试值_{row_idx + 1}_{col}" for col in sheet_columns}
            for row_idx in range(5)
        ]
        return sheet_columns, sample_rows, True, None
    return columns, fetched_rows, False, None


def _build_llm_test_source_data(
    filtered_columns: list[str],
    filtered_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build batch input payload for field matching."""
    if len(filtered_rows) >= 5:
        return prepare_batch_input(filtered_columns, filtered_rows[:10], min_rows=5)
    return [
        {
            "index": idx,
            "header": col,
            "data": [str(row.get(col, "") or "") for row in filtered_rows],
        }
        for idx, col in enumerate(filtered_columns)
    ]


def prepare_llm_test_prompt(
    template: TemplateConfig | None,
    test_cols: list | None,
    worksheet_name: str | None,
    credentials: Any,
    start_time: float,
) -> tuple[dict[str, Any] | None, str, str, str]:
    """
    Step 1: gather sheet data and build the LLM prompt without loading the model.

    Returns (prepared_state, prompt_display, llm_response, elapsed_label).
    """
    elapsed = _running_elapsed_label(start_time)

    if not template:
        return None, "", "// 请先选择模板", elapsed

    try:
        sheet_columns, sample_rows, using_manual_cols, fetch_error = _gather_llm_test_sheet_data(
            template, test_cols, worksheet_name, credentials
        )
        if fetch_error:
            gr.Warning(fetch_error)
            return None, "", f"// {fetch_error}", elapsed

        if using_manual_cols:
            gr.Info("使用手动选择的列进行测试")
        else:
            sheet_label = worksheet_name or "Sheet"
            gr.Info(f"已读取 {sheet_label}：{len(sheet_columns)} 列，{len(sample_rows)} 行样本")

        if len(sample_rows) < 5:
            gr.Warning(f"仅有 {len(sample_rows)} 行样本，建议至少 5 行以提高匹配准确率")

        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            return None, "", "// 模板配置未找到", elapsed

        if test_cols and len(test_cols) > 0:
            filtered_columns = [c for c in sheet_columns if c in test_cols]
            filtered_rows = [
                {k: v for k, v in row.items() if k in filtered_columns} for row in sample_rows
            ]
            gr.Info(f"仅测试选中的 {len(filtered_columns)} 列：{', '.join(filtered_columns)}")
        else:
            filtered_columns = sheet_columns
            filtered_rows = sample_rows

        if not filtered_columns:
            return None, "", "// 无可用列可用于匹配", elapsed

        yaml_field_names = list(paste_config.field_rules.keys())
        if not yaml_field_names:
            return None, "", "// 模板无字段", elapsed

        yaml_fields = _collect_yaml_fields(paste_config.to_dict())
        source_data = _build_llm_test_source_data(filtered_columns, filtered_rows)
        prompt_text = build_batch_field_mapping_prompt(source_data, yaml_field_names)

        prepared: dict[str, Any] = {
            "template_id": template.id,
            "source_data": source_data,
            "yaml_field_names": yaml_field_names,
            "yaml_fields": yaml_fields,
            "filtered_columns": filtered_columns,
            "filtered_rows": filtered_rows,
            "using_manual_cols": using_manual_cols,
            "prompt_text": prompt_text,
        }

        gr.Info(f"Prompt 已构建（{len(prompt_text)} 字符），即将加载模型并推理…")
        return (
            prepared,
            prompt_text,
            "等待 LLM 响应…（正在加载模型）",
            elapsed,
        )

    except Exception as exc:
        logger.error("LLM test prompt preparation failed: %s", exc)
        return None, "", f"// 构建 Prompt 失败：{exc}", elapsed


def run_llm_test_generation(
    template: TemplateConfig | None,
    prepared_state: dict[str, Any] | None,
    cancel_state: dict[str, bool],
    start_time: float,
    progress: gr.Progress = gr.Progress(),
):
    """
    Step 2: load model (if needed), run LLM inference, and format results.

    Yields (prompt_display, llm_response, test_result_yaml, elapsed_label).
    """
    def _tick(
        prompt: str = "",
        response: str = "",
        yaml_result: str = "",
    ) -> tuple[str, str, str, str]:
        return prompt, response, yaml_result, _running_elapsed_label(start_time)

    def _tick_stopped(
        prompt: str = "",
        response: str = "",
        yaml_result: str = "",
    ) -> tuple[str, str, str, str]:
        gr.Info("已停止测试")
        return prompt, response, yaml_result, _final_elapsed_label(start_time, stopped=True)

    if not template or not prepared_state:
        yield "", "// 无有效测试上下文（请先构建 Prompt）", "", "用时: —"
        return

    prompt_text = str(prepared_state.get("prompt_text") or "")
    source_data = prepared_state.get("source_data") or []
    yaml_field_names: list[str] = prepared_state.get("yaml_field_names") or []
    filtered_columns: list[str] = prepared_state.get("filtered_columns") or []

    try:
        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            yield _tick(prompt_text, response="// 模板配置未找到")
            return

        if not find_model_file():
            gr.Info("正在下载 Gemma 4 模型…")
            progress(0.15, desc="正在下载 Gemma 4 模型…")
            yield _tick(prompt_text, "正在下载模型…")
            if _is_llm_test_cancelled(cancel_state):
                yield _tick_stopped(prompt_text)
                return

            def download_progress(stage, current, total, msg):
                progress(0.15 + 0.15 * (current / total), desc=msg)

            try:
                ensure_model_downloaded(on_progress=download_progress)
                gr.Info("模型下载完成")
            except ModelDownloadError as exc:
                logger.error("Model download failed: %s", exc)
                yield _tick(prompt_text, response=f"// 模型下载失败：{exc}")
                return
            except Exception as exc:
                logger.error("Download failed: %s", exc)
                yield _tick(
                    prompt_text,
                    response=(
                        f"// 下载失败：{exc}\n"
                        "// 请运行 install.bat 安装依赖，或手动执行: pip install huggingface-hub psutil"
                    ),
                )
                return

        gr.Info("正在加载 Gemma 4 到内存（CPU，首次约 1–3 分钟）…")
        progress(0.35, desc="⏳ 正在加载 Gemma 4…")
        yield _tick(prompt_text, "正在加载模型到内存…")
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text)
            return

        def load_progress(stage, current, total, msg):
            progress(0.35 + 0.25 * (current / total), desc=f"⏳ {msg}")

        matcher = get_or_create_field_matcher(on_progress=load_progress)

        progress(0.65, desc="✓ Gemma 4 已加载")
        yield _tick(prompt_text, "模型已加载，正在推理…")
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text)
            return
        if not matcher:
            detail = get_last_load_error()
            if detail:
                yield _tick(prompt_text, response=f"// Gemma 4 模型加载失败\n// {detail}")
            else:
                yield _tick(
                    prompt_text,
                    response=(
                        "// Gemma 4 模型加载失败\n"
                        f"// 当前 Python: {sys.executable}\n"
                        "// 请确认 models/gemma4/ 下已有 gemma-4-E4B_q4_0-it.gguf，并执行:\n"
                        f'// "{sys.executable}" -m pip install llama-cpp-python==0.3.28 '
                        f'--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu psutil'
                    ),
                )
            return

        gr.Info("开始 LLM 推理（CPU 上可能需数分钟，最长 10 分钟）…")
        progress(0.7, desc="⏳ LLM 推理中…")
        yield _tick(prompt_text, "LLM 推理中…")
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text)
            return

        gen_started = time.monotonic()
        inference_result: dict[str, Any] = {}
        inference_error: list[Exception] = []

        def _run_batch_inference() -> None:
            try:
                batch_mappings, _, batch_response = matcher.batch_match_all_fields(
                    source_data,
                    yaml_field_names,
                    prompt=prompt_text,
                )
                inference_result["mappings"] = batch_mappings
                inference_result["response_text"] = batch_response
            except Exception as exc:
                inference_error.append(exc)

        inference_thread = threading.Thread(target=_run_batch_inference, daemon=True)
        inference_thread.start()
        while inference_thread.is_alive():
            if _is_llm_test_cancelled(cancel_state):
                yield _tick_stopped(prompt_text, "推理已取消（模型可能仍在后台运行）")
                return
            yield _tick(prompt_text, "LLM 推理中…")
            inference_thread.join(timeout=LLM_TEST_TICK_INTERVAL_S)
        gen_elapsed = time.monotonic() - gen_started
        if inference_error:
            raise inference_error[0]
        mappings = inference_result.get("mappings") or {}
        response_text = str(inference_result.get("response_text") or "")
        logger.info("LLM test batch inference completed in %.1fs", gen_elapsed)
        if gen_elapsed >= 120:
            gr.Warning(f"LLM 推理耗时 {_format_elapsed_seconds(gen_elapsed)}（CPU 较慢属正常）")

        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text, response_text)
            return

        filtered_rows: list[dict[str, str]] = prepared_state.get("filtered_rows") or []
        transform_prompts: list[str] = []
        prompt_with_transforms = prompt_text
        if filtered_rows and mappings:
            progress(0.78, desc="⏳ 检测格式不匹配并推断转换…")
            mismatches = matcher.detect_format_mismatches(mappings, filtered_rows)
            for source_column, target_fields in mismatches.items():
                sample_values = [
                    str(row.get(source_column, "") or "") for row in filtered_rows[:5]
                ]
                transform_prompts.append(
                    matcher._build_transformation_inference_prompt(
                        source_column,
                        sample_values,
                        target_fields,
                    )
                )
            prompt_with_transforms = prompt_text
            if transform_prompts:
                prompt_with_transforms += (
                    "\n\n--- Transformation pass prompts ---\n\n"
                    + "\n\n---\n\n".join(transform_prompts)
                )
            yield _tick(prompt_with_transforms, response_text + "\n\n--- 转换推断中… ---")
            transform_result: dict[str, Any] = {}
            transform_error: list[Exception] = []

            def _run_transform_inference() -> None:
                try:
                    transform_rules, enriched = matcher.enrich_mappings_with_transformations(
                        mappings,
                        filtered_rows,
                    )
                    transform_result["transformations"] = transform_rules
                    transform_result["mappings"] = enriched
                except Exception as exc:
                    transform_error.append(exc)

            transform_thread = threading.Thread(target=_run_transform_inference, daemon=True)
            transform_thread.start()
            while transform_thread.is_alive():
                if _is_llm_test_cancelled(cancel_state):
                    yield _tick_stopped(prompt_with_transforms, response_text)
                    return
                yield _tick(prompt_with_transforms, response_text + "\n\n--- 转换推断中… ---")
                transform_thread.join(timeout=LLM_TEST_TICK_INTERVAL_S)
            if transform_error:
                logger.warning("Transformation pass failed: %s", transform_error[0])
            else:
                transformations = transform_result.get("transformations") or {}
                mappings = transform_result.get("mappings") or mappings
                response_text += _format_transformation_summary(transformations)

        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text, response_text)
            return

        progress(0.85, desc="⏳ 生成 YAML 结果…")
        yield _tick(prompt_with_transforms if transform_prompts else prompt_text, response_text)

        from app.services.data_source import load_template_data_source

        data_source = load_template_data_source(template.id)
        id_sheet_col = data_source.id_column if data_source else None

        result_yaml = _build_llm_test_yaml_from_mappings(
            paste_config,
            mappings,
            filtered_columns,
            id_sheet_col,
        )
        yield _tick(prompt_text, response_text, result_yaml)

        progress(1.0, desc="✓ 匹配完成")
        gr.Info("LLM 测试完成")

    except Exception as exc:
        logger.error("LLM test failed: %s", exc)
        yield _tick(prompt_text, response=f"// 测试失败：{exc}")


def handle_sections_save(
    template: TemplateConfig | None,
    input_area: str,
    move_direction: str,
    offset: int
) -> str:
    """
    Save sections configuration
    
    Returns:
        Status message
    """
    if not template:
        return "❌ 请先选择模板"
    
    if not input_area or not input_area.strip():
        return "❌ 请输入区域范围"
    
    try:
        # Ensure config exists (create default if not)
        from pathlib import Path
        from app.services.paste_parse_config import ensure_config_exists
        
        template_path = Path(template.file_path)
        ensure_config_exists(template.id, template_path)
        
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            default_config = create_default_config_from_template(template_path)
            paste_config = default_config
        
        # Create sections config
        sections_config = [{
            "input_area": input_area.strip(),
            "move_to": move_direction,
            "offset": int(offset)
        }]
        
        paste_config.sections = sections_config
        
        config_path = paste_config_path(template.id)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        yaml_str = config_to_yaml(paste_config.to_dict())
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(yaml_str)
        
        logger.info(f"Saved sections config for template: {template.id}")
        
        return f"✓ 区域配置已保存\n输入区域: {input_area}\n方向: {move_direction}\n偏移: {offset}"
    
    except Exception as e:
        logger.error(f"Failed to save sections: {e}")
        return f"❌ 保存失败：{str(e)}"
