from nicegui import ui, app

from nicegui_ui.components.general import Auth


def _set_sidebar_pref(key: str, value) -> None:
    """
    函数名: _set_sidebar_pref
    作用: 将侧栏偏好写入带 principal 前缀的键（并清理旧裸键）
    输入:
    key (str): 偏好名，如 sidebar_width / sidebar_collapsed
    value: 要持久化的值
    输出:
    None: 无返回值
    """
    app.storage.user[Auth.pref_key(key)] = value
    # 兼容迁移：去掉历史上无前缀的重复写入
    try:
        del app.storage.user[key]
    except KeyError:
        pass


def _read_sidebar_pref(key: str, default=None):
    """
    函数名: _read_sidebar_pref
    作用: 读取侧栏偏好；若仅有旧裸键则迁移到 pref_key
    输入:
    key (str): 偏好名
    default: 缺失时的默认值
    输出:
    任意: 存储值或 default
    """
    pref = Auth.pref_key(key)
    if pref in app.storage.user:
        return app.storage.user.get(pref, default)
    legacy = app.storage.user.get(key, default)
    if key in app.storage.user:
        app.storage.user[pref] = app.storage.user[key]
        del app.storage.user[key]
    return legacy


def _clamp_sidebar_width(value: float | int) -> int:
    """
    函数名: _clamp_sidebar_width
    作用: 将侧栏像素宽度限制在可拖动范围内
    输入:
    value (float | int): 原始宽度
    输出:
    int: 120..400 之间的整数像素
    """
    return max(120, min(400, int(value)))


def render_shell():
    """
    函数名: render_shell
    作用: 渲染主壳层（侧栏、标签栏、主区）并绑定侧栏拖宽
    输入:
    无
    输出:
    None: 无返回值
    """
    ui.query("body").classes("p-0 m-0 overflow-hidden")
    # 解析端侧折叠与宽度偏好
    user_agent = ui.context.client.request.headers.get("user-agent", "").lower()
    is_mobile = (
        "mobi" in user_agent or "android" in user_agent or "iphone" in user_agent
    )
    is_collapsed = _read_sidebar_pref(
        "sidebar_collapsed", True if is_mobile else False
    )
    stored_width = _read_sidebar_pref("sidebar_width")
    try:
        stored_width = _clamp_sidebar_width(250 if stored_width is None else stored_width)
    except (TypeError, ValueError):
        stored_width = 250
    with ui.element("div").classes("shell w-full h-full").props(
        f'id="app-shell" style="--sidebar-w: {stored_width}px;"'
    ):
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

        def switch_tab(tab_name: str) -> None:
            nonlocal active_tab
            if active_tab == tab_name:
                return
            active_tab = tab_name
            app.storage.user["active_tab"] = tab_name
            render_tabs.refresh()
            render_panels.refresh()

        def set_tab(tab_name):
            switch_tab(tab_name)

        with ui.element("nav").classes("tabs"):
            with ui.element("div").classes("tabs-primary"):

                @ui.refreshable
                def render_tabs():
                    for t in ["输入", "输入配置", "存储配置", "Google 连接"]:
                        cls = "tab active" if t == active_tab else "tab"
                        ui.label(t).classes(cls).on(
                            "click", lambda e, name=t: set_tab(name)
                        )

                render_tabs()

            @ui.refreshable
            def render_runtime_bar():
                from nicegui_ui.components.model_runtime import render_runtime_controls

                render_runtime_controls(show_shutdown=not is_mobile)

            render_runtime_bar()

            from nicegui_ui.components.model_runtime import register_runtime_refresh

            register_runtime_refresh(render_runtime_bar.refresh)

        with ui.element("aside").classes("sidebar").props('id="sidebar"'):

            @ui.refreshable
            def render_wizard_sidebar_section():
                from nicegui_ui.components.wizard_ui import render_wizard_sidebar_chat

                render_wizard_sidebar_chat()

            render_wizard_sidebar_section()

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

                    async def on_click(e, tid=t_id):
                        from nicegui_ui.components.for_main import ForMain
                        from nicegui_ui.components.wizard_ui import is_wizard_active, stop_wizard

                        if is_wizard_active():
                            await stop_wizard("模板已切换，向导已结束")
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
            # 拖拽改宽：放在 refreshable 外，避免对话刷新打断拖动
            ui.element("div").classes("sidebar-resize-rail").props(
                'id="sidebar-resize-rail" title="拖动调整侧栏宽度"'
            )

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

        @ui.refreshable
        def render_wizard_chrome():
            from nicegui_ui.components.wizard_ui import render_wizard_fab

            render_wizard_fab()

        render_wizard_chrome()

        from nicegui_ui.components.wizard_ui import register_shell

        register_shell(
            switch_tab=switch_tab,
            refresh_chrome=render_wizard_chrome.refresh,
            refresh_sidebar=render_wizard_sidebar_section.refresh,
        )

    def _on_sidebar_resized(e) -> None:
        """
        函数名: _on_sidebar_resized
        作用: 接收浏览器拖宽结束事件并持久化侧栏宽度
        输入:
        e: NiceGUI 自定义事件，args 为像素宽度
        输出:
        None: 无返回值
        """
        try:
            width = _clamp_sidebar_width(e.args)
        except (TypeError, ValueError):
            return
        _set_sidebar_pref("sidebar_width", width)

    ui.on("sidebar_resized", _on_sidebar_resized)
    ui.run_javascript(
        """
(() => {
  const bind = () => {
    const shell = document.getElementById('app-shell');
    const rail = document.getElementById('sidebar-resize-rail');
    if (!shell || !rail || rail.dataset.bound === '1') return false;
    rail.dataset.bound = '1';
    let dragging = false;
    const clamp = (w) => Math.max(120, Math.min(400, Math.round(w)));
    const apply = (w) => shell.style.setProperty('--sidebar-w', clamp(w) + 'px');
    const onMove = (ev) => {
      if (!dragging) return;
      apply(ev.clientX - shell.getBoundingClientRect().left);
    };
    const endDrag = () => {
      if (!dragging) return;
      dragging = false;
      shell.classList.remove('is-sidebar-resizing');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', endDrag);
      window.removeEventListener('pointercancel', endDrag);
      const raw = shell.style.getPropertyValue('--sidebar-w').replace('px', '');
      const w = clamp(Number(raw) || 250);
      apply(w);
      if (typeof emitEvent === 'function') emitEvent('sidebar_resized', w);
    };
    rail.addEventListener('pointerdown', (ev) => {
      if (shell.classList.contains('is-sidebar-collapsed')) return;
      if (ev.button != null && ev.button !== 0) return;
      dragging = true;
      shell.classList.add('is-sidebar-resizing');
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', endDrag);
      window.addEventListener('pointercancel', endDrag);
      ev.preventDefault();
    });
    return true;
  };
  if (bind()) return;
  let n = 0;
  const t = setInterval(() => { if (bind() || ++n > 40) clearInterval(t); }, 50);
})();
"""
    )
