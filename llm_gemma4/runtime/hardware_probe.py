"""Auto-detect the fastest usable LiteRT-LM hardware backend (docs §1.1/§1.3).

Real facts this relies on (verified 2026-07-11 against `litert-lm` 0.14.0 on a
Windows machine with an NVIDIA RTX 4070, see docs/embed_gemma4.md §1.3):
  - `Backend.NPU()` with no explicit `litert_dispatch_lib_dir` auto-probes Intel
    OpenVINO's NPU plugin (`import openvino; "NPU" in ov.Core().available_devices`)
    ONLY on `sys.platform == "win32"`; it *raises* `RuntimeError` at construction
    time when unavailable (no `openvino` package, or no NPU device), so trying
    to construct it IS the probe -- no separate capability query exists.
  - `Backend.GPU()` never raises at construction (zero args, zero validation).
    The real probe only happens inside `Engine(model_path, backend=...)`, which
    drives a cross-vendor WebGPU delegate (Direct3D 12 on Windows, Vulkan on
    Linux/Android, Metal on macOS). One `GPU()` class covers NVIDIA/AMD/Qualcomm
    alike; there is no separate "CUDA" backend class and no ONNX or OpenVINO-IR
    inference path anywhere in litert_lm -- those are not concepts this runtime
    has, unlike the llama.cpp/OpenVINO-GenAI stack this project moved away from.
  - GPU cold start pays a one-time shader-compile cost (~10-12s on the RTX 4070
    test machine) on top of the model mmap; CPU load is ~0.4s. Decode throughput
    is still faster on GPU once warm. This cost is why the cascade below is only
    run once per process (the caller, LiteRtBackend, caches the resulting Engine).
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import litert_lm as lm


_log = logging.getLogger(__name__)

# Explicit profile -> forced backend label; "auto" (or anything unrecognized)
# instead runs the NPU -> GPU -> CPU cascade in build_engine().
FORCED_BACKEND_BY_PROFILE = {"cpu": "cpu", "cuda": "gpu", "openvino": "gpu"}

# litert_lm's native C++ layer writes directly to the process's stderr fd
# (absl/glog-based logging, bypasses Python's own logging module entirely).
# Every real caller so far -- CLI, another service embedding llm_gemma4 --
# only wants the plain-text answer, not thousands of lines of accelerator
# registration/shader-compile chatter (user ask: "another service is
# difficult to read this shit"). Set LLM_GEMMA4_VERBOSE=1 to opt back in
# (e.g. while debugging a GPU/NPU backend selection issue).
_VERBOSE_ENV = "LLM_GEMMA4_VERBOSE"
_native_logging_silenced = False



def _silence_native_logs(lm_module) -> None:
    """Calls litert_lm.set_min_log_severity(ERROR) exactly once per process,
    before the first Backend()/Engine() construction -- silencing has to
    happen before those calls, not after, or the noisy lines already fired."""
    global _native_logging_silenced
    if _native_logging_silenced or os.environ.get(_VERBOSE_ENV, "").strip() == "1":
        return
    lm_module.set_min_log_severity(lm_module.LogSeverity.ERROR)
    _native_logging_silenced = True



def _openvino_npu_device_names() -> list[str]:
    """
    函数名: _openvino_npu_device_names
    作用: 通过 OpenVINO 枚举 NPU 设备名（Windows / Linux 通用，需已装驱动与 openvino）
    输入: 无
    输出:
        list[str]: 可用 NPU 设备标识列表，无 openvino 或无 NPU 时为空
    """
    try:
        import openvino as ov
        devices = ov.Core().available_devices()
        return [d for d in devices if str(d).upper().startswith("NPU")]
    except ImportError:
        return []
    except Exception:
        return []


def _probe_npu_exists() -> bool:
    """
    函数名: _probe_npu_exists
    作用: 轻量探测是否存在 Intel NPU（不构造 litert_lm Engine）
    输入: 无
    输出:
        bool: OpenVINO 报告有 NPU 设备时为 True
    """
    return bool(_openvino_npu_device_names())



def probe_npu_backend() -> "lm.Backend | None":
    """Cheap probe: constructing NPU() itself performs the OpenVINO/device check."""
    if not _probe_npu_exists():
        _log.info("NPU backend skipped: no OpenVINO NPU device")
        return None
    import litert_lm as lm
    _silence_native_logs(lm)
    try:
        return lm.Backend.NPU()
    except Exception as exc:
        _log.info("NPU backend unavailable: %s", exc)
        return None



def build_engine(
    model_path: str, profile: str, *, enable_vision: bool = False
) -> tuple["lm.Engine", str]:
    """Resolve `profile` into a real, constructed `Engine`.

    `profile` in `FORCED_BACKEND_BY_PROFILE` demands exactly that backend and
    lets its error propagate (explicit override, e.g. a test pinning `"cpu"`).
    Any other value (including the "auto" default) runs the NPU -> GPU -> CPU
    cascade and returns the first backend that actually constructs.

    `enable_vision`: also pass the same winning `Backend` as `vision_backend=`
    (real `gemma-4-E4B-it.litertlm`, CPU, empirically confirmed 2026-07-12: no
    error, image actually gets read). A plain-text `Engine()` never needs this,
    so it stays opt-in rather than always-on -- forcing vision on for every
    caller (judge/correct/wizard) would pay its extra weight-load cost even
    when nobody sends an image.
    """
    import litert_lm as lm
    _silence_native_logs(lm)
    forced = FORCED_BACKEND_BY_PROFILE.get(profile)
    if forced is not None:
        backend = lm.Backend.CPU() if forced == "cpu" else lm.Backend.GPU()
        vision_kwargs = {"vision_backend": backend} if enable_vision else {}
        return lm.Engine(model_path, backend=backend, **vision_kwargs), forced
    candidates: list[tuple["lm.Backend | None", str]] = [
        (probe_npu_backend(), "npu"),
        (lm.Backend.GPU(), "gpu"),
        (lm.Backend.CPU(), "cpu"),
    ]
    last_error: Exception | None = None
    for backend, label in candidates:
        if backend is None:
            continue
        try:
            vision_kwargs = {"vision_backend": backend} if enable_vision else {}
            return lm.Engine(model_path, backend=backend, **vision_kwargs), label
        except Exception as exc:
            _log.warning("Engine() failed on %s backend, falling back: %s", label, exc)
            last_error = exc
    # CPU never failed in testing; this only triggers on something like a
    # corrupt weight file, so surface the last real error rather than a generic one.
    raise RuntimeError(f"All LiteRT-LM backends failed; last error: {last_error}")



def planned_backend_hint(profile: str) -> str:
    """Non-blocking hint of which backend health_check() expects to use.

    Does not construct an Engine or litert_lm Backend.NPU() -- only queries
    OpenVINO device list via _probe_npu_exists(). Real Backend construction
    happens once in build_engine() cascade.
    """
    forced = FORCED_BACKEND_BY_PROFILE.get(profile)
    if forced is not None:
        return forced
    if _probe_npu_exists():
        names = _openvino_npu_device_names()
        suffix = f" ({', '.join(names)})" if names else ""
        return f"npu{suffix}"
    return "gpu (unconfirmed, falls back to cpu)"
