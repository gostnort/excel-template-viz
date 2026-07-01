from nicegui import ui
from nicegui_ui.components.session import SessionRegistry

@ui.refreshable
def render_google_tab():
    session = SessionRegistry.for_current()
    if not session.ui_provider:
        ui.label('请先从左侧选择有效的模板配置').classes('text-gray-500 italic p-4')
        return

    with ui.element('div'):
        # OAuth Section
        with ui.element('div').classes('section'):
            ui.label('OAuth 授权').classes('section-title')
            with ui.element('div').classes('section-body'):
                with ui.element('div').classes('row'):
                    ui.label('客户端 JSON').classes('field-label')
                    ui.label('选择 oauth_client.json …').classes('file-pick')
                    ui.label('上传').classes('btn')
                with ui.element('div').classes('row'):
                    ui.label('授权状态').classes('field-label')
                    ui.label('等待凭证').classes('ctrl medium status-warn')
                    
                    def handle_auth():
                        ui.notify('请在控制台或系统弹窗完成 OAuth 登录...', type='info')
                    ui.label('授权 Google 账号').classes('btn').on('click', handle_auth)
                ui.label('首次授权打开浏览器；之后复用 token 文件。未授权时本 Tab 表格不可用。').classes('hint')

        # Connection Status Section
        with ui.element('div').classes('section'):
            ui.label('连接状态（模板激活时自动连接）').classes('section-title')
            with ui.element('div').classes('section-body'):
                with ui.element('div').classes('row'):
                    ui.label('Google 连接').classes('field-label')
                    ui.label('未连接').classes('ctrl medium status-off')
                with ui.element('div').classes('row'):
                    ui.label('主 ID 表').classes('field-label')
                    ui.label('等待连接').classes('ctrl wide')
                ui.label('每次切换模板：先 disconnect 旧连接，再按新 TOML [[sources]] 自动 connect。').classes('hint')

        # Main ID Sheet Table
        with ui.element('div').classes('section'):
            ui.label('主 ID 工作表（多选 + 预览，同一张 HTML5 表）').classes('section-title')
            with ui.element('div').classes('section-body'):
                columns = [{'name': 'id', 'label': '主键 ID', 'field': 'id'}]
                ui.table(columns=columns, rows=[], selection='multiple').classes('w-full').style('border-radius: 0; box-shadow: none; border: 1px solid #000;')
                
                with ui.element('div').classes('row').style('margin-top:8px'):
                    ui.label('全选').classes('btn')
                    ui.label('取消全选').classes('btn')
                    ui.label('导入选中行').classes('btn primary').on('click', lambda: ui.notify('开发中：执行数据注入', type='warning'))
                ui.label('表格数据 = fetch_fields 的 sheet_rows 浅拷贝（主 ID 表原始列）。').classes('hint')
