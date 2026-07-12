"""Download / warm only required PP-OCR + PP-Structure models into paddle_ocr/models."""

from __future__ import annotations

from pathlib import Path

from paddle_ocr import config
from paddle_ocr.gate.hardware_probe import AcceleratorAvailable, detect_accelerator
from paddle_ocr.gate.memory_guard import init_refine_path
from paddle_ocr.models_catalog import (
    prune_extra_official_models,
    required_models_present,
)


# Same REGION1 strip as test/paddle_ocr (warms textline + v4 mobile field stack).
_WARM_REGION1_BOX = (445, 629, 1040, 84)



def _warm_vl(sample) -> None:
    """Warm PaddleOCRVL(GPU) on sample；仅 AcceleratorAvailable（paddlepaddle-gpu 已装）时才预热。

    硬件在但库未装时跳过（VL 模型下载由 scripts/install_backend.py 在装好库后负责）。
    """
    if not AcceleratorAvailable():
        return
    try:
        from paddle_ocr.engines.paddle_vl.backend import GetVlBackend
        backend = GetVlBackend()
        backend.warm()
        engine = backend._ensure_engine()
        if engine is None:
            return
        if sample is not None and Path(sample).is_file():
            from paddle_ocr.runtime.image_decode import load_for_ocr
            engine.predict(load_for_ocr(sample, None))
        else:
            import numpy as np
            engine.predict(np.zeros((960, 640, 3), dtype=np.uint8))
    except Exception:
        # VL warm 是可选增强；失败不应阻断 fast 模型就绪。
        pass



def download_models() -> tuple[bool, str]:
    """Warm field + structure paths, then drop any non-required official_models."""
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.ensure_pdx_cache_env()
    config.INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    init_refine_path()
    # VL 模型按硬件去留：有加速器硬件 → 保留；纯 CPU → prune。
    keep_vl = detect_accelerator() in ("gpu", "npu")
    prune_extra_official_models(keep_vl=keep_vl)
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
                from paddle_ocr.engines.pp_ocr.backend import GetFieldStripBackend
                from paddle_ocr.engines.pp_structure.backend import GetStructureBackend
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
            # fast 热启动完成后，仅 AcceleratorAvailable 才预热 VL（GPU）。
            if keep_vl:
                _warm_vl(sample if sample.is_file() else None)
            prune_extra_official_models(keep_vl=keep_vl)
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
