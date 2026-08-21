"""Local model directory helpers for paddle_ocr/models."""

from __future__ import annotations

import shutil

from paddle_ocr.config import MODELS_DIR


OFFICIAL_MODELS_ROOT = MODELS_DIR / "official_models"

# paddleocr-mcp local：PP-OCRv6 medium（fast 细条）。Structure 其余权重由首次 predict 拉取。
REQUIRED_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec",
})

# 旧 PaddleOCR-VL 权重一律删除（客户机带不动；精修改走 PP-StructureV3）。
VL_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-DocLayoutV3",
    "PaddleOCR-VL",
    "PaddleOCR-VL-1.5",
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



def list_vl_official_models() -> list[str]:
    """official_models/ 下已知 VL 目录名。"""
    if not OFFICIAL_MODELS_ROOT.is_dir():
        return []
    found: list[str] = []
    for path in OFFICIAL_MODELS_ROOT.iterdir():
        if path.is_dir() and path.name in VL_OFFICIAL_MODELS:
            found.append(path.name)
    return sorted(found)



def prune_vl_official_models() -> list[str]:
    """
    函数名: prune_vl_official_models
    作用: 删除 official_models/ 下 PaddleOCR-VL 相关目录，释放客户机磁盘。
    输入: 无。
    输出:
        list[str]: 被删除的目录名列表。
    """
    removed: list[str] = []
    for name in list_vl_official_models():
        target = OFFICIAL_MODELS_ROOT / name
        shutil.rmtree(target, ignore_errors=True)
        removed.append(name)
    return removed


# 兼容旧调用名：不再保留 VL。
def prune_extra_official_models(keep_vl: bool = False) -> list[str]:
    """
    函数名: prune_extra_official_models
    作用: 兼容旧安装脚本；始终删除 VL 权重（keep_vl 忽略）。
    输入:
        keep_vl (bool): 已废弃，始终按 False 处理。
    输出:
        list[str]: 被删除的目录名列表。
    """
    _ = keep_vl
    return prune_vl_official_models()
