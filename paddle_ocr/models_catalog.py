"""Local model directory helpers for paddle_ocr/models."""

from __future__ import annotations

from paddle_ocr.config import MODELS_DIR


def models_dir_nonempty() -> bool:
    if not MODELS_DIR.is_dir():
        return False
    for path in MODELS_DIR.rglob("*"):
        if path.is_file():
            return True
    return False
