"""CPU SIMD feature detection for llama-cpp-python wheel selection."""

import ctypes
import platform
import sys
from pathlib import Path
from typing import Callable

LLAMA_CPP_VERSION_AVX2 = "0.3.28"
LLAMA_CPP_VERSION_AVX512 = "0.3.29"
LLAMA_CPP_CPU_WHEEL_INDEX = "https://abetlen.github.io/llama-cpp-python/whl/cpu"

_cpuid_leaf_fn: Callable[[int, int], tuple[int, int, int, int]] | None = None
_cpuid_leaf_fn_initialized = False

_CPUID_X64_CODE = bytes([
    0x53,
    0x8B, 0xC1,
    0x8B, 0xCA,
    0x0F, 0xA2,
    0x4D, 0x8B, 0xD0,
    0x41, 0x89, 0x02,
    0x41, 0x89, 0x58, 0x04,
    0x41, 0x89, 0x48, 0x08,
    0x41, 0x89, 0x50, 0x0C,
    0x5B,
    0xC3,
])

PF_AVX_INSTRUCTIONS_AVAILABLE = 39
PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
PF_AVX512F_INSTRUCTIONS_AVAILABLE = 41


def _is_x86() -> bool:
    machine = platform.machine().lower()
    return machine in {"amd64", "x86_64", "i386", "x86", "ia32"}


def _init_cpuid_leaf_fn() -> None:
    global _cpuid_leaf_fn, _cpuid_leaf_fn_initialized
    if _cpuid_leaf_fn_initialized:
        return
    _cpuid_leaf_fn_initialized = True
    if not _is_x86():
        _cpuid_leaf_fn = None
        return
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        _cpuid_leaf_fn = _cpuid_leaf_windows
        return
    _cpuid_leaf_fn = None


def _cpuid_leaf_windows(leaf: int, subleaf: int = 0) -> tuple[int, int, int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualAlloc.restype = ctypes.c_void_p
    kernel32.VirtualAlloc.argtypes = [
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    kernel32.VirtualFree.restype = ctypes.c_int
    kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
    MEM_COMMIT = 0x1000
    MEM_RESERVE = 0x2000
    PAGE_EXECUTE_READWRITE = 0x40
    MEM_RELEASE = 0x8000
    size = len(_CPUID_X64_CODE)
    address = kernel32.VirtualAlloc(None, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
    if not address:
        return (0, 0, 0, 0)
    try:
        code_buf = (ctypes.c_char * size).from_buffer_copy(_CPUID_X64_CODE)
        ctypes.memmove(address, code_buf, size)
        out_type = ctypes.c_uint32 * 4
        out = out_type()
        func_type = ctypes.CFUNCTYPE(
            None,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        )
        func = func_type(address)
        func(ctypes.c_uint32(leaf), ctypes.c_uint32(subleaf), out)
        return (int(out[0]), int(out[1]), int(out[2]), int(out[3]))
    except OSError:
        return (0, 0, 0, 0)
    finally:
        kernel32.VirtualFree(address, 0, MEM_RELEASE)


def _flags_from_windows_kernel() -> dict[str, bool]:
    kernel32 = ctypes.windll.kernel32

    def _has(feature_id: int) -> bool:
        try:
            return bool(kernel32.IsProcessorFeaturePresent(feature_id))
        except Exception:
            return False

    avx = _has(PF_AVX_INSTRUCTIONS_AVAILABLE)
    avx2 = _has(PF_AVX2_INSTRUCTIONS_AVAILABLE)
    avx512f = _has(PF_AVX512F_INSTRUCTIONS_AVAILABLE)
    return {
        "avx": avx,
        "avx2": avx2,
        "avx512f": avx512f,
        "avx512": avx512f,
    }


def _flags_from_proc_cpuinfo() -> dict[str, bool]:
    proc_cpuinfo = Path("/proc/cpuinfo")
    if not proc_cpuinfo.is_file():
        return {}
    flag_tokens: set[str] = set()
    for line in proc_cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.lower().startswith("flags"):
            continue
        _, _, value = line.partition(":")
        flag_tokens.update(value.strip().split())
        break
    avx512f = "avx512f" in flag_tokens
    return {
        "avx": "avx" in flag_tokens,
        "avx2": "avx2" in flag_tokens,
        "avx512f": avx512f,
        "avx512": avx512f or any(token.startswith("avx512") for token in flag_tokens),
    }


def cpuid_leaf(leaf: int, subleaf: int = 0) -> tuple[int, int, int, int]:
    _init_cpuid_leaf_fn()
    if _cpuid_leaf_fn is None:
        return (0, 0, 0, 0)
    return _cpuid_leaf_fn(leaf, subleaf)


def _flags_from_cpuid() -> dict[str, bool]:
    max_leaf = cpuid_leaf(0)[0]
    if max_leaf < 1:
        return {
            "avx": False,
            "avx2": False,
            "avx512f": False,
            "avx512": False,
        }
    _, _, ecx_leaf1, _ = cpuid_leaf(1)
    avx = bool(ecx_leaf1 & (1 << 28))
    avx2 = False
    avx512f = False
    if max_leaf >= 7:
        _, ebx_leaf7, _, _ = cpuid_leaf(7, 0)
        avx2 = bool(ebx_leaf7 & (1 << 5))
        avx512f = bool(ebx_leaf7 & (1 << 16))
    return {
        "avx": avx,
        "avx2": avx2,
        "avx512f": avx512f,
        "avx512": avx512f,
    }


def detect_simd_features() -> dict[str, bool | str]:
    if not _is_x86():
        return {
            "avx": False,
            "avx2": False,
            "avx512f": False,
            "avx512": False,
            "source": "non_x86",
        }
    if sys.platform != "win32":
        proc_flags = _flags_from_proc_cpuinfo()
        if proc_flags:
            return {
                **proc_flags,
                "source": "proc_cpuinfo",
            }
    if sys.platform == "win32":
        win_flags = _flags_from_windows_kernel()
        if any(win_flags.values()):
            return {
                **win_flags,
                "source": "cpuid",
            }
        cpuid_flags = _flags_from_cpuid()
        if any(cpuid_flags.values()):
            return {
                **cpuid_flags,
                "source": "cpuid",
            }
        return {
            **win_flags,
            "source": "cpuid",
        }
    cpuid_flags = _flags_from_cpuid()
    return {
        **cpuid_flags,
        "source": "cpuid",
    }


def recommended_llama_cpp_version() -> str:
    features = detect_simd_features()
    if features.get("avx512f") or features.get("avx512"):
        return LLAMA_CPP_VERSION_AVX512
    return LLAMA_CPP_VERSION_AVX2


def llama_cpp_install_command(
    version: str | None = None,
    *,
    python_executable: str | None = None,
) -> str:
    chosen = version or recommended_llama_cpp_version()
    python = python_executable or sys.executable
    if " " in python and not (python.startswith('"') and python.endswith('"')):
        python = f'"{python}"'
    return (
        f"{python} -m pip install llama-cpp-python=={chosen} "
        f"--extra-index-url {LLAMA_CPP_CPU_WHEEL_INDEX}"
    )
