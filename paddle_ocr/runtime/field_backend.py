"""Lightweight field OCR for thin pre-cropped strips (original pixels, no upscale)."""

from __future__ import annotations

import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.runtime.infer_lock import INFER_LOCK
from paddle_ocr.runtime.postprocess import FieldPredictToStringJson


_lock = threading.Lock()
_instance: "FieldStripBackend | None" = None



class FieldStripBackend:
    def __init__(self) -> None:
        self._engine = None
        self._init_error: str | None = None

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        if self._init_error:
            return None
        config.ensure_pdx_cache_env()
        try:
            from paddleocr import PaddleOCR
            from paddlex.utils import logging as pdx_logging
            pdx_logging._logger.disabled = True
        except Exception:
            self._init_error = "import"
            return None
        try:
            self._engine = PaddleOCR(
                text_detection_model_name=config.DEFAULT_FIELD_DET_MODEL,
                text_recognition_model_name=config.DEFAULT_FIELD_REC_MODEL,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=True,
                text_det_limit_side_len=config.DEFAULT_TEXT_DET_LIMIT_SIDE_LEN,
                text_det_limit_type=config.DEFAULT_TEXT_DET_LIMIT_TYPE,
                enable_mkldnn=config.DEFAULT_ENABLE_MKLDNN,
                device=config.resolve_device(),
            )
            return self._engine
        except Exception:
            self._init_error = "init"
            return None

    def Run(self, img) -> dict[str, Any]:
        height, width = int(img.shape[0]), int(img.shape[1])
        long_side = max(height, width)
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "mode": "fast"}
            try:
                raw = engine.predict(
                    img,
                    text_det_limit_type=config.DEFAULT_TEXT_DET_LIMIT_TYPE,
                    text_det_limit_side_len=long_side,
                )
            except Exception:
                return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast"}
        return FieldPredictToStringJson(raw)



def GetFieldStripBackend() -> FieldStripBackend:
    global _instance
    with _lock:
        if _instance is None:
            _instance = FieldStripBackend()
        return _instance



def ResetFieldStripBackend() -> None:
    global _instance
    with _lock:
        _instance = None
