"""create_backend(profile) -> LlmBackend (docs/embed_gemma4.md §3.2)."""

from __future__ import annotations

from llm_gemma4 import config, hf_download
from llm_gemma4.backends.base import LlmBackend


def create_backend(profile: str | None = None, *, enable_vision: bool = False) -> LlmBackend:
    resolved = config.resolve_profile(profile)
    # Non-blocking: kicks a background download if the weight is missing; the
    # backend only awaits it lazily on first real generate()/open_session() call.
    pending = hf_download.ensure_model_async()
    from llm_gemma4.backends.litert.backend import LiteRtBackend
    return LiteRtBackend(profile=resolved, pending_download=pending, enable_vision=enable_vision)
