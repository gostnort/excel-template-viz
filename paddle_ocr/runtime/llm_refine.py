"""PaddleOCR-VL backend (LLM path): local Paddle-owned VL models."""

from __future__ import annotations

import logging
import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr
from paddle_ocr.runtime.infer_lock import INFER_LOCK
from paddle_ocr.runtime.postprocess import HasContent, StructureResultToJson


_log = logging.getLogger(__name__)
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
        config.ensure_pdx_cache_env()
        try:
            from paddleocr import PaddleOCRVL
        except Exception:
            _log.exception("PaddleOCRVL import failed")
            self._init_error = "import"
            return None
        try:
            self._engine = PaddleOCRVL(
                pipeline_version=config.DEFAULT_VL_PIPELINE_VERSION,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_seal_recognition=False,
                use_chart_recognition=False,
                enable_mkldnn=config.DEFAULT_ENABLE_MKLDNN,
                device=config.resolve_device(),
            )
            self._package_version()
            return self._engine
        except Exception:
            _log.exception("PaddleOCRVL init failed")
            self._init_error = "init"
            self._engine = None
            return None

    def Run(
        self,
        pic,
        rectangle: tuple[int, int, int, int] | None = None,
        *,
        draft: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ver = self._package_version()
        try:
            img = load_for_ocr(pic, rectangle)
        except ImageDecodeError:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": "llm"}
        except CropBoxError:
            return {"ok": False, "message": config.MSG_BAD_CROP, "version": ver, "mode": "llm"}
        except Exception:
            _log.exception("VL decode/crop failed")
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver, "mode": "llm"}
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "version": ver, "mode": "llm"}
            try:
                raw = engine.predict(img)
            except Exception:
                _log.exception("PaddleOCRVL predict failed")
                return {"ok": False, "message": config.MSG_INFER_FAIL, "version": ver, "mode": "llm"}
        result = StructureResultToJson(raw, mode="llm")
        result["version"] = ver
        if draft and HasContent(draft) and not HasContent(result):
            result = dict(draft)
            result["mode"] = "llm"
            result["message"] = config.MSG_LLM_PARTIAL
            result["version"] = ver
            return result
        if not HasContent(result):
            result["message"] = config.MSG_EMPTY
        return result



def GetVlBackend() -> VlBackend:
    global _instance
    with _lock:
        if _instance is None:
            _instance = VlBackend()
        return _instance



def ResetVlBackend() -> None:
    """Drop VL singleton so next call picks up OCR_PROFILE / device changes."""
    global _instance
    with _lock:
        _instance = None



def ShouldTryLlm(fast: dict[str, Any]) -> bool:
    """True when fast cannot deliver content and LLM is allowed to run."""
    msg = str(fast.get("message") or "")
    if msg in (config.MSG_BAD_IMAGE, config.MSG_BAD_CROP, config.MSG_NOT_READY, config.MSG_MODEL_MISSING):
        return False
    if fast.get("ok") and HasContent(fast):
        return False
    return True



def LlmRefine(
    pic,
    rectangle: tuple[int, int, int, int] | None = None,
    *,
    draft: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run PaddleOCR-VL on crop; optional fast draft kept when VL returns empty."""
    return GetVlBackend().Run(pic, rectangle, draft=draft)
