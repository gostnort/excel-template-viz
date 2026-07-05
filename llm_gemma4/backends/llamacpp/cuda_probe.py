"""NVIDIA CUDA visibility for profile cuda."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CudaProbeResult:
    has_nvidia_cuda: bool
    gpu_name: str | None
    driver_version: str | None
    llama_cpp_cuda_import_ok: bool
    note: str | None


def probe_cuda() -> CudaProbeResult:
    """Detect NVIDIA GPU via nvidia-smi and optional llama_cpp GPU import."""
    gpu_name: str | None = None
    driver_version: str | None = None
    has_smi = False
    if shutil.which("nvidia-smi"):
        try:
            completed = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version",
                    "--format=csv,noheader",
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if completed.returncode == 0 and completed.stdout.strip():
                has_smi = True
                first_line = completed.stdout.strip().splitlines()[0]
                parts = [part.strip() for part in first_line.split(",")]
                if parts:
                    gpu_name = parts[0] or None
                if len(parts) > 1:
                    driver_version = parts[1] or None
        except (OSError, subprocess.TimeoutExpired):
            has_smi = False
    llama_ok = False
    llama_note: str | None = None
    try:
        from llm_gemma4.backends.llamacpp.cuda_env import prepare_cuda_runtime
        prepare_cuda_runtime()
        import llama_cpp  # noqa: F401
        llama_ok = True
    except ImportError:
        llama_note = "llama-cpp-python not installed (CUDA wheel optional)"
    except Exception:
        llama_note = "llama-cpp-python installed but native DLL load failed"
    has_cuda = has_smi
    note = llama_note
    if has_smi and not llama_ok:
        note = "nvidia-smi OK; install llama-cpp-python CUDA wheel for profile cuda"
    return CudaProbeResult(
        has_nvidia_cuda=has_cuda,
        gpu_name=gpu_name,
        driver_version=driver_version,
        llama_cpp_cuda_import_ok=llama_ok,
        note=note,
    )
