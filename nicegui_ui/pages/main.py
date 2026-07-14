from nicegui import ui, app

from nicegui_ui.components.general import Auth

SIDEBAR_DEFAULT = 250
SIDEBAR_STORE_MIN = 20
SIDEBAR_STORE_MAX = 400
SIDEBAR_QUASAR_LIMITS = (0, 1000)

def _clamp_store(raw: int) -> int:
    return max(SIDEBAR_STORE_MIN, min(int(raw), SIDEBAR_STORE_MAX))


def _set_sidebar_pref(key: str, value) -> None:
    app.storage.user[Auth.pref_key(key)] = value
    app.storage.user[key] = value


def render_shell():
    ui.query("body").classes("p-0 m-0 overflow-hidden")

    user_agent = ui.context.client.request.headers.get("user-agent", "").lower()
    is_mobile = (
        "mobi" in user_agent or "android" in user_agent or "iphone" in user_agent
    )

    stored_w = app.storage.user.get(Auth.pref_key("sidebar_width"))
    is_collapsed = app.storage.user.get(
        Auth.pref_key("sidebar_collapsed"), True if is_mobile else False
    )

    with ui.element("div").classes("shell w-full h-full").props('id="app-shell"'):
        if is_collapsed:
            ui.query(".shell").classes("is-sidebar-collapsed")

        # Top Bar
        with ui.element("header").classes("shell-top"):
            with ui.element("div").classes("sidebar-header"):

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

                programmatic_resize_count = 0
                is_loading = True

                def clear_loading():
                    nonlocal is_loading
                    is_loading = False

                ui.timer(0.05, clear_loading, once=True)

                def on_fold_click():
                    nonlocal is_collapsed, programmatic_resize_count
                    # 1) 收起前：用当前显示宽度刷新存储（防止 resize 未触发）
                    if not is_collapsed:
                        _set_sidebar_pref("sidebar_width", _clamp_store(splitter.value))
                        
                    # 2) 若已有存储，归一化写回（纠正历史脏数据）
                    w_str = app.storage.user.get(Auth.pref_key("sidebar_width"))
                    w_store = _clamp_store(w_str) if w_str is not None else None
                    if w_str is not None and int(w_str) != w_store:
                        _set_sidebar_pref("sidebar_width", w_store)
                        
                    is_collapsed = not is_collapsed
                    _set_sidebar_pref("sidebar_collapsed", is_collapsed)
                    
                    if is_collapsed:
                        ui.query(".shell").classes("is-sidebar-collapsed")
                        fold_btn.props('aria-expanded="false"')
                    else:
                        ui.query(".shell").classes(remove="is-sidebar-collapsed")
                        fold_btn.props('aria-expanded="true"')
                        
                        restore = w_store if w_store is not None else SIDEBAR_DEFAULT
                        if splitter.value != restore:
                            programmatic_resize_count += 1
                            splitter.value = restore

                fold_btn.on("click", on_fold_click)
                fold_btn.on("dblclick", on_fold_click)

                # initial state
                if is_collapsed:
                    fold_btn.props('aria-expanded="false"')
                else:
                    fold_btn.props('aria-expanded="true"')

            with ui.element("nav").classes("tabs"):
                active_tab = app.storage.user.get("active_tab", "输入")

                def set_tab(tab_name):
                    nonlocal active_tab
                    active_tab = tab_name
                    app.storage.user["active_tab"] = tab_name
                    render_tabs.refresh()
                    render_panels.refresh()

                @ui.refreshable
                def render_tabs():
                    for t in ["输入", "输入配置", "存储配置", "Google 连接"]:
                        cls = "tab active" if t == active_tab else "tab"
                        ui.label(t).classes(cls).on(
                            "click", lambda e, name=t: set_tab(name)
                        )

                render_tabs()

        # Body
        with ui.element("div").classes("shell-body"):
            stored = app.storage.user.get(Auth.pref_key("sidebar_width"))
            if stored is not None:
                initial = _clamp_store(stored)
            else:
                initial = SIDEBAR_DEFAULT
                
            kwargs = {"limits": SIDEBAR_QUASAR_LIMITS}
            if initial is not None:
                kwargs["value"] = initial

            with (
                ui.splitter(**kwargs)
                .props("unit=px")
                .classes("shell-splitter w-full h-full") as splitter
            ):

                def on_splitter_resize(e):
                    nonlocal is_collapsed, programmatic_resize_count
                    if is_loading:
                        return
                    if programmatic_resize_count > 0:
                        programmatic_resize_count -= 1
                        return
                    try:
                        raw = int(float(e.args[0]))
                    except (TypeError, ValueError, IndexError):
                        return
                        
                    if is_collapsed:
                        is_collapsed = False
                        _set_sidebar_pref("sidebar_collapsed", False)
                        ui.query(".shell").classes(remove="is-sidebar-collapsed")
                        fold_btn.props('aria-expanded="true"')
                        
                    _set_sidebar_pref("sidebar_width", _clamp_store(raw))

                splitter.on(
                    "update:model-value",
                    on_splitter_resize,
                    throttle=0.2,
                    leading_events=False,
                )

                with splitter.before:
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
                                cls = (
                                    "template-item active"
                                    if is_active
                                    else "template-item muted"
                                )

                                def on_click(e, tid=t_id):
                                    from nicegui_ui.components.for_main import ForMain

                                    path = registry.TemplateIDs.get(tid)
                                    if path:
                                        ForMain.load_template(tid, path)
                                        render_template_name.refresh()
                                        render_sidebar_list.refresh()
                                        from nicegui_ui.pages.tab_input import (
                                            render_input_tab,
                                        )
                                        from nicegui_ui.pages.tab_toml import (
                                            render_toml_tab,
                                        )
                                        from nicegui_ui.pages.tab_db import (
                                            render_db_tab,
                                        )
                                        from nicegui_ui.pages.tab_google import (
                                            render_google_tab,
                                        )

                                        render_input_tab.refresh()
                                        render_toml_tab.refresh()
                                        render_db_tab.refresh()
                                        render_google_tab.refresh()

                                ui.label(display_name).classes(cls).on(
                                    "click", lambda e, tid=t_id: on_click(e, tid)
                                )

                        render_sidebar_list()

                with splitter.after:
                    with ui.element("main").classes(
                        "main w-full h-full overflow-y-auto"
                    ):

                        @ui.refreshable
                        def render_panels():
                            with ui.element("div").classes("tab-body"):
                                if active_tab == "输入":
                                    from nicegui_ui.pages.tab_input import (
                                        render_input_tab,
                                    )

                                    render_input_tab()
                                elif active_tab == "输入配置":
                                    from nicegui_ui.pages.tab_toml import (
                                        render_toml_tab,
                                    )

                                    render_toml_tab()
                                elif active_tab == "存储配置":
                                    from nicegui_ui.pages.tab_db import render_db_tab

                                    render_db_tab()
                                elif active_tab == "Google 连接":
                                    from nicegui_ui.pages.tab_google import (
                                        render_google_tab,
                                    )

                                    render_google_tab()

                        render_panels()
