"""Local model directory helpers for paddle_ocr/models."""

from __future__ import annotations

import shutil

from paddle_ocr.config import MODELS_DIR


OFFICIAL_MODELS_ROOT = MODELS_DIR / "official_models"

# PP-OCR strip + PP-Structure full page (v4 mobile, no DocBlock / v5 / doc_ori / VL).
REQUIRED_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-OCRv4_mobile_det",
    "PP-OCRv4_mobile_rec",
    "PP-LCNet_x1_0_textline_ori",
    "PP-DocLayout_plus-L",
    "PP-LCNet_x1_0_table_cls",
    "SLANeXt_wired",
    "SLANet_plus",
    "RT-DETR-L_wired_table_cell_det",
    "RT-DETR-L_wireless_table_cell_det",
})



def models_dir_nonempty() -> bool:
    if not MODELS_DIR.is_dir():
        return False
    for path in MODELS_DIR.rglob("*"):
        if path.is_file():
            return True
    return False



def required_models_present() -> bool:
    if not OFFICIAL_MODELS_ROOT.is_dir():
        return False
    for name in REQUIRED_OFFICIAL_MODELS:
        if not (OFFICIAL_MODELS_ROOT / name).is_dir():
            return False
    return True



def list_extra_official_models() -> list[str]:
    if not OFFICIAL_MODELS_ROOT.is_dir():
        return []
    extras: list[str] = []
    for path in OFFICIAL_MODELS_ROOT.iterdir():
        if not path.is_dir():
            continue
        if path.name not in REQUIRED_OFFICIAL_MODELS:
            extras.append(path.name)
    return sorted(extras)



def prune_extra_official_models() -> list[str]:
    """Remove official_models/* not in REQUIRED_OFFICIAL_MODELS."""
    removed: list[str] = []
    for name in list_extra_official_models():
        target = OFFICIAL_MODELS_ROOT / name
        shutil.rmtree(target, ignore_errors=True)
        removed.append(name)
    return removed
