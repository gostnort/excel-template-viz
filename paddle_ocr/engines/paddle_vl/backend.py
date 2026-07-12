"""PaddleOCRVL v1.6 精修后端（仅 GPU；无加速器时不构造，CPU-only 走 Gemma4 纠错）。

设计变更（C3.1）：放弃 CPU 版 PaddleOCRVL（268s/页，不可用）。VL 仅在
AcceleratorAvailable（GPU 硬件 + paddlepaddle-gpu 已装）时构造，device="gpu"。
无加速器时 VlBackend 不构造，main 走 CPU-only Gemma4 直接纠错分支。
"""

from __future__ import annotations

import threading
from typing import Any

from paddle_ocr import config
import paddle_ocr.gate.hardware_probe as _hw
from paddle_ocr.models_catalog import vl_models_present
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr
from paddle_ocr.runtime.infer_lock import INFER_LOCK
from paddle_ocr.runtime.postprocess import HasContent, StructureResultToJson


_lock = threading.Lock()
_instance: "VlBackend | None" = None



class VlBackend:
    def __init__(self) -> None:
        self._engine = None
        self._version = ""
        self._init_error: str | None = None

    def _package_version(self) -> str:
        if self._version:
            return self._version
        try:
            import importlib.metadata
            self._version = importlib.metadata.version("paddleocr")
        except Exception:
            self._version = ""
        return self._version

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        if self._init_error:
            return None
        # 无加速器（CPU-only）：VL 不可用，不构造引擎。
        if not _hw.AcceleratorAvailable():
            self._init_error = "no_accelerator"
            return None
        config.ensure_pdx_cache_env()
        try:
            from paddleocr import PaddleOCRVL
            from paddlex.utils import logging as pdx_logging
            pdx_logging._logger.disabled = True
        except Exception:
            self._init_error = "import"
            return None
        try:
            self._engine = PaddleOCRVL(
                pipeline_version=config.DEFAULT_VL_PIPELINE_VERSION,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_seal_recognition=False,
                use_chart_recognition=False,
                enable_mkldnn=False,
                device="gpu",
            )
            self._package_version()
            return self._engine
        except Exception:
            self._init_error = "init"
            self._engine = None
            return None

    def warm(self) -> None:
        """提前触发引擎构造（与 Gemma StartGemma 一起在启动时调）；无加速器时空操作。"""
        self._ensure_engine()

    def Run(
        self,
        pic,
        rectangle: tuple[int, int, int, int] | None = None,
        *,
        draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ver = self._package_version()
        if not _hw.AcceleratorAvailable():
            return {"ok": False, "message": config.MSG_LLM_PARTIAL, "version": ver, "mode": "llm"}
        try:
            img = load_for_ocr(pic, rectangle)
        except ImageDecodeError:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": "llm"}
        except CropBoxError:
            return {"ok": False, "message": config.MSG_BAD_CROP, "version": ver, "mode": "llm"}
        except Exception:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": "llm"}
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "version": ver, "mode": "llm"}
            try:
                raw = engine.predict(img)
            except Exception:
                return {"ok": False, "message": config.MSG_INFER_FAIL, "version": ver, "mode": "llm"}
        result = StructureResultToJson(raw, mode="llm")
        result["version"] = ver
        # VL 空 + fast 草稿有内容：返回草稿，标注精修未生效。
        if not HasContent(result):
            if draft and HasContent(draft):
                result = dict(draft)
                result["mode"] = "llm"
                result["message"] = config.MSG_LLM_PARTIAL
                result["version"] = ver
                return result
            result["message"] = config.MSG_EMPTY
        return result



def GetVlBackend() -> VlBackend:
    global _instance
    with _lock:
        if _instance is None:
            _instance = VlBackend()
        return _instance



def ResetVlBackend() -> None:
    """Drop VL singleton so next call picks up 加速器/paddle 版本变化。"""
    global _instance
    with _lock:
        _instance = None



def LlmRefine(
    pic,
    rectangle: tuple[int, int, int, int] | None = None,
    *,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run PaddleOCRVL on GPU; optional fast draft kept when VL returns empty."""
    return GetVlBackend().Run(pic, rectangle, draft=draft)



def VlModelsPresent() -> bool:
    """True when the optional VL official_models are on disk."""
    return vl_models_present()
