"""In-app TOML wizard panel (W5b)."""

from __future__ import annotations

from typing import Any, Callable

from nicegui import run, ui

from llm_gemma4.agent.wizard_runner import create_wizard_runner
from llm_gemma4.backends.factory import create_backend
from llm_gemma4.wizard import prompts
from llm_gemma4.wizard.runner import WizardCallbacks
from llm_gemma4.wizard.state import WizardPhase


_WIZARD_PHASES = (
    'PRECHECK',
    'GOOGLE',
    'READ_TOML',
    'PASTE',
    '字段映射',
    '完成',
)

_UI_STATES = (
    'LOADING_MODEL',
    'RUNNING',
    'WAIT_USER',
    'ERROR',
    'DONE',
)


def _phase_index(phase: str) -> int:
    mapping = {
        WizardPhase.INIT.value: 0,
        WizardPhase.PRECHECK.value: 0,
        WizardPhase.GOOGLE_PROBE.value: 1,
        WizardPhase.READ_TOML.value: 2,
        WizardPhase.COLLECT_PASTE.value: 3,
        WizardPhase.TOP_LEVEL_QA.value: 4,
        WizardPhase.FIELD_MAP_LOOP.value: 4,
        WizardPhase.FINAL_VERIFY.value: 5,
        WizardPhase.DONE.value: 5,
    }
    return mapping.get(phase, 0)


def _phase_label(phase: str) -> str:
    idx = _phase_index(phase)
    if idx < len(_WIZARD_PHASES):
        return _WIZARD_PHASES[idx]
    return phase


