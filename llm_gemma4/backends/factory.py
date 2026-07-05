"""Map profile name to LlmBackend implementation."""

from __future__ import annotations

from llm_gemma4.backends.base import LlmBackend
from llm_gemma4.backends.llamacpp.backend import LlamaCppBackend
from llm_gemma4.backends.openvino.backend import OpenVinoBackend


def create_backend(profile: str) -> LlmBackend:
    """Return backend for cpu, cuda, or openvino."""
    name = profile.strip().lower()
    if name in {"cpu", "cuda"}:
        return LlamaCppBackend(name)
    if name == "openvino":
        return OpenVinoBackend(name)
    raise ValueError(f"Unknown profile: {profile}")
