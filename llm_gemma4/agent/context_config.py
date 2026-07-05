"""Context compression limits per inference profile."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextConfig:
    n_ctx: int = 8192
    recent_turns_k: int = 3
    compress_trigger_ratio: float = 0.65
    dom_excerpt_max_chars: int = 6000
    browser_observation_max_chars: int = 8000
    tool_observation_max_chars: int = 2000
    interactive_refs_max: int = 40


def context_config_for_profile(profile: str) -> ContextConfig:
    name = profile.strip().lower()
    if name == "cuda":
        return ContextConfig(
            recent_turns_k=4,
            compress_trigger_ratio=0.75,
            dom_excerpt_max_chars=8000,
            browser_observation_max_chars=10000,
        )
    return ContextConfig(
        recent_turns_k=3,
        compress_trigger_ratio=0.65,
        dom_excerpt_max_chars=6000,
        browser_observation_max_chars=8000,
    )
