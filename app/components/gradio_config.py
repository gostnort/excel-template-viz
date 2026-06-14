"""
Gradio Config Tab Component

Handles YAML configuration editing, LLM settings, and template parameters.
"""
import gradio as gr
import logging
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
    ModelDownloadError,
    create_field_matcher,
    ensure_model_downloaded,
    find_model_file,
    get_last_load_error,
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
                
                test_llm_btn = gr.Button("🧪 测试 LLM 匹配", variant="primary")
                
                test_result = gr.Code(
                    label="匹配结果",
                    language="json",
                    lines=15,
                    value=""
                )
                
                components["test_sheet_cols"] = test_sheet_cols
                components["test_llm_btn"] = test_llm_btn
                components["test_result"] = test_result
    
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
    test_llm_btn.click(
        fn=lambda: gr.update(interactive=False),
        outputs=[test_llm_btn],
    ).then(
        fn=handle_llm_test,
        inputs=[current_template, test_sheet_cols, credentials_state],
        outputs=[test_result],
    ).then(
        fn=lambda: gr.update(interactive=True),
        outputs=[test_llm_btn],
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


def _fetch_sheet_columns_and_sample(
    template: TemplateConfig,
    credentials: Any,
) -> tuple[list[str], dict[str, str], str | None]:
    """Load sheet column names and a sample row from the connected data source."""
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
            return [], {}, "工作表为空，无法获取列名"
        return columns, {col: "" for col in columns}, None

    columns = list(df.columns)
    first_row = df.row(0, named=True)
    sample_row = {col: str(first_row.get(col, "") or "") for col in columns}
    return columns, sample_row, None


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
) -> Iterator[tuple[str, dict[str, str | None]]]:
    """Yield (stage, column_map) while LLM-matching remaining template fields."""
    used_columns = {col for col in existing_mapping.values() if col}
    remaining_fields = [f for f in template_fields if not existing_mapping.get(f)]
    result = dict(existing_mapping)

    if not remaining_fields:
        yield ("", result)
        return

    yaml_fields: list[tuple[str, str]] = []
    for field_name in remaining_fields:
        rules = paste_config.field_rules.get(field_name, [])
        hint = field_name
        if rules:
            rule = rules[0]
            if rule.filed and rule.filed != "?":
                hint = rule.filed
        yaml_fields.append((field_name, hint))

    total = len(yaml_fields)
    for index, (field_name, hint) in enumerate(yaml_fields, start=1):
        stage = f"正在匹配 {field_name} ({index}/{total})…"
        yield (stage, dict(result))

        available = [c for c in sheet_columns if c not in used_columns]
        column = matcher._try_exact_column_match(field_name, hint, available)
        if column is None:
            empty_row = {col: "" for col in available}
            column = matcher._llm_match_column(
                field_name, hint, empty_row, available
            )

        if column and column not in used_columns:
            result[field_name] = column
            used_columns.add(column)
        elif column:
            result[field_name] = column
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
        matcher, template_fields, sheet_columns, paste_config, existing_mapping
    ):
        result = partial
        if on_progress and stage:
            on_progress(stage, {k: v or "" for k, v in partial.items() if k in partial})
    return result


def _format_llm_test_json(
    stage: str,
    matched: dict[str, str],
    *,
    sheet_columns: list[str] | None = None,
    sample_row: dict[str, str] | None = None,
) -> str:
    """Format incremental LLM test output for the result panel."""
    import json

    payload: dict[str, Any] = {
        "阶段": stage,
        "匹配结果": matched,
    }
    if sheet_columns is not None:
        payload["Sheet列"] = sheet_columns
    if sample_row is not None:
        payload["样本行"] = sample_row
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _apply_column_mapping_to_config(
    paste_config: PasteParseConfig,
    column_map: dict[str, str | None],
    sheet_columns: list[str],
    id_sheet_col: str | None,
) -> PasteParseConfig:
    """Update field_rules and order entries from a template-field -> sheet-column map."""
    col_index = {col: idx for idx, col in enumerate(sheet_columns)}

    new_field_rules: dict[str, list[PasteParseRule]] = {}
    for field_name, rules in paste_config.field_rules.items():
        matched_col = column_map.get(field_name)
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
        matched_col = column_map.get(field_name)
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
):
    """
    Auto-fill YAML field mappings using sheet columns and Phi-4 matching.

    Yields incremental (yaml_editor, yaml_status) updates while matching.
    """
    if not template:
        yield "", "❌ 请先选择模板"
        return

    yield gr.skip(), "⏳ 正在读取 Sheet 列…"
    columns, sample_row, fetch_error = _fetch_sheet_columns_and_sample(template, credentials)
    if fetch_error:
        gr.Warning(fetch_error)
        yield gr.skip(), f"⚠️ {fetch_error}"
        return

    gr.Info(f"已读取 Sheet：{len(columns)} 列")

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
            if not rules:
                continue
            rule = rules[0]
            if rule.filed and rule.filed != "?" and rule.index >= 0:
                filed_hints[field_name] = rule.filed

        yield gr.skip(), f"⏳ 精确匹配 {len(template_fields)} 个字段…"
        column_map = _exact_match_columns(template_fields, columns, filed_hints)
        exact_count = sum(1 for col in column_map.values() if col)

        unmatched = [f for f in template_fields if not column_map.get(f)]
        llm_used = False

        if unmatched:
            if not find_model_file():
                gr.Info("正在下载 Phi-4 模型…")
                yield gr.skip(), "⏳ 正在下载 Phi-4 模型…"
                try:
                    ensure_model_downloaded(auto_mode=True)
                    gr.Info("模型下载完成")
                except ModelDownloadError as exc:
                    logger.error("Model download failed: %s", exc)
                    if exact_count == 0:
                        yield "", f"❌ 模型下载失败：{exc}"
                        return
                    gr.Warning(f"LLM 不可用（{exc}），已使用精确名称匹配")
                except Exception as exc:
                    logger.error("Download failed: %s", exc)
                    if exact_count == 0:
                        yield "", f"❌ LLM 不可用：{exc}"
                        return
                    gr.Warning(f"LLM 不可用（{exc}），已使用精确名称匹配")

            if find_model_file():
                gr.Info("正在加载 Phi-4…")
                yield gr.skip(), "⏳ 正在加载 Phi-4…"
                matcher = create_field_matcher()
                if matcher:
                    llm_used = True
                    gr.Info(f"Phi-4 就绪，匹配剩余 {len(unmatched)} 个字段…")

                    for stage, partial_map in _iter_llm_match_columns(
                        matcher,
                        template_fields,
                        columns,
                        paste_config,
                        column_map,
                    ):
                        column_map = partial_map
                        if stage:
                            matched_so_far = sum(1 for c in column_map.values() if c)
                            status = f"⏳ {stage}（已匹配 {matched_so_far}/{len(template_fields)}）"
                            gr.Info(stage)
                            yield gr.skip(), status
                elif exact_count == 0:
                    yield "", "❌ Phi-4 模型加载失败，且精确名称匹配无结果"
                    return
                else:
                    gr.Warning("Phi-4 模型加载失败，已使用精确名称匹配")
            elif exact_count == 0:
                yield "", "❌ LLM 模型不可用，且精确名称匹配无结果"
                return

        from app.services.data_source import load_template_data_source

        data_source = load_template_data_source(template.id)
        id_sheet_col = data_source.id_column if data_source else None

        updated_config = _apply_column_mapping_to_config(
            paste_config,
            column_map,
            columns,
            id_sheet_col,
        )
        yaml_str = config_to_yaml(updated_config.to_dict())

        matched_count = sum(1 for col in column_map.values() if col)
        unmapped_count = len(template_fields) - matched_count
        method = "Phi-4 + 精确匹配" if llm_used else "精确名称匹配"
        status = f"✓ 自动配置完成（{method}）：{matched_count}/{len(template_fields)} 个字段已匹配"
        if unmapped_count:
            status += f"，{unmapped_count} 个未映射（filed=\"?\", index=-1）"

        yield yaml_str, status

    except Exception as exc:
        logger.error("Auto config failed: %s", exc)
        yield "", f"❌ 自动配置失败：{exc}"


