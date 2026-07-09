"""Download / warm PPStructureV3 (+ OCR) models into paddle_ocr/models."""

from __future__ import annotations

import logging
from pathlib import Path

from paddle_ocr import config
from paddle_ocr.models_catalog import models_dir_nonempty


_log = logging.getLogger(__name__)


def download_models() -> tuple[bool, str]:
    """Materialize structure weights under paddle_ocr/models via PADDLE_PDX_CACHE_HOME."""
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.ensure_pdx_cache_env()
    config.INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            from paddle_ocr.main import PaddleOcr
            sample = config.SAMPLE_IMAGE
            if sample.is_file():
                result = PaddleOcr(sample, None)
            else:
                import numpy as np
                from paddle_ocr.runtime.structure_backend import GetStructureBackend
                blank = np.zeros((64, 64, 3), dtype=np.uint8)
                # Force engine init + predict via backend
                backend = GetStructureBackend()
                engine = backend._ensure_engine()
                if engine is None:
                    raise RuntimeError("structure engine missing")
                engine.predict(blank)
                result = {"ok": True}
            if result.get("ok") or models_dir_nonempty():
                ok_msg = f"models ready under {config.MODELS_DIR} (nonempty={models_dir_nonempty()})"
                _append_log(ok_msg)
                return True, ok_msg
            last_err = RuntimeError(result.get("message") or "download predict not ok")
        except Exception as exc:
            last_err = exc
            _log.exception("download attempt %s failed", attempt + 1)
            _append_log(f"attempt {attempt + 1} failed: {exc}")
    msg = f"download failed after retry: {last_err}"
    _append_log(msg)
    return False, config.MSG_MODEL_MISSING


def _append_log(line: str) -> None:
    try:
        path = config.INSTALL_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    ok, message = download_models()
    print(message)
    raise SystemExit(0 if ok else 1)
