"""Runtime defaults for paddleocr_mcp_controller (CPU only)."""

from __future__ import annotations

import os
import warnings
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]
# 中文注释: 默认 models 落在源码树内（独立跑 / editable 时 PACKAGE_ROOT 即源码根）
_DEFAULT_MODELS_DIR = PACKAGE_ROOT / "models"
# 中文注释: 用户可用此环境变量把 models 指到任意位置，解耦 models 与包安装位置
MODELS_ENV = "PADDLEOCR_MCP_MODELS_DIR"
SAMPLE_IMAGE = PROJECT_ROOT / "test" / "ocr_sample.jpg"
INSTALL_LOG = PACKAGE_ROOT / "install.log"

# PaddleX / PaddleOCR 3.x cache root (set before importing paddleocr).
PDX_CACHE_ENV = "PADDLE_PDX_CACHE_HOME"

DEFAULT_DEVICE = "cpu"

# paddleocr-mcp HTTP 子进程端口
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
# 大图预处理（送 MCP 之前）：min(w,h)>2048 时等比缩小到短边==2048；短边<=2048 不放大。
OCR_PRESCALE_MIN_SIDE = 2048
# MCP 检测：type=max，limit=送出图的长边（预处理之后）。禁止再传 960。
DEFAULT_TEXT_DET_LIMIT_TYPE = "max"
# PaddlePaddle 3.3.x + oneDNN/PIR crash on CPU; keep mkldnn off until framework fix.
DEFAULT_ENABLE_MKLDNN = False
# 第 3 步：仅当 LM 分低于此阈值才采纳 proposed。
SIMILARITY_ADOPT_BELOW = 35
# PDF2MD：渲染 DPI；抽出文本去空白后少于此字符数视为图片/扫描页。
# 150 用于文本页/OCR 页/矢量轮廓页（分支3）；表格页单独用更低的 DPI（见下）。
PDF2MD_RENDER_DPI = 150
# 表格页（分支1 矢量表格 + 分支3 chart）渲染 DPI；低于文本页以削减像素量、加速 Structure。
PDF2MD_TABLE_RENDER_DPI = 110
PDF2MD_TEXT_CHAR_MIN = 80
# Opt2：表格页并行 Structure 工作进程数；0/1 走单进程串行回退。
PDF2MD_PARALLEL_WORKERS = max(1, (os.cpu_count() or 2) // 2)
# Opt2：Structure MCP 池端口分配基址；池内第 i 个 server 用 base+i（仍经 pick_free_mcp_port 校验空闲）。
STRUCTURE_MCP_PORT_BASE = 18090
# 分支2 嵌入图过滤：短边小于此像素的图（mask/装饰）跳过不送 OCR/Structure。
PDF2MD_IMAGE_MIN_SIDE = 16
PDF2MD_PAGE_NAME = "{stem}_p{page:04d}.md"

MSG_OK = "识别完成。"
MSG_EMPTY = "未识别到文字，请调整选区或重新拍照。"
MSG_BAD_IMAGE = "无法读取图片，请重新拍照或选择文件。"
MSG_BAD_CROP = "选区无效，请重新框选识别区域。"
MSG_INFER_FAIL = "文字识别失败，请稍后重试。"
MSG_NOT_READY = "OCR 组件未就绪，请运行 python install.py 后重试。"
MSG_MODEL_MISSING = "OCR 模型未就绪，请运行 python install.py 后重试。"
MSG_HEALTH_OK = "OCR 引擎就绪。"
MSG_LLM_PARTIAL = "识别完成（快速结果，精修未生效）。"
MSG_PDF2MD_OK = "PDF 已转为 Markdown。"
MSG_PDF2MD_PARTIAL = "部分页面转换失败。"
MSG_PDF2MD_BAD_FILE = "无法读取 PDF 文件。"
MSG_PDF2MD_PAGE_OK = "本页已写出。"
MSG_PDF2MD_PAGE_FAIL = "本页转换失败。"
MSG_PDF2MD_EMPTY_FALLBACK = "本页无可用文本，改走版面识别。"


def resolve_device() -> str:
    """
    函数名: resolve_device
    作用: 固定返回 cpu（本包仅 CPU）。
    输入: 无。
    输出:
        str: "cpu"。
    """
    return DEFAULT_DEVICE


def resolve_models_dir() -> Path:
    """
    函数名: resolve_models_dir
    作用: 解析 models 目录；优先 PADDLEOCR_MCP_MODELS_DIR，次选 PADDLE_PDX_CACHE_HOME，回退源码树默认值。解耦 models 与包安装位置，支持跨机器复制即用。
    输入: 无。
    输出:
        Path: models 目录路径（不保证已存在）。
    """
    env = os.environ.get(MODELS_ENV) or os.environ.get(PDX_CACHE_ENV)
    if env:
        return Path(env).expanduser()
    return _DEFAULT_MODELS_DIR


def ensure_pdx_cache_env() -> Path:
    """
    函数名: ensure_pdx_cache_env
    作用: 把 PaddleX 模型缓存指到 resolve_models_dir()，并压低 paddle 日志。MCP 子进程继承环境。
    输入: 无。
    输出:
        Path: 缓存目录。
    """
    models = resolve_models_dir()
    models.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault(PDX_CACHE_ENV, str(models))
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("GLOG_logtostderr", "0")
    warnings.filterwarnings("ignore", module="paddle.utils.cpp_extension.extension_utils")
    return Path(os.environ[PDX_CACHE_ENV])
