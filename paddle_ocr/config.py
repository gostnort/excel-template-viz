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

DEFAULT_DEVICE = "cpu"
# Full-page cap: only downscale when long side > limit (limit_type=max). Never upscale.
DEFAULT_TEXT_DET_LIMIT_SIDE_LEN = 960
DEFAULT_TEXT_DET_LIMIT_TYPE = "max"
# Thin-strip field OCR: mobile det/rec (faster on CPU; original pixels at predict).
DEFAULT_FIELD_DET_MODEL = "PP-OCRv4_mobile_det"
DEFAULT_FIELD_REC_MODEL = "PP-OCRv4_mobile_rec"
# PP-Structure text stack: same mobile pair (avoid also loading PP-OCRv5_server_*).
DEFAULT_STRUCTURE_DET_MODEL = DEFAULT_FIELD_DET_MODEL
DEFAULT_STRUCTURE_REC_MODEL = DEFAULT_FIELD_REC_MODEL
# PaddlePaddle 3.3.x + oneDNN/PIR crash on CPU; keep mkldnn off until framework fix.
DEFAULT_ENABLE_MKLDNN = False

MSG_OK = "识别完成。"
MSG_EMPTY = "未识别到文字，请调整选区或重新拍照。"
MSG_BAD_IMAGE = "无法读取图片，请重新拍照或选择文件。"
MSG_BAD_CROP = "选区无效，请重新框选识别区域。"
MSG_INFER_FAIL = "文字识别失败，请稍后重试。"
MSG_NOT_READY = "OCR 组件未就绪，请重新运行 install.bat 并完成 OCR 安装。"
MSG_MODEL_MISSING = "OCR 模型未就绪，请运行 install.bat 或 python paddle_ocr/main.py 后重试。"
MSG_HEALTH_OK = "OCR 引擎就绪。"


def resolve_device() -> str:
    profile = os.environ.get("OCR_PROFILE", "").strip().lower()
    if profile in ("cuda", "gpu"):
        return "gpu"
    if profile == "cpu":
        return "cpu"
    return DEFAULT_DEVICE



def ensure_pdx_cache_env() -> Path:
    """Point PaddleX model cache at paddle_ocr/models before paddleocr import."""
    import warnings
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(PDX_CACHE_ENV, str(MODELS_DIR))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("GLOG_logtostderr", "0")
    warnings.filterwarnings("ignore", module="paddle.utils.cpp_extension.extension_utils")
    return Path(os.environ[PDX_CACHE_ENV])
