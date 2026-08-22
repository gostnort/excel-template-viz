"""CLI entry and public facade for the paddle_ocr platform."""

from __future__ import annotations

import sys
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable

from paddle_ocr import config
from paddle_ocr.engines.pp_ocr.backend import GetFieldStripBackend
from paddle_ocr.engines.pp_structure.backend import GetStructureBackend
from paddle_ocr.gate.hardware_probe import AcceleratorAvailable, detect_accelerator
from paddle_ocr.gate.lm_similarity import lm_similarity_score as _lm_similarity_score
from paddle_ocr.gate.semantic_gate import semantic_judge as _semantic_judge
from paddle_ocr.models_catalog import required_models_present
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr


class OcrStage(IntEnum):
    IDLE = 0b000
    FAST_OCR = 0b001
    SEMANTIC_CHECK = 0b010
    STRUCTURE_REFINE = 0b100


PicInput = bytes | Path | str
Rectangle = tuple[int, int, int, int] | None
OcrTask = tuple[PicInput, Rectangle]


def PaddleOcr(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: Callable[[OcrStage], None] = None,
) -> dict[str, Any]:
    """
    函数名: PaddleOcr
    作用: 解码裁切后只跑 PP-OCRv6 字段 OCR；不读表、不 judge、不 Structure、不 RefineTier。
    输入:
        pic (bytes|Path|str): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 可选阶段回调；T2 仅 FAST_OCR。
    输出:
        dict: engine="ocr" 的 string* JSON。返回后不停 OCR daemon。
    """
    if status_callback:
        status_callback(OcrStage.FAST_OCR)
    # 中文注释: 解码并按 ROI 裁切；失败不启动 MCP
    try:
        img = load_for_ocr(pic, rectangle)
    except ImageDecodeError:
        return {"ok": False, "message": config.MSG_BAD_IMAGE, "mode": "fast", "engine": "ocr"}
    except CropBoxError:
        return {"ok": False, "message": config.MSG_BAD_CROP, "mode": "fast", "engine": "ocr"}
    except Exception:
        return {"ok": False, "message": config.MSG_BAD_IMAGE, "mode": "fast", "engine": "ocr"}
    # 中文注释: FieldStripBackend 内经 ensure_ocr_mcp 懒启动后只调 call_ocr_mcp；返回不停 OCR
    return GetFieldStripBackend().Run(img)


def PpStructure(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: Callable[[OcrStage], None] = None,
) -> dict[str, Any]:
    """
    函数名: PpStructure
    作用: 解码裁切后只跑 PP-StructureV3；不调 PaddleOcr、不 judge、不按 HasTableGrid 分流字段 OCR。
    输入:
        pic (bytes|Path|str): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 可选阶段回调；T3 仅 STRUCTURE_REFINE。
    输出:
        dict: engine="structure" 的 JSON。返回后不停 Structure daemon。
    """
    # T5: list runner 在 finally 里 stop_structure_mcp；本 callee 禁止 stop。
    if status_callback:
        status_callback(OcrStage.STRUCTURE_REFINE)
    # 中文注释: 懒启动与 MCP 调用在 StructureBackend.Run；无网格细条也走 Structure
    return GetStructureBackend().Run(pic, rectangle, mode="structure")


def semantic_judge(draft: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: semantic_judge
    作用: LLM 只做语义通顺判定；不 OCR、不 Structure、不 load_model。出错或未加载 keep_draft。
    输入:
        draft (dict): OCR 草稿 JSON（string*/table*）。
    输出:
        dict: fluent / keep_draft / has_problem；可选 reason。
    """
    return _semantic_judge(draft)


def lm_similarity_score(
    pic: PicInput,
    rectangle: Rectangle,
    engine_draft: dict[str, Any],
) -> dict[str, Any]:
    """
    函数名: lm_similarity_score
    作用: 第 3 步 callee：按 JSON 字段/单元格打 0–100 分，仅低分采纳 proposed；不改引擎草稿副本。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)。
        engine_draft (dict): paddleocr-mcp 引擎 JSON。
    输出:
        dict: result / lm_draft / lm_scores / lm_adopted。
    """
    return _lm_similarity_score(pic, rectangle, engine_draft)


def run_ocr_job(
    pic: PicInput,
    rectangle: Rectangle = None,
    status_callback: Callable[[str], None] = None,
) -> dict[str, Any]:
    """
    函数名: run_ocr_job
    作用: job.ocr.request 入口：BOOT 选模板后按事件表调度 callee；Structure 在 finally 释放，不停 OCR。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 按事件 kind 字符串回调（无 Gemma 文案）。
    输出:
        dict: OCR 或 Structure JSON，并带 engine_draft / lm_draft / lm_scores / lm_adopted；解码失败 ok=False。
    """
    # 中文注释: 延后导入 runner，避免 job.runner 与 main 循环依赖
    from paddle_ocr.job.runner import run_ocr_job as _run_ocr_job
    return _run_ocr_job(pic, rectangle, status_callback=status_callback)


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



def main(argv: list[str] | None = None) -> int:
    """CLI gate: 硬件探测 → EnsureModels → one PaddleOcr on sample（不按档预热 Structure / 不 load_model）。"""
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print(f"usage: python paddle_ocr/main.py  (ignored args: {argv!r})")
    if detect_accelerator() == "gpu" and not AcceleratorAvailable():
        print("检测到 NVIDIA GPU，但当前 paddle 为 CPU 版。")
        print("如需 GPU 加速 PP-OCRv6 / PP-StructureV3，请运行: python paddle_ocr/scripts/install_backend.py")
    ok, message = EnsureModels()
    print(message)
    if not ok:
        return 1
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
