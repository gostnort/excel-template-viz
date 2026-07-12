"""PPStructureV3 fast backend for PaddleOcr()."""

from __future__ import annotations

import threading
from typing import Any

from paddle_ocr import config
from paddle_ocr.engines.pp_ocr.backend import GetFieldStripBackend
from paddle_ocr.models_catalog import required_models_present
from paddle_ocr.runtime.image_decode import CropBoxError, ImageDecodeError, load_for_ocr
from paddle_ocr.runtime.infer_lock import INFER_LOCK
from paddle_ocr.runtime.postprocess import HasContent, StructureResultToJson
from paddle_ocr.runtime.table_grid import HasTableGrid


_lock = threading.Lock()
_instance: "StructureBackend | None" = None



class StructureBackend:
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
            from paddleocr import PPStructureV3
            from paddlex.utils import logging as pdx_logging
            pdx_logging._logger.disabled = True
        except Exception:
            self._init_error = "import"
            return None
        try:
            self._engine = PPStructureV3(
                text_detection_model_name=config.DEFAULT_STRUCTURE_DET_MODEL,
                text_recognition_model_name=config.DEFAULT_STRUCTURE_REC_MODEL,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
                use_seal_recognition=False,
                use_formula_recognition=False,
                use_chart_recognition=False,
                # Skip PP-DocBlockLayout; layout blocks come from PP-DocLayout_plus-L only.
                use_region_detection=False,
                text_det_limit_side_len=config.DEFAULT_TEXT_DET_LIMIT_SIDE_LEN,
                text_det_limit_type=config.DEFAULT_TEXT_DET_LIMIT_TYPE,
                enable_mkldnn=config.DEFAULT_ENABLE_MKLDNN,
                device=config.resolve_device(),
            )
            self._package_version()
            return self._engine
        except Exception:
            self._init_error = "init"
            self._engine = None
            return None

    def HealthCheck(self) -> dict[str, Any]:
        """Import + cache-dir gate only; does not load PP-Structure weights."""
        ver = self._package_version()
        if self._init_error == "import":
            return {"ok": False, "message": config.MSG_NOT_READY, "version": ver}
        config.ensure_pdx_cache_env()
        try:
            from paddleocr import PPStructureV3  # noqa: F401
        except Exception:
            self._init_error = "import"
            return {"ok": False, "message": config.MSG_NOT_READY, "version": ver}
        if not required_models_present():
            return {"ok": False, "message": config.MSG_MODEL_MISSING, "version": ver}
        return {"ok": True, "message": config.MSG_HEALTH_OK, "version": ver}

    def _use_field_ocr(self, img, rectangle: tuple[int, int, int, int] | None) -> bool:
        if rectangle is None:
            return False
        return not HasTableGrid(img)

    def _det_limit_kwargs(self, img) -> dict[str, Any]:
        """Crops: detect at original pixels (no upscale). Full page: downscale-only cap."""
        height, width = int(img.shape[0]), int(img.shape[1])
        long_side = max(height, width)
        return {
            "text_det_limit_type": config.DEFAULT_TEXT_DET_LIMIT_TYPE,
            "text_det_limit_side_len": long_side,
        }

    def _predict_kwargs(self, img, rectangle: tuple[int, int, int, int] | None) -> dict[str, Any]:
        kwargs = self._det_limit_kwargs(img)
        # Keep predict-time flags aligned with init so PaddleX does not lazy-load
        # doc-orient / textline / v5-server stacks we never use.
        kwargs["use_doc_orientation_classify"] = False
        kwargs["use_doc_unwarping"] = False
        kwargs["use_textline_orientation"] = False
        kwargs["use_seal_recognition"] = False
        kwargs["use_formula_recognition"] = False
        kwargs["use_chart_recognition"] = False
        kwargs["use_table_orientation_classify"] = False
        kwargs["use_region_detection"] = False
        # Golden samples use wired tables; skip wireless e2e path at predict time.
        kwargs["use_e2e_wireless_table_rec_model"] = False
        kwargs["use_ocr_results_with_table_cells"] = True
        if rectangle is None:
            kwargs["text_det_limit_side_len"] = config.DEFAULT_TEXT_DET_LIMIT_SIDE_LEN
            return kwargs
        return kwargs

    def Run(
        self,
        pic,
        rectangle: tuple[int, int, int, int] | None = None,
    ) -> dict[str, Any]:
        ver = self._package_version()
        try:
            img = load_for_ocr(pic, rectangle)
        except ImageDecodeError:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver}
        except CropBoxError:
            return {"ok": False, "message": config.MSG_BAD_CROP, "version": ver}
        except Exception:
            return {"ok": False, "message": config.MSG_BAD_IMAGE, "version": ver}
        if self._use_field_ocr(img, rectangle):
            result = GetFieldStripBackend().Run(img)
            result["version"] = ver
            return result
        with INFER_LOCK:
            engine = self._ensure_engine()
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return {"ok": False, "message": msg, "version": ver}
            try:
                predict_kwargs = self._predict_kwargs(img, rectangle)
                raw = engine.predict(img, **predict_kwargs)
            except Exception:
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



def ResetStructureBackend() -> None:
    """Drop singleton so next call picks up OCR_PROFILE / device changes."""
    global _instance
    with _lock:
        _instance = None
