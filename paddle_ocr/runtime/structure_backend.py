"""PPStructureV3 fast backend for PaddleOcr()."""

from __future__ import annotations

import logging
import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, apply_crop_box, decode_image, prepare_for_predict
from paddle_ocr.runtime.postprocess import HasContent, StructureResultToJson


_log = logging.getLogger(__name__)
_lock = threading.Lock()
_instance: "StructureBackend | None" = None



class StructureBackend:
    def __init__(self) -> None:
        self._engine = None
        self._version = ""
        self._init_error: str | None = None
        self._infer_lock = threading.Lock()

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
            from paddleocr import PPStructureV3
        except Exception:
            _log.exception("PPStructureV3 import failed")
            self._init_error = "import"
            return None
        try:
            self._engine = PPStructureV3(
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_seal_recognition=False,
                use_formula_recognition=False,
                use_chart_recognition=False,
                enable_mkldnn=config.DEFAULT_ENABLE_MKLDNN,
                device=config.resolve_device(),
            )
            self._package_version()
            return self._engine
        except Exception:
            _log.exception("PPStructureV3 init failed")
            self._init_error = "init"
            self._engine = None
            return None

    def HealthCheck(self) -> dict[str, Any]:
        ver = self._package_version()
        engine = self._ensure_engine()
        if engine is None:
            msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
            return {"ok": False, "message": msg, "version": ver}
        return {"ok": True, "message": config.MSG_HEALTH_OK, "version": self._package_version()}

    def Run(
        self,
        pic,
        rectangle: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        ver = self._package_version()
        try:
            img = decode_image(pic)
            img = apply_crop_box(img, rectangle)
            img = prepare_for_predict(img)
        except ImageDecodeError:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver}
        except CropBoxError:
            return {"ok": False, "message": config.MSG_BAD_CROP, "version": ver}
        except Exception:
            _log.exception("decode/crop failed")
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver}
        with self._infer_lock:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "version": ver}
            try:
                raw = engine.predict(img)
            except Exception:
                _log.exception("PPStructureV3 predict failed")
                return {"ok": False, "message": config.MSG_INFER_FAIL, "version": ver, "mode": "fast"}
        result = StructureResultToJson(raw, mode="fast")
        result["version"] = self._package_version()
        if not HasContent(result):
            result["message"] = config.MSG_EMPTY
        return result



def GetStructureBackend() -> StructureBackend:
    global _instance
    with _lock:
        if _instance is None:
            _instance = StructureBackend()
        return _instance
