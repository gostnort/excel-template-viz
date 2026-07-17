from pathlib import Path
from nicegui import ui, app

# 加载全局 CSS
ui.add_css(Path(__file__).parent.joinpath('components', 'style.css').read_text(encoding='utf-8'), shared=True)

@ui.page('/')
def index_page():
    # 利用 app.storage.browser 的唯一 ID 作为会话主键，确保即便是默认 admin 也不会跨标签页串车
    browser_id = app.storage.browser.get('id')
    if not browser_id:
        import uuid
        app.storage.browser['id'] = str(uuid.uuid4())
    
    # 渲染 Main Shell
    from nicegui_ui.pages.main import render_shell
    render_shell()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host='0.0.0.0',
        port=8738,
        title='Excel Template Viz',
        storage_secret='local-offline-secret-key-2026',  # 必须项：开启浏览器 Cookie 存储
        reload=False,                                     # 单进程；E2E 测试前避免热重载子进程缓存旧模块
        native=False,                                    # 暂不使用 pywebview 避免多窗口渲染问题
        language='zh-CN',
        show=False,                                      # 防止每次热重载都弹新网页
    )
