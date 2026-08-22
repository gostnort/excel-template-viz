"""进程级模型预加载：LM Studio 顶栏开关；OCR daemon 无开关（首次使用懒启动）。"""

from __future__ import annotations

import asyncio
import atexit
import threading
from collections.abc import Callable
from typing import Any

from nicegui import app, run, ui
from nicegui.client import Client


_refresh_runtime: Callable[[], None] | None = None
_gemma_loading = False
_models_released = False
_release_lock = threading.Lock()
_shutdown_hooks_registered = False



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
    _register_shutdown_hooks()



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
    _ = client
    async def _run() -> None:
        await asyncio.sleep(0.05)
        _refresh_runtime_safe()
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _refresh_runtime_safe()



def sync_model_runtime_ui(client: Client | None = None) -> None:
    """
    函数名: sync_model_runtime_ui
    作用: 将顶栏 LM Studio 开关与远端加载状态对齐
    输入:
        client (Client | None): NiceGUI 客户端；OCR 等跨线程回调应传入
    输出: 无
    """
    _schedule_runtime_refresh(client)



def _dismiss_notification(handle: Any) -> None:
    if handle is None:
        return
    try:
        if getattr(handle, "deleted", False) or getattr(handle, "is_deleted", False):
            return
        if hasattr(handle, "dismiss"):
            handle.dismiss()
    except RuntimeError as exc:
        if "deleted" in str(exc).lower():
            return
    except Exception:
        pass



def is_gemma_loading() -> bool:
    """
    函数名: is_gemma_loading
    作用: LM Studio 模型是否正在 load
    输入: 无
    输出:
        bool: 加载中为 True
    """
    return _gemma_loading



def is_gemma_loaded() -> bool:
    """
    函数名: is_gemma_loaded
    作用: 判断配置中的 LM Studio 模型是否已加载
    输入: 无
    输出:
        bool: 已加载为 True
    """
    try:
        from llm_lmstudio.models import is_model_loaded
        return is_model_loaded()
    except Exception:
        return False



async def ensure_gemma_loaded(*, notify: bool = True, client: Client | None = None) -> bool:
    """
    函数名: ensure_gemma_loaded
    作用: 若当前模型未加载则 POST /api/v1/models/load
    输入:
        notify (bool): 是否显示加载中通知
        client (Client | None): NiceGUI 客户端，用于跨 refresh 安全通知
    输出:
        bool: 是否已成功就绪
    """
    global _gemma_loading
    from llm_lmstudio.config import load_user_config
    if not str(load_user_config().get("model") or "").strip():
        resolved = _resolve_client(client)
        if notify and resolved is not None:
            with resolved:
                ui.notify("请先填写 LM Studio 模型名称", type="warning")
        return False
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
            progress = ui.notification("正在通过 LM Studio 加载模型…", spinner=True, type="ongoing")
    try:
        from llm_lmstudio.models import load_model
        await run.io_bound(load_model)
        return is_gemma_loaded()
    except Exception:
        return False
    finally:
        _gemma_loading = False
        _dismiss_notification(progress)
        _schedule_runtime_refresh(resolved)



async def set_gemma_preload(enabled: bool, client: Client | None = None) -> bool:
    """
    函数名: set_gemma_preload
    作用: 顶栏开关：遥控 LM Studio 加载或卸载当前模型
    输入:
        enabled (bool): True 加载，False 卸载
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
                    ui.notify("LM Studio 模型已加载", type="positive")
                else:
                    ui.notify("LM Studio 模型加载失败", type="negative")
        return ok
    from nicegui_ui.components.workflow_ui import is_workflow_active, stop_wizard
    if is_workflow_active():
        await stop_wizard("模型已卸载，配置向导已结束")
    from llm_lmstudio.models import unload_model
    await run.io_bound(unload_model)
    _schedule_runtime_refresh(resolved)
    if resolved is not None:
        with resolved:
            ui.notify("LM Studio 模型已卸载", type="info")
    return False



def release_all_models_sync() -> None:
    """
    函数名: release_all_models_sync
    作用: 进程退出前结束向导、卸载 LM Studio，并 stop_mcp 停 OCR 与 Structure。
    输入: 无
    输出: 无
    """
    global _models_released
    with _release_lock:
        if _models_released:
            return
        _models_released = True
    # 中文注释: 先结束配置向导，避免 dispatch 与 unload 竞态
    try:
        from nicegui_ui.components.workflow_ui import is_workflow_active
        from nicegui_ui.components.toml_wizard import get_toml_wizard
        wizard = get_toml_wizard()
        if is_workflow_active() or wizard.started or wizard.orchestrator is not None:
            wizard.stop()
        elif is_gemma_loaded():
            from llm_lmstudio.models import unload_model
            unload_model()
    except Exception:
        pass
    try:
        # T1：进程退出双杀；ResetStructureBackend 只杀 Structure 并清单例
        from paddle_ocr.mcp_runtime import stop_mcp
        stop_mcp()
        from paddle_ocr.engines.pp_structure.backend import ResetStructureBackend
        ResetStructureBackend()
    except Exception:
        pass



def _register_shutdown_hooks() -> None:
    """
    函数名: _register_shutdown_hooks
    作用: 注册 NiceGUI on_shutdown 与 atexit 兜底
    输入: 无
    输出: 无
    """
    global _shutdown_hooks_registered
    with _release_lock:
        if _shutdown_hooks_registered:
            return
        _shutdown_hooks_registered = True
    app.on_shutdown(release_all_models_sync)
    atexit.register(release_all_models_sync)



def shutdown_application() -> None:
    """
    函数名: shutdown_application
    作用: 释放模型资源后关闭 NiceGUI 服务进程
    输入: 无
    输出: 无
    """
    release_all_models_sync()
    app.shutdown()



def render_runtime_controls(*, show_shutdown: bool = True) -> None:
    """
    函数名: render_runtime_controls
    作用: 渲染顶栏可编辑模型名、LM Studio 加载开关与关闭程序（无 OCR/Structure 开关）
    输入:
        show_shutdown (bool): 是否显示关闭程序按钮（手机浏览器为 False）
    输出: 无
    """
    from llm_lmstudio.config import load_user_config, save_user_config
    from nicegui_ui.components.buttons import AppBtn
    cfg = load_user_config()
    gemma_loaded = is_gemma_loaded()
    gemma_busy = is_gemma_loading()
    with ui.element("div").classes("tabs-runtime"):
        model_input = (
            ui.input(placeholder="LM Studio 模型名", value=str(cfg.get("model") or ""))
            .classes("model-name-input")
            .props("dense outlined hide-bottom-space")
        )
        async def _on_model_blur(_e) -> None:
            name = str(model_input.value or "").strip()
            save_user_config(model=name, remember_model=bool(name))
        model_input.on("blur", _on_model_blur)
        gemma_switch = ui.switch("", value=gemma_loaded).classes("model-toggle").props("dense")
        if gemma_busy:
            gemma_switch.disable()
        async def _on_gemma(_e):
            client = ui.context.client
            target = bool(gemma_switch.value)
            if target == is_gemma_loaded():
                return
            await set_gemma_preload(target, client=client)
        gemma_switch.on("update:model-value", _on_gemma)
        if show_shutdown:
            AppBtn("关闭程序", on_click=shutdown_application, extra_classes="app-btn-shutdown")


_register_shutdown_hooks()
