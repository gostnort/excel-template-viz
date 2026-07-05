import subprocess
import sys

from nicegui import ui
from nicegui_ui.components.general import SessionRegistry
from nicegui_ui.wizard_panel import WizardUiController


def _default_wizard_profile() -> str:
    """Pick default --profile (cuda first when probe lists it)."""
    try:
        from llm_gemma4.runtime.hardware_probe import detect
        profiles = detect().available_profiles
        if profiles:
            return profiles[0]
    except Exception:
        pass
    return 'cuda'


def _launch_wizard_subprocess(
    template_id: str,
    *,
    resume: bool = False,
    llm: bool = True,
    profile: str = 'cuda',
) -> None:
    """Spawn CLI wizard in a new console (debug / fallback only)."""
    cmd = [sys.executable, '-m', 'llm_gemma4', 'wizard', '--template', template_id, '--headed']
    if resume:
        cmd.append('--resume')
    if llm:
        cmd.append('--llm')
        cmd.extend(['--profile', profile])
    try:
        if sys.platform == 'win32':
            subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(cmd, start_new_session=True)
        ui.notify(f'已在终端启动向导（调试模式）：{template_id}', type='info')
    except Exception as exc:
        ui.notify(f'启动向导失败: {exc}', type='negative')


def open_in_app_wizard(
    session,
    *,
    llm: bool = True,
    profile: str = 'cuda',
    resume: bool = False,
) -> None:
    """Open in-app wizard panel bound to ``WizardRunner`` (W5b)."""
    if not session.template_id:
        ui.notify('请先选择模板', type='warning')
        return
    template_id = session.template_id
    controller = WizardUiController(
        session,
        template_id=template_id,
        llm=llm,
        profile=profile,
        resume=resume,
        on_apply=lambda: trigger_toml_save(session),
        on_terminal=lambda: _launch_wizard_subprocess(
            template_id, resume=resume, llm=llm, profile=profile,
        ),
    )
    controller.open()


def open_wizard_dialog(session) -> None:
    """Open wizard start options, then in-app panel (primary path)."""
    if not session.template_id:
        ui.notify('请先选择模板', type='warning')
        return
    template_id = session.template_id
    with ui.dialog() as dialog, ui.card().classes('gap-2'):
        ui.label('开始 AI 配置向导').classes('text-lg font-bold')
        ui.label(
            '向导将在本页面内分步协助 TOML 配置：可见加载状态、模型解说、'
            '选项与「完成并继续」。需 NiceGUI 已运行。'
        ).classes('text-sm')
        llm_cb = ui.checkbox('启用 LLM 字段映射', value=True)
        profile_select = ui.select(
            options=['cuda', 'cpu', 'openvino'],
            value=_default_wizard_profile(),
            label='推理配置',
        ).classes('w-full').props('dense')
        resume_cb = ui.checkbox('从上次进度继续', value=False)
        with ui.row().classes('w-full gap-2'):
            ui.button(
                '开始向导',
                on_click=lambda: (
                    dialog.close(),
                    open_in_app_wizard(
                        session,
                        llm=llm_cb.value,
                        profile=profile_select.value,
                        resume=resume_cb.value,
                    ),
                ),
            ).props('color=primary')
            ui.button('取消', on_click=dialog.close).props('flat')
    dialog.open()


