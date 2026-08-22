"""Structure 低内存只 warn：不按档位分叉、不跳过事件表模板。"""

from __future__ import annotations

import subprocess
import warnings

from paddle_ocr import config



def measure_available_ram_gb() -> float:
    """
    函数名: measure_available_ram_gb
    作用: 读操作系统报告的剩余可分配物理内存。psutil 不可用时返回 0.0。
    输入: 无。
    输出:
        float: 可用内存 GB；探测失败返回 0.0。
    """
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        return 0.0



def measure_available_vram_gb() -> float:
    """
    函数名: measure_available_vram_gb
    作用: 用 nvidia-smi 查 NVIDIA GPU 剩余显存。无 GPU 时返回 0.0。
    输入: 无。
    输出:
        float: 可用显存 GB；无 GPU/探测失败返回 0.0。
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return 0.0
    if r.returncode != 0 or not (r.stdout or "").strip():
        return 0.0
    try:
        return float(r.stdout.strip().splitlines()[0].strip()) / 1024.0
    except Exception:
        return 0.0



def available_budget_gb() -> float:
    """
    函数名: available_budget_gb
    作用: Structure 低内存警告用的预算 = max(可用 RAM, 可用 VRAM)。
    输入: 无。
    输出:
        float: 预算 GB。
    """
    return max(measure_available_ram_gb(), measure_available_vram_gb())



def warn_if_structure_low_memory() -> bool:
    """
    函数名: warn_if_structure_low_memory
    作用: Structure 即将运行时测预算；偏低只 warn，不改模板、不跳过、不分档。
    输入: 无。
    输出:
        bool: True=已发出低内存警告；False=预算足够。
    """
    budget = available_budget_gb()
    if budget >= config.STRUCTURE_LOW_MEMORY_GB:
        return False
    warnings.warn(config.MSG_STRUCTURE_LOW_MEMORY, UserWarning, stacklevel=2)
    return True
