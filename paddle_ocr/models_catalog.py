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

# PaddleOCRVL v1.6 refine path; only kept when RefinePathEnabled (≥7GB available RAM).
# Names match the actual official_models dir names PaddleX creates on download.
OPTIONAL_VL_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-DocLayoutV3",
    "PaddleOCR-VL-1.6",
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



def vl_models_present() -> bool:
    """True when all OPTIONAL_VL_OFFICIAL_MODELS dirs exist on disk."""
    if not OFFICIAL_MODELS_ROOT.is_dir():
        return False
    for name in OPTIONAL_VL_OFFICIAL_MODELS:
        if not (OFFICIAL_MODELS_ROOT / name).is_dir():
            return False
    return True



def list_extra_official_models(keep_vl: bool = False) -> list[str]:
    """Dir names not in REQUIRED_OFFICIAL_MODELS (and not VL when keep_vl=True)."""
    if not OFFICIAL_MODELS_ROOT.is_dir():
        return []
    allowed = REQUIRED_OFFICIAL_MODELS | (OPTIONAL_VL_OFFICIAL_MODELS if keep_vl else frozenset())
    extras: list[str] = []
    for path in OFFICIAL_MODELS_ROOT.iterdir():
        if not path.is_dir():
            continue
        if path.name not in allowed:
            extras.append(path.name)
    return sorted(extras)



def prune_extra_official_models(keep_vl: bool = False) -> list[str]:
    """
    函数名: prune_extra_official_models
    作用: 删除 official_models/ 下不在 REQUIRED 集合里的模型目录。keep_vl=True 时
        保留 OPTIONAL_VL_OFFICIAL_MODELS（RefinePathEnabled 时）；keep_vl=False 时
        连 VL 模型一起删（低内存机器保持磁盘干净）。
    输入:
        keep_vl (bool): True=保留 VL 模型；False=连 VL 一起 prune。
    输出:
        list[str]: 被删除的目录名列表。
    """
    removed: list[str] = []
    for name in list_extra_official_models(keep_vl=keep_vl):
        target = OFFICIAL_MODELS_ROOT / name
        shutil.rmtree(target, ignore_errors=True)
        removed.append(name)
    return removed

