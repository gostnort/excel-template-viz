"""
Gradio Config Tab Component

Handles YAML configuration editing, LLM settings, and template parameters.
"""
import gradio as gr
import logging
from pathlib import Path
from typing import Any

from app.services.registry import TemplateConfig
from app.services.paste_parse_config import (
    load_paste_parse_config, config_to_yaml, config_from_dict,
    ensure_config_exists, create_default_config_from_template
)
from app.services.phi4_field_matcher import create_field_matcher, find_model_file

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
                    yaml_load_btn = gr.Button("🔄 重新加载", variant="secondary")
                    yaml_save_btn = gr.Button("💾 保存配置", variant="primary")
                    yaml_validate_btn = gr.Button("✓ 验证语法", variant="secondary")
                
                yaml_status = gr.Markdown("等待操作...")
                
                components["yaml_editor"] = yaml_editor
                components["yaml_load_btn"] = yaml_load_btn
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
    
    # Event bindings
    
    # Update dropdown when template changes or data source connects
    current_template.change(
        fn=update_llm_test_columns,
        inputs=[current_template, credentials_state],
        outputs=[test_sheet_cols]
    )
    
    # Load config when template changes
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
    )
    
    # YAML tab events
    yaml_load_btn.click(
        fn=handle_yaml_load,
        inputs=[current_template],
        outputs=[yaml_editor, yaml_status]
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
        fn=handle_llm_test,
        inputs=[current_template, test_sheet_cols],
        outputs=[test_result]
    )
    
    # Sections tab events
    sections_enabled.change(
        fn=lambda enabled: gr.update(visible=enabled),
        inputs=[sections_enabled],
        outputs=[sections_config_panel]
    )
    
    sections_save_btn.click(
        fn=handle_sections_save,
        inputs=[current_template, input_area, move_direction, offset_value],
        outputs=[sections_status]
    )
    
    return components


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


def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: list | None
) -> str:
    """
    Test LLM field matching (auto-downloads model if needed)
    
    Returns:
        JSON result
    """
    if not template:
        return "// 请先选择模板"
    
    if not test_cols or len(test_cols) == 0:
        return "// 请从下拉列表中选择列名"
    
    try:
        import json
        
        # Create test sheet row
        test_sheet_row = {col: f"测试值_{i+1}" for i, col in enumerate(test_cols)}
        
        # Load paste config
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            return "// 模板配置未找到"
        
        # Check if model exists, if not, auto-download
        model_file = find_model_file()
        if not model_file:
            gr.Info("首次使用，正在自动下载模型（根据内存自动选择量化版本）...")
            logger.info("Model not found, starting auto-download")
            
            try:
                import subprocess
                result = subprocess.run(
                    ["python", "scripts/download_phi4_model.py", "--auto"],
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minutes timeout
                )
                
                if result.returncode != 0:
                    error_msg = result.stderr or result.stdout
                    logger.error(f"Model download failed: {error_msg}")
                    return f"// 模型下载失败：{error_msg}"
                
                logger.info("Model downloaded successfully")
                gr.Info("模型下载完成！正在加载...")
            
            except subprocess.TimeoutExpired:
                return "// 模型下载超时，请检查网络连接"
            except Exception as e:
                logger.error(f"Download failed: {e}")
                return f"// 下载失败：{str(e)}"
        
        # Create matcher
        matcher = create_field_matcher()
        
        if not matcher:
            return "// Phi-4 模型加载失败"
        
        # Perform matching
        matched = matcher.match_sheet_fields_to_yaml(
            test_sheet_row,
            paste_config.to_dict()
        )
        
        # Format result
        result = {
            "输入列": test_cols,
            "匹配结果": matched
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        logger.error(f"LLM test failed: {e}")
        return f"// 测试失败：{str(e)}"


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
        
        # Load existing config
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            return "❌ 模板配置未找到"
        
        # Create sections config
        sections_config = [{
            "input_area": input_area.strip(),
            "move_to": move_direction,
            "offset": int(offset)
        }]
        
        # Update config
        paste_config.sections = sections_config
        
        # Save to file
        config_path = Path(f"templates/{template.id}/{template.id}.paste.yaml")
        
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        yaml_str = config_to_yaml(paste_config.to_dict())
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(yaml_str)
        
        logger.info(f"Saved sections config for template: {template.id}")
        
        return f"✓ 区域配置已保存\n输入区域: {input_area}\n方向: {move_direction}\n偏移: {offset}"
    
    except Exception as e:
        logger.error(f"Failed to save sections: {e}")
        return f"❌ 保存失败：{str(e)}"
