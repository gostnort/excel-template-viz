"""OpenVINO GenAI backend (profile openvino)."""

from __future__ import annotations

import time
from pathlib import Path

from llm_gemma4.backends.base import GenerateResult
from llm_gemma4.config import load_profile
from llm_gemma4.hf_download import openvino_present
from llm_gemma4.models_catalog import OV_INT4_DIR, repo_root
from llm_gemma4.runtime.thinking import parse_thinking


class OpenVinoBackend:
    """Load OpenVINO IR via openvino-genai when available."""

    def __init__(self, profile_name: str = "openvino"):
        self.profile = profile_name
        self._cfg = load_profile(profile_name)
        self._pipe = None


    def health_check(self) -> str:
        path = self._resolved_model_dir()
        return f"profile={self.profile} openvino device={self._cfg.device} model_dir={path.name}"


    def _resolved_model_dir(self) -> Path:
        rel = self._cfg.model_dir or "models/gemma4-openvino-int4"
        path = (repo_root() / rel).resolve()
        if not path.is_dir() or not openvino_present():
            raise FileNotFoundError(
                f"OpenVINO model not found under {path}. "
                "Run: python -m llm_gemma4 download --profile openvino"
            )
        return path


    def _ensure_loaded(self) -> None:
        if self._pipe is not None:
            return
        try:
            import openvino_genai as ov_genai
        except ImportError as exc:
            raise ImportError(
                "openvino-genai not installed. "
                "See llm_gemma4/backends/openvino/requirements.txt"
            ) from exc
        model_dir = self._resolved_model_dir()
        device = self._cfg.device
        try:
            self._pipe = ov_genai.LLMPipeline(str(model_dir), device)
        except Exception as exc:
            if self._cfg.allow_cpu_fallback and device.upper() != "CPU":
                self._pipe = ov_genai.LLMPipeline(str(model_dir), "CPU")
                return
            raise RuntimeError(f"OpenVINO LLMPipeline failed on {device}: {exc}") from exc


    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        thinking: bool = False,
    ) -> GenerateResult:
        self._ensure_loaded()
        cap = max_tokens
        if thinking and cap < self._cfg.thinking_budget:
            cap = self._cfg.thinking_budget
        config = self._pipe.get_generation_config()
        config.max_new_tokens = cap
        config.temperature = temperature if temperature > 0 else 0.0
        raw = self._pipe.generate(prompt, config)
        parsed = parse_thinking(str(raw))
        return GenerateResult(
            text=parsed.answer,
            thought=parsed.thought,
            completion_tokens=None,
            finish_reason=None,
        )


def smoke_generate(prompt: str = "Reply with one word: OK") -> dict:
    """Load OV model, generate once, return timing stats."""
    backend = OpenVinoBackend()
    print(backend.health_check())
    started = time.perf_counter()
    result = backend.generate(prompt, max_tokens=32, temperature=0.0)
    elapsed = time.perf_counter() - started
    print(f"answer={result.text!r} elapsed={elapsed:.2f}s")
    return {"answer": result.text, "elapsed_s": elapsed}
