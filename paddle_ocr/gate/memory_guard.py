"""启动时测可用内存（RAM + VRAM）→ 内存分级精修策略。

fast = PP-OCRv6（细条）/ PP-StructureV3（整图表格）。
精修 = PP-StructureV3（替代 PaddleOCR-VL；可 CPU）。
预算 budget = max(可用 RAM, 可用 VRAM)。分档：
  < 4GB                → none        仅 fast。
  4GB ≤ budget < 10GB  → gemma_only  LM Studio 检查 + 视觉纠错。
  10GB ≤ budget < 14GB → sequential  检查 → 卸载 LM Studio → StructureV3。
  budget ≥ 14GB        → both_resident 检查 + 可常驻 StructureV3。
10GB+ 档不要求 GPU（Structure 可 CPU）。
"""

from __future__ import annotations

import subprocess
import threading

from paddle_ocr import config


_lock = threading.Lock()
_budget: float | None = None



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
    作用: 精修预算 = max(可用 RAM, 可用 VRAM)。
    输入: 无。
    输出:
        float: 预算 GB。
    """
    return max(measure_available_ram_gb(), measure_available_vram_gb())



def init_refine_path(probe: bool = True) -> None:
    """
    函数名: init_refine_path
    作用: OCR 平台加载时测一次预算并缓存。probe=False 时缓存为 0。
    输入:
        probe (bool): True=测量并缓存；False=直接缓存为 0（none 档）。
    输出: 无（副作用：写入模块级 _budget）。
    """
    global _budget
    with _lock:
        if _budget is not None:
            return
        _budget = available_budget_gb() if probe else 0.0



def RefineTier() -> str:
    """
    函数名: RefineTier
    作用: 读缓存预算，返回 none/gemma_only/sequential/both_resident。
    输入: 无。
    输出:
        str: 档位名。
    """
    global _budget
    if _budget is None:
        init_refine_path(probe=True)
    with _lock:
        budget = float(_budget or 0.0)
    if budget < config.REFINE_MIN_RAM_GB:
        return "none"
    if budget < config.REFINE_STRUCTURE_MIN_GB:
        return "gemma_only"
    if budget < config.REFINE_BOTH_RESIDENT_MIN_GB:
        return "sequential"
    return "both_resident"



def RefinePathEnabled() -> bool:
    """
    函数名: RefinePathEnabled
    作用: 精修路径是否启用 = 档位非 none。
    输入: 无。
    输出:
        bool: True=启用精修；False=仅 fast。
    """
    return RefineTier() != "none"



def ResetRefinePathCache() -> None:
    """
    函数名: ResetRefinePathCache
    作用: 清空缓存的 _budget，供测试隔离。
    输入: 无。
    输出: 无。
    """
    global _budget
    with _lock:
        _budget = None
