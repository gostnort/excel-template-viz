"""启动时硬件探测：GPU / NPU / CPU-only；决定 VL 精修走哪条路（或跳过）。"""

from __future__ import annotations

import subprocess
import threading
from functools import lru_cache



_lock = threading.Lock()



def detect_gpu_hardware() -> bool:
    """
    函数名: detect_gpu_hardware
    作用: 用 nvidia-smi -L 探测是否存在 NVIDIA GPU 硬件（不依赖 paddle 是否为 CUDA 版）。
        nvidia-smi 不可用或无 GPU 时返回 False。
    输入: 无。
    输出:
        bool: True=本机有 NVIDIA GPU 硬件；False=无或探测失败。
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    return "GPU" in (r.stdout or "")



def detect_npu_hardware() -> bool:
    """
    函数名: detect_npu_hardware
    作用: 探测是否存在 Intel NPU 硬件（通过 OpenVINO 设备枚举）。openvino 未安装或
        无 NPU 时返回 False。NPU 后端为未来扩展（当前仅探测，不启用 VL）。
    输入: 无。
    输出:
        bool: True=存在 Intel NPU；False=无或 openvino 不可用。
    """
    try:
        from openvino import Core  # 延迟 import：openvino 为可选依赖
    except Exception:
        return False
    try:
        core = Core()
        devices = core.available_devices
        return any(str(d).upper().startswith("NPU") for d in devices)
    except Exception:
        return False



@lru_cache(maxsize=1)
def paddle_is_cuda() -> bool:
    """
    函数名: paddle_is_cuda
    作用: 判断当前安装的 paddle 是否为 CUDA 版（paddlepaddle-gpu）。用 importlib.metadata
        查包名，避免为探测而 import paddle（paddle 已被 OCR 栈 import 时也无妨）。
        paddlepaddle-gpu 装着 → True；只装 paddlepaddle(CPU) → False。
    输入: 无。
    输出:
        bool: True=已装 CUDA 版 paddle；False=CPU 版或探测失败。
    """
    try:
        import importlib.metadata as md
        md.version("paddlepaddle-gpu")
        return True
    except md.PackageNotFoundError:
        return False
    except Exception:
        return False



@lru_cache(maxsize=1)
def detect_accelerator() -> str:
    """
    函数名: detect_accelerator
    作用: 硬件级探测（不考虑 paddle 库是否匹配），返回最强可用加速器类型。
        优先级 GPU > NPU > CPU。仅判断硬件是否存在，不判断库是否就绪。
    输入: 无。
    输出:
        str: "gpu" / "npu" / "cpu"。
    """
    if detect_gpu_hardware():
        return "gpu"
    if detect_npu_hardware():
        return "npu"
    return "cpu"



@lru_cache(maxsize=1)
def AcceleratorAvailable() -> bool:
    """
    函数名: AcceleratorAvailable
    作用: 运行时判断 VL 精修路径是否真能跑：GPU 硬件存在 且 paddlepaddle-gpu(CUDA 版)
        已安装。任一不满足返回 False（此时走 CPU-only Gemma4 直接纠错分支，不调 VL）。
        结果缓存（进程内不变）。
    输入: 无。
    输出:
        bool: True=可走 GPU VL 精修；False=走 CPU-only Gemma4 纠错。
    """
    return detect_gpu_hardware() and paddle_is_cuda()



def VlBackendKind() -> str:
    """
    函数名: VlBackendKind
    作用: 返回当前应使用的 VL 后端类型："gpu"（AcceleratorAvailable）/ "npu"（未来扩展）/
        "none"（CPU-only，不跑 VL，走 Gemma4 直接纠错）。
    输入: 无。
    输出:
        str: "gpu" / "npu" / "none"。
    """
    if AcceleratorAvailable():
        return "gpu"
    if detect_npu_hardware():
        return "npu"
    return "none"



def ResetHardwareCache() -> None:
    """清空硬件探测缓存（测试隔离；装完 paddlepaddle-gpu 后强制重测）。"""
    with _lock:
        paddle_is_cuda.cache_clear()
        detect_accelerator.cache_clear()
        AcceleratorAvailable.cache_clear()