@ui.refreshable
def render_toml_tab():
    session = SessionRegistry.for_current()
    if not session.cfg:
        ui.label('请先从左侧选择模板').classes('text-gray-500 italic p-4')
        return

    with ui.element('div'):
        # 校验操作区域
        with ui.element('div').classes('section'):
            ui.label('校验与应用').classes('section-title')
            with ui.element('div').classes('section-body'):
                with ui.element('div').classes('row'):
                    ui.label('校验并应用配置').classes('btn primary').on('click', lambda: trigger_toml_save(session))
                    
                    if session.verify_report:
                        if session.verify_report.get('ok'):
                            ui.label('当前配置已校验通过').classes('ctrl wide status-ok')
                        else:
                            with ui.element('div').classes('ctrl wide status-warn').style('flex-direction: column; align-items: flex-start; height: auto;'):
                                ui.label('配置校验失败').classes('font-bold text-red')
                                if session.verify_report.get('missing_labels'):
                                    ui.label(f"缺失标签: {', '.join(session.verify_report['missing_labels'])}").classes('text-sm')
                                if session.verify_report.get('duplicate_labels'):
                                    ui.label(f"重复标签: {', '.join(session.verify_report['duplicate_labels'])}").classes('text-sm')
                                if session.verify_report.get('out_of_area_labels'):
                                    ui.label(f"越界标签: {', '.join(session.verify_report['out_of_area_labels'])}").classes('text-sm')
                                if session.verify_report.get('errors'):
                                    for err in session.verify_report['errors']:
                                        ui.label(f"- {err}").classes('text-sm text-red')

        # AI 配置向导（Gemma4 E4B）
        with ui.element('div').classes('section'):
            ui.label('AI 配置向导').classes('section-title')
            with ui.element('div').classes('section-body'):
                with ui.element('div').classes('row'):
                    ui.button('AI 配置向导', on_click=lambda: open_wizard_dialog(session)).props('color=primary')
                    ui.label('首次配置或校验失败时，在页面内启动分步向导').classes('text-sm text-gray-600')

        # 高级（TOML 全文）
        with ui.element('div').classes('section'):
            ui.label('高级（TOML 全文）').classes('section-title')
            with ui.element('div').classes('section-body'):
                from app.core_toml import _core_toml_path
                toml_path = _core_toml_path(session.template_id) if session.template_id else None
                try:
                    with open(toml_path, 'r', encoding='utf-8') as f:
                        raw_toml = f.read()
                except Exception:
                    raw_toml = ""
                    
                toml_editor = ui.textarea(value=raw_toml).classes('w-full font-mono text-sm').props('rows="25" outlined').style('border-radius: 0; border: 1px solid #000; padding: 4px;')
                
                def save_raw_toml():
                    new_toml = toml_editor.value
                    if not toml_path: return
                    try:
                        with open(toml_path, 'w', encoding='utf-8') as f:
                            f.write(new_toml)
                        trigger_toml_save(session)
                    except Exception as e:
                        ui.notify(f"保存文件失败: {str(e)}", type='negative')
                        
                with ui.element('div').classes('row').style('margin-top:8px'):
                    ui.label('保存').classes('btn').on('click', save_raw_toml)
                    ui.label('重置').classes('btn').on('click', render_toml_tab.refresh)

def trigger_toml_save(session):
    try:
        from app.core_toml import load_toml, verify_toml
        session.cfg = load_toml(session.template_id)
        session.verify_report = verify_toml(session.template_path, session.cfg)
        
        if session.verify_report.get('ok'):
            from app.core_store import SecureSQLite, default_db_path, UiProvider
            from app.core_transform import Template2DB, ExcelWriter
            
            session.located = session.verify_report.get('located', {})
            db_path = default_db_path(session.template_id)
            session.db_path = db_path
            
            if session.db:
                session.db.close()
                
            session.db = SecureSQLite(db_path)
            session.ui_provider = UiProvider(session.cfg, session.db)
            session.t2db = Template2DB(session.cfg)
            session.writer = ExcelWriter(session.cfg, session.located)
            
            session.input_capacity = session.writer.max_instance_count(session.template_path)
            session.template_defaults = session.writer.read_values(session.template_path, 0) if session.template_path else {}
            session.current_instance_index = 0
            session.draft.clear()
            session.draft.update(session.template_defaults)
            session.session_rows.clear()
            session.selected_session_index = None
            session.selected_session_indices.clear()
            
            ui.notify('配置保存并加载成功', type='positive')
        else:
            session.ui_provider = None
            session.writer = None
            session.t2db = None
            if session.db: 
                session.db.close()
            session.db = None
            ui.notify('配置保存成功，但校验失败，工作区已锁定', type='warning')
            
        # Refresh tabs
        render_toml_tab.refresh()
        
        from nicegui_ui.pages.tab_input import render_input_tab
        render_input_tab.refresh()
        
    except Exception as e:
        ui.notify(f"应用失败: {str(e)}", type='negative')