class WizardUiController:
    """Page-in wizard UI bound to ``WizardRunner`` via ``WizardCallbacks``."""

    def __init__(
        self,
        session,
        *,
        template_id: str,
        llm: bool = True,
        profile: str = 'cuda',
        resume: bool = False,
        on_apply: Callable[[], None] | None = None,
        on_terminal: Callable[[], None] | None = None,
    ):
        self.session = session
        self.template_id = template_id
        self.llm = llm
        self.profile = profile
        self.resume = resume
        self.on_apply = on_apply
        self.on_terminal = on_terminal
        self.ui_state = 'RUNNING'
        self.phase = WizardPhase.INIT.value
        self.llm_calls = 0
        self.log_lines: list[tuple[str, str]] = []
        self._action_kind = 'confirm'
        self._action_prompt = ''
        self._action_options: list[str] | None = None
        self._choice_value: str | None = None
        self._dialog: ui.dialog | None = None
        self._runner = None
        self.callbacks = WizardCallbacks()
        self._wire_callbacks()


    def _wire_callbacks(self) -> None:
        self.callbacks.on_phase = lambda phase: self._schedule(self._set_phase, phase)
        self.callbacks.on_log = lambda role, text: self._schedule(self.append_log, role, text)
        self.callbacks.on_ui_state = lambda state: self._schedule(self._set_ui_state, state)
        self.callbacks.bind_present_user(
            lambda kind, prompt, options: self._schedule(
                self._present_user_action, kind, prompt, options,
            ),
        )


    def _schedule(self, fn: Callable[..., None], *args: Any) -> None:
        ui.timer(0.01, lambda: fn(*args), once=True)


    def append_log(self, role: str, text: str) -> None:
        self.log_lines.append((role, text))
        self._refresh_log()


    def _set_phase(self, phase: str) -> None:
        self.phase = phase
        self._refresh_stepper()
        self._refresh_status()


    def _set_ui_state(self, state: str) -> None:
        if state in _UI_STATES:
            self.ui_state = state
        self._refresh_status()
        self._refresh_action()


    def _present_user_action(
        self,
        kind: str,
        prompt: str,
        options: list[str] | None,
    ) -> None:
        self._action_kind = kind
        self._action_prompt = prompt
        self._action_options = options
        self._choice_value = options[0] if options else None
        self.ui_state = 'WAIT_USER'
        self.append_log('向导', prompt)
        self._refresh_action()
        self._refresh_status()


    def show_choices(
        self,
        options: list[str],
        callback: Callable[[str], None],
    ) -> None:
        self._action_kind = 'choice'
        self._action_options = options
        self._choice_value = options[0] if options else None
        self._choice_callback = callback
        self._refresh_action()


    def show_continue(self, callback: Callable[[], None]) -> None:
        self._action_kind = 'confirm'
        self._action_options = None
        self._continue_callback = callback
        self._refresh_action()


    def _submit_user(self, answer: str) -> None:
        self.callbacks.submit_user(answer)
        self.ui_state = 'RUNNING'
        self._refresh_action()
        self._refresh_status()


    def _on_dialog_closed(self) -> None:
        # User cancelled the panel; release Playwright Edge if the runner is still active.
        if self._runner is not None:
            self._runner.close_browser_if_open()
            self._runner = None


    def open(self) -> None:
        with ui.dialog() as dialog, ui.card().classes('w-full max-w-3xl gap-0 p-0'):
            self._dialog = dialog
            dialog.on('hide', lambda: self._on_dialog_closed())
            with ui.row().classes('w-full items-center justify-between p-3 bg-gray-100 border-b'):
                ui.label(f'Gemma4 E4B 配置向导 · {self.template_id}').classes('text-lg font-bold')
                ui.button(icon='close', on_click=dialog.close).props('flat round dense')
            self._status_row()
            self._stepper_row()
            self._log_area()
            self._action_area()
            with ui.expansion('高级 · 在终端中运行（调试）', icon='terminal').classes('w-full px-3 pb-3'):
                ui.label('仅开发调试；默认请使用页面向导。').classes('text-xs text-gray-600')
                if self.on_terminal:
                    ui.button('在终端启动', on_click=self.on_terminal).props('flat dense')
        dialog.open()
        if self.resume:
            ui.notify('将从 temp/wizard 恢复进度', type='info')
        ui.timer(0.05, self._start_runner, once=True)


    def _status_row(self) -> None:
        @ui.refreshable
        def _render() -> None:
            with ui.row().classes('w-full items-center gap-3 px-3 py-2 border-b text-sm'):
                badge_color = {
                    'LOADING_MODEL': 'blue',
                    'RUNNING': 'blue',
                    'WAIT_USER': 'orange',
                    'ERROR': 'red',
                    'DONE': 'green',
                }.get(self.ui_state, 'grey')
                badge_text = {
                    'LOADING_MODEL': '加载模型',
                    'RUNNING': '运行中',
                    'WAIT_USER': '等待您',
                    'ERROR': '错误',
                    'DONE': '完成',
                }.get(self.ui_state, self.ui_state)
                ui.badge(badge_text, color=badge_color).props('outline')
                ui.label(f'阶段: {_phase_label(self.phase)}')
                ui.label(f'LLM: {self.profile if self.llm else "关"}')
                ui.label(f'调用 {self.llm_calls}/{prompts.MAX_LLM_CALLS}')
                spinner = ui.spinner('dots', size='sm')
                spinner.set_visibility(self.ui_state == 'LOADING_MODEL')
        self._refresh_status = _render
        _render()


    def _stepper_row(self) -> None:
        @ui.refreshable
        def _render() -> None:
            current = _phase_index(self.phase)
            with ui.row().classes('w-full flex-wrap gap-1 px-3 py-2 border-b'):
                for idx, name in enumerate(_WIZARD_PHASES):
                    chip = ui.chip(name)
                    if idx < current or self.phase == WizardPhase.DONE.value:
                        chip.props('color=positive outline')
                    elif idx == current:
                        chip.props('color=warning')
                    else:
                        chip.props('outline')
        self._refresh_stepper = _render
        _render()


    def _log_area(self) -> None:
        @ui.refreshable
        def _render() -> None:
            with ui.column().classes('w-full gap-1 p-3 bg-gray-50 max-h-72 overflow-y-auto'):
                if not self.log_lines:
                    ui.label('（等待日志…）').classes('text-sm text-gray-500')
                for role, text in self.log_lines:
                    css = 'text-sm text-gray-700' if role == '系统' else 'text-sm'
                    ui.label(f'[{role}] {text}').classes(css)
        self._refresh_log = _render
        _render()


    def _action_area(self) -> None:
        @ui.refreshable
        def _render() -> None:
            with ui.column().classes('w-full gap-2 p-3 border-t'):
                if self.ui_state == 'DONE':
                    ui.label('向导已完成，请校验并应用配置。').classes('text-sm text-green-700')
                    if self.on_apply:
                        ui.button(
                            '校验并应用配置',
                            on_click=self.on_apply,
                        ).props('color=primary')
                    return
                if self.ui_state == 'ERROR':
                    ui.label('向导出错，可关闭后重试。').classes('text-sm text-red')
                    return
                if self.ui_state != 'WAIT_USER':
                    ui.label('向导运行中…').classes('text-sm text-gray-500')
                    return
                ui.label(self._action_prompt or '需要您完成外部操作').classes('text-sm text-gray-600')
                if self._action_kind == 'choice' and self._action_options:
                    choice = ui.radio(
                        self._action_options,
                        value=self._choice_value,
                    ).props('inline')
                    def _confirm_choice() -> None:
                        value = choice.value or ''
                        self._submit_user(str(value))
                    ui.button('确认', on_click=_confirm_choice).props('color=primary')
                elif self._action_kind == 'message':
                    ui.button(
                        '知道了',
                        on_click=lambda: self._submit_user('ok'),
                    ).props('color=primary flat')
                else:
                    ui.button(
                        '完成并继续',
                        on_click=lambda: self._submit_user('continue'),
                    ).props('color=primary')
        self._refresh_action = _render
        _render()


    async def _start_runner(self) -> None:
        backend = None
        try:
            if self.llm:
                self.ui_state = 'LOADING_MODEL'
                self.append_log('系统', f'正在加载模型 Gemma4-E4B ({self.profile})…')
                self._refresh_status()
                backend = await run.io_bound(create_backend, self.profile)
                health = await run.io_bound(backend.health_check)
                self.append_log('系统', health)
            self.ui_state = 'RUNNING'
            self._refresh_status()
            runner = create_wizard_runner(
                self.template_id,
                profile=self.profile,
                no_llm=not self.llm,
                resume=self.resume,
                use_browser=True,
                headless=False,
                backend=backend,
                callbacks=self.callbacks,
            )
            self._runner = runner
            result = await run.io_bound(runner.run)
            self._runner = None
            self.llm_calls = result.state.llm_calls
            self.phase = result.state.phase
            if result.state.phase == WizardPhase.DONE.value:
                self.ui_state = 'DONE'
                self._refresh_stepper()
                self._refresh_status()
                self._refresh_action()
                ui.notify('向导完成，请校验并应用配置', type='positive')
            else:
                self.ui_state = 'ERROR'
                self.append_log('系统', f'向导未正常结束: phase={result.state.phase}')
                self._refresh_status()
                self._refresh_action()
        except Exception as exc:
            self.ui_state = 'ERROR'
            if self._runner is not None:
                self._runner.close_browser_if_open()
                self._runner = None
            self.append_log('系统', f'错误: {exc}')
            self._refresh_status()
            self._refresh_action()
            ui.notify(f'向导失败: {exc}', type='negative')
