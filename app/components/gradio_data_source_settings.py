"""
Gradio Data Source Settings Component

Handles OAuth flow, Google Sheet connection, and worksheet configuration.
"""
import gradio as gr
import logging
from typing import Any

from app.services.registry import TemplateConfig

logger = logging.getLogger(__name__)


def build_datasource_tab(
    current_template: gr.State,
    credentials_state: gr.State
) -> dict:
    """
    Build the data source configuration tab
    
    Returns:
        Dict of component references
    """
    components = {}
    
    with gr.Column():
        gr.Markdown("## 数据源配置")
        gr.Markdown("连接到 Google Sheet 以获取数据")
        
        # OAuth section
        with gr.Group():
            gr.Markdown("### 1. 授权 Google 账号")
            
            oauth_status = gr.Textbox(
                label="授权状态",
                value="未授权",
                interactive=False
            )
            
            with gr.Row():
                oauth_btn = gr.Button("🔐 开始授权", variant="primary")
                revoke_btn = gr.Button("🗑️ 撤销授权", variant="secondary")
        
        components["oauth_status"] = oauth_status
        components["oauth_btn"] = oauth_btn
        components["revoke_btn"] = revoke_btn
        
        # Sheet connection section
        with gr.Group():
            gr.Markdown("### 2. 配置 Google Sheet")
            
            sheet_url = gr.Textbox(
                label="Sheet URL",
                placeholder="https://docs.google.com/spreadsheets/d/...",
                interactive=True
            )
            
            connect_btn = gr.Button("连接", variant="primary")
            
            connection_status = gr.Textbox(
                label="连接状态",
                value="未连接",
                interactive=False
            )
        
        components["sheet_url"] = sheet_url
        components["connect_btn"] = connect_btn
        components["connection_status"] = connection_status
        
        # Worksheet selector
        with gr.Group(visible=False) as worksheet_group:
            gr.Markdown("### 3. 选择工作表和 ID 列")
            
            worksheet_dropdown = gr.Dropdown(
                label="工作表",
                choices=[],
                value=None,
                interactive=True
            )
            
            id_column_dropdown = gr.Dropdown(
                label="ID 列（用于查询）",
                choices=[],
                value=None,
                interactive=True
            )
            
            save_config_btn = gr.Button("💾 保存配置", variant="primary")
        
        components["worksheet_group"] = worksheet_group
        components["worksheet_dropdown"] = worksheet_dropdown
        components["id_column_dropdown"] = id_column_dropdown
        components["save_config_btn"] = save_config_btn
        
        # Test section
        with gr.Group(visible=False) as test_group:
            gr.Markdown("### 测试连接")
            
            test_id = gr.Textbox(
                label="输入 ID 测试查询",
                placeholder="输入 ID...",
                interactive=True
            )
            
            test_btn = gr.Button("测试查询")
            
            test_result = gr.JSON(
                label="查询结果",
                visible=False
            )
        
        components["test_group"] = test_group
        components["test_id"] = test_id
        components["test_btn"] = test_btn
        components["test_result"] = test_result
    
    # Event bindings
    
    # OAuth authorization
    oauth_btn.click(
        fn=handle_oauth_start,
        inputs=[credentials_state],
        outputs=[oauth_status, credentials_state]
    )
    
    # Revoke OAuth
    revoke_btn.click(
        fn=handle_oauth_revoke,
        inputs=[credentials_state],
        outputs=[oauth_status, credentials_state, connection_status, worksheet_group]
    )
    
    # Connect to sheet
    connect_btn.click(
        fn=handle_sheet_connect,
        inputs=[sheet_url, credentials_state],
        outputs=[connection_status, worksheet_group, worksheet_dropdown]
    )
    
    # Worksheet selected - load columns
    worksheet_dropdown.change(
        fn=handle_worksheet_change,
        inputs=[worksheet_dropdown, sheet_url, credentials_state],
        outputs=[id_column_dropdown, test_group]
    )
    
    # Save configuration
    save_config_btn.click(
        fn=handle_save_config,
        inputs=[current_template, sheet_url, worksheet_dropdown, id_column_dropdown],
        outputs=[]
    )
    
    # Test query
    test_btn.click(
        fn=handle_test_query,
        inputs=[test_id, sheet_url, worksheet_dropdown, id_column_dropdown, credentials_state],
        outputs=[test_result]
    )
    
    return components


def handle_oauth_start(credentials: Any) -> tuple:
    """Start OAuth authorization flow"""
    try:
        from app.services.google_sheets import authenticate_google_sheets_desktop
        
        gr.Info("正在打开授权页面...")
        
        # Start OAuth flow
        creds = authenticate_google_sheets_desktop()
        
        if creds and creds.valid:
            gr.Info("✅ 授权成功！")
            return "✅ 已授权", creds
        else:
            gr.Warning("授权失败或已取消")
            return "❌ 授权失败", None
            
    except Exception as e:
        logger.error(f"OAuth failed: {e}")
        gr.Warning(f"授权失败：{str(e)}")
        return f"❌ 授权失败：{str(e)}", None


