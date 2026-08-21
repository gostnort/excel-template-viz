"""CLI entry and public facade for the paddle_ocr platform."""

from __future__ import annotations

import sys
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

from paddle_ocr import config
from paddle_ocr.engines.pp_structure.backend import GetStructureBackend, StructureRefine
from paddle_ocr.gate.hardware_probe import AcceleratorAvailable, detect_accelerator
from paddle_ocr.gate.memory_guard import RefineTier, init_refine_path
from paddle_ocr.gate.semantic_gate import HasOcrSemanticProblem
from paddle_ocr.models_catalog import required_models_present


class OcrStage(IntEnum):
    IDLE = 0b000
    FAST_OCR = 0b001
    SEMANTIC_CHECK = 0b010
    GEMMA_REFINE = 0b011
    STRUCTURE_REFINE = 0b100


PicInput = bytes | Path | str
Rectangle = tuple[int, int, int, int] | None
OcrTask = tuple[PicInput, Rectangle]



def _unload_lm_studio() -> None:
    """卸载当前 LM Studio 模型（sequential 档：Structure 推理前释放显存）。"""
    try:
        from llm_lmstudio.models import unload_model
        unload_model()
    except Exception:
        pass



def PaddleOcr(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: Callable[[OcrStage], None] = None,
) -> dict[str, Any]:
    """One picture + optional OpenCV ROI → string*/table* JSON (no HealthCheck).

    Pipeline:
      fast (PP-OCRv6 细条 / PP-StructureV3 整图表格) → RefineTier() →
        none(<4GB)            → 返回 fast；
        gemma_only(4-10GB)    → 语义检查 → 有问题则 Pic2Str 视觉纠错；
        sequential(10-14GB)   → 语义检查 → 有问题则 卸载 LM Studio → PP-StructureV3；
        both_resident(≥14GB)  → 语义检查 → 有问题则 PP-StructureV3（可常驻）；
      无问题 → 返回 fast。
      已走 Structure 的 fast 不再重复精修，改为视觉纠错。
    """
    if status_callback: status_callback(OcrStage.FAST_OCR)
    try:
        fast = GetStructureBackend().Run(pic, rectangle, mode="fast")
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast"}
    if not fast.get("ok"):
        return fast
    tier = RefineTier()
    if tier == "none":
        return fast
    if status_callback: status_callback(OcrStage.SEMANTIC_CHECK)
    if not HasOcrSemanticProblem(fast):
        return fast
    if tier == "gemma_only" or fast.get("engine") == "structure":
        from paddle_ocr.gate.gemma_vision_correct import GemmaVisionCorrect
        if status_callback: status_callback(OcrStage.GEMMA_REFINE)
        try:
            return GemmaVisionCorrect(pic, rectangle, fast)
        except Exception:
            out = dict(fast)
            out["message"] = config.MSG_LLM_PARTIAL
            return out
    if tier == "sequential":
        _unload_lm_studio()
    if status_callback: status_callback(OcrStage.STRUCTURE_REFINE)
    try:
        refined = StructureRefine(pic, rectangle, draft=fast)
    except Exception:
        refined = None
    if refined and refined.get("ok"):
        return refined
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
    作用: 检查 PP-OCRv6 / PP-StructureV3 模型是否完整并自动补齐；始终 prune PaddleOCR-VL 权重。
    输入: 无。
    输出:
        tuple[bool, str]: (fast 模型是否就绪, 状态消息)。
    """
    init_refine_path()
    report = HealthCheck()
    if not (report.get("ok") and required_models_present()):
        from paddle_ocr.scripts.download_models import download_models
        ok, message = download_models()
        if not ok:
            return False, message
    from paddle_ocr.models_catalog import prune_vl_official_models
    prune_vl_official_models()
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
    try:
        from llm_lmstudio.config import load_user_config
        from llm_lmstudio.models import load_model
        name = str(load_user_config().get("model") or "").strip()
        if name:
            load_model(name, remember=True)
    except Exception:
        pass
    if tier == "both_resident":
        import threading
        try:
            def _warm():
                try:
                    GetStructureBackend().warm()
                except Exception:
                    pass
            threading.Thread(target=_warm, daemon=True).start()
        except Exception:
            pass



def main(argv: list[str] | None = None) -> int:
    """CLI gate: 硬件探测 → 内存分级 → EnsureModels → 按档预热 → one PaddleOcr on sample."""
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print(f"usage: python paddle_ocr/main.py  (ignored args: {argv!r})")
    init_refine_path()
    tier = RefineTier()
    print(f"精修档位: {tier}")
    if detect_accelerator() == "gpu" and not AcceleratorAvailable():
        print("检测到 NVIDIA GPU，但当前 paddle 为 CPU 版。")
        print("如需 GPU 加速 PP-OCRv6 / PP-StructureV3，请运行: python paddle_ocr/scripts/install_backend.py")
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
