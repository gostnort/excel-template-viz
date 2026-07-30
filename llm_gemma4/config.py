"""Runtime defaults for the llm_gemma4 platform. See docs/embed_gemma4.md."""

from __future__ import annotations

import os
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PLATFORM_ROOT.parent
MODELS_DIR = PROJECT_ROOT / "models" / "gemma4"
PROFILES_DIR = PLATFORM_ROOT / "profiles"
INSTALL_LOG = PROJECT_ROOT / "temp" / "install_llm_gemma4.log"

HF_REPO_ID = "litert-community/gemma-4-E4B-it-litert-lm"
MODEL_FILENAME = "gemma-4-E4B-it.litertlm"

PROFILE_ENV = "LLM_PROFILE"
# "auto" runs the NPU -> GPU -> CPU cascade in runtime/hardware_probe.py; the
# other three force one specific Backend (docs/embed_gemma4.md §1.3, step 5
# now defers to that cascade instead of the old "exactly one match" rule).
KNOWN_PROFILES = ("auto", "cpu", "cuda", "openvino")
DEFAULT_PROFILE = "auto"

# Constrained-decoding tool-call path needs headroom the plain-text path does not
# (docs/embed_gemma4.md §3.6.1a: 96 tokens truncates mid tool-call, 200 is stable).
CONSTRAINED_DECODING_MIN_TOKENS = 200

MSG_MODEL_MISSING = "Gemma 4 模型未就绪，正在后台下载（首次约 3.66GB），请稍后重试。"
MSG_DOWNLOAD_FAILED = "Gemma 4 模型下载失败，请检查网络后重试。"

_THINKING_BUDGET_BY_BACKEND = {"cpu": 512, "gpu": 1024, "npu": 512}
_THINKING_BUDGET_FALLBACK = 512



def default_output_tokens_for_backend(litert_backend: str | None) -> int:
    """
    函数名: default_output_tokens_for_backend
    作用: 按已探测 litert backend 返回默认 max_output_tokens（generate / thinking 回退）
    输入:
        litert_backend (str | None): gpu / cpu / npu 等标签
    输出:
        int: 默认输出 token 预算
    """
    backend_key = (litert_backend or "").strip().lower()
    return _THINKING_BUDGET_BY_BACKEND.get(backend_key, _THINKING_BUDGET_FALLBACK)


def model_path() -> Path:
    return MODELS_DIR / MODEL_FILENAME


def model_exists() -> bool:
    return model_path().is_file()


def resolve_profile(explicit: str | None = None) -> str:
    """Priority per §1.3, steps 1-2 (explicit arg, env var); falls through to
    DEFAULT_PROFILE ("auto") when neither is given, which runtime.hardware_probe
    resolves into a concrete Backend at Engine-construction time. Reading
    profiles/*.toml for MTP/thinking-budget tuning (step 3) and the CLI menu
    (step 4) are not implemented yet."""
    if explicit and explicit in KNOWN_PROFILES:
        return explicit
    from_env = os.environ.get(PROFILE_ENV, "").strip().lower()
    if from_env in KNOWN_PROFILES:
        return from_env
    return DEFAULT_PROFILE


def load_thinking_budget(profile: str | None = None, *, litert_backend: str | None = None) -> int:
    """
    函数名: load_thinking_budget
    作用: 从 profile TOML 读取 thinking_budget；缺失时按 litert_backend 回退
    输入:
        profile (str | None): 显式 profile，None 时走 resolve_profile()
        litert_backend (str | None): 已探测的 backend 标签（gpu/cpu/npu）
    输出:
        int: thinking 场景 max_output_tokens 预算
    """
    resolved = resolve_profile(profile)
    profile_file = PROFILES_DIR / f"{resolved}.toml"
    if resolved != "auto" and profile_file.is_file():
        try:
            import tomllib
            data = tomllib.loads(profile_file.read_text(encoding="utf-8"))
            budget = data.get("thinking_budget")
            if isinstance(budget, int) and budget > 0:
                return budget
        except Exception:
            pass
    return default_output_tokens_for_backend(litert_backend)
