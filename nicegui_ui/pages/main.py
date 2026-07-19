from nicegui import ui, app

from nicegui_ui.components.general import Auth


def _set_sidebar_pref(key: str, value) -> None:
    app.storage.user[Auth.pref_key(key)] = value
    app.storage.user[key] = value


def render_shell():
    ui.query("body").classes("p-0 m-0 overflow-hidden")

    user_agent = ui.context.client.request.headers.get("user-agent", "").lower()
    is_mobile = (
        "mobi" in user_agent or "android" in user_agent or "iphone" in user_agent
    )

    is_collapsed = app.storage.user.get(
        Auth.pref_key("sidebar_collapsed"), True if is_mobile else False
    )

    with ui.element("div").classes("shell w-full h-full").props('id="app-shell"'):
        if is_collapsed:
            ui.query(".shell").classes("is-sidebar-collapsed")

        with ui.element("div").classes("sidebar-header").props('id="sidebar-header"'):

            @ui.refreshable
            def render_template_name():
                from nicegui_ui.components.general import SessionRegistry

                session = SessionRegistry.for_current()
                name = session.template_id or "未选择"
                ui.label(name).classes("selected-template-name").props(
                    f'title="{name}"'
                )

            render_template_name()

            fold_btn = (
                ui.element("button")
                .classes("sidebar-fold-btn")
                .props('title="折叠/展开左侧模板栏"')
            )
            with fold_btn:
                ui.html("""
                    <svg class="fold-chevron" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M14 5 L8 12 L14 19" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                      <path d="M19 5 L13 12 L19 19" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                """)

            def on_fold_click():
                nonlocal is_collapsed
                is_collapsed = not is_collapsed
                _set_sidebar_pref("sidebar_collapsed", is_collapsed)
                if is_collapsed:
                    ui.query(".shell").classes("is-sidebar-collapsed")
                    fold_btn.props('aria-expanded="false"')
                else:
                    ui.query(".shell").classes(remove="is-sidebar-collapsed")
                    fold_btn.props('aria-expanded="true"')

            fold_btn.on("click", on_fold_click)
            fold_btn.on("dblclick", on_fold_click)

            if is_collapsed:
                fold_btn.props('aria-expanded="false"')
            else:
                fold_btn.props('aria-expanded="true"')

        active_tab = app.storage.user.get("active_tab", "输入")

        def set_tab(tab_name):
            nonlocal active_tab
            active_tab = tab_name
            app.storage.user["active_tab"] = tab_name
            render_tabs.refresh()
            render_panels.refresh()

        with ui.element("nav").classes("tabs"):

            @ui.refreshable
            def render_tabs():
                for t in ["输入", "输入配置", "存储配置", "Google 连接"]:
                    cls = "tab active" if t == active_tab else "tab"
                    ui.label(t).classes(cls).on(
                        "click", lambda e, name=t: set_tab(name)
                    )

            render_tabs()

        with ui.element("aside").classes("sidebar").props('id="sidebar"'):

            @ui.refreshable
            def render_sidebar_list():
                from app.core_registry import SortTemplates
                from nicegui_ui.components.general import SessionRegistry

                registry = SortTemplates()
                session = SessionRegistry.for_current()
                display_to_id = {
                    v: k for k, v in registry.template_display_names.items()
                }
                for display_name in registry.sort_templates_timeline:
                    t_id = display_to_id.get(display_name)
                    if not t_id:
                        continue
                    is_active = session.template_id == t_id
                    cls = "template-item active" if is_active else "template-item muted"

                    def on_click(e, tid=t_id):
                        from nicegui_ui.components.for_main import ForMain

                        path = registry.TemplateIDs.get(tid)
                        if path:
                            ForMain.load_template(tid, path)
                            render_template_name.refresh()
                            render_sidebar_list.refresh()
                            from nicegui_ui.pages.tab_input import render_input_tab
                            from nicegui_ui.pages.tab_toml import render_toml_tab
                            from nicegui_ui.pages.tab_db import render_db_tab
                            from nicegui_ui.pages.tab_google import render_google_tab

                            render_input_tab.refresh()
                            render_toml_tab.refresh()
                            render_db_tab.refresh()
                            render_google_tab.refresh()

                    ui.label(display_name).classes(cls).on(
                        "click", lambda e, tid=t_id: on_click(e, tid)
                    )

            render_sidebar_list()

        with ui.element("main").classes("main w-full h-full overflow-y-auto"):

            @ui.refreshable
            def render_panels():
                with ui.element("div").classes("tab-body"):
                    if active_tab == "输入":
                        from nicegui_ui.pages.tab_input import render_input_tab

                        render_input_tab()
                    elif active_tab == "输入配置":
                        from nicegui_ui.pages.tab_toml import render_toml_tab

                        render_toml_tab()
                    elif active_tab == "存储配置":
                        from nicegui_ui.pages.tab_db import render_db_tab

                        render_db_tab()
                    elif active_tab == "Google 连接":
                        from nicegui_ui.pages.tab_google import render_google_tab

                        render_google_tab()

            render_panels()
