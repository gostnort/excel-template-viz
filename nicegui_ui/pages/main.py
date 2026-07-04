from nicegui import ui, app

from nicegui_ui.components.general import Auth


def _sidebar_pref(key: str, default):
    return app.storage.user.get(Auth.pref_key(key), app.storage.user.get(key, default))


def _set_sidebar_pref(key: str, value) -> None:
    app.storage.user[Auth.pref_key(key)] = value
    app.storage.user[key] = value


def render_shell():
    # 消除多余内边距
    ui.query('body').classes('p-0 m-0 overflow-hidden')
    # 初始化侧边栏状态
    sidebar_width = _sidebar_pref('sidebar_width', 240)
    is_collapsed = _sidebar_pref('sidebar_collapsed', False)
    init_limits = (0, 400) if is_collapsed else (150, 400)
    init_value = 0 if is_collapsed else sidebar_width
    with ui.splitter(value=init_value, limits=init_limits).props('unit=px').classes('shell-splitter w-full h-screen') as splitter:
        
        def toggle_sidebar(e=None):
            if splitter.value > 0:
                # 折叠
                _set_sidebar_pref('sidebar_width', splitter.value)
                _set_sidebar_pref('sidebar_collapsed', True)
                splitter.props['limits'] = (0, 400)
                splitter.value = 0
            else:
                # 展开
                _set_sidebar_pref('sidebar_collapsed', False)
                splitter.props['limits'] = (150, 400)
                splitter.value = _sidebar_pref('sidebar_width', 240)
        def on_splitter_change(e):
            val = splitter.value
            if val is None or val <= 0:
                return
            if val > 0:
                if _sidebar_pref('sidebar_collapsed', False):
                    _set_sidebar_pref('sidebar_collapsed', False)
                    splitter.props['limits'] = (150, 400)
                if val >= 150:
                    _set_sidebar_pref('sidebar_width', val)
        splitter.on('update:model-value', on_splitter_change)
        splitter.on('dblclick', toggle_sidebar)
        def bind_separator_dblclick() -> None:
            sid = splitter.id
            ui.run_javascript(f'''
                (() => {{
                    const cmp = getElement({sid});
                    if (!cmp || cmp.__sepDblBound) return;
                    const root = cmp.$el;
                    const sep = root?.querySelector('.q-splitter__separator');
                    if (!sep) return;
                    cmp.__sepDblBound = true;
                    sep.addEventListener('dblclick', () => cmp.$emit('dblclick', {{}}));
                }})();
            ''')
        ui.timer(0.15, bind_separator_dblclick, once=True)
        # 左侧边栏 (Sidebar)
        with splitter.before:
            with ui.column().classes('sidebar w-full h-full border-r overflow-hidden').style('will-change: width'):
                @ui.refreshable
                def render_template_header():
                    from nicegui_ui.components.general import SessionRegistry
                    session = SessionRegistry.for_current()
                    with ui.element('div').classes('sidebar-header w-full flex-shrink-0'):
                        if session.template_id:
                            ui.label(f'已选择 {session.template_id}')
                        else:
                            ui.label('模板: 未选择')
                render_template_header()
                with ui.element('div').classes('sidebar-body w-full flex-1 overflow-y-auto overflow-x-hidden'):
                    # 模板列表
                    from app.core_registry import SortTemplates
                    registry = SortTemplates()
                    with ui.list().classes('w-full'):
                        # sort_templates_timeline 存储的是 display_name
                        # TemplateIDs 的 key 是 id，我们需要构建反向映射
                        display_to_id = {v: k for k, v in registry.template_display_names.items()}
                        for display_name in registry.sort_templates_timeline:
                            t_id = display_to_id.get(display_name)
                            if not t_id:
                                continue
                            def on_click(e, tid=t_id):
                                from nicegui_ui.components.for_main import ForMain
                                path = registry.TemplateIDs.get(tid)
                                if path:
                                    ForMain.load_template(tid, path)
                                    render_template_header.refresh()
                                    from nicegui_ui.pages.tab_input import render_input_tab
                                    from nicegui_ui.pages.tab_toml import render_toml_tab
                                    from nicegui_ui.pages.tab_db import render_db_tab
                                    from nicegui_ui.pages.tab_google import render_google_tab
                                    render_input_tab.refresh()
                                    render_toml_tab.refresh()
                                    render_db_tab.refresh()
                                    render_google_tab.refresh()
                            ui.item(display_name).classes('template-item cursor-pointer').props('clickable v-ripple').on('click', lambda e, tid=t_id: on_click(e, tid))

        # 右侧主工作区 (Main Tabs)
        with splitter.after:
            with ui.element('main').classes('main w-full h-full p-0 m-0'):
                # State for custom tabs
                active_tab = app.storage.user.get('active_tab', '输入')
                
                def set_tab(tab_name):
                    nonlocal active_tab
                    active_tab = tab_name
                    app.storage.user['active_tab'] = tab_name
                    render_tabs.refresh()
                    render_panels.refresh()

                @ui.refreshable
                def render_tabs():
                    with ui.element('nav').classes('tabs'):
                        for t in ['输入', '输入配置', '存储配置', 'Google 连接']:
                            cls = 'tab active' if t == active_tab else 'tab'
                            ui.label(t).classes(cls).on('click', lambda e, name=t: set_tab(name))
                            
                render_tabs()

                @ui.refreshable
                def render_panels():
                    with ui.element('div').classes('tab-body'):
                        if active_tab == '输入':
                            from nicegui_ui.pages.tab_input import render_input_tab
                            render_input_tab()
                        elif active_tab == '输入配置':
                            from nicegui_ui.pages.tab_toml import render_toml_tab
                            render_toml_tab()
                        elif active_tab == '存储配置':
                            from nicegui_ui.pages.tab_db import render_db_tab
                            render_db_tab()
                        elif active_tab == 'Google 连接':
                            from nicegui_ui.pages.tab_google import render_google_tab
                            render_google_tab()
                            
                render_panels()
