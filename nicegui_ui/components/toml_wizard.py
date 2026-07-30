"""TOML 智能向导控制器（无 UI；由 wizard_ui 协调进程内向导）。"""

from __future__ import annotations

from typing import Any

from nicegui import run, ui

from nicegui_ui.components.model_runtime import ensure_gemma_loaded
from llm_gemma4.__main__ import EndGemma, _get_backend
from llm_gemma4.wizard.orchestrator import WizardOrchestrator
from nicegui_ui.components.general import SessionRegistry


_controller_singleton: TomlWizardController | None = None



def get_toml_wizard() -> TomlWizardController:
    """
    函数名: get_toml_wizard
    作用: 返回模块级向导控制器单例
    输入: 无
    输出:
        TomlWizardController: 控制器实例
    """
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = TomlWizardController()
    return _controller_singleton



class TomlWizardController:
    """
    类名: TomlWizardController
    作用: 管理 WizardOrchestrator 生命周期与步骤调度，UI 由 wizard_ui 进程内引导
    """

    def __init__(self) -> None:
        self.orchestrator: WizardOrchestrator | None = None
        self.log_widget = None
        self.chat_widget = None
        self._log_history: list[str] = []
        self._chat_history: list[str] = []
        self._busy = False
        self._starting = False
        self.started = False
        self.ui_step: int = 0
        self._client = None

    @property
    def chat_text(self) -> str:
        return "\n\n".join(self._chat_history)

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
        try:
            ui.timer(delay, self._scroll_chat_to_end, once=True)
        except RuntimeError:
            self._scroll_chat_to_end()

    def _sync_chat_widget(self) -> None:
        """
        函数名: _sync_chat_widget
        作用: 把对话历史写回 textarea 并延迟滚到底
        输入: 无
        输出: 无
        """
        if self.chat_widget is not None:
            self.chat_widget.value = self.chat_text
            self._schedule_chat_scroll(0.05)

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
            with client:
                ui.timer(0.01, _show, once=True)
        except Exception:
            pass

    def _chat(self, role: str, text: str) -> None:
        label = "用户" if role == "user" else "Gemma"
        block = f"【{label}】\n{text.strip()}"
        self._chat_history.append(block)
        client = self._client
        if client is None:
            self._sync_chat_widget()
            return
        with client:
            if self.chat_widget is not None:
                self._sync_chat_widget()
            else:
                from nicegui_ui.components.wizard_ui import _schedule_sidebar_refresh
                _schedule_sidebar_refresh(client)

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
        chat_widget.value = self.chat_text
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
            from llm_gemma4.wizard.template_labels import list_template_labels
            return list_template_labels(session.template_path)
        return []

    def clear_histories(self) -> None:
        """
        函数名: clear_histories
        作用: 清空进度日志与 Gemma 对话历史，并同步已绑定的 UI 控件
        输入: 无
        输出: 无
        """
        self._log_history.clear()
        self._chat_history.clear()
        if self.log_widget is not None:
            try:
                self.log_widget.clear()
            except Exception:
                pass
        if self.chat_widget is not None:
            try:
                self.chat_widget.value = ""
            except Exception:
                pass

    async def start(self, client=None) -> bool:
        """
        函数名: start
        作用: 预热 Gemma 并创建 orchestrator
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
        backend = _get_backend()
        health = backend.health_check()
        # 新建向导会话时清空上次对话/日志残留
        self.clear_histories()
        self.orchestrator = WizardOrchestrator(
            backend, on_progress=self._log, on_chat=self._chat,
            on_match_notify=self._match_notify,
        )
        self._log("向导已启动，Engine profile=" + health.litert_backend)
        if not health.ok:
            self._log(health.message)
        self.started = True
        return True

    async def run_step(self, step: int, payload: dict[str, Any]):
        """
        函数名: run_step
        作用: 在 worker 线程执行 orchestrator.advance
        输入:
            step (int): 步骤 1–8
            payload (dict): 步骤数据
        输出:
            WizardOrchestrator | None: 成功时返回 orchestrator
        """
        if self._busy or self.orchestrator is None:
            return None
        self._busy = True
        try:
            await run.io_bound(self.orchestrator.advance, step, payload)
            return self.orchestrator
        except Exception as exc:
            self._log(f"错误: {exc}")
            raise
        finally:
            self._busy = False

    def stop(self) -> None:
        """
        函数名: stop
        作用: 关闭 orchestrator 并释放 Gemma 模型
        输入: 无
        输出: 无
        """
        if self.orchestrator:
            self.orchestrator.close()
            self.orchestrator = None
        self.log_widget = None
        self.chat_widget = None
        self._client = None
        self.clear_histories()
        EndGemma()
        self.started = False
        self.ui_step = 0
        from nicegui_ui.components.model_runtime import sync_model_runtime_ui
        sync_model_runtime_ui()

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
