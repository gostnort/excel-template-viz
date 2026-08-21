"""Runtime defaults for the paddle_ocr platform."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PLATFORM_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PLATFORM_ROOT.parent
MODELS_DIR = PLATFORM_ROOT / "models"
SAMPLE_IMAGE = PROJECT_ROOT / "test" / "ocr_sample.jpg"
INSTALL_LOG = PROJECT_ROOT / "temp" / "install_paddle_ocr.log"

# PaddleX / PaddleOCR 3.x cache root (set before importing paddleocr).
PDX_CACHE_ENV = "PADDLE_PDX_CACHE_HOME"

DEFAULT_DEVICE = "cpu"
# paddleocr-mcp local 默认：PP-OCRv6 medium（fast）；PP-StructureV3（精修，替代 VL）。
MCP_HOST = "127.0.0.1"
# 五位数端口；避开 8000（常见占用）与 9999（LM Studio）。
MCP_PORT_MIN = 10000
MCP_PORT_MAX = 65535
MCP_PREFERRED_OCR_PORT = 18081
MCP_PREFERRED_STRUCTURE_PORT = 18082
MCP_RESERVED_PORTS = frozenset({8000, 9999})
MCP_START_TIMEOUT_SEC = 600
DEFAULT_OCR_VERSION = "PP-OCRv6"
DEFAULT_OCR_DET_MODEL = "PP-OCRv6_medium_det"
DEFAULT_OCR_REC_MODEL = "PP-OCRv6_medium_rec"
# Full-page cap: only downscale when long side > limit (limit_type=max). Never upscale.
DEFAULT_TEXT_DET_LIMIT_SIDE_LEN = 960
DEFAULT_TEXT_DET_LIMIT_TYPE = "max"
# PaddlePaddle 3.3.x + oneDNN/PIR crash on CPU; keep mkldnn off until framework fix.
DEFAULT_ENABLE_MKLDNN = False
# 内存分级精修：fast=PP-OCRv6；精修=PP-StructureV3（不再加载 PaddleOCR-VL）。
#   < 4GB                  → 仅 fast。
#   4GB ≤ budget < 10GB    → LM Studio 语义检查 + 视觉纠错。
#   10GB ≤ budget < 14GB   → 语义检查 → 卸载 LM Studio → PP-StructureV3。
#   budget ≥ 14GB          → 语义检查的同时可常驻 Structure。
# StructureV3 可 CPU 推理，10GB+ 档不再要求 GPU。
REFINE_MIN_RAM_GB = 4
REFINE_STRUCTURE_MIN_GB = 10
REFINE_BOTH_RESIDENT_MIN_GB = 14

MSG_OK = "识别完成。"
MSG_EMPTY = "未识别到文字，请调整选区或重新拍照。"
MSG_BAD_IMAGE = "无法读取图片，请重新拍照或选择文件。"
MSG_BAD_CROP = "选区无效，请重新框选识别区域。"
MSG_INFER_FAIL = "文字识别失败，请稍后重试。"
MSG_NOT_READY = "OCR 组件未就绪，请重新运行 install.bat 并完成 OCR 安装。"
MSG_MODEL_MISSING = "OCR 模型未就绪，请运行 install.bat 或 python paddle_ocr/main.py 后重试。"
MSG_HEALTH_OK = "OCR 引擎就绪。"
MSG_LLM_PARTIAL = "识别完成（快速结果，精修未生效）。"
MSG_GEMMA_VISION = "识别完成（Gemma4 视觉纠错）。"


def _cudnn_loadable() -> bool:
    """
    函数名: _cudnn_loadable
    作用: Windows 上探测 cudnn64_9.dll 能否加载；其它平台视为可用。
    输入: 无。
    输出:
        bool: True=可走 GPU paddle。
    """
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        ctypes.WinDLL("cudnn64_9.dll")
        return True
    except OSError:
        return False



def resolve_device() -> str:
    """
    函数名: resolve_device
    作用: 决定 paddleocr-mcp --device。OCR_PROFILE 优先；否则需 GPU 包+cuDNN 才用 gpu。
    输入: 无。
    输出:
        str: "gpu" 或 "cpu"。
    """
    profile = os.environ.get("OCR_PROFILE", "").strip().lower()
    if profile in ("cuda", "gpu"):
        return "gpu"
    if profile == "cpu":
        return "cpu"
    try:
        from paddle_ocr.gate.hardware_probe import AcceleratorAvailable
        if AcceleratorAvailable() and _cudnn_loadable():
            return "gpu"
    except Exception:
        pass
    return DEFAULT_DEVICE



def ensure_pdx_cache_env() -> Path:
    """
    函数名: ensure_pdx_cache_env
    作用: 把 PaddleX 模型缓存指到 paddle_ocr/models，并压低 paddle 日志。MCP 子进程继承环境。
    输入: 无。
    输出:
        Path: 缓存目录。
    """
    import warnings
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(PDX_CACHE_ENV, str(MODELS_DIR))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("GLOG_logtostderr", "0")
    warnings.filterwarnings("ignore", module="paddle.utils.cpp_extension.extension_utils")
    return Path(os.environ[PDX_CACHE_ENV])
