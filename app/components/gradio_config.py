"""
Gradio Config Tab Component

Handles YAML configuration editing, LLM settings, and template parameters.
"""
import gradio as gr
import logging
from pathlib import Path
from typing import Any

from app.services.registry import TemplateConfig
from app.services.paste_parse_config import load_paste_parse_config, config_to_yaml, config_from_dict
from app.services.phi4_field_matcher import create_field_matcher, find_model_file

logger = logging.getLogger(__name__)


def build_config_tab(
    current_template: gr.State
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
            # Sub-tab 1: YAML Configuration
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
            
            # Sub-tab 2: LLM Settings
            with gr.TabItem("LLM 设置"):
                gr.Markdown("配置 Phi-4 模型用于字段智能匹配")
                
                # Model info
                with gr.Row():
                    model_status = gr.Textbox(
                        label="模型状态",
                        value="检测中...",
                        interactive=False,
                        lines=2
                    )
                    
                    model_refresh_btn = gr.Button("🔄 刷新状态", size="sm")
                
                # Model selection (quantization)
                model_quant_selector = gr.Dropdown(
                    label="量化版本",
                    choices=["Q8_0", "Q6_K", "Q5_K_M", "Q4_K_M", "Q3_K_M", "Q2_K"],
                    value="Q4_K_M",
                    info="选择模型量化级别（越高质量越好，内存占用越大）"
                )
                
                model_download_btn = gr.Button("⬇️ 下载模型", variant="primary")
                
                # Test LLM matching
                gr.Markdown("---")
                gr.Markdown("### 测试字段匹配")
                
                with gr.Row():
                    test_sheet_cols = gr.Textbox(
                        label="测试 Sheet 列名（逗号分隔）",
                        placeholder="例如: PO Number, Container, Date",
                        lines=2
                    )
                
                test_llm_btn = gr.Button("🧪 测试 LLM 匹配", variant="secondary")
                
                test_result = gr.Code(
                    label="匹配结果",
                    language="json",
                    lines=10,
                    value=""
                )
                
                components["model_status"] = model_status
                components["model_refresh_btn"] = model_refresh_btn
                components["model_quant_selector"] = model_quant_selector
                components["model_download_btn"] = model_download_btn
                components["test_sheet_cols"] = test_sheet_cols
                components["test_llm_btn"] = test_llm_btn
                components["test_result"] = test_result
            
            # Sub-tab 3: Sections Configuration (for multi-area templates)
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
    
    # Event bindings
    
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
    model_refresh_btn.click(
        fn=handle_model_status_refresh,
        outputs=[model_status]
    )
    
    model_download_btn.click(
        fn=handle_model_download,
        inputs=[model_quant_selector],
        outputs=[model_status]
    )
    
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
        
        # Parse YAML to validate
        yaml_dict = yaml.safe_load(yaml_content)
        
        if not isinstance(yaml_dict, dict):
            return "❌ YAML 格式错误：根节点必须是字典"
        
        # Convert back to config
        paste_config = config_from_dict(yaml_dict)
        
        # Save to file
        config_path = Path(f"templates/{template.id}/{template.id}.paste.yaml")
        
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


def handle_model_status_refresh() -> str:
    """
    Refresh model status
    
    Returns:
        Status message
    """
    try:
        model_file = find_model_file()
        
        if model_file:
            filename, path = model_file
            size_gb = path.stat().st_size / (1024 ** 3)
            return f"✓ 模型已就绪\n文件: {filename}\n大小: {size_gb:.2f} GB"
        else:
            return "❌ 未找到模型文件\n请点击「下载模型」按钮"
    
    except Exception as e:
        logger.error(f"Model status check failed: {e}")
        return f"❌ 检查失败：{str(e)}"


def handle_model_download(
    quant_version: str
) -> str:
    """
    Download model
    
    Returns:
        Status message
    """
    try:
        gr.Info(f"开始下载 {quant_version} 量化模型，请稍候...")
        
        # Run download script
        import subprocess
        
        result = subprocess.run(
            ["python", "scripts/download_phi4_model.py"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return "✓ 模型下载成功！"
        else:
            return f"❌ 下载失败：\n{result.stderr}"
    
    except Exception as e:
        logger.error(f"Model download failed: {e}")
        return f"❌ 下载失败：{str(e)}"


def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: str
) -> str:
    """
    Test LLM field matching
    
    Returns:
        JSON result
    """
    if not template:
        return "// 请先选择模板"
    
    if not test_cols or not test_cols.strip():
        return "// 请输入测试列名"
    
    try:
        import json
        
        # Parse test columns
        cols = [c.strip() for c in test_cols.split(',') if c.strip()]
        
        if not cols:
            return "// 没有有效的列名"
        
        # Create test sheet row
        test_sheet_row = {col: f"测试值_{i+1}" for i, col in enumerate(cols)}
        
        # Load paste config
        paste_config = load_paste_parse_config(template.id)
        
        if not paste_config:
            return "// 模板配置未找到"
        
        # Create matcher
        matcher = create_field_matcher()
        
        if not matcher:
            return "// Phi-4 模型未就绪，请先下载模型"
        
        # Perform matching
        matched = matcher.match_sheet_fields_to_yaml(
            test_sheet_row,
            paste_config.to_dict()
        )
        
        # Format result
        result = {
            "输入列": cols,
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
        yaml_str = config_to_yaml(paste_config.to_dict())
        
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(yaml_str)
        
        logger.info(f"Saved sections config for template: {template.id}")
        
        return f"✓ 区域配置已保存\n输入区域: {input_area}\n方向: {move_direction}\n偏移: {offset}"
    
    except Exception as e:
        logger.error(f"Failed to save sections: {e}")
        return f"❌ 保存失败：{str(e)}"
