"""LiteRtBackend: long-lived Engine + Conversation-per-call `generate()`.

Real API facts this file relies on (verified 2026-07-11 against `litert-lm`
0.14.0 + gemma-4-E4B-it.litertlm, see docs/embed_gemma4.md ?1.3/?3.1/?3.2.1/?3.6.1a):
  - `Engine(model_path, backend=Backend.CPU()|Backend.GPU()|Backend.NPU())` is the
    long-lived handle; which concrete `Backend` to pass is resolved by
    `runtime/hardware_probe.py`'s NPU -> GPU -> CPU cascade, not hardcoded here.
  - `thinking`/`temperature` are conversation-level (`create_conversation(extra_context=...,
    sampler_config=...)`), not per-message.
  - constrained judgment output goes through a synthetic tool + `enable_constrained_decoding=True`,
    not a raw json_schema kwarg.
  - a truncated response looks identical to a complete one (no finish_reason); the
    constrained-decoding path needs >=200 max_output_tokens or the tool call never parses.
"""

from __future__ import annotations

import inspect
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from llm_gemma4 import config, hf_download
from llm_gemma4.backends.base import GenerateResult, HealthReport, JudgmentToolSpec, LlmSession
from llm_gemma4.runtime import hardware_probe
from llm_gemma4.runtime.thinking import split_thought_answer

if TYPE_CHECKING:
    import litert_lm as lm


# Self-determined output-token budget when a caller passes max_tokens=None
# (docs/embed_gemma4.md ?3.1a/?1.2): GPU decodes ~9x faster than CPU (?1.1
# breakeven test), so it can afford a larger default reply length for the
# same wall-clock cost. Reused from the existing cpu/cuda/openvino profile
# thinking_budget numbers rather than inventing a new table.
_DEFAULT_MAX_TOKENS_BY_BACKEND = {"cpu": 512, "gpu": 1024, "npu": 512}
_DEFAULT_MAX_TOKENS_FALLBACK = 512


