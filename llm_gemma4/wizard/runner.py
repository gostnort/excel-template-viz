"""Wizard state machine with Playwright phases."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core_toml import load_toml

from llm_gemma4.agent.compressor import Compressor
from llm_gemma4.agent.context_config import context_config_for_profile
from llm_gemma4.agent.context_store import ContextStore
from llm_gemma4.backends.base import LlmBackend
from llm_gemma4.runtime.thinking import parse_thinking
from llm_gemma4.tools.browser_playwright import (
    BrowserPlaywrightError,
    NiceGuiBrowser,
)
from llm_gemma4.tools.browser_state import format_page_state
from llm_gemma4.wizard.action_parser import ActionParseError, parse_action
from llm_gemma4.wizard import prompts, toml_io
from llm_gemma4.wizard.precheck import run_precheck
from llm_gemma4.wizard.state import WizardPhase, WizardState, load_state, save_state
from llm_gemma4.wizard.tools import dispatch


@dataclass
class WizardRunResult:
    state: WizardState
    messages: list[str]


@dataclass
class WizardCallbacks:
    """Optional UI bridge; ``on_ask_user`` blocks until ``submit_user``."""

    on_phase: Callable[[str], None] | None = None
    on_log: Callable[[str, str], None] | None = None
    on_ui_state: Callable[[str], None] | None = None
    _present_user: Callable[[str, str, list[str] | None], None] | None = field(
        default=None, repr=False,
    )
    _event: threading.Event = field(default_factory=threading.Event, repr=False)
    _answer: str = field(default="", repr=False)


    def bind_present_user(
        self,
        fn: Callable[[str, str, list[str] | None], None],
    ) -> None:
        self._present_user = fn


    def on_ask_user(
        self,
        kind: str,
        prompt: str,
        options: list[str] | None = None,
    ) -> str:
        self._event.clear()
        self._answer = ""
        if self.on_ui_state:
            self.on_ui_state("WAIT_USER")
        if self._present_user:
            self._present_user(kind, prompt, options)
        elif self.on_log:
            self.on_log("向导", prompt)
        self._event.wait()
        if self.on_ui_state:
            self.on_ui_state("RUNNING")
        return self._answer


    def submit_user(self, answer: str) -> None:
        self._answer = answer
        self._event.set()


class WizardRunner:
    """Fixed-phase TOML wizard orchestrator."""

    def __init__(
        self,
        template_id: str,
        *,
        template_xlsx: Path | None = None,
        profile: str = "cpu",
        no_llm: bool = True,
        skip_google: bool = False,
        resume: bool = False,
        use_browser: bool = True,
        headless: bool = True,
        base_url: str = "http://127.0.0.1:8738/",
        backend: LlmBackend | None = None,
        callbacks: WizardCallbacks | None = None,
    ):
        self.template_id = template_id
        self.template_xlsx = template_xlsx or toml_io.resolve_template_xlsx(template_id)
        self.profile = profile
        self.no_llm = no_llm
        self.skip_google = skip_google
        self.use_browser = use_browser
        self.headless = headless
        self.base_url = base_url
        self.backend = backend
        self.callbacks = callbacks
        self.state = load_state(template_id) if resume else WizardState(template_id=template_id)
        if skip_google:
            self.state.skip_google = True
        ctx_cfg = context_config_for_profile(profile)
        self.context = ContextStore(ctx_cfg)
        self.context.set_system(prompts.WIZARD_SYSTEM)
        self.context.set_task_anchor(f"TOML wizard for template {template_id}")
        self.compressor = Compressor(self.context)
        self._browser: NiceGuiBrowser | None = None


    def _notify_phase(self) -> None:
        if self.callbacks and self.callbacks.on_phase:
            self.callbacks.on_phase(self.state.phase)


    def _emit_log(self, role: str, text: str) -> None:
        if self.callbacks and self.callbacks.on_log:
            self.callbacks.on_log(role, text)


    def _emit_lines(self, lines: list[str], *, role: str = "向导") -> list[str]:
        for line in lines:
            self._emit_log(role, line)
        return lines


    def _wait_user(
        self,
        kind: str,
        prompt: str,
        options: list[str] | None = None,
    ) -> str:
        if self.callbacks:
            return self.callbacks.on_ask_user(kind, prompt, options)
        return ""


    def run(self) -> WizardRunResult:
        messages: list[str] = []
        try:
            while self.state.phase != WizardPhase.DONE.value:
                phase = self.state.phase
                self._notify_phase()
                if phase == WizardPhase.INIT.value:
                    self.state.phase = WizardPhase.PRECHECK.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.PRECHECK.value:
                    messages.extend(self._emit_lines(self._step_precheck()))
                    self.state.phase = WizardPhase.GOOGLE_PROBE.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.GOOGLE_PROBE.value:
                    messages.extend(self._emit_lines(self._step_google_probe()))
                    self.state.phase = WizardPhase.READ_TOML.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.READ_TOML.value:
                    messages.extend(self._emit_lines(self._step_read_toml()))
                    self.state.phase = WizardPhase.COLLECT_PASTE.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.COLLECT_PASTE.value:
                    messages.extend(self._emit_lines(self._step_collect_paste()))
                    if self.no_llm:
                        self.state.phase = WizardPhase.DONE.value
                        messages.append("no-llm: stopped before TOP_LEVEL_QA / FIELD_MAP")
                    else:
                        self.state.phase = WizardPhase.TOP_LEVEL_QA.value
                    save_state(self.state)
                    continue
                if self.no_llm:
                    self.state.phase = WizardPhase.DONE.value
                    save_state(self.state)
                    break
                if phase == WizardPhase.TOP_LEVEL_QA.value:
                    messages.extend(self._emit_lines(self._step_top_level_qa()))
                    self.state.phase = WizardPhase.FIELD_MAP_LOOP.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.FIELD_MAP_LOOP.value:
                    messages.extend(self._emit_lines(self._step_field_map_loop()))
                    self.state.phase = WizardPhase.FINAL_VERIFY.value
                    save_state(self.state)
                    continue
                if phase == WizardPhase.FINAL_VERIFY.value:
                    messages.extend(self._emit_lines(self._step_final_verify()))
                    self.state.phase = WizardPhase.DONE.value
                    save_state(self.state)
                    continue
                messages.append(f"unknown phase {phase}")
                self.state.phase = WizardPhase.DONE.value
                save_state(self.state)
                break
        finally:
            # Headed Edge must stay open across GOOGLE_PROBE / COLLECT_PASTE WAIT_USER.
            if self.state.phase == WizardPhase.DONE.value:
                self._close_browser()
        if self.context.should_compress():
            self.compressor.run()
        return WizardRunResult(state=self.state, messages=messages)


    def _llm_budget_left(self) -> int:
        return prompts.MAX_LLM_CALLS - self.state.llm_calls


    def _current_determiner(self) -> str:
        cfg = load_toml(self.template_id)
        if cfg is None:
            return "\t"
        return cfg.determiner


    def _build_llm_prompt(self) -> str:
        messages = self.context.build_messages()
        return "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)


    def _call_llm(self, user_text: str, *, thinking: bool = False) -> dict[str, Any]:
        if self.backend is None:
            raise RuntimeError("LLM backend not loaded")
        if self._llm_budget_left() <= 0:
            raise RuntimeError("LLM call budget exhausted")
        self.context.append_turn("user", user_text)
        prompt = self._build_llm_prompt()
        result = self.backend.generate(prompt, thinking=thinking, temperature=0.0)
        self.state.llm_calls += 1
        parsed = parse_thinking(result.text)
        action = parse_action(parsed.answer)
        self.context.append_turn("assistant", parsed.answer)
        save_state(self.state)
        return action


    def _dispatch_action(self, action: dict[str, Any]) -> dict[str, Any]:
        out = dispatch(
            action,
            template_id=self.template_id,
            template_xlsx=self.template_xlsx,
            state_paste=self.state.paste_sample,
            determiner=self._current_determiner(),
            browser=self._browser,
            observation_max_chars=self.context.config.tool_observation_max_chars,
        )
        obs = json.dumps(out, ensure_ascii=False)
        self.context.append_tool_observation(obs, tool_name=str(action.get("action", "")))
        return out


    def _record_regex_attempt(self, label: str, action: dict[str, Any], out: dict[str, Any]) -> None:
        entry = {
            "input_label": label,
            "action": action.get("action"),
            "ok": out.get("ok"),
            "error": out.get("error"),
        }
        self.state.regex_attempts.append(entry)
        # Keep last K attempts for compression
        if len(self.state.regex_attempts) > 12:
            self.state.regex_attempts = self.state.regex_attempts[-12:]


    def _open_browser(self) -> NiceGuiBrowser | None:
        if not self.use_browser:
            return None
        if self._browser is not None:
            return self._browser
        try:
            self._browser = NiceGuiBrowser(
                base_url=self.base_url,
                headless=self.headless,
                context_config=self.context.config,
            )
            self._browser.start()
            return self._browser
        except BrowserPlaywrightError as exc:
            self.context.append_tool_observation(f"browser_error: {exc}", tool_name="browser")
            return None


    def _close_browser(self) -> None:
        if self._browser is not None:
            self._browser.stop()
            self._browser = None


    def close_browser_if_open(self) -> None:
        """Release Playwright Edge (wizard finished or user closed dialog)."""
        self._close_browser()


    def _step_precheck(self) -> list[str]:
        report = run_precheck(self.base_url)
        lines = ["[PRECHECK]"]
        if report.node:
            lines.append(f"  node: {report.node}")
        lines.append(f"  playwright: {report.playwright}")
        if report.nicegui_url:
            lines.append(f"  nicegui: HTTP {report.nicegui_url}")
        for issue in report.issues:
            lines.append(f"  note: {issue}")
        if not report.ok:
            lines.append("  WARN: fix Playwright before GOOGLE_PROBE")
        self.context.append_tool_observation("\n".join(lines), tool_name="precheck")
        return lines


    def _step_google_probe(self) -> list[str]:
        lines = ["[GOOGLE_PROBE]"]
        if self.state.skip_google:
            lines.append("  skip_google=true (no Google TOML sources)")
            self.state.user_notes["google"] = "skipped"
            return lines
        browser = self._open_browser()
        if browser is None:
            lines.append("  browser unavailable; use --skip-google or start NiceGUI")
            return lines
        try:
            # Same order as COLLECT_PASTE: open tab → WAIT_USER → snapshot after user acts.
            browser.click_tab("Google 连接")
            if self.callbacks:
                answer = self._wait_user(
                    "choice",
                    "请在 Playwright 打开的 Edge 窗口完成 Google OAuth，然后选择",
                    ["是，已连接 Google Sheet", "否，稍后再连", "跳过 Google 数据源"],
                )
                if answer and "跳过" in answer:
                    self.state.skip_google = True
                    self.state.user_notes["google"] = "skipped"
                    lines.append("  user chose skip Google")
                    return lines
                if answer and "否" in answer:
                    self.state.user_notes["google"] = "not_connected"
                    lines.append("  user deferred Google connection")
                else:
                    self.state.user_notes["google"] = "connected"
                    lines.append("  user confirmed Google connected")
            page_state = browser.probe_google_tab(self.template_id)
            text = format_page_state(page_state)
            self.context.set_browser_state(text)
            hint = page_state.google_connected_hint or "unknown"
            lines.append(f"  google_hint={hint}")
            if not self.callbacks:
                if hint in {"maybe_connected", "connected_no_visible_rows"}:
                    self.state.user_notes["google"] = "connected"
                else:
                    self.state.user_notes["google"] = "not_connected"
                    lines.append("  see docs/connect_google.md for OAuth setup")
                lines.append("  WAIT_USER: confirm Google Sheet connected (yes/no)")
        except Exception as exc:
            lines.append(f"  FAIL: {exc}")
        return lines


    def _step_read_toml(self) -> list[str]:
        payload = toml_io.read_toml_digest(self.template_id, self.template_xlsx)
        lines = ["[READ_TOML]", payload["digest"]]
        if payload.get("errors"):
            lines.append("  verify_errors: " + "; ".join(payload["errors"][:6]))
        self.context.append_tool_observation(payload["digest"], tool_name="read_toml")
        return lines


    def _step_collect_paste(self) -> list[str]:
        lines = ["[COLLECT_PASTE]"]
        browser = self._open_browser()
        if browser is None:
            if self.state.paste_sample:
                lines.append(f"  paste_sample chars={len(self.state.paste_sample)} (from state)")
            else:
                lines.append("  browser unavailable; paste_sample empty")
            return lines
        try:
            browser.click_tab("输入")
            if self.callbacks:
                self._wait_user(
                    "confirm",
                    "请在 Playwright Edge 的「输入」Tab 粘贴样例后点「完成并继续」",
                )
            page_state = browser.collect_input_tab(self.template_id)
            text = format_page_state(page_state)
            self.context.set_browser_state(text)
            ghost = page_state.paste_ghost_value
            if ghost:
                self.state.paste_sample = ghost
            fields = page_state.form_fields
            self.state.form_snapshot = {row["label"]: row["value"] for row in fields}
            lines.append(f"  form_fields={len(fields)} paste_ghost_len={len(ghost)}")
            if fields:
                preview = "; ".join(
                    f"{k}={v!r}" for k, v in list(self.state.form_snapshot.items())[:6]
                )
                lines.append(f"  snapshot: {preview}")
            if not self.callbacks:
                lines.append("  WAIT_USER: paste sample in 输入 tab, then resume wizard")
        except Exception as exc:
            lines.append(f"  FAIL: {exc}")
        return lines


    def _step_top_level_qa(self) -> list[str]:
        payload = toml_io.read_toml_digest(self.template_id, self.template_xlsx)
        lines = ["[TOP_LEVEL_QA]", payload["digest"]]
        if payload.get("verify_ok") and not payload.get("errors"):
            lines.append("  verify ok; skipping LLM top-level patch")
            return lines
        if self.backend is None:
            lines.append("  no backend; skipping LLM")
            return lines
        user_prompt = prompts.top_level_user_prompt(
            payload["digest"],
            skip_google=self.state.skip_google,
        )
        try:
            action = self._call_llm(user_prompt, thinking=False)
        except (RuntimeError, ActionParseError) as exc:
            lines.append(f"  LLM skip: {exc}")
            return lines
        out = self._dispatch_action(action)
        if action.get("action") == "set_top_level":
            lines.append(f"  patch ok={out.get('ok')}")
            if out.get("errors"):
                lines.append("  errors: " + "; ".join(out["errors"][:4]))
        elif action.get("action") == "ask_user":
            question = str(out.get("question", ""))
            kind = str(out.get("kind", "confirm"))
            options = out.get("options")
            option_list = list(options) if isinstance(options, list) else None
            if self.callbacks:
                answer = self._wait_user(kind, question, option_list)
                if answer:
                    self.state.user_notes["last_ask_user"] = answer
            lines.append(f"  WAIT_USER: {question}")
        else:
            lines.append(f"  action={action.get('action')} ok={out.get('ok')}")
        return lines


    def _apply_heuristic_batch(self, labels: list[str]) -> list[str]:
        cfg = load_toml(self.template_id)
        if cfg is None:
            return []
        lines: list[str] = []
        determiner = cfg.determiner
        for label in labels:
            updates = toml_io.heuristic_field_index(
                label,
                self.state.paste_sample,
                self.state.form_snapshot,
                determiner,
            )
            if updates is None:
                continue
            out = toml_io.apply_patch(
                self.template_id,
                field_label=label,
                field_updates=updates,
                template_xlsx=self.template_xlsx,
            )
            if out.get("ok"):
                lines.append(f"  heuristic {label} index={updates['index']}")
        return lines


    def _step_field_map_loop(self) -> list[str]:
        cfg = load_toml(self.template_id)
        if cfg is None:
            return ["[FIELD_MAP_LOOP] cannot load cfg"]
        lines = [f"[FIELD_MAP_LOOP] llm_calls={self.state.llm_calls}"]
        loops = 0
        while loops < 20:
            loops += 1
            cfg = load_toml(self.template_id)
            if cfg is None:
                break
            pending = toml_io.pending_field_labels(cfg)
            if not pending:
                lines.append("  all fields mapped")
                break
            batch = pending[: prompts.FIELD_BATCH_SIZE]
            lines.append(f"  pending={len(pending)} batch={batch}")
            lines.extend(self._apply_heuristic_batch(batch))
            cfg = load_toml(self.template_id)
            if cfg is None:
                break
            pending = toml_io.pending_field_labels(cfg)
            still_need = [label for label in batch if label in pending]
            if not still_need:
                self.state.field_map_cursor += len(batch)
                save_state(self.state)
                continue
            if self.backend is None or self._llm_budget_left() <= 0:
                lines.append(f"  unmapped remain: {still_need}")
                break
            digest_payload = toml_io.read_toml_digest(self.template_id, self.template_xlsx)
            retry_note = ""
            mapped_in_batch = False
            for attempt in range(prompts.MAX_FIELD_RETRIES):
                if self._llm_budget_left() <= 0:
                    break
                user_prompt = prompts.field_map_user_prompt(
                    digest_payload["digest"],
                    still_need,
                    cfg=cfg,
                    paste_sample=self.state.paste_sample,
                    form_snapshot=self.state.form_snapshot,
                    determiner=cfg.determiner,
                    retry_note=retry_note,
                )
                try:
                    action = self._call_llm(user_prompt, thinking=True)
                except (RuntimeError, ActionParseError) as exc:
                    lines.append(f"  LLM error: {exc}")
                    break
                out = self._dispatch_action(action)
                action_name = str(action.get("action", ""))
                label = str(action.get("input_label", still_need[0]))
                if action_name in {"test_regex", "test_paste_split", "test_source_row"}:
                    self._record_regex_attempt(label, action, out)
                    retry_note = prompts.tool_retry_prompt(out)
                    if out.get("ok"):
                        retry_note = f"tool ok: {json.dumps(out, ensure_ascii=False)[:200]}"
                    continue
                if action_name == "patch_field":
                    self._record_regex_attempt(label, action, out)
                    if out.get("ok"):
                        mapped_in_batch = True
                        lines.append(f"  patched {label} ok=True")
                        break
                    retry_note = prompts.tool_retry_prompt(out)
                    continue
                if action_name == "ask_user":
                    question = str(out.get("question", ""))
                    kind = str(out.get("kind", "confirm"))
                    options = out.get("options")
                    option_list = list(options) if isinstance(options, list) else None
                    if self.callbacks:
                        answer = self._wait_user(kind, question, option_list)
                        if answer:
                            self.state.user_notes["last_ask_user"] = answer
                    lines.append(f"  WAIT_USER: {question}")
                    break
                retry_note = f"unexpected action {action_name}"
            self.state.field_map_cursor += len(batch)
            save_state(self.state)
            if not mapped_in_batch:
                lines.append(f"  batch incomplete: {still_need}")
                break
        cfg = load_toml(self.template_id)
        if cfg is not None:
            remaining = len(toml_io.pending_field_labels(cfg))
            lines.append(f"  remaining_unmapped={remaining} llm_calls={self.state.llm_calls}")
        return lines


    def _step_final_verify(self) -> list[str]:
        payload = toml_io.read_toml_digest(self.template_id, self.template_xlsx)
        lines = ["[FINAL_VERIFY]", payload["digest"]]
        ok = payload.get("verify_ok")
        lines.append(f"  verify_ok={ok} llm_calls={self.state.llm_calls}")
        if payload.get("errors"):
            lines.append("  errors: " + "; ".join(payload["errors"][:8]))
        return lines
