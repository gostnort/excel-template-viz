"""进程级模型预加载：Gemma4 / Paddle-VL 与 NiceGUI 顶栏开关。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from nicegui import app, run, ui
from nicegui.client import Client


_refresh_runtime: Callable[[], None] | None = None
_gemma_loading = False
_vl_loading = False



def register_runtime_refresh(refresh: Callable[[], None]) -> None:
    """
    函数名: register_runtime_refresh
    作用: 由 main.render_shell 注入顶栏运行时控件刷新回调
    输入:
        refresh: refreshable 刷新函数
    输出: 无
    """
    global _refresh_runtime
    _refresh_runtime = refresh



def _refresh_runtime_safe() -> None:
    if _refresh_runtime is not None:
        _refresh_runtime()



def _resolve_client(client: Client | None) -> Client | None:
    if client is not None:
        return client
    try:
        return ui.context.client
    except RuntimeError:
        return None



def _schedule_runtime_refresh(client: Client | None) -> None:
    resolved = _resolve_client(client)
    if resolved is None:
        _refresh_runtime_safe()
        return
    with resolved:
        ui.timer(0.05, _refresh_runtime_safe, once=True)



def sync_model_runtime_ui(client: Client | None = None) -> None:
    """
    函数名: sync_model_runtime_ui
    作用: 将顶栏 Gemma4 / Paddle-VL 开关与进程内模型单例状态对齐
    输入:
        client (Client | None): NiceGUI 客户端；OCR 等跨线程回调应传入
    输出: 无
    """
    _schedule_runtime_refresh(client)



def _dismiss_notification(handle: Any) -> None:
    if handle is None:
        return
    try:
        if hasattr(handle, "dismiss"):
            handle.dismiss()
    except Exception:
        pass



def is_gemma_loading() -> bool:
    """
    函数名: is_gemma_loading
    作用: Gemma4 是否正在后台预加载
    输入: 无
    输出:
        bool: 加载中为 True
    """
    return _gemma_loading



def is_vl_loading() -> bool:
    """
    函数名: is_vl_loading
    作用: Paddle-VL 是否正在后台预加载
    输入: 无
    输出:
        bool: 加载中为 True
    """
    return _vl_loading



def is_gemma_loaded() -> bool:
    """
    函数名: is_gemma_loaded
    作用: 判断 Gemma4 Engine 是否已 warm
    输入: 无
    输出:
        bool: 已加载为 True
    """
    try:
        from llm_gemma4.__main__ import _get_backend
        backend = _get_backend()
        return getattr(backend, "_engine", None) is not None
    except Exception:
        return False



def is_vl_loaded() -> bool:
    """
    函数名: is_vl_loaded
    作用: 判断 Paddle-VL 引擎是否已构造
    输入: 无
    输出:
        bool: 已加载为 True
    """
    try:
        from paddle_ocr.engines.paddle_vl.backend import GetVlBackend
        return GetVlBackend()._engine is not None
    except Exception:
        return False



async def ensure_gemma_loaded(*, notify: bool = True, client: Client | None = None) -> bool:
    """
    函数名: ensure_gemma_loaded
    作用: 若 Gemma4 未加载则后台 warm；已加载时立即返回
    输入:
        notify (bool): 是否显示加载中通知
        client (Client | None): NiceGUI 客户端，用于跨 refresh 安全通知
    输出:
        bool: 是否已成功就绪
    """
    global _gemma_loading
    if is_gemma_loaded():
        if client is not None:
            sync_model_runtime_ui(client)
        return True
    if _gemma_loading:
        return False
    _gemma_loading = True
    resolved = _resolve_client(client)
    progress = None
    if notify and resolved is not None:
        with resolved:
            progress = ui.notification("正在加载 Gemma4…", spinner=True, type="ongoing")
    try:
        from llm_gemma4.__main__ import StartGemma
        await run.io_bound(StartGemma)
        return is_gemma_loaded()
    except Exception:
        return False
    finally:
        _gemma_loading = False
        if resolved is not None:
            with resolved:
                _dismiss_notification(progress)
        else:
            _dismiss_notification(progress)
        _schedule_runtime_refresh(resolved)



async def set_gemma_preload(enabled: bool, client: Client | None = None) -> bool:
    """
    函数名: set_gemma_preload
    作用: 顶栏开关：开启预加载或卸载 Gemma4
    输入:
        enabled (bool): True 预加载，False 卸载
        client (Client | None): NiceGUI 客户端
    输出:
        bool: 操作后是否处于已加载状态
    """
    resolved = _resolve_client(client)
    if enabled:
        ok = await ensure_gemma_loaded(notify=True, client=resolved)
        if resolved is not None:
            with resolved:
                if ok:
                    ui.notify("Gemma4 已预加载", type="positive")
                else:
                    ui.notify("Gemma4 预加载失败", type="negative")
        return ok
    from nicegui_ui.components.workflow_ui import is_workflow_active, stop_wizard
    if is_workflow_active():
        await stop_wizard("Gemma4 已卸载，配置向导已结束")
    from llm_gemma4.__main__ import EndGemma
    await run.io_bound(EndGemma)
    _schedule_runtime_refresh(resolved)
    if resolved is not None:
        with resolved:
            ui.notify("Gemma4 已卸载", type="info")
    return False



async def set_vl_preload(enabled: bool, client: Client | None = None) -> bool:
    """
    函数名: set_vl_preload
    作用: 顶栏开关：开启预加载或卸载 Paddle-VL
    输入:
        enabled (bool): True 预加载，False 卸载
        client (Client | None): NiceGUI 客户端
    输出:
        bool: 操作后是否处于已加载状态
    """
    global _vl_loading
    resolved = _resolve_client(client)
    if enabled:
        if is_vl_loaded():
            sync_model_runtime_ui(resolved)
            return True
        if _vl_loading:
            return False
        _vl_loading = True
        progress = None
        if resolved is not None:
            with resolved:
                progress = ui.notification("正在预加载 Paddle-VL…", spinner=True, type="ongoing")
        try:
            from paddle_ocr.engines.paddle_vl.backend import GetVlBackend
            await run.io_bound(GetVlBackend().warm)
            ok = is_vl_loaded()
            if resolved is not None:
                with resolved:
                    if ok:
                        ui.notify("Paddle-VL 已预加载", type="positive")
                    else:
                        ui.notify("Paddle-VL 不可用（需 GPU 与模型）", type="warning")
            return ok
        except Exception:
            if resolved is not None:
                with resolved:
                    ui.notify("Paddle-VL 预加载失败", type="negative")
            return False
        finally:
            _vl_loading = False
            if resolved is not None:
                with resolved:
                    _dismiss_notification(progress)
            else:
                _dismiss_notification(progress)
            _schedule_runtime_refresh(resolved)
    from paddle_ocr.engines.paddle_vl.backend import ResetVlBackend
    await run.io_bound(ResetVlBackend)
    _schedule_runtime_refresh(resolved)
    if resolved is not None:
        with resolved:
            ui.notify("Paddle-VL 已卸载", type="info")
    return False



def shutdown_application() -> None:
    """
    函数名: shutdown_application
    作用: 关闭 NiceGUI 服务进程
    输入: 无
    输出: 无
    """
    app.shutdown()



def render_runtime_controls(*, show_shutdown: bool = True) -> None:
    """
    函数名: render_runtime_controls
    作用: 渲染顶栏右侧 Gemma4 / Paddle-VL 预加载开关与关闭程序按钮
    输入:
        show_shutdown (bool): 是否显示关闭程序按钮（手机浏览器为 False）
    输出: 无
    """
    from nicegui_ui.components.buttons import AppBtn

    gemma_loaded = is_gemma_loaded()
    vl_loaded = is_vl_loaded()
    gemma_busy = is_gemma_loading()
    vl_busy = is_vl_loading()
    with ui.element("div").classes("tabs-runtime"):
        gemma_switch = ui.switch(
            "Gemma4",
            value=gemma_loaded,
        ).classes("model-toggle").props("dense")
        if gemma_busy:
            gemma_switch.disable()
        async def _on_gemma(_e):
            client = ui.context.client
            target = bool(gemma_switch.value)
            if target == is_gemma_loaded():
                return
            await set_gemma_preload(target, client=client)
        gemma_switch.on("update:model-value", _on_gemma)
        vl_switch = ui.switch(
            "Paddle-VL",
            value=vl_loaded,
        ).classes("model-toggle").props("dense")
        if vl_busy:
            vl_switch.disable()
        async def _on_vl(_e):
            client = ui.context.client
            target = bool(vl_switch.value)
            if target == is_vl_loaded():
                return
            await set_vl_preload(target, client=client)
        vl_switch.on("update:model-value", _on_vl)
        if show_shutdown:
            AppBtn("关闭程序", on_click=shutdown_application, extra_classes="app-btn-shutdown")
