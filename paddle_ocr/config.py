"""Runtime defaults for the paddle_ocr platform."""

from __future__ import annotations

import os
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PLATFORM_ROOT.parent
MODELS_DIR = PLATFORM_ROOT / "models"
SAMPLE_IMAGE = PROJECT_ROOT / "test" / "ocr_sample.jpg"
INSTALL_LOG = PROJECT_ROOT / "temp" / "install_paddle_ocr.log"

# PaddleX / PaddleOCR 3.x cache root (set before importing paddleocr).
PDX_CACHE_ENV = "PADDLE_PDX_CACHE_HOME"

DEFAULT_LANG = "ch"
DEFAULT_DEVICE = "cpu"
DEFAULT_TASK = "field"
DEFAULT_USE_TEXTLINE_ORIENTATION = True
DEFAULT_USE_DOC_ORIENTATION_CLASSIFY = False
DEFAULT_USE_DOC_UNWARPING = False
DEFAULT_TEXT_DET_LIMIT_SIDE_LEN = 960
# Prefer max-side limit: limit_type=min upscales thin field crops (e.g. h=84 → 960)
# into multi-thousand-pixel widths and triggers max_side_limit warnings + bad OCR.
DEFAULT_TEXT_DET_LIMIT_TYPE = "max"
# PaddlePaddle 3.3.x + oneDNN/PIR crash on CPU; keep mkldnn off until framework fix.
DEFAULT_ENABLE_MKLDNN = False

ENGINE_NAME = "paddleocr"

MSG_OK = "识别完成。"
MSG_EMPTY = "未识别到文字，请调整选区或重新拍照。"
MSG_BAD_IMAGE = "无法读取图片，请重新拍照或选择文件。"
MSG_BAD_CROP = "选区无效，请重新框选识别区域。"
MSG_INFER_FAIL = "文字识别失败，请稍后重试。"
MSG_NOT_READY = "OCR 组件未就绪，请重新运行 install.bat 并完成 OCR 安装。"
MSG_MODEL_MISSING = "OCR 模型未就绪，请运行 python paddle_ocr/main.py download 后重试。"
MSG_HEALTH_OK = "OCR 引擎就绪。"
MSG_TASK_UNSUPPORTED = "当前仅支持字段级识别（task=field）。"


def resolve_lang(override: str | None = None) -> str:
    if override:
        return override
    env = os.environ.get("OCR_LANG", "").strip()
    if env:
        return env
    return DEFAULT_LANG


def resolve_device() -> str:
    profile = os.environ.get("OCR_PROFILE", "").strip().lower()
    if profile in ("cuda", "gpu"):
        return "gpu"
    if profile == "cpu":
        return "cpu"
    return DEFAULT_DEVICE


def ensure_pdx_cache_env() -> Path:
    """Point PaddleX model cache at paddle_ocr/models before paddleocr import."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(PDX_CACHE_ENV, str(MODELS_DIR))
    # Skip slow hoster connectivity probe during install/smoke.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    return Path(os.environ[PDX_CACHE_ENV])


def paddle_ocr_init_kwargs(lang: str | None = None) -> dict:
    """Shared constructor kwargs for PaddleOCR 3.x (CPU-safe defaults)."""
    return {
        "lang": resolve_lang(lang),
        "device": resolve_device(),
        "use_textline_orientation": DEFAULT_USE_TEXTLINE_ORIENTATION,
        "use_doc_orientation_classify": DEFAULT_USE_DOC_ORIENTATION_CLASSIFY,
        "use_doc_unwarping": DEFAULT_USE_DOC_UNWARPING,
        "text_det_limit_side_len": DEFAULT_TEXT_DET_LIMIT_SIDE_LEN,
        "text_det_limit_type": DEFAULT_TEXT_DET_LIMIT_TYPE,
        "enable_mkldnn": DEFAULT_ENABLE_MKLDNN,
    }
