"""Download / warm only required PP-OCR + PP-Structure models into paddle_ocr/models."""

from __future__ import annotations

from pathlib import Path

from paddle_ocr import config
from paddle_ocr.models_catalog import (
    prune_extra_official_models,
    required_models_present,
)


# Same REGION1 strip as test/paddle_ocr (warms textline + v4 mobile field stack).
_WARM_REGION1_BOX = (445, 629, 1040, 84)



def download_models() -> tuple[bool, str]:
    """Warm field + structure paths, then drop any non-required official_models."""
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.ensure_pdx_cache_env()
    config.INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    prune_extra_official_models()
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            sample = config.SAMPLE_IMAGE
            if sample.is_file():
                from paddle_ocr.main import PaddleOcr
                PaddleOcr(sample, _WARM_REGION1_BOX)
                result = PaddleOcr(sample, None)
            else:
                import numpy as np
                from paddle_ocr.runtime.field_backend import GetFieldStripBackend
                from paddle_ocr.runtime.structure_backend import GetStructureBackend
                strip = np.zeros((84, 1040, 3), dtype=np.uint8)
                page = np.zeros((960, 640, 3), dtype=np.uint8)
                field = GetFieldStripBackend().Run(strip)
                if not field.get("ok"):
                    raise RuntimeError(field.get("message") or "field warm failed")
                backend = GetStructureBackend()
                engine = backend._ensure_engine()
                if engine is None:
                    raise RuntimeError("structure engine missing")
                engine.predict(page)
                result = {"ok": True}
            prune_extra_official_models()
            if required_models_present() and (result.get("ok") or required_models_present()):
                ok_msg = f"required models ready under {config.MODELS_DIR}"
                _append_log(ok_msg)
                return True, ok_msg
            last_err = RuntimeError(result.get("message") or "warm predict not ok")
        except Exception as exc:
            last_err = exc
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
