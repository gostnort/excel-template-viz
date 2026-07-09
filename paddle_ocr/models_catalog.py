"""Model catalog and local path helpers for paddle_ocr/models."""

from __future__ import annotations

from pathlib import Path

from paddle_ocr.config import MODELS_DIR, ensure_pdx_cache_env


# Default pipeline names used by PaddleOCR 3.7+ when lang=ch (auto-downloaded).
DEFAULT_DET_MODEL = "PP-OCRv6_medium_det"
DEFAULT_REC_MODEL = "PP-OCRv6_medium_rec"
DEFAULT_TEXTLINE_ORIENTATION_MODEL = "PP-LCNet_x1_0_textline_ori"


def models_root() -> Path:
    return ensure_pdx_cache_env()


def catalog_summary() -> dict[str, str]:
    root = models_root()
    return {
        "models_dir": str(root),
        "det": DEFAULT_DET_MODEL,
        "rec": DEFAULT_REC_MODEL,
        "textline_orientation": DEFAULT_TEXTLINE_ORIENTATION_MODEL,
    }


def models_dir_nonempty() -> bool:
    root = MODELS_DIR
    if not root.is_dir():
        return False
    for _ in root.rglob("*"):
        if _.is_file():
            return True
    return False
