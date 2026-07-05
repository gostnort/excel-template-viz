"""llama.cpp backend for profiles cpu and cuda."""

from __future__ import annotations

import time
from pathlib import Path

from llm_gemma4.backends.base import GenerateResult
from llm_gemma4.config import load_profile
from llm_gemma4.hf_download import gguf_present, gguf_weight_path
from llm_gemma4.models_catalog import repo_root
from llm_gemma4.runtime.thinking import parse_thinking


class LlamaCppBackend:
    """Load GGUF via llama-cpp-python."""

    def __init__(self, profile_name: str):
        self.profile = profile_name
        self._cfg = load_profile(profile_name)
        self._llama = None


    def health_check(self) -> str:
        path = self._resolved_gguf()
        layers = self._cfg.n_gpu_layers
        device = "cuda" if layers != 0 else "CPU"
        return f"profile={self.profile} llama.cpp device={device} model={path.name}"


    def _resolved_gguf(self) -> Path:
        rel = self._cfg.model_path or "models/gemma4/gemma-4-E4B_q4_0-it.gguf"
        path = (repo_root() / rel).resolve()
        if not path.is_file():
            if gguf_present():
                return gguf_weight_path().resolve()
            raise FileNotFoundError(
                f"GGUF not found: {path}. "
                f"Run: python -m llm_gemma4 download --profile {self.profile}"
            )
        return path


    def _ensure_loaded(self) -> None:
        if self._llama is not None:
            return
        if self.profile == "cuda":
            from llm_gemma4.backends.llamacpp.cuda_env import prepare_cuda_runtime
            prepare_cuda_runtime()
        from llama_cpp import Llama
        gguf = self._resolved_gguf()
        self._llama = Llama(
            model_path=str(gguf),
            n_ctx=self._cfg.n_ctx,
            n_gpu_layers=self._cfg.n_gpu_layers,
            verbose=False,
        )


    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        thinking: bool = False,
    ) -> GenerateResult:
        self._ensure_loaded()
        user = prompt
        if thinking:
            user = f"{prompt}\n\nUse step-by-step reasoning in a thought channel if needed."
        messages = [{"role": "user", "content": user}]
        temp = temperature if temperature > 0 else 0.0
        cap = max_tokens
        if thinking and cap < self._cfg.thinking_budget:
            cap = self._cfg.thinking_budget
        response = self._llama.create_chat_completion(
            messages=messages,
            max_tokens=cap,
            temperature=temp,
        )
        choice = response["choices"][0]
        message = choice.get("message") or {}
        raw = str(message.get("content") or "")
        parsed = parse_thinking(raw)
        usage = response.get("usage") or {}
        return GenerateResult(
            text=parsed.answer,
            thought=parsed.thought,
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=str(choice.get("finish_reason") or ""),
        )


def smoke_generate(profile: str, prompt: str = "Reply with one word: OK") -> dict:
    """Load model, generate once, return timing stats."""
    backend = LlamaCppBackend(profile)
    print(backend.health_check())
    started = time.perf_counter()
    result = backend.generate(prompt, max_tokens=32, temperature=0.0)
    elapsed = time.perf_counter() - started
    tokens = result.completion_tokens or 0
    tps = (tokens / elapsed) if elapsed > 0 and tokens else 0.0
    print(f"answer={result.text!r} tokens={tokens} elapsed={elapsed:.2f}s tok/s={tps:.2f}")
    return {
        "answer": result.text,
        "elapsed_s": elapsed,
        "completion_tokens": tokens,
        "tok_per_s": tps,
    }