def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: list | None,
    credentials: Any,
):
    """
    Test LLM field matching with incremental result updates.

    Yields JSON strings into the result panel as each field is matched.
    """
    if not template:
        yield "// 请先选择模板"
        return

    try:
        sheet_columns: list[str] = []
        sample_row: dict[str, str] = {}
        using_manual_cols = False

        yield _format_llm_test_json("正在读取 Sheet 列…", {})

        columns, fetched_sample, fetch_error = _fetch_sheet_columns_and_sample(
            template, credentials
        )
        if fetch_error:
            if not test_cols:
                gr.Warning(fetch_error)
                yield f"// {fetch_error}"
                return
            sheet_columns = list(test_cols)
            sample_row = {col: f"测试值_{i + 1}" for i, col in enumerate(test_cols)}
            using_manual_cols = True
            gr.Info("使用手动选择的列进行测试")
        else:
            sheet_columns = columns
            sample_row = fetched_sample
            gr.Info(f"已读取 Sheet：{len(columns)} 列")

        yield _format_llm_test_json(
            f"已读取 {len(sheet_columns)} 列",
            {},
            sheet_columns=sheet_columns,
            sample_row=sample_row if not using_manual_cols else None,
        )

        paste_config = load_paste_parse_config(template.id)
        if not paste_config:
            yield "// 模板配置未找到"
            return

        if not find_model_file():
            gr.Info("正在下载 Phi-4 模型…")
            yield _format_llm_test_json("正在下载 Phi-4 模型…", {})
            try:
                ensure_model_downloaded(auto_mode=True)
                gr.Info("模型下载完成")
            except ModelDownloadError as exc:
                logger.error("Model download failed: %s", exc)
                yield f"// 模型下载失败：{exc}"
                return
            except Exception as exc:
                logger.error("Download failed: %s", exc)
                yield (
                    f"// 下载失败：{exc}\n"
                    "// 请运行 install.bat 安装依赖，或手动执行: pip install huggingface-hub psutil"
                )
                return

        gr.Info("正在加载 Phi-4…")
        yield _format_llm_test_json("正在加载 Phi-4…", {})

        matcher = create_field_matcher()
        if not matcher:
            detail = get_last_load_error()
            if detail:
                yield f"// Phi-4 模型加载失败\n// {detail}"
            else:
                yield (
                    "// Phi-4 模型加载失败\n"
                    "// 请确认 models/phi4/ 下已有 GGUF 文件，并运行 install.bat 安装 "
                    "torch、transformers>=5.0、gguf>=0.10.0"
                )
            return

        gr.Info("Phi-4 就绪，开始逐字段匹配…")
        yaml_dict = paste_config.to_dict()
        matched: dict[str, str] = {}

        for stage, partial in matcher.iter_match_sheet_fields_to_yaml(
            sample_row, yaml_dict
        ):
            matched = partial
            if "正在匹配" in stage:
                gr.Info(stage)
            yield _format_llm_test_json(
                stage,
                matched,
                sheet_columns=sheet_columns,
                sample_row=sample_row if not using_manual_cols else None,
            )

    except Exception as exc:
        logger.error("LLM test failed: %s", exc)
        yield f"// 测试失败：{exc}"


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
