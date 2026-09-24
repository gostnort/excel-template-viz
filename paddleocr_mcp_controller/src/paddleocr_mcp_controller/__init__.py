"""paddleocr_mcp_controller: thin controller over paddleocr-mcp HTTP subprocess.

Public API:
    run_ocr_job(pic, rectangle, status_callback, *, vision_fn=None) -> dict
    PaddleOcr_PDF2MDs(FilePath, OutputPath=None, multipages=True) -> dict
    HealthCheck() -> dict
    EnsureModels() -> tuple[bool, str]

Internally also exposes PaddleOcr / PpStructure for advanced callers,
but the UI only needs run_ocr_job + PaddleOcr_PDF2MDs.

Heavy submodules (job / mcp_runtime / lm_similarity / models_catalog / pdf2md) are
imported lazily via PEP 562 __getattr__ so that `python -m paddleocr_mcp_controller.pdf2md`
does not load pdf2md into sys.modules before runpy executes it (avoids the runpy
RuntimeWarning and the swallowed __main__ block).
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

from paddleocr_mcp_controller import config


# 中文注释: 重子模块 -> 模块路径映射；首次访问时按需 import
_LAZY: dict[str, str] = {
    "run_ocr_job": "paddleocr_mcp_controller.job",
    "PicInput": "paddleocr_mcp_controller.job",
    "Rectangle": "paddleocr_mcp_controller.job",
    "StatusCb": "paddleocr_mcp_controller.job",
    "VisionFn": "paddleocr_mcp_controller.lm_similarity",
    "lm_similarity_score": "paddleocr_mcp_controller.lm_similarity",
    "call_ocr_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "call_structure_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "ensure_ocr_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "is_mcp_running": "paddleocr_mcp_controller.mcp_runtime",
    "is_structure_mcp_running": "paddleocr_mcp_controller.mcp_runtime",
    "ocr_mcp_url": "paddleocr_mcp_controller.mcp_runtime",
    "start_ocr_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "start_structure_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "stop_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "stop_ocr_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "stop_structure_mcp": "paddleocr_mcp_controller.mcp_runtime",
    "structure_mcp_url": "paddleocr_mcp_controller.mcp_runtime",
    "prune_vl_official_models": "paddleocr_mcp_controller.models_catalog",
    "required_models_present": "paddleocr_mcp_controller.models_catalog",
    "PaddleOcr_PDF2MDs": "paddleocr_mcp_controller.pdf2md",
}


__all__ = [
    "PaddleOcr",
    "PaddleOcr_PDF2MDs",
    "PpStructure",
    "HealthCheck",
    "EnsureModels",
    "run_ocr_job",
    "lm_similarity_score",
    "stop_mcp",
    "is_mcp_running",
    "is_structure_mcp_running",
]


def __getattr__(name: str) -> Any:
    """
    函数名: __getattr__
    作用: PEP 562 模块级懒加载；首次访问 _LAZY 中的名字时才 import 对应子模块，避免包加载时把重子模块拉进 sys.modules。
    输入:
        name (str): 被访问的属性名。
    输出:
        Any: 子模块中的对应对象；非 _LAZY 名字抛 AttributeError。
    """
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'paddleocr_mcp_controller' has no attribute {name!r}")
    mod = importlib.import_module(target)
    return getattr(mod, name)


def PaddleOcr(
    pic: "PicInput",
    rectangle: "Rectangle" = None,
    status_callback: Callable[[str], None] = None,
) -> dict[str, Any]:
    """
    函数名: PaddleOcr
    作用: 解码裁切后只跑 PP-OCRv6 字段 OCR；不读表、不 Structure、不 LM 校对。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 可选阶段回调。
    输出:
        dict: engine="ocr" 的 string* JSON。
    """
    from paddleocr_mcp_controller.image_decode import load_for_ocr
    from paddleocr_mcp_controller.mcp_runtime import call_ocr_mcp, ensure_ocr_mcp
    if status_callback:
        status_callback("infer.ocr")
    img = load_for_ocr(pic, rectangle)
    if not ensure_ocr_mcp():
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"}
    return call_ocr_mcp(img)


def PpStructure(
    pic: "PicInput",
    rectangle: "Rectangle" = None,
    status_callback: Callable[[str], None] = None,
) -> dict[str, Any]:
    """
    函数名: PpStructure
    作用: 解码裁切后只跑 PP-StructureV3；不调 PaddleOcr、不 LM 校对。
    输入:
        pic (bytes|Path|str|ndarray): 图片。
        rectangle (tuple|None): OpenCV ROI (x, y, w, h)；None 表示整图。
        status_callback (Callable|None): 可选阶段回调。
    输出:
        dict: engine="structure" 的 JSON。
    """
    from paddleocr_mcp_controller.image_decode import load_for_ocr
    from paddleocr_mcp_controller.mcp_runtime import call_structure_mcp, start_structure_mcp
    if status_callback:
        status_callback("infer.structure")
    img = load_for_ocr(pic, rectangle)
    if not start_structure_mcp():
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "structure", "engine": "structure"}
    return call_structure_mcp(img, mode="structure")


def HealthCheck() -> dict[str, Any]:
    """
    函数名: HealthCheck
    作用: paddleocr-mcp 可导入即可；权重由 MCP 子进程首次启动时下载。
    输入: 无。
    输出:
        dict: ok / message / version。
    """
    try:
        import importlib.metadata as md
        ver = md.version("paddleocr-mcp")
    except Exception:
        return {"ok": False, "message": config.MSG_NOT_READY, "version": ""}
    try:
        import paddleocr_mcp  # noqa: F401
    except Exception:
        return {"ok": False, "message": config.MSG_NOT_READY, "version": ver}
    return {"ok": True, "message": config.MSG_HEALTH_OK, "version": ver}


def EnsureModels() -> tuple[bool, str]:
    """
    函数名: EnsureModels
    作用: 检查 PP-OCRv6 / PP-StructureV3 模型是否完整并自动补齐；始终 prune PaddleOCR-VL 权重。
    输入: 无。
    输出:
        tuple[bool, str]: (fast 模型是否就绪, 状态消息)。
    """
    from paddleocr_mcp_controller.models_catalog import (
        prune_vl_official_models,
        required_models_present,
    )
    report = HealthCheck()
    if not (report.get("ok") and required_models_present()):
        from paddleocr_mcp_controller.install import warm_models
        ok, message = warm_models()
        if not ok:
            return False, message
    prune_vl_official_models()
    report = HealthCheck()
    if not report.get("ok"):
        return False, config.MSG_NOT_READY
    return True, config.MSG_HEALTH_OK
