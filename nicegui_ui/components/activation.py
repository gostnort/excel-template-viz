from nicegui import ui
from nicegui_ui.components.session import SessionRegistry

from app.services.core_toml import load_toml, verify_toml, ensure_exists
from app.services.core_store import SecureSQLite, default_db_path, UiProvider
from app.services.core_transform import Template2DB, ExcelWriter

def activate_template(template_id: str, template_path: str):
    """
    加载、校验并激活指定的模板。
    只向当前操作者的 SessionState 中写入核心对象。
    """
    state = SessionRegistry.for_current()
    try:
        ensure_exists(template_id, template_path)
        state.template_id = template_id
        from pathlib import Path
        state.template_path = Path(template_path)
    except Exception as e:
        ui.notify(f"模板文件不存在: {str(e)}", type='negative')
        return False
        
    try:
        cfg = load_toml(template_id)
        state.cfg = cfg
    except Exception as e:
        ui.notify(f"TOML 读取失败: {str(e)}", type='negative')
        return False
        
    # Verify
    report = verify_toml(template_path, cfg)
    state.verify_report = report
    
    if not report.get('ok', False):
        ui.notify(f"模板 {template_id} 校验失败，请检查 [输入配置] 面板！", type='negative', position='top')
        # 防止污染正常工作区，清空引擎
        state.ui_provider = None
        state.writer = None
        state.t2db = None
        if state.db:
            state.db.close()
        state.db = None
        return False
        
    # 成功通过校验
    ui.notify(f"模板 {template_id} 已就绪", type='positive')
    state.located = report.get('located', {})
    
    # 构造 DB
    db_path = default_db_path(template_id)
    state.db_path = db_path
    
    if state.db:
        state.db.close()
        
    state.db = SecureSQLite(db_path)
    state.ui_provider = UiProvider(cfg, state.db)
    state.t2db = Template2DB(cfg)
    state.writer = ExcelWriter(cfg, state.located)
    
    # 重置输入视图
    state.input_capacity = state.writer.max_instance_count(template_path)
    state.template_defaults = state.writer.read_values(template_path, 0) if template_path else {}
    state.current_instance_index = 0
    state.draft.clear()
    state.draft.update(state.template_defaults)
    state.session_rows.clear()
    
    return True
