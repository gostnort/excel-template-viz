"""Download Gemma 4 weights from Hugging Face Hub."""

from __future__ import annotations

import sys
from pathlib import Path

from llm_gemma4.models_catalog import (
    GGUF_DIR,
    GGUF_FILENAME,
    GGUF_REPO,
    OV_INT4_DIR,
    OV_INT4_REPO,
    OV_MARKER_FILES,
)


class DownloadError(Exception):
    """User-facing download failure."""


def gguf_weight_path() -> Path:
    return GGUF_DIR / GGUF_FILENAME


def gguf_present() -> bool:
    return gguf_weight_path().is_file()


def openvino_present() -> bool:
    if not OV_INT4_DIR.is_dir():
        return False
    return any((OV_INT4_DIR / name).is_file() for name in OV_MARKER_FILES)


def download_gguf(*, force: bool = False) -> Path:
    """Download GGUF Q4_0 into models/gemma4/."""
    dest = gguf_weight_path()
    if dest.is_file() and not force:
        return dest
    _require_hub()
    from huggingface_hub import hf_hub_download
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {GGUF_REPO} / {GGUF_FILENAME} ...")
    try:
        cached = hf_hub_download(
            repo_id=GGUF_REPO,
            filename=GGUF_FILENAME,
            local_dir=str(GGUF_DIR),
            local_dir_use_symlinks=False,
        )
    except Exception as exc:
        raise DownloadError(
            f"GGUF download failed: {exc}\n"
            f"See https://huggingface.co/{GGUF_REPO}"
        ) from exc
    path = Path(cached)
    if path.is_file():
        return path
    if dest.is_file():
        return dest
    raise DownloadError(f"Download finished but file missing: {dest}")


def download_openvino_int4(*, force: bool = False) -> Path:
    """Snapshot OpenVINO INT4 IR into models/gemma4-openvino-int4/."""
    if openvino_present() and not force:
        return OV_INT4_DIR
    _require_hub()
    from huggingface_hub import snapshot_download
    OV_INT4_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {OV_INT4_REPO} (snapshot) ...")
    try:
        snapshot_download(
            repo_id=OV_INT4_REPO,
            local_dir=str(OV_INT4_DIR),
            local_dir_use_symlinks=False,
        )
    except Exception as exc:
        raise DownloadError(
            f"OpenVINO INT4 download failed: {exc}\n"
            f"See https://huggingface.co/{OV_INT4_REPO}"
        ) from exc
    if not openvino_present():
        raise DownloadError(
            f"Snapshot saved under {OV_INT4_DIR} but IR markers not found"
        )
    return OV_INT4_DIR


def _require_hub() -> None:
    try:
        import huggingface_hub  # noqa: F401
    except ImportError as exc:
        raise DownloadError(
            f"huggingface_hub not installed. Run: {sys.executable} -m pip install huggingface-hub"
        ) from exc
