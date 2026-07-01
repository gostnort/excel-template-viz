from nicegui import ui, app

def render_shell():
    # 消除多余内边距
    ui.query('body').classes('p-0 m-0 overflow-hidden')
    
    # 初始化侧边栏状态
    sidebar_width = app.storage.user.get('sidebar_width', 240)
    is_collapsed = app.storage.user.get('sidebar_collapsed', False)
    
    init_limits = '[0, 400]' if is_collapsed else '[150, 400]'
    init_value = 0 if is_collapsed else sidebar_width
    
    with ui.splitter(value=init_value).props(f'unit=px limits="{init_limits}"').classes('w-full h-screen') as splitter:
        
        def toggle_sidebar(e=None):
            if splitter.value > 0:
                # 折叠
                app.storage.user['sidebar_width'] = splitter.value
                app.storage.user['sidebar_collapsed'] = True
                splitter.props('limits=[0, 400]')
                splitter.value = 0
            else:
                # 展开
                app.storage.user['sidebar_collapsed'] = False
                splitter.props('limits=[150, 400]')
                splitter.value = app.storage.user.get('sidebar_width', 240)
                
        def on_splitter_change(e):
            val = e.value
            if val > 0:
                if app.storage.user.get('sidebar_collapsed'):
                    app.storage.user['sidebar_collapsed'] = False
                    splitter.props('limits=[150, 400]')
                if val >= 150:
                    app.storage.user['sidebar_width'] = val
                    
        splitter.on('update:model-value', on_splitter_change)
        
        with splitter.separator:
            # 扩大双击热区，通过透明背景覆盖在原生分割线上
            ui.element('div').classes('w-4 h-full bg-transparent cursor-col-resize').style('margin-left: -6px; z-index: 100;').on('dblclick', toggle_sidebar)

        # 左侧边栏 (Sidebar)
        with splitter.before:
            with ui.column().classes('w-full h-full p-2 border-r overflow-x-hidden overflow-y-auto').style('will-change: width'):
                ui.label('模板: 未选择').classes('text-lg font-bold mb-2')
                ui.separator()
                
                # 模板列表
                from app.services.core_registry import SortTemplates
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
                            print(f"Clicked on {tid}", flush=True)
                            from nicegui_ui.components.activation import activate_template
                            path = registry.TemplateIDs.get(tid)
                            print(f"Path for {tid}: {path}", flush=True)
                            if path:
                                res = activate_template(tid, path)
                                print(f"Activate result: {res}", flush=True)
                                if res:
                                    from nicegui_ui.pages.tab_input import render_input_tab
                                    render_input_tab.refresh()
                                    
                        ui.item(display_name).classes('cursor-pointer hover:bg-gray-100').props('clickable v-ripple').on('click', lambda e, tid=t_id: on_click(e, tid))

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
