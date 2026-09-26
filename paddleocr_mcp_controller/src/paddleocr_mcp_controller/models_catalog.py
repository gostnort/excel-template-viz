"""Local model directory helpers for paddleocr_mcp_controller/models."""

from __future__ import annotations

import shutil
from pathlib import Path

from paddleocr_mcp_controller.config import resolve_models_dir


# paddleocr-mcp local：PP-OCRv6 medium（fast 细条）。Structure 其余权重由首次 predict 拉取。
REQUIRED_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-OCRv6_medium_det",
    "PP-OCRv6_medium_rec",
})

# 旧 PaddleOCR-VL 权重一律删除（仅 CPU，不跑 VL）。
VL_OFFICIAL_MODELS: frozenset[str] = frozenset({
    "PP-DocLayoutV3",
    "PaddleOCR-VL",
    "PaddleOCR-VL-1.5",
    "PaddleOCR-VL-1.6",
})


def _official_root() -> Path:
    """
    函数名: _official_root
    作用: 返回当前解析的 models 目录下的 official_models 子目录。
    输入: 无。
    输出:
        Path: official_models 目录路径（不保证已存在）。
    """
    return resolve_models_dir() / "official_models"


def models_dir_nonempty() -> bool:
    models = resolve_models_dir()
    if not models.is_dir():
        return False
    for path in models.rglob("*"):
        if path.is_file():
            return True
    return False


def required_models_present() -> bool:
    root = _official_root()
    if not root.is_dir():
        return False
    for name in REQUIRED_OFFICIAL_MODELS:
        if not (root / name).is_dir():
            return False
    return True


def list_vl_official_models() -> list[str]:
    """official_models/ 下已知 VL 目录名。"""
    root = _official_root()
    if not root.is_dir():
        return []
    found: list[str] = []
    for path in root.iterdir():
        if path.is_dir() and path.name in VL_OFFICIAL_MODELS:
            found.append(path.name)
    return sorted(found)


def prune_vl_official_models() -> list[str]:
    """
    函数名: prune_vl_official_models
    作用: 删除 official_models/ 下 PaddleOCR-VL 相关目录，释放磁盘。
    输入: 无。
    输出:
        list[str]: 被删除的目录名列表。
    """
    removed: list[str] = []
    root = _official_root()
    for name in list_vl_official_models():
        target = root / name
        shutil.rmtree(target, ignore_errors=True)
        removed.append(name)
    return removed
