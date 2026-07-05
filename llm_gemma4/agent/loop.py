"""General chat ReAct loop (embed_gemma4.md §6.1, Phase 5)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_gemma4.agent.compressor import Compressor
from llm_gemma4.agent.context_config import context_config_for_profile
from llm_gemma4.agent.context_store import ContextStore
from llm_gemma4.agent import prompts
from llm_gemma4.backends.base import LlmBackend
from llm_gemma4.backends.factory import create_backend
from llm_gemma4.runtime.hardware_probe import choose_profile, detect
from llm_gemma4.runtime.thinking import parse_thinking
from llm_gemma4.tools.browser_playwright import BrowserPlaywrightError, NiceGuiBrowser
from llm_gemma4.tools import file_config
from llm_gemma4.wizard.action_parser import ActionParseError, parse_action
from llm_gemma4.wizard import toml_io
from llm_gemma4.wizard.tools import dispatch as wizard_dispatch


MAX_STEPS = 8
STALL_THRESHOLD = 3


@dataclass
class ChatRunResult:
    answer: str
    steps: int
    messages: list[str]


class AgentLoop:
    """ReAct loop for short chat tasks."""

    def __init__(
        self,
        backend: LlmBackend,
        *,
        task: str,
        template_id: str | None = None,
        template_xlsx: Path | None = None,
        use_browser: bool = True,
        headless: bool = True,
        base_url: str = "http://127.0.0.1:8738/",
    ):
        self.backend = backend
        self.task = task.strip()
        self.template_id = template_id
        self.template_xlsx = template_xlsx
        self.use_browser = use_browser
        self.headless = headless
        self.base_url = base_url
        ctx_cfg = context_config_for_profile(backend.profile)
        self.context = ContextStore(ctx_cfg)
        self.context.set_system(prompts.CHAT_SYSTEM)
        self.context.set_task_anchor(self.task)
        self.compressor = Compressor(self.context)
        self._browser: NiceGuiBrowser | None = None
        self._stall_count = 0
        self._last_snapshot = ""


    def run(self) -> ChatRunResult:
        messages: list[str] = []
        answer = ""
        steps = 0
        try:
            for step in range(1, MAX_STEPS + 1):
                steps = step
                self._maybe_compress()
                if self.context.estimate_tokens() > int(self.context.config.n_ctx * 0.9):
                    self.compressor.emergency_trim()
                prompt = self._build_prompt()
                thinking = backend_thinking_enabled(self.backend.profile)
                result = self.backend.generate(prompt, thinking=thinking, temperature=0.0)
                parsed = parse_thinking(result.text)
                self.context.append_turn("assistant", parsed.answer)
                try:
                    action = parse_action(parsed.answer)
                except ActionParseError:
                    answer = parsed.answer
                    messages.append(f"[step {step}] final answer")
                    break
                action_name = str(action.get("action", "")).strip()
                if action_name in {"finish", "done"}:
                    answer = str(action.get("message") or parsed.answer)
                    messages.append(f"[step {step}] finish")
                    break
                obs = self._dispatch(action)
                obs_text = json.dumps(obs, ensure_ascii=False)
                self.context.append_tool_observation(obs_text, tool_name=action_name)
                messages.append(f"[step {step}] {action_name} -> ok={obs.get('ok', True)}")
                self._track_stall(action_name, obs)
                if result.finish_reason == "length":
                    self.compressor.run()
            else:
                answer = "max steps reached without finish"
                messages.append("[loop] max_steps exhausted")
        finally:
            self._close_browser()
        if not answer:
            answer = "no answer produced"
        return ChatRunResult(answer=answer, steps=steps, messages=messages)


    def _build_prompt(self) -> str:
        messages = self.context.build_messages()
        return "\n\n".join(f"{item['role']}: {item['content']}" for item in messages)


    def _maybe_compress(self) -> None:
        if self.context.should_compress() or self._stall_count >= STALL_THRESHOLD:
            self.compressor.run()
            self._stall_count = 0


    def _track_stall(self, action_name: str, obs: dict[str, Any]) -> None:
        progressed = bool(obs.get("ok", True))
        if action_name == "browser_snapshot":
            page_state = str(obs.get("page_state", ""))
            if page_state and page_state == self._last_snapshot:
                progressed = False
            else:
                self._last_snapshot = page_state
                if page_state:
                    self.context.set_browser_state(page_state)
        if progressed:
            self._stall_count = 0
        else:
            self._stall_count += 1


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
        except BrowserPlaywrightError as exc:
            return None
        return self._browser


    def _close_browser(self) -> None:
        if self._browser is not None:
            self._browser.stop()
            self._browser = None


    def _dispatch(self, action: dict[str, Any]) -> dict[str, Any]:
        name = str(action.get("action", "")).strip()
        max_chars = self.context.config.tool_observation_max_chars
        if name in {"browser_snapshot", "browser_click"}:
            browser = self._open_browser()
            if browser is None:
                return {"ok": False, "error": "browser unavailable (install playwright?)"}
            return wizard_dispatch(
                action,
                template_id=self.template_id or "",
                template_xlsx=self.template_xlsx,
                browser=browser,
                observation_max_chars=max_chars,
            )
        if name == "read_file":
            return file_config.read_file(
                str(action.get("path", "")),
                max_chars=max_chars,
            )
        if name == "list_files":
            return file_config.list_files(str(action.get("path", ".")))
        if name == "read_toml":
            tid = str(action.get("template_id") or self.template_id or "").strip()
            if not tid:
                return {"ok": False, "error": "template_id required"}
            out = toml_io.read_toml_digest(tid, self.template_xlsx)
            text = json.dumps(out, ensure_ascii=False)
            if len(text) > max_chars:
                out = dict(out)
                out["_truncated"] = True
            return out
        return {"ok": False, "error": f"unknown chat action: {name}"}


def backend_thinking_enabled(profile: str) -> bool:
    """openvino/cpu use thinking_budget=512 per platform spec."""
    return profile.strip().lower() in {"openvino", "cpu", "cuda"}


def run_chat(
    task: str,
    *,
    profile: str | None = None,
    template_id: str | None = None,
    template_xlsx: Path | None = None,
    interactive_profile: bool = True,
    use_browser: bool = True,
    headless: bool = True,
    base_url: str = "http://127.0.0.1:8738/",
    backend: LlmBackend | None = None,
) -> int:
    """CLI entry: probe, pick profile, run AgentLoop."""
    report = detect()
    if profile is None:
        profile = os.environ.get("LLM_PROFILE")
    chosen = choose_profile(report, profile, interactive=interactive_profile)
    print(f"[chat] profile={chosen}")
    active_backend = backend or create_backend(chosen)
    print(active_backend.health_check())
    loop = AgentLoop(
        active_backend,
        task=task,
        template_id=template_id,
        template_xlsx=template_xlsx,
        use_browser=use_browser,
        headless=headless,
        base_url=base_url,
    )
    result = loop.run()
    for line in result.messages:
        print(line)
    print(f"[chat] steps={result.steps} tokens~={loop.context.estimate_tokens()}")
    print(result.answer)
    return 0
