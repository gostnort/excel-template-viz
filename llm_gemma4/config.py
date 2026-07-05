"""Load profile TOML from llm_gemma4/profiles/."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomlkit


_PROFILES_DIR = Path(__file__).resolve().parent / "profiles"


@dataclass(frozen=True)
class ProfileConfig:
    profile: str
    model_path: str | None = None
    model_dir: str | None = None
    n_ctx: int = 8192
    n_gpu_layers: int = 0
    device: str = "GPU"
    thinking_budget: int = 512
    temperature: float = 0.0
    compress_model_summary: bool = False
    allow_cpu_fallback: bool = False
    raw: dict | None = None


def profiles_dir() -> Path:
    return _PROFILES_DIR


def load_profile(name: str) -> ProfileConfig:
    """Load profiles/{name}.toml."""
    path = _PROFILES_DIR / f"{name}.toml"
    if not path.is_file():
        raise FileNotFoundError(f"Profile not found: {path}")
    data = tomlkit.parse(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid profile TOML: {path}")
    return ProfileConfig(
        profile=str(data.get("profile", name)),
        model_path=_optional_str(data.get("model_path")),
        model_dir=_optional_str(data.get("model_dir")),
        n_ctx=int(data.get("n_ctx", 8192)),
        n_gpu_layers=int(data.get("n_gpu_layers", 0)),
        device=str(data.get("device", "GPU")),
        thinking_budget=int(data.get("thinking_budget", 512)),
        temperature=float(data.get("temperature", 0.0)),
        compress_model_summary=bool(data.get("compress_model_summary", False)),
        allow_cpu_fallback=bool(data.get("allow_cpu_fallback", False)),
        raw=dict(data),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
