"""TOML 工作流控制器（无 UI；由 workflow_ui 协调进程内工作流）。"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from nicegui import run, ui

from nicegui_ui.components.model_runtime import ensure_gemma_loaded
from llm_lmstudio.backend import get_backend
from llm_toml_wizard.toml_config.workflow_orchestrator import WorkflowOrchestrator
from llm_toml_wizard.workflow.events import EVENT_RESUME, EVENT_START, WorkflowEvent
from nicegui_ui.components.general import Auth, SessionRegistry


_controller_singleton: TomlWizardController | None = None



def get_toml_wizard() -> TomlWizardController:
    """
    函数名: get_toml_wizard
    作用: 返回模块级工作流控制器单例
    输入: 无
    输出:
        TomlWizardController: 控制器实例
    """
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = TomlWizardController()
    return _controller_singleton


def get_workflow_controller() -> TomlWizardController:
    """
    函数名: get_workflow_controller
    作用: get_toml_wizard 的 Phase D 别名
    输入: 无
    输出:
        TomlWizardController: 控制器实例
    """
    return get_toml_wizard()



class TomlWizardController:
    """
    类名: TomlWizardController
    作用: 管理 WorkflowOrchestrator 生命周期与 Graph dispatch 调度，UI 由 workflow_ui 进程内引导
    """

    def __init__(self) -> None:
        self.orchestrator: WorkflowOrchestrator | None = None
        self.log_widget = None
        self.chat_widget = None
        self._log_history: list[str] = []
        self._chat_history: list[str] = []
        self._busy = False
        self._starting = False
        self._stopping = False
        self.started = False
        self._client = None

    @property
    def is_stopping(self) -> bool:
        """
        函数名: is_stopping
        作用: 是否正在请求停止（等待当前 dispatch 结束）
        输入: 无
        输出:
            bool: 停止流程进行中为 True
        """
        return self._stopping

    @property
    def chat_text(self) -> str:
        return "\n\n".join(self._chat_history)

    @property
    def sidebar_feed_text(self) -> str:
        """
        函数名: sidebar_feed_text
        作用: 合并运行日志与 Gemma 对话，供 sidebar textarea 展示
        输入: 无
        输出:
            str: 多行侧栏活动文本
        """
        parts: list[str] = []
        if self._log_history:
            parts.append("【运行日志】")
            parts.extend(self._log_history)
        if self._chat_history:
            if parts:
                parts.append("")
            parts.extend(self._chat_history)
        return "\n\n".join(parts)

    @property
    def is_busy(self) -> bool:
        """
        函数名: is_busy
        作用: 是否正在执行 orchestrator.advance 或模型加载
        输入: 无
        输出:
            bool: 忙碌时为 True
        """
        return self._busy or self._starting

    def _log(self, msg: str) -> None:
        self._log_history.append(msg)
        if self.log_widget is not None:
            self.log_widget.push(msg)
        self._push_sidebar_update()

    def _push_sidebar_update(self) -> None:
        """
        函数名: _push_sidebar_update
        作用: 将运行日志与对话历史同步到 sidebar 或触发 refresh 重建绑定
        输入: 无
        输出: 无
        """
        from nicegui_ui.components.workflow_ui import _schedule_sidebar_refresh, is_workflow_active
        client = self._client
        if not is_workflow_active():
            _schedule_sidebar_refresh(client)
            return
        if client is None:
            _schedule_sidebar_refresh(client)
            return
        with client:
            if self.chat_widget is not None:
                self._sync_chat_widget()
            else:
                _schedule_sidebar_refresh(client)

    def _scroll_chat_to_end(self) -> None:
        """
        函数名: _scroll_chat_to_end
        作用: 将 sidebar Gemma 对话区滚到最新消息
        输入: 无
        输出: 无
        """
        try:
            ui.run_javascript(
                """
