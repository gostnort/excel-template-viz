"""
Gradio Config Tab Component

Handles YAML configuration editing, LLM settings, and template parameters.
"""
import gradio as gr
import json
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from app.services.registry import TemplateConfig
from app.services.paste_parse_config import (
    PasteParseConfig,
    PasteParseRule,
    UNMAPPED_INDEX,
    _default_order_entry,
    _default_unmapped_rule,
    _order_entry_to_dict,
    config_to_yaml,
    config_from_dict,
    create_default_config_from_template,
    ensure_config_exists,
    load_paste_parse_config,
    paste_config_path,
    resolve_sheet_header,
)
from app.services.phi4_field_matcher import (
    FieldMatchResult,
    ModelDownloadError,
    create_field_matcher,
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


def update_llm_test_columns(
    template: TemplateConfig | None,
    credentials: Any
) -> gr.Dropdown:
    """
    Update LLM test columns dropdown with columns from connected data source
    
    Returns:
        gr.update with dropdown choices
    """
    if not template:
        return gr.update(choices=[], value=None, info='从已连接的 Google Sheet 中选择列（如未显示选项，请先在"数据源"标签页连接 Sheet）')
    
    try:
        from app.services.data_source import load_template_data_source
        from app.services.google_sheets import fetch_sheet_preview
        
        # Load data source config
        data_source = load_template_data_source(template.id)
        
        if not data_source:
            return gr.update(
                choices=[], 
                value=None, 
                info='⚠️ 未配置数据源，请先在"数据源"标签页连接 Google Sheet'
            )
        
        if not credentials:
            return gr.update(
                choices=[], 
                value=None, 
                info='⚠️ 未授权，请先在"数据源"标签页授权 Google 账号'
            )
        
        # Fetch columns from sheet
        df, _ = fetch_sheet_preview(
            credentials,
            data_source.sheet_url,
            data_source.worksheet_name
        )
        
        if df.height == 0:
            return gr.update(
                choices=[], 
                value=None, 
                info="⚠️ 工作表为空"
            )
        
        columns = list(df.columns)
        
        return gr.update(
            choices=columns, 
            value=None, 
            info=f"✓ 已加载 {len(columns)} 列（来自 {data_source.worksheet_name}）"
        )
        
    except Exception as e:
        logger.error(f"Failed to load columns: {e}")
        return gr.update(
            choices=[], 
            value=None, 
            info=f"⚠️ 加载列失败：{str(e)}"
        )


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
                gr.Markdown("使用 Phi-4 模型智能匹配字段（首次使用会自动下载）")
                
                # Test LLM matching
                with gr.Row():
                    test_sheet_cols = gr.Dropdown(
                        label="测试 Sheet 列名",
                        choices=[],
                        value=None,
                        multiselect=True,
                        interactive=True,
                        info='从已连接的 Google Sheet 中选择列（如未显示选项，请先在"数据源"标签页连接 Sheet）'
                    )
                
                llm_test_cancel = gr.State({"cancelled": False})
                llm_test_start_time = gr.State(0.0)

                with gr.Row():
                    test_llm_btn = gr.Button("🧪 测试 LLM 匹配", variant="primary")
                    stop_llm_btn = gr.Button("⏹ 停止测试", variant="stop", interactive=False)
                    llm_test_elapsed = gr.Markdown("已用时: —")
                
                # 新增：显示 Prompt
                with gr.Accordion("📝 LLM Prompt", open=False):
                    prompt_display = gr.Textbox(
                        label="发送给 LLM 的 Prompt",
                        lines=10,
                        interactive=False,
                        placeholder="点击测试后将显示 prompt..."
                    )
                
                # 新增：显示 LLM 响应
                with gr.Accordion("🤖 LLM 响应", open=False):
                    llm_response = gr.Textbox(
                        label="LLM 原始响应",
                        lines=5,
                        interactive=False,
                        placeholder="等待 LLM 响应..."
                    )
                
                # 匹配结果
                with gr.Accordion("✅ 匹配结果", open=True):
                    test_result_yaml = gr.Code(
                        label="可复制 YAML 片段（粘贴到「YAML 配置」标签页或 .paste.yaml）",
                        language="yaml",
                        lines=18,
                        value="",
                        interactive=False,
                    )
                    with gr.Accordion("JSON 调试输出", open=False):
                        test_result = gr.Code(
                            label="匹配结果 JSON",
                            language="json",
                            lines=12,
                            value="",
                            interactive=False,
                        )
                
                components["test_sheet_cols"] = test_sheet_cols
                components["llm_test_cancel"] = llm_test_cancel
                components["llm_test_start_time"] = llm_test_start_time
                components["test_llm_btn"] = test_llm_btn
                components["stop_llm_btn"] = stop_llm_btn
                components["llm_test_elapsed"] = llm_test_elapsed
                components["prompt_display"] = prompt_display
                components["llm_response"] = llm_response
                components["test_result"] = test_result
                components["test_result_yaml"] = test_result_yaml
    
    components["config_tabs"] = config_tabs

    # Event bindings
    
    # Update dropdown when template changes or data source connects
    current_template.change(
        fn=update_llm_test_columns,
        inputs=[current_template, credentials_state],
        outputs=[test_sheet_cols]
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
    
    # LLM tab events
    llm_test_event = test_llm_btn.click(
        fn=_begin_llm_test,
        outputs=[test_llm_btn, stop_llm_btn, llm_test_cancel, llm_test_start_time, llm_test_elapsed],
    ).then(
        fn=handle_llm_test,
        inputs=[current_template, test_sheet_cols, credentials_state, llm_test_cancel, llm_test_start_time],
        outputs=[prompt_display, llm_response, test_result, test_result_yaml, llm_test_elapsed],
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
) -> tuple[list[str], list[dict[str, str]], str | None]:
    """Load sheet columns and sample rows from the connected data source."""
    from app.services.data_source import load_template_data_source
    from app.services.google_sheets import fetch_sheet_preview

    data_source = load_template_data_source(template.id)
    if not data_source:
        return [], {}, '请先在"数据源"标签页连接 Google Sheet'

    if not credentials:
        return [], {}, '请先在"数据源"标签页授权 Google 账号'

    try:
        df, _ = fetch_sheet_preview(
            credentials,
            data_source.sheet_url,
            data_source.worksheet_name,
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


def _fetch_sheet_columns_and_sample(
    template: TemplateConfig,
    credentials: Any,
) -> tuple[list[str], dict[str, str], str | None]:
    """Backward compatible wrapper returning only the first sample row."""
    columns, sample_rows, err = _fetch_sheet_columns_and_samples(template, credentials)
    first_row = sample_rows[0] if sample_rows else {col: "" for col in columns}
    return columns, first_row, err


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


def _iter_llm_match_columns(
    matcher: Any,
    template_fields: list[str],
    sheet_columns: list[str],
    paste_config: PasteParseConfig,
    existing_mapping: dict[str, str | None],
    sample_row: dict[str, str],  # Now use sample values
) -> Iterator[tuple[str, dict[str, str | None]]]:
    """
    Yield (stage, column_map) while using semantic similarity for batch matching.

    Args:
        matcher: Phi4FieldMatcher instance
        template_fields: List of template field names
        sheet_columns: List of sheet column names
        paste_config: Paste parse configuration
        existing_mapping: Existing exact matches
        sample_row: Sample row values for semantic matching

    Yields:
        (stage_message, column_map) tuples
    """
    used_columns = {col for col in existing_mapping.values() if col}
    remaining_fields = [f for f in template_fields if not existing_mapping.get(f)]
    result = dict(existing_mapping)

    if not remaining_fields:
        yield ("", result)
        return

    # Build (field_name, hint) list for semantic matching
    yaml_fields: list[tuple[str, str]] = []
    for field_name in remaining_fields:
        rules = paste_config.field_rules.get(field_name, [])
        hint = field_name
        if rules:
            rule = rules[0]
            if rule.filed and rule.filed != "?":
                hint = rule.filed
        yaml_fields.append((field_name, hint))

    # Get available columns
    available = [c for c in sheet_columns if c not in used_columns]
    
    if not available:
        yield ("无可用列", result)
        return

    # Batch semantic similarity computation
    yield ("正在计算语义相似度...", result)
    
    try:
        matches = matcher.compute_semantic_similarity(
            yaml_fields,
            available,
            sample_row
        )
    except Exception as exc:
        logger.error("Semantic similarity failed: %s", exc)
        # Fallback to LLM single-field matching
        matches = {}

    # Yield results one by one for progress display
    total = len(yaml_fields)
    for index, (field_name, hint) in enumerate(yaml_fields, start=1):
        stage = f"正在匹配 {field_name} ({index}/{total})…"
        
        if field_name in matches:
            column, similarity, col_idx = matches[field_name]
            
            # Similarity threshold check (≥0.7)
            if similarity >= 0.7:
                result[field_name] = column
                used_columns.add(column)
                logger.debug(f"Matched {field_name} → {column} (similarity: {similarity:.2f})")
            else:
                # Similarity too low, fallback to LLM single-field match
                logger.debug(f"Similarity too low ({similarity:.2f}), using LLM for {field_name}")
                available_now = [c for c in sheet_columns if c not in used_columns]
                column_llm = matcher._try_exact_column_match(field_name, hint, available_now)
                if column_llm is None:
                    column_llm = matcher._llm_match_column(
                        field_name, hint, sample_row, available_now
                    )
                
                if column_llm and column_llm not in used_columns:
                    result[field_name] = column_llm
                    used_columns.add(column_llm)
                else:
                    result[field_name] = None
        else:
            result[field_name] = None
        
        yield (stage, dict(result))


def _llm_match_columns(
    matcher: Any,
    template_fields: list[str],
    sheet_columns: list[str],
    sample_row: dict[str, str],
    paste_config: PasteParseConfig,
    existing_mapping: dict[str, str | None],
    on_progress: Any | None = None,
) -> dict[str, str | None]:
    """Use Phi4FieldMatcher to map remaining template fields to sheet columns."""
    result = dict(existing_mapping)
    for stage, partial in _iter_llm_match_columns(
        matcher, template_fields, sheet_columns, paste_config, existing_mapping, sample_row
    ):
        result = partial
        if on_progress and stage:
            on_progress(stage, {k: v or "" for k, v in partial.items() if k in partial})
    return result


def _format_llm_test_json(
    progress_stage: str,
    yaml_config_dict: dict[str, list[FieldMatchResult]],
    *,
    sheet_columns: list[str] | None = None,
    sample_row: dict[str, str] | None = None,
    batch_mappings: dict[str, dict[str, Any]] | None = None,
    transformations: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """
    Format test output as YAML-ready JSON.

    Args:
        progress_stage: Current stage message
        yaml_config_dict: Field name -> list of FieldMatchResult
        sheet_columns: Sheet column names (optional)
        sample_row: Sample row data (optional)

    Returns:
        JSON string with YAML configuration format
    """
    import json

    payload: dict[str, Any] = {
        "progress": {
            "stage": "match",
            "message": progress_stage,
        },
        "yaml_config": {
            field: [asdict(result) for result in results]
            for field, results in yaml_config_dict.items()
        },
    }
    
    if sheet_columns is not None or sample_row is not None:
        payload["sheet_meta"] = {}
        if sheet_columns is not None:
            payload["sheet_meta"]["columns"] = sheet_columns
        if sample_row is not None:
            payload["sheet_meta"]["sample_row"] = sample_row
    if batch_mappings is not None:
        payload["batch_mappings"] = batch_mappings
    if transformations is not None:
        payload["transformations"] = transformations
    
    return json.dumps(payload, ensure_ascii=False, indent=2)


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
    )
    return config_to_yaml(updated_config.to_dict())


def _apply_column_mapping_to_config(
    paste_config: PasteParseConfig,
    column_map: dict[str, str | None] | dict[str, dict[str, Any]],
    sheet_columns: list[str],
    id_sheet_col: str | None,
) -> PasteParseConfig:
    """Update field_rules and order entries from a template-field -> sheet-column map."""
    col_index = {col: idx for idx, col in enumerate(sheet_columns)}

    new_field_rules: dict[str, list[PasteParseRule]] = {}
    for field_name, rules in paste_config.field_rules.items():
        mapping_entry = column_map.get(field_name)
        matched_col: str | None
        if isinstance(mapping_entry, dict):
            matched_col = str(mapping_entry.get("filed", "?") or "?")
            if matched_col == "?":
                matched_col = None
        else:
            matched_col = mapping_entry
        new_rules: list[PasteParseRule] = []
        for rule in rules:
            if matched_col:
                idx = col_index.get(matched_col, UNMAPPED_INDEX)
                id_flag = rule.id_flag
                if id_sheet_col and matched_col == id_sheet_col:
                    id_flag = True
                new_rules.append(
                    PasteParseRule(
                        filed=matched_col,
                        index=idx,
                        regex=rule.regex,
                        id_flag=id_flag,
                    )
                )
            else:
                new_rules.append(_default_unmapped_rule(id_flag=rule.id_flag))
        new_field_rules[field_name] = new_rules

    new_order = [_default_order_entry()]
    for field_name in paste_config.field_rules:
        mapping_entry = column_map.get(field_name)
        if isinstance(mapping_entry, dict):
            matched_col = str(mapping_entry.get("filed", "?") or "?")
            if matched_col == "?":
                matched_col = None
        else:
            matched_col = mapping_entry
        if matched_col:
            idx = col_index.get(matched_col, UNMAPPED_INDEX)
            new_order.append(_order_entry_to_dict({"filed": matched_col, "index": idx}))
        else:
            new_order.append(_default_order_entry())

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
    Auto-fill YAML field mappings using sheet columns and Phi-4 matching.

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
            gr.Info("正在下载 Phi-4 模型…")
            progress(0.2, desc="⏳ 正在下载 Phi-4 模型…")
            yield gr.skip(), "⏳ 正在下载 Phi-4 模型…"

            def download_progress(stage, current, total, msg):
                progress(0.2 + 0.2 * (current / total), desc=msg)

            try:
                ensure_model_downloaded(auto_mode=True, on_progress=download_progress)
                gr.Info("模型下载完成")
            except ModelDownloadError as exc:
                logger.error("Model download failed: %s", exc)
                gr.Warning(f"LLM 不可用（{exc}），已回退到精确名称匹配")
            except Exception as exc:
                logger.error("Download failed: %s", exc)
                gr.Warning(f"LLM 不可用（{exc}），已回退到精确名称匹配")

        progress(0.4, desc="⏳ 正在加载 Phi-4…")
        yield gr.skip(), "⏳ 正在加载 Phi-4…"

        def load_progress(stage, current, total, msg):
            progress(0.4 + 0.2 * (current / total), desc=f"⏳ {msg}")

        matcher = get_or_create_field_matcher(on_progress=load_progress)
        batch_mappings: dict[str, dict[str, Any]] = {}
        llm_used = False

        if matcher and sample_rows and columns:
            progress(0.65, desc="⏳ 一次性批量匹配所有字段…")
            yield gr.skip(), "⏳ 一次性批量匹配所有字段…"
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
            batch_mappings, _, _ = matcher.batch_match_all_fields(source_data, template_fields)
            llm_used = True
        else:
            gr.Warning("Phi-4 模型不可用，已回退到精确名称匹配")

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
        method = "批量 Phi-4 + 精确回退" if llm_used else "精确名称匹配"
        
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


def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: list | None,
    credentials: Any,
    cancel_state: dict[str, bool],
    start_time: float,
    progress: gr.Progress = gr.Progress(),
):
    """
    Test LLM field matching with prompt and response display.

    Args:
        template: Current template
        test_cols: Selected test columns (optional)
        credentials: Google OAuth credentials
        cancel_state: Mutable cancel flag from gr.State
        start_time: Monotonic timestamp when the test started
        progress: Gradio Progress component

    Yields (prompt_display, llm_response, test_result_json, test_result_yaml, elapsed_label) tuples.
    """
    def _tick(
        prompt: str = "",
        response: str = "",
        result: str = "",
        yaml_result: str = "",
    ) -> tuple[str, str, str, str, str]:
        return prompt, response, result, yaml_result, _running_elapsed_label(start_time)

    def _tick_stopped(
        prompt: str = "",
        response: str = "",
        result: str = "// 测试已停止",
        yaml_result: str = "",
    ) -> tuple[str, str, str, str, str]:
        gr.Info("已停止测试")
        return prompt, response, result, yaml_result, _final_elapsed_label(start_time, stopped=True)

    if not template:
        yield "", "", "// 请先选择模板", "", "用时: —"
        return

    try:
        sheet_columns: list[str] = []
        sample_rows: list[dict[str, str]] = []
        using_manual_cols = False

        progress(0, desc="正在读取 Sheet 样本数据…")
        yield _tick(result=_format_llm_test_json("正在读取 Sheet 样本数据…", {}))
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped()
            return

        columns, fetched_rows, fetch_error = _fetch_sheet_columns_and_samples(
            template, credentials
        )
        if fetch_error:
            if not test_cols:
                gr.Warning(fetch_error)
                yield _tick(result=f"// {fetch_error}")
                return
            sheet_columns = list(test_cols)
            sample_rows = [
                {col: f"测试值_{row_idx + 1}_{col}" for col in sheet_columns}
                for row_idx in range(5)
            ]
            using_manual_cols = True
            gr.Info("使用手动选择的列进行测试")
        else:
            sheet_columns = columns
            sample_rows = fetched_rows
            gr.Info(f"已读取 Sheet：{len(columns)} 列，{len(sample_rows)} 行样本")

        if len(sample_rows) < 5:
            gr.Warning(f"仅有 {len(sample_rows)} 行样本，建议至少 5 行以提高匹配准确率")

        progress(0.1, desc=f"已读取 {len(sheet_columns)} 列")
        yield _tick(
            result=_format_llm_test_json(
                f"已读取 {len(sheet_columns)} 列",
                {},
                sheet_columns=sheet_columns,
                sample_row=sample_rows[0] if sample_rows and not using_manual_cols else None,
            )
        )
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped()
            return

        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            yield _tick(result="// 模板配置未找到")
            return

        if not find_model_file():
            gr.Info("正在下载 Phi-4 模型…")
            progress(0.2, desc="正在下载 Phi-4 模型…")
            yield _tick(result=_format_llm_test_json("正在下载 Phi-4 模型…", {}))
            if _is_llm_test_cancelled(cancel_state):
                yield _tick_stopped()
                return
            
            def download_progress(stage, current, total, msg):
                progress(0.2 + 0.2 * (current / total), desc=msg)
            
            try:
                ensure_model_downloaded(auto_mode=True, on_progress=download_progress)
                gr.Info("模型下载完成")
            except ModelDownloadError as exc:
                logger.error("Model download failed: %s", exc)
                yield _tick(result=f"// 模型下载失败：{exc}")
                return
            except Exception as exc:
                logger.error("Download failed: %s", exc)
                yield _tick(
                    result=(
                        f"// 下载失败：{exc}\n"
                        "// 请运行 install.bat 安装依赖，或手动执行: pip install huggingface-hub psutil"
                    )
                )
                return

        gr.Info("正在加载 Phi-4…")
        progress(0.4, desc="⏳ 正在加载 Phi-4…")
        yield _tick(result=_format_llm_test_json("正在加载 Phi-4…", {}))
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped()
            return

        def load_progress(stage, current, total, msg):
            # Update progress bar during model loading
            progress(0.4 + 0.2 * (current / total), desc=f"⏳ {msg}")

        matcher = get_or_create_field_matcher(on_progress=load_progress)
        
        # Update progress after matcher is ready (important for cached matcher)
        progress(0.6, desc="✓ Phi-4 已加载")
        yield _tick(result=_format_llm_test_json("Phi-4 已加载", {}))
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped()
            return
        if not matcher:
            detail = get_last_load_error()
            if detail:
                yield _tick(result=f"// Phi-4 模型加载失败\n// {detail}")
            else:
                yield _tick(
                    result=(
                        "// Phi-4 模型加载失败\n"
                        "// 请确认 models/phi4/ 下已有 GGUF 文件，并运行 install.bat 安装 "
                        "torch、transformers>=5.0、gguf>=0.10.0"
                    )
                )
            return

        gr.Info("Phi-4 就绪，开始批量匹配…")
        yaml_dict = paste_config.to_dict()

        # Filter columns based on test_cols
        if test_cols and len(test_cols) > 0:
            filtered_columns = [c for c in sheet_columns if c in test_cols]
            filtered_rows = [{k: v for k, v in row.items() if k in filtered_columns} for row in sample_rows]
            gr.Info(f"仅测试选中的 {len(filtered_columns)} 列：{', '.join(filtered_columns)}")
        else:
            filtered_columns = sheet_columns
            filtered_rows = sample_rows

        if not filtered_columns:
            yield _tick(result="// 无可用列可用于匹配")
            return

        # Collect YAML fields
        yaml_fields = _collect_yaml_fields(yaml_dict)
        if not yaml_fields:
            yield _tick(result="// 模板无字段")
            return

        yaml_field_names = [name for name, _, _ in yaml_fields]

        progress(0.7, desc="⏳ 构建批量输入并调用 LLM…")
        if len(filtered_rows) >= 5:
            source_data = prepare_batch_input(filtered_columns, filtered_rows[:10], min_rows=5)
        else:
            source_data = [
                {
                    "index": idx,
                    "header": col,
                    "data": [str(row.get(col, "") or "") for row in filtered_rows],
                }
                for idx, col in enumerate(filtered_columns)
            ]

        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped()
            return

        mappings, prompt_text, response_text = matcher.batch_match_all_fields(source_data, yaml_field_names)
        if _is_llm_test_cancelled(cancel_state):
            yield _tick_stopped(prompt_text, response_text)
            return

        mismatches = matcher.detect_format_mismatches(mappings, filtered_rows)
        transformations = (
            matcher.infer_transformations_for_mismatches(mismatches, filtered_rows)
            if mismatches and not _is_llm_test_cancelled(cancel_state)
            else {}
        )

        yaml_config_results: dict[str, list[FieldMatchResult]] = {}
        field_regex_by_name = {field: regex for field, _, regex in yaml_fields}
        first_row = filtered_rows[0] if filtered_rows else {}
        for field_name in yaml_field_names:
            mapping = mappings.get(field_name, {"filed": "?", "index": -1})
            matched_col = str(mapping.get("filed", "?") or "?")
            col_index = int(mapping.get("index", -1) or -1)
            matched_value = str(first_row.get(matched_col, "") or "") if matched_col != "?" else ""
            similarity = 1.0 if matched_col != "?" else 0.0
            yaml_config_results[field_name] = [
                FieldMatchResult(
                    filed=matched_col,
                    index=col_index,
                    regex=field_regex_by_name.get(field_name),
                    similarity=similarity,
                    matched_value=matched_value,
                    regex_suggested=False,
                    ID=False,
                )
            ]

        from app.services.data_source import load_template_data_source

        data_source = load_template_data_source(template.id)
        id_sheet_col = data_source.id_column if data_source else None

        result_yaml = _build_llm_test_yaml_from_mappings(
            paste_config,
            mappings,
            filtered_columns,
            id_sheet_col,
        )

        result_json = _format_llm_test_json(
            "批量匹配完成",
            yaml_config_results,
            sheet_columns=filtered_columns,
            sample_row=first_row if not using_manual_cols else None,
            batch_mappings=mappings,
            transformations=transformations,
        )
        yield _tick(prompt_text, response_text, result_json, result_yaml)

        progress(1.0, desc="✓ 匹配完成")

    except Exception as exc:
        logger.error("LLM test failed: %s", exc)
        yield _tick(result=f"// 测试失败：{exc}")


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
