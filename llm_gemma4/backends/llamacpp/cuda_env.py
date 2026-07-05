"""Windows CUDA runtime PATH and AVX2 ggml-cpu fallback for llama-cpp-python."""

from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from llm_gemma4.backends.llamacpp.cpu_features import (
    LLAMA_CPP_CPU_WHEEL_INDEX,
    detect_simd_features,
    recommended_llama_cpp_version,
)


_NVIDIA_DLL_SUBDIRS = (
    "nvidia/cuda_runtime/bin",
    "nvidia/cublas/bin",
    "nvidia/cuda_nvrtc/bin",
)


def _site_packages_dir() -> Path:
    candidates = [Path(entry) for entry in site.getsitepackages()]
    for path in reversed(candidates):
        if (path / "llama_cpp").is_dir() or (path / "nvidia").is_dir():
            return path
    return candidates[-1]


def _llama_cpp_lib_dir() -> Path | None:
    lib_dir = _site_packages_dir() / "llama_cpp" / "lib"
    return lib_dir if lib_dir.is_dir() else None


def _prepend_path(*entries: Path) -> None:
    # PATH must use os.environ; pathlib builds the segment list.
    existing = os.environ.get("PATH", "")
    existing_parts = existing.split(os.pathsep) if existing else []
    parts = [
        str(path)
        for path in entries
        if path.is_dir() and str(path) not in existing_parts
    ]
    if not parts:
        return
    os.environ["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))


def ensure_cuda_dll_path() -> list[Path]:
    """Prepend nvidia pip CUDA DLL dirs and llama_cpp/lib to PATH."""
    site_packages = _site_packages_dir()
    added: list[Path] = []
    for rel in _NVIDIA_DLL_SUBDIRS:
        path = site_packages / rel
        if path.is_dir():
            added.append(path)
    lib_dir = _llama_cpp_lib_dir()
    if lib_dir is not None:
        added.append(lib_dir)
    _prepend_path(*added)
    return added


def _ggml_cpu_load_ok(dll_path: Path) -> bool:
    import ctypes
    if not dll_path.is_file():
        return False
    try:
        ctypes.CDLL(str(dll_path))
        return True
    except OSError:
        return False


def _download_cpu_wheel_ggml_cpu_dll() -> bytes:
    version = recommended_llama_cpp_version()
    with tempfile.TemporaryDirectory(prefix="llama_cpp_cpu_wheel_") as tmp:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                f"llama-cpp-python=={version}",
                "--extra-index-url",
                LLAMA_CPP_CPU_WHEEL_INDEX,
                "--only-binary",
                ":all:",
                "-d",
                tmp,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"pip download llama-cpp-python CPU wheel failed: {detail}"
            )
        wheels = sorted(Path(tmp).glob("llama_cpp_python-*.whl"))
        if not wheels:
            raise RuntimeError("pip download did not produce a llama_cpp_python wheel")
        with zipfile.ZipFile(wheels[0]) as archive:
            member = "llama_cpp/lib/ggml-cpu.dll"
            try:
                return archive.read(member)
            except KeyError as exc:
                raise RuntimeError(f"{member} missing in CPU wheel") from exc


def ensure_avx2_ggml_cpu() -> bool:
    """On AVX2-only CPUs, replace CUDA wheel ggml-cpu.dll with the CPU wheel build."""
    if sys.platform != "win32":
        return False
    features = detect_simd_features()
    if features.get("avx512f") or features.get("avx512"):
        return False
    lib_dir = _llama_cpp_lib_dir()
    if lib_dir is None:
        return False
    target = lib_dir / "ggml-cpu.dll"
    if not target.is_file():
        return False
    if _ggml_cpu_load_ok(target):
        return False
    backup = lib_dir / "ggml-cpu.dll.cuda_bak"
    avx2_cache = lib_dir / "ggml-cpu.dll.avx2"
    if not backup.is_file():
        shutil.copy2(target, backup)
    if not avx2_cache.is_file():
        avx2_cache.write_bytes(_download_cpu_wheel_ggml_cpu_dll())
    shutil.copy2(avx2_cache, target)
    return True


def prepare_cuda_runtime() -> None:
    """Apply PATH and optional ggml-cpu swap before loading the CUDA wheel."""
    ensure_cuda_dll_path()
    ensure_avx2_ggml_cpu()
