"""启动时测可用内存（RAM + VRAM）→ 内存分级精修策略（C3.2）。

实测峰值占用：Gemma4(LiteRT 底座) 4.6GB VRAM；PaddleOCRVL 10.8GB VRAM；合计 15.4GB。
阈值定在峰值之下（Paddle-VL 与 LiteRT 会往内存倒垃圾/复用，实际需求略低于峰值）。
预算 budget = max(可用 RAM, 可用 VRAM)。分档：
  < 4GB                → none        仅 fast，直接结束（不够装 Gemma4）。
  4GB ≤ budget < 10GB  → gemma_only  Gemma4 检查 + 直接纠错（不加载 VL）。
  10GB ≤ budget < 14GB → sequential  Gemma4 检查 → 卸载 Gemma4 → 加载 PaddleVL 推理（不能同时驻留）。
  budget ≥ 14GB        → both_resident Gemma4 检查 + 异步加载 PaddleVL；两者常驻。
10GB+ 两档需 AcceleratorAvailable（GPU + paddlepaddle-gpu）；无 GPU 降级 gemma_only。
"""

from __future__ import annotations

import subprocess
import threading

from paddle_ocr import config
import paddle_ocr.gate.hardware_probe as _hw


_lock = threading.Lock()
_budget: float | None = None



def measure_available_ram_gb() -> float:
    """
    函数名: measure_available_ram_gb
    作用: 读操作系统报告的剩余可分配物理内存（非总装容量）。psutil 在 Windows/Linux
        一致用 available 字段；psutil 不可用时返回 0.0（视为低内存，保守关闭精修）。
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
    作用: 用 nvidia-smi 查 NVIDIA GPU 剩余显存（memory.free）。无 GPU 或 nvidia-smi
        不可用时返回 0.0。VL 峰值 10.8GB VRAM，故 VRAM 是 10GB+ 档的关键判据。
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
        # 多 GPU 时取第一块（与 detect_gpu_hardware 一致）。
        return float(r.stdout.strip().splitlines()[0].strip()) / 1024.0
    except Exception:
        return 0.0



def available_budget_gb() -> float:
    """
    函数名: available_budget_gb
    作用: 精修预算 = max(可用 RAM, 可用 VRAM)。RAM 供 Gemma4，VRAM 供 PaddleVL；
        取大者作为分级判据（"内存或显存" whichever larger）。
    输入: 无。
    输出:
        float: 预算 GB。
    """
    return max(measure_available_ram_gb(), measure_available_vram_gb())



def init_refine_path(probe: bool = True) -> None:
    """
    函数名: init_refine_path
    作用: OCR 平台加载时测一次预算 budget=max(RAM,VRAM)，缓存进进程内单例。幂等：
        重复调用只在第一次真正测量。probe=False 时把缓存置 0（用于 --skip-ocr / 测试
        强制 none 档）。
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
    作用: 读缓存的预算，返回精修档位："none"/"gemma_only"/"sequential"/"both_resident"。
        未初始化时惰性测一次。10GB+ 档需 AcceleratorAvailable，否则降级 gemma_only。
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
    if budget < config.REFINE_VL_MIN_GB:
        return "gemma_only"
    if not _hw.AcceleratorAvailable():
        return "gemma_only"
    if budget < config.REFINE_BOTH_RESIDENT_MIN_GB:
        return "sequential"
    return "both_resident"



def RefinePathEnabled() -> bool:
    """
    函数名: RefinePathEnabled
    作用: 精修路径是否启用 = 档位非 none（预算 ≥ 4GB）。保留旧 API 名供既有调用方。
    输入: 无。
    输出:
        bool: True=启用精修（gemma_only/sequential/both_resident）；False=仅 fast。
    """
    return RefineTier() != "none"



def ResetRefinePathCache() -> None:
    """
    函数名: ResetRefinePathCache
    作用: 清空缓存的 _budget，让下一次 RefineTier/init_refine_path 重新测量。供测试隔离。
    输入: 无。
    输出: 无。
    """
    global _budget
    with _lock:
        _budget = None