(() => {
  const roots = document.querySelectorAll('.wizard-sidebar-chat-log');
  roots.forEach((root) => {
    const native = root.querySelector('textarea')
      || root.querySelector('.q-field__native');
    if (native) native.scrollTop = native.scrollHeight;
  });
})();
"""
            )
        except Exception:
            pass

    def _install_chat_scroll_binding(self) -> None:
        """
        函数名: _install_chat_scroll_binding
        作用: 在 sidebar 对话区安装 MutationObserver/input 监听，内容变化时自动滚到底
        输入: 无
        输出: 无
        """
        try:
            ui.run_javascript(
                """
(() => {
  const install = () => {
    const roots = document.querySelectorAll('.wizard-sidebar-chat-log');
    roots.forEach((root) => {
      if (root.dataset.scrollBound === '1') return;
      root.dataset.scrollBound = '1';
      const scrollNative = () => {
        const el = root.querySelector('textarea')
          || root.querySelector('.q-field__native');
        if (el) el.scrollTop = el.scrollHeight;
      };
      const bindNative = () => {
        const native = root.querySelector('textarea')
          || root.querySelector('.q-field__native');
        if (!native || native.dataset.scrollBound === '1') return;
        native.dataset.scrollBound = '1';
        native.addEventListener('input', scrollNative);
        try {
          const proto = Object.getOwnPropertyDescriptor(
            HTMLTextAreaElement.prototype, 'value'
          );
          if (proto && proto.set && proto.get) {
            Object.defineProperty(native, 'value', {
              configurable: true,
              enumerable: true,
              get() { return proto.get.call(this); },
              set(v) {
                proto.set.call(this, v);
                requestAnimationFrame(scrollNative);
              },
            });
          }
        } catch (_) {}
      };
      const obs = new MutationObserver(() => {
        bindNative();
        scrollNative();
      });
      obs.observe(root, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
      });
      bindNative();
      scrollNative();
    });
  };
  install();
  setTimeout(install, 50);
  setTimeout(install, 150);
})();
"""
            )
        except Exception:
            pass

    def _schedule_chat_scroll(self, delay: float) -> None:
        """
        函数名: _schedule_chat_scroll
        作用: 延迟到下一轮事件循环再滚动，避免 textarea 刚写入时 DOM/scrollHeight 未就绪
        输入:
            delay (float): 延迟秒数
        输出: 无
        """
        async def _run() -> None:
            await asyncio.sleep(delay)
            self._scroll_chat_to_end()
        try:
            asyncio.get_running_loop().create_task(_run())
        except RuntimeError:
            self._scroll_chat_to_end()

    def _sync_chat_widget(self) -> None:
        """
        函数名: _sync_chat_widget
        作用: 把运行日志与对话历史写回 sidebar textarea 并延迟滚到底
        输入: 无
        输出: 无
        """
        if self.chat_widget is None:
            return
        try:
            self.chat_widget.value = self.sidebar_feed_text
            self._schedule_chat_scroll(0.05)
        except Exception:
            self.chat_widget = None
            from nicegui_ui.components.workflow_ui import _schedule_sidebar_refresh
            _schedule_sidebar_refresh(self._client)

    def _match_notify(self, msg: str) -> None:
        """
        函数名: _match_notify
        作用: 将匹配 toast 调度到 NiceGUI client 事件循环弹出（避免在 worker 线程直接 ui.notify）
        输入:
            msg (str): 提示文案（含 label/index 等短信息）
        输出: 无
        """
        client = self._client
        if client is None:
            return
        try:
            def _show() -> None:
                try:
                    with client:
                        ui.notify(
                            msg,
                            type="positive",
                            position="top",
                            multi_line=True,
                            close_button=True,
                        )
                except Exception:
                    pass
            async def _delayed_show() -> None:
                await asyncio.sleep(0.01)
                _show()
            try:
                asyncio.get_running_loop().create_task(_delayed_show())
            except RuntimeError:
                with client:
                    _show()
        except Exception:
            pass

    def _chat(self, role: str, text: str) -> None:
        label = "用户" if role == "user" else "模型"
        block = f"【{label}】\n{text.strip()}"
        self._chat_history.append(block)
        self._push_sidebar_update()

    def bind_log(self, log_widget) -> None:
        """
        函数名: bind_log
        作用: 绑定向导对话框中的 ui.log 并回放历史消息
        输入:
            log_widget: NiceGUI log 组件
        输出: 无
        """
        self.log_widget = log_widget
        for line in self._log_history:
            log_widget.push(line)

    def bind_chat(self, chat_widget) -> None:
        """
        函数名: bind_chat
        作用: 绑定 sidebar 对话 textarea、回放历史，并安装粘性滚底监听
        输入:
            chat_widget: NiceGUI textarea 组件
        输出: 无
        """
        self.chat_widget = chat_widget
        chat_widget.value = self.sidebar_feed_text
        # 浏览器侧 MutationObserver：并发匹配时比 timer 备份更稳
        self._install_chat_scroll_binding()
        self._schedule_chat_scroll(0.15)

    def session_payload_base(self) -> dict[str, Any]:
        session = SessionRegistry.for_current()
        return {
            "template_id": session.template_id or "",
            "template_path": str(session.template_path) if session.template_path else "",
        }

    def google_payload(self) -> dict[str, Any]:
        session = SessionRegistry.for_current()
        headers: list[str] = []
        rows: list[list[Any]] = []
        conn = getattr(session, "connect_google", None)
        if conn is not None:
            try:
                table = conn.prepare_id_sheet_table()
                headers = list(table.columns)
                rows = [[row.get(c, "") for c in headers] for row in table.rows[:5]]
            except Exception:
                pass
        return {"google_sheet_headers": headers, "google_sheet_sample": rows, "source_sheet": "Sheet1"}

    def template_labels(self) -> list[str]:
        session = SessionRegistry.for_current()
        if session.ui_provider:
            return session.ui_provider.get_labels()
        if session.template_path:
            from llm_toml_wizard.toml_config.template_labels import list_template_labels
            return list_template_labels(session.template_path)
        return []

    def clear_histories(self) -> None:
        """
        函数名: clear_histories
        作用: 清空进度日志与 Gemma 对话历史，并同步已绑定的 UI 控件
        输入: 无
        输出: 无
        """
        self.chat_widget = None
        self._log_history.clear()
        self._chat_history.clear()
        if self.log_widget is not None:
            try:
                self.log_widget.clear()
            except Exception:
                pass

    async def start(self, client=None) -> bool:
        """
        函数名: start
        作用: 确认 LM Studio 模型已加载并创建 orchestrator
        输入:
            client: NiceGUI 客户端（可选，用于跨 refresh 安全加载）
        输出:
            bool: 是否成功启动
        """
        session = SessionRegistry.for_current()
        if not session.template_id or not session.template_path:
            return False
        if self.started and self.orchestrator is not None:
            return True
        self.chat_widget = None
        self._starting = True
        self._client = client
        try:
            ok = await ensure_gemma_loaded(notify=False, client=client)
            if not ok:
                return False
        except Exception:
            return False
        finally:
            self._starting = False
        backend = get_backend()
        health = backend.health_check()
        principal = Auth.resolve_principal()
        thread_id = f"{principal.principal_id}:workflow"
        # 新建向导会话时清空上次对话/日志残留
        self.clear_histories()
        self.orchestrator = WorkflowOrchestrator(
            backend, on_progress=self._log, on_chat=self._chat,
            on_match_notify=self._match_notify,
            thread_id=thread_id,
        )
        labels = self.template_labels()
        self.orchestrator.init_workflow(
            session.template_id,
            Path(session.template_path),
            labels,
        )
        self._log(
            "向导已启动，LM Studio "
            + str(health.api_url)
            + " model="
            + str(health.model)
            + " vision="
            + str(health.vision)
        )
        if not health.ok:
            self._log(health.message)
        self.started = True
        return True

    async def dispatch(self, event: WorkflowEvent) -> WorkflowEvent | None:
        """
        函数名: dispatch
        作用: 在线程池执行 orchestrator.dispatch（LM Studio HTTP）
        输入:
            event (WorkflowEvent): start / resume / stop
        输出:
            WorkflowEvent | None: 出站事件；忙碌或已停止时为 None
        """
        if self._stopping or self._busy or self.orchestrator is None:
            return None
        self._busy = True
        try:
            orch = self.orchestrator
            outbound = await run.io_bound(orch.dispatch, event)
            if self._stopping:
                return None
            return outbound
        except Exception as exc:
            self._log(f"错误: {exc}")
            raise
        finally:
            self._busy = False

    async def run_turn(self, payload: dict[str, Any] | None = None) -> WorkflowEvent | None:
        """
        函数名: run_turn
        作用: 兼容入口：按是否中断映射为 Resume 或 Start（图内会 Continue）
        输入:
            payload (dict | None): 步骤/恢复数据
        输出:
            WorkflowEvent | None: 出站事件
        """
        orch = self.orchestrator
        if orch is None:
            return None
        kind = EVENT_RESUME if orch.is_interrupted() else EVENT_START
        return await self.dispatch(WorkflowEvent(type=kind, payload=dict(payload or {})))

    def _persist_workflow_toml(self) -> None:
        """
        函数名: _persist_workflow_toml
        作用: 停止前将 orchestrator 内已匹配字段写入 TOML，避免中断退出丢进度
        输入: 无
        输出: 无
        """
        if self.orchestrator is None:
            return
        st = self.orchestrator.state
        tid = str(st.template_id or "").strip()
        if not tid:
            return
        try:
            from llm_toml_wizard.toml_config.toml_patcher import persist_wizard_toml
            persist_wizard_toml(st, tid)
        except Exception as exc:
            self._log(f"停止前 TOML 保存失败: {exc}")

    def _release_gemma(self) -> None:
        """
        函数名: _release_gemma
        作用: 关闭 orchestrator（不卸载 LM Studio 权重；由顶栏开关遥控）
        输入: 无
        输出: 无
        """
        orch = self.orchestrator
        if orch is not None:
            orch.close()
        self.orchestrator = None
        self.log_widget = None
        self.chat_widget = None
        self._client = None
        self.clear_histories()
        self.started = False
        from nicegui_ui.components.model_runtime import sync_model_runtime_ui
        sync_model_runtime_ui()

    async def stop_async(self, timeout: float = 300.0) -> None:
        """
        函数名: stop_async
        作用: 等待当前 dispatch 结束后关闭向导，不卸载远端模型
        输入:
            timeout (float): 等待 dispatch 结束的最长秒数
        输出: 无
        """
        if not self.started and self.orchestrator is None and not self._busy:
            return
        self._stopping = True
        deadline = time.monotonic() + timeout
        while self._busy or self._starting:
            if time.monotonic() >= deadline:
                self._log("停止超时：仍有任务执行中，将强制结束向导")
                break
            await asyncio.sleep(0.05)
        self._persist_workflow_toml()
        self._release_gemma()
        self._stopping = False

    def stop(self) -> None:
        """
        函数名: stop
        作用: 同步停止入口（优先使用 stop_async）；无事件循环时直接释放
        输入: 无
        输出: 无
        """
        self._stopping = True
        self._persist_workflow_toml()
        self._release_gemma()
        self._stopping = False

    def has_google_sheet_source(self) -> bool:
        """
        函数名: has_google_sheet_source
        作用: 判断当前会话是否已配置可用的 Google Sheet 数据源
        输入: 无
        输出:
            bool: 已连接且可读取 ID 表时为 True
        """
        session = SessionRegistry.for_current()
        if session.google_connected:
            return True
        conn = getattr(session, "connect_google", None)
        if conn is None:
            return False
        try:
            conn.prepare_id_sheet_table()
            return True
        except Exception:
            return False

    def build_data_sources(self) -> list[dict[str, str]]:
        """
        函数名: build_data_sources
        作用: 根据当前会话 Google 连接状态组装步骤 1 的 data_sources
        输入: 无
        输出:
            list[dict[str, str]]: 数据源列表（无 Google 时为空列表）
        """
        if self.has_google_sheet_source():
            return [{"type": "google_sheet", "source1": "google"}]
        return []
