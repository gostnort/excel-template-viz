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
    from nicegui_ui.ssl_manager import ensure_tls_certs
    cert_dir = Path(__file__).parent.parent / "certs"
    cert_file, key_file = ensure_tls_certs(cert_dir)
    run_kwargs = {
        'host': '0.0.0.0',
        'port': 8738,
        'title': 'Excel Template Viz',
        'storage_secret': 'local-offline-secret-key-2026',
        'reload': False,
        'native': False,
        'language': 'zh-CN',
        'show': False,
    }
    if cert_file and key_file:
        run_kwargs['ssl_certfile'] = cert_file
        run_kwargs['ssl_keyfile'] = key_file
    ui.run(**run_kwargs)