def handle_oauth_revoke(credentials: Any) -> tuple:
    """Revoke OAuth credentials"""
    try:
        if credentials:
            # TODO: Implement credential revocation
            gr.Info("已撤销授权")
        
        return "未授权", None, "未连接", gr.update(visible=False)
        
    except Exception as e:
        logger.error(f"Revoke failed: {e}")
        gr.Warning(f"撤销失败：{str(e)}")
        return "未授权", None, "未连接", gr.update(visible=False)


def handle_sheet_connect(
    sheet_url: str | None,
    credentials: Any
) -> tuple:
    """Connect to Google Sheet"""
    if not sheet_url:
        gr.Warning("请输入 Sheet URL")
        return "未连接", gr.update(visible=False), gr.update()
    
    if not credentials:
        gr.Warning("请先授权 Google 账号")
        return "未连接", gr.update(visible=False), gr.update()
    
    try:
        from app.services.google_sheets import list_worksheets
        
        # List worksheets
        worksheets = list_worksheets(credentials, sheet_url)
        
        if not worksheets:
            gr.Warning("Sheet 中没有工作表")
            return "❌ 连接失败", gr.update(visible=False), gr.update()
        
        gr.Info(f"✅ 连接成功，找到 {len(worksheets)} 个工作表")
        
        return (
            f"✅ 已连接 ({len(worksheets)} 个工作表)",
            gr.update(visible=True),
            gr.update(choices=worksheets, value=worksheets[0] if worksheets else None)
        )
        
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        gr.Warning(f"连接失败：{str(e)}")
        return f"❌ 连接失败：{str(e)}", gr.update(visible=False), gr.update()


def handle_worksheet_change(
    worksheet_name: str | None,
    sheet_url: str | None,
    credentials: Any
) -> tuple:
    """Handle worksheet selection change"""
    if not worksheet_name or not sheet_url or not credentials:
        return gr.update(), gr.update(visible=False)
    
    try:
        from app.services.google_sheets import fetch_sheet_preview
        
        # Fetch preview to get columns
        df, _ = fetch_sheet_preview(credentials, sheet_url, worksheet_name)
        
        if df.height == 0:
            gr.Warning("工作表为空")
            return gr.update(), gr.update(visible=False)
        
        columns = df.columns
        gr.Info(f"工作表有 {len(columns)} 列")
        
        return (
            gr.update(choices=columns, value=columns[0] if columns else None),
            gr.update(visible=True)
        )
        
    except Exception as e:
        logger.error(f"Worksheet loading failed: {e}")
        gr.Warning(f"加载工作表失败：{str(e)}")
        return gr.update(), gr.update(visible=False)


def handle_save_config(
    template: TemplateConfig | None,
    sheet_url: str | None,
    worksheet_name: str | None,
    id_column: str | None
) -> None:
    """Save data source configuration"""
    if not template:
        gr.Warning("请先选择模板")
        return
    
    if not all([sheet_url, worksheet_name, id_column]):
        gr.Warning("请填写完整配置")
        return
    
    try:
        from app.services.data_source import save_template_data_source, DataSourceConfig
        
        config = DataSourceConfig(
            template_id=template.id,
            sheet_url=sheet_url,
            worksheet_name=worksheet_name,
            id_column=id_column
        )
        
        save_template_data_source(config)
        
        gr.Info("✅ 配置已保存")
        
    except Exception as e:
        logger.error(f"Save config failed: {e}")
        gr.Warning(f"保存配置失败：{str(e)}")


def handle_test_query(
    test_id: str | None,
    sheet_url: str | None,
    worksheet_name: str | None,
    id_column: str | None,
    credentials: Any
) -> gr.JSON:
    """Test ID query"""
    if not test_id:
        gr.Warning("请输入测试 ID")
        return gr.update(visible=False)
    
    if not all([sheet_url, worksheet_name, id_column, credentials]):
        gr.Warning("请先完成配置")
        return gr.update(visible=False)
    
    try:
        from app.services.google_sheets import fetch_row_by_id
        
        result = fetch_row_by_id(
            credentials,
            sheet_url,
            worksheet_name,
            id_column,
            test_id
        )
        
        if result:
            gr.Info("✅ 查询成功")
            return gr.update(value=result, visible=True)
        else:
            gr.Warning(f"未找到 ID: {test_id}")
            return gr.update(visible=False)
            
    except Exception as e:
        logger.error(f"Test query failed: {e}")
        gr.Warning(f"查询失败：{str(e)}")
        return gr.update(visible=False)