class LiteRtBackend:
    def __init__(
        self,
        profile: str,
        pending_download: "Future[tuple[bool, str]] | None" = None,
        *,
        enable_vision: bool = False,
    ) -> None:
        self._profile = profile
        self._pending_download = pending_download
        self._enable_vision = enable_vision
        self._engine: "lm.Engine | None" = None
        self._engine_lock = threading.Lock()
        self._backend_label: str | None = None
        self._sessions: dict[str, Any] = {}

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool: JudgmentToolSpec | None = None,
    ) -> GenerateResult:
        import litert_lm as lm
        engine = self._ensure_engine()  # populates self._backend_label as a side effect
        system_message, user_message = _split_system_user(messages)
        create_kwargs: dict[str, Any] = {
            "system_message": system_message,
            "sampler_config": lm.SamplerConfig(temperature=temperature),
            "extra_context": {"enable_thinking": True} if thinking else None,
        }
        if max_tokens is not None:
            budget = max_tokens
        else:
            # Caller left it unset -> self-determine from the realized hardware,
            # not the machine this code happened to be written on (user ask).
            budget = _DEFAULT_MAX_TOKENS_BY_BACKEND.get(self._backend_label, _DEFAULT_MAX_TOKENS_FALLBACK)
        if judgment_tool is not None:
            create_kwargs["tools"] = [_build_judgment_tool_function(judgment_tool)]
            create_kwargs["automatic_tool_calling"] = False
            create_kwargs["enable_constrained_decoding"] = True
            # ?3.6.1a: below this the tool call itself gets truncated mid-generation.
            budget = max(budget, config.CONSTRAINED_DECODING_MIN_TOKENS)
        conversation = engine.create_conversation(**create_kwargs)
        try:
            response = conversation.send_message(user_message, max_output_tokens=budget)
        finally:
            conversation.close()
        return _to_generate_result(response)

    def generate_vision(
        self,
        image: "str | Path | bytes",
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerateResult:
        """Stateless single call with an image attached; only meaningful when
        this instance was built with `enable_vision=True` (?3.1d) -- otherwise
        `Engine.create_conversation` still accepts the multimodal message, but
        `litert_lm` raises inside `send_message` because no vision_backend was
        ever set on the underlying Engine."""
        import litert_lm as lm
        engine = self._ensure_engine()
        image_content = (
            lm.Content.ImageBytes(image)
            if isinstance(image, bytes)
            else lm.Content.ImageFile(str(Path(image).resolve()))
        )
        multimodal_input = lm.Contents.of(image_content, prompt)
        create_kwargs: dict[str, Any] = {
            "system_message": system,
            "sampler_config": lm.SamplerConfig(temperature=temperature),
        }
        if max_tokens is not None:
            budget = max_tokens
        else:
            budget = _DEFAULT_MAX_TOKENS_BY_BACKEND.get(self._backend_label, _DEFAULT_MAX_TOKENS_FALLBACK)
        conversation = engine.create_conversation(**create_kwargs)
        try:
            response = conversation.send_message(multimodal_input, max_output_tokens=budget)
        finally:
            conversation.close()
        return _to_generate_result(response)

    def open_session(self, session_id: str) -> LlmSession:
        from llm_gemma4.backends.litert.session import LiteRtSession
        if session_id not in self._sessions:
            conversation = self._ensure_engine().create_conversation()
            self._sessions[session_id] = LiteRtSession(conversation)
        return self._sessions[session_id]

    def warm(self) -> None:
        self._ensure_engine()

    def count_tokens(self, text: str) -> int:
        # No standalone tokenizer call confirmed in litert_lm 0.14.0 (?4.2); this
        # estimate is only used before a Conversation exists to query token_count.
        return max(1, len(text) // 3)

    def health_check(self) -> HealthReport:
        ready = config.model_exists()
        # Once an Engine has actually been built, report what it really landed
        # on; before that, only the cheap NPU probe is safe to run (? hardware_probe).
        litert_backend = self._backend_label or hardware_probe.planned_backend_hint(self._profile)
        return HealthReport(
            ok=ready,
            profile=self._profile,
            litert_backend=litert_backend,
            mtp=False,
            model_path=str(config.model_path()),
            message="ready" if ready else config.MSG_MODEL_MISSING,
        )

    def close(self) -> None:
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        if self._engine is not None:
            self._engine.close()
            self._engine = None

    def _ensure_engine(self) -> "lm.Engine":
        # Blocks here, on first real use, on any in-flight async download ÿÿÿ
        # construction (`__init__`) itself never blocks (see hf_download.py).
        if self._engine is not None:
            return self._engine
        with self._engine_lock:
            if self._engine is not None:
                return self._engine
            ok, message = hf_download.wait_for_model(self._pending_download)
            if not ok:
                raise RuntimeError(f"{config.MSG_DOWNLOAD_FAILED} ({message})")
            self._engine, self._backend_label = hardware_probe.build_engine(
                str(config.model_path()), self._profile, enable_vision=self._enable_vision
            )
            return self._engine


def _split_system_user(messages: Sequence[Mapping[str, Any]]) -> tuple[str | None, str]:
    """`send_message` takes one message; fold the list into system + single user turn."""
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    user_parts = [m["content"] for m in messages if m.get("role") != "system"]
    system_message = "\n".join(system_parts) if system_parts else None
    return system_message, "\n".join(user_parts)


def _to_generate_result(response: Mapping[str, Any]) -> GenerateResult:
    tool_calls = response.get("tool_calls")
    if tool_calls:
        return GenerateResult(text="", tool_call_arguments=tool_calls[0]["function"]["arguments"], raw=response)
    thought, answer = split_thought_answer(response)
    return GenerateResult(text=answer, thought=thought, raw=response)


def _build_judgment_tool_function(spec: JudgmentToolSpec):
    """Synthesize a callable whose signature litert_lm's `_FunctionTool` (tools.py)
    turns into the OpenAPI schema for constrained decoding (?3.6.1a)."""
    def _tool(**_kwargs: Any) -> None:
        return None
    parameters = [
        inspect.Parameter(spec.verdict_key, inspect.Parameter.KEYWORD_ONLY, annotation=bool),
        inspect.Parameter(spec.reason_key, inspect.Parameter.KEYWORD_ONLY, annotation=str),
    ]
    _tool.__signature__ = inspect.Signature(parameters=parameters)
    _tool.__name__ = spec.name
    _tool.__doc__ = spec.description
    return _tool
