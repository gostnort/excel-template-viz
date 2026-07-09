"""PaddleOCR 3.x backend: lazy singleton + serialized recognize."""

from __future__ import annotations

import logging
import threading
from typing import Protocol

from paddle_ocr import config
from paddle_ocr.runtime import HealthReport, OcrResult
from paddle_ocr.runtime.image_decode import (
    CropBoxError,
    ImageDecodeError,
    apply_crop_box,
    decode_image,
    prepare_for_predict,
)
from paddle_ocr.runtime.postprocess import extract_lines, join_text


_log = logging.getLogger(__name__)
_lock = threading.Lock()
_instance: "PaddleOcrBackend | None" = None


class OcrBackend(Protocol):
    def recognize(
        self,
        image,
        *,
        crop_box: tuple[int, int, int, int] | None = None,
        lang: str = "ch",
        task: str = "field",
    ) -> OcrResult: ...

    def health_check(self) -> HealthReport: ...



class PaddleOcrBackend:
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

    def _ensure_engine(self, lang: str | None = None):
        if self._engine is not None:
            return self._engine
        if self._init_error:
            return None
        config.ensure_pdx_cache_env()
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:
            _log.exception("paddleocr import failed")
            self._init_error = "import"
            return None
        try:
            self._engine = PaddleOCR(**config.paddle_ocr_init_kwargs(lang))
            self._package_version()
            return self._engine
        except Exception as exc:
            _log.exception("PaddleOCR init failed: %s", exc)
            self._init_error = "init"
            self._engine = None
            return None

    def health_check(self) -> HealthReport:
        ver = self._package_version()
        # Import paddleocr before paddle on Windows; reverse order can pull broken torch via modelscope.
        engine = self._ensure_engine()
        if engine is None:
            if self._init_error == "import":
                return HealthReport(ok=False, message=config.MSG_NOT_READY, version=ver)
            return HealthReport(ok=False, message=config.MSG_MODEL_MISSING, version=ver)
        return HealthReport(ok=True, message=config.MSG_HEALTH_OK, version=self._package_version())

    def recognize(
        self,
        image,
        *,
        crop_box: tuple[int, int, int, int] | None = None,
        lang: str = "ch",
        task: str = "field",
    ) -> OcrResult:
        ver = self._package_version()
        if task != config.DEFAULT_TASK:
            return OcrResult(ok=False, message=config.MSG_TASK_UNSUPPORTED, version=ver)
        try:
            img = decode_image(image)
            img = apply_crop_box(img, crop_box)
            img = prepare_for_predict(img)
        except ImageDecodeError:
            return OcrResult(ok=False, message=config.MSG_BAD_IMAGE, version=ver)
        except CropBoxError:
            return OcrResult(ok=False, message=config.MSG_BAD_CROP, version=ver)
        except Exception:
            _log.exception("decode/crop failed")
            return OcrResult(ok=False, message=config.MSG_BAD_IMAGE, version=ver)
        with self._infer_lock:
            engine = self._ensure_engine(lang=lang)
            if engine is None:
                msg = config.MSG_NOT_READY if self._init_error == "import" else config.MSG_MODEL_MISSING
                return OcrResult(ok=False, message=msg, version=ver)
            try:
                raw = engine.predict(img)
            except Exception:
                _log.exception("predict failed")
                return OcrResult(ok=False, message=config.MSG_INFER_FAIL, version=ver)
        lines = extract_lines(raw)
        text = join_text(lines)
        if text.strip() == "":
            return OcrResult(
                ok=True,
                text="",
                lines=lines,
                engine=config.ENGINE_NAME,
                version=ver,
                message=config.MSG_EMPTY,
            )
        return OcrResult(
            ok=True,
            text=text,
            lines=lines,
            engine=config.ENGINE_NAME,
            version=ver,
            message=config.MSG_OK,
        )



def get_backend() -> PaddleOcrBackend:
    global _instance
    with _lock:
        if _instance is None:
            _instance = PaddleOcrBackend()
        return _instance
