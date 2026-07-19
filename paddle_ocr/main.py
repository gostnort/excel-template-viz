"""CLI entry and public facade for the paddle_ocr platform."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable
from enum import IntEnum

class OcrStage(IntEnum):
    IDLE = 0b000
    FAST_OCR = 0b001
    SEMANTIC_CHECK = 0b010
    GEMMA_REFINE = 0b011
    VL_REFINE = 0b100

from paddle_ocr import config
from paddle_ocr.engines.paddle_vl.backend import LlmRefine
from paddle_ocr.engines.pp_structure.backend import GetStructureBackend
from paddle_ocr.gate.hardware_probe import AcceleratorAvailable, detect_accelerator
from paddle_ocr.gate.memory_guard import RefineTier, init_refine_path
from paddle_ocr.gate.semantic_gate import HasOcrSemanticProblem
from paddle_ocr.models_catalog import required_models_present, vl_models_present


PicInput = bytes | Path | str
Rectangle = tuple[int, int, int, int] | None
OcrTask = tuple[PicInput, Rectangle]



def _unload_gemma4() -> None:
    """卸载 Gemma4 单例（sequential 档：VL 推理前释放 RAM/VRAM 给 PaddleVL）。"""
    try:
        import llm_gemma4.__main__ as gemma_main
        gemma_main.ResetBackend()
    except Exception:
        pass



def PaddleOcr(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: Callable[[OcrStage], None] = None,
) -> dict[str, Any]:
    """One picture + optional OpenCV ROI → string*/table* JSON (no HealthCheck).

    Pipeline (内存分级, C3.2/C3.3):
      fast (PP-Structure/field) → RefineTier() →
        none(<4GB)            → 返回 fast；
        gemma_only(4-10GB)    → Gemma4 检查 → 有问题则 C3.3 Pic2Str 视觉读图 + 逐单元择优合并（保结构）；
        sequential(10-14GB)   → Gemma4 检查 → 有问题则 卸载Gemma4 → PaddleOCRVL(GPU) 推理；
        both_resident(≥14GB)  → Gemma4 检查 → 有问题则 PaddleOCRVL(GPU) 推理（两者常驻）；
      无问题 → 返回 fast。
    实测峰值：Gemma4 4.6GB VRAM，VL 10.8GB VRAM（合计 15.4 → ≥14GB 才能同时驻留）。
    """
    if status_callback: status_callback(OcrStage.FAST_OCR)
    try:
        fast = GetStructureBackend().Run(pic, rectangle)
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast"}
    # 坏图/坏选区/引擎未就绪/模型缺失：精修救不了，直接返回 fast。
    if not fast.get("ok"):
        return fast
    tier = RefineTier()
    if tier == "none":
        return fast
    # Gemma4 语义检查（首次调用自动加载 Gemma4 单例）。
    if status_callback: status_callback(OcrStage.SEMANTIC_CHECK)
    if not HasOcrSemanticProblem(fast):
        return fast
    # 存在语义问题 → 按档位精修。
    if tier == "gemma_only":
        # C3.3：Pic2Str 视觉读图 + 逐单元择优合并（保结构）。幻觉可接受——角色
        # character 是关键约束（见 docs/embed_paddle_ocr.md §3.2a / embed_gemma4.md §3.1d）。
        from paddle_ocr.gate.gemma_vision_correct import GemmaVisionCorrect
        if status_callback: status_callback(OcrStage.GEMMA_REFINE)
        try:
            return GemmaVisionCorrect(pic, rectangle, fast)
        except Exception:
            out = dict(fast)
            out["message"] = config.MSG_LLM_PARTIAL
            return out
    # sequential / both_resident → PaddleOCRVL(GPU) 最终推理。
    if tier == "sequential":
        # VL 峰值 10.8GB + Gemma4 4.6GB = 15.4 不能同时驻留 → 先卸载 Gemma4。
        _unload_gemma4()
    if status_callback: status_callback(OcrStage.VL_REFINE)
    try:
        vl = LlmRefine(pic, rectangle, draft=fast)
    except Exception:
        vl = None
    if vl and vl.get("ok"):
        return vl
    # VL 失败：保留 fast 内容，标注精修未生效。
    out = dict(fast)
    out["message"] = config.MSG_LLM_PARTIAL
    return out



def PaddleOcrTasks(tasks: list[OcrTask]) -> list[dict[str, Any]]:
    """Run multiple (pic, rectangle) jobs in order; each item is one PaddleOcr result."""
    results: list[dict[str, Any]] = []
    for pic, rectangle in tasks:
        results.append(PaddleOcr(pic, rectangle))
    return results



def HealthCheck() -> dict[str, Any]:
    try:
        return GetStructureBackend().HealthCheck()
    except Exception:
        return {"ok": False, "message": config.MSG_NOT_READY, "version": ""}



def EnsureModels() -> tuple[bool, str]:
    """
    函数名: EnsureModels
    作用: 检查所需模型是否完整并自动补齐。fast 模型缺失 → 调 download_models 下载。
        VL 模型按 硬件 决定去留：detect_accelerator() 为 gpu/npu（有加速器硬件）→ 保留/补下载
        VL 模型（哪怕 paddlepaddle-gpu 还没装，装好后即可用）；cpu（无加速器硬件）→ prune
        释放磁盘。库文件（paddlepaddle-gpu）的安装由 scripts/install_backend.py 负责
        （不能在已 import paddle 的进程内热替换）。
    输入: 无。
    输出:
        tuple[bool, str]: (fast 模型是否就绪, 状态消息)。
    """
    init_refine_path()
    # fast 模型（PP-OCR + PP-Structure）——任何硬件都需要。
    report = HealthCheck()
    if not (report.get("ok") and required_models_present()):
        from paddle_ocr.scripts.download_models import download_models
        ok, message = download_models()
        if not ok:
            return False, message
    # VL 模型按硬件去留：有加速器硬件 → 保留/补下载；纯 CPU → prune 释放磁盘。
    has_accel_hw = detect_accelerator() in ("gpu", "npu")
    if has_accel_hw:
        if not vl_models_present():
            from paddle_ocr.scripts.download_models import download_models
            ok, message = download_models()
            if not ok:
                return False, message
    else:
        from paddle_ocr.models_catalog import prune_extra_official_models
        prune_extra_official_models(keep_vl=False)
    report = HealthCheck()
    if not report.get("ok"):
        return False, str(report.get("message") or config.MSG_NOT_READY)
    if not required_models_present():
        return False, config.MSG_MODEL_MISSING
    return True, str(report.get("message") or config.MSG_HEALTH_OK)



def _warm_for_tier(tier: str) -> None:
    """按档位在启动时预加载常驻引擎（CLI / 服务启动阶段扛冷启动成本）。"""
    if tier == "none":
        return
    # gemma_only / sequential / both_resident 都需 Gemma4 常驻做语义检查。
    try:
        import llm_gemma4.__main__ as gemma_main
        gemma_main.StartGemma()
    except Exception:
        pass
    if tier == "both_resident":
        # ≥14GB：Gemma4(4.6GB) + PaddleVL(10.8GB) 同时常驻（合计 15.4GB）；异步预热 VL（不阻塞 CLI）。
        import threading
        try:
            from paddle_ocr.engines.paddle_vl.backend import GetVlBackend

            def _warm():
                try:
                    GetVlBackend().warm()
                except Exception:
                    pass
            threading.Thread(target=_warm, daemon=True).start()
        except Exception:
            pass
    # sequential：VL 不预热，按需在 PaddleOcr 内卸载 Gemma4 后加载（避免与 Gemma4 同时驻留）。



def main(argv: list[str] | None = None) -> int:
    """CLI gate: 硬件探测 → 内存分级 → EnsureModels → 按档预热 → one PaddleOcr on sample."""
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print(f"usage: python paddle_ocr/main.py  (ignored args: {argv!r})")
    init_refine_path()
    tier = RefineTier()
    print(f"精修档位: {tier}")
    # GPU 硬件在但 paddlepaddle-gpu 未装 → 10GB+ 档降级为 gemma_only；提示装 GPU paddle。
    if detect_accelerator() == "gpu" and not AcceleratorAvailable():
        print("检测到 NVIDIA GPU，但当前 paddle 为 CPU 版（VL 已禁用，降级 gemma_only）。")
        print("如需 GPU VL 精修，请运行: python paddle_ocr/scripts/install_backend.py")
    ok, message = EnsureModels()
    print(message)
    if not ok:
        return 1
    _warm_for_tier(tier)
    sample = config.SAMPLE_IMAGE
    if not sample.is_file():
        print(f"缺少样图: {sample}")
        return 1
    result = PaddleOcr(sample, None)
    print(result.get("message"))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    raise SystemExit(main())
