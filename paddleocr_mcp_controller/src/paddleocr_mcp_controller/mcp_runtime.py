"""paddleocr-mcp HTTP subprocess: pick port, spawn, call tool, stop.

Simplified: no threading lock, no daemon, no _starting flag.

Opt1 (daemon): Structure MCP subprocess is kept RESIDENT across PDF jobs —
PaddleOcr_PDF2MDs no longer calls stop_structure_mcp() in its finally block.
The warm Structure daemon is reused by the next PDF (no ~40-50s respawn).
Explicit shutdown is the caller's responsibility (UI calls stop_mcp() on
app exit via nicegui_ui/components/model_runtime.py:release_all_models_sync).
OCR MCP stays lazy-started and resident as before.

Opt2 (parallel pool): start_structure_pool(k) spawns k Structure MCP
subprocesses on k distinct ports, kept resident across jobs like the single
daemon. Multiprocessing workers call call_structure_mcp_on_port(port, img)
which uses a per-worker fresh asyncio loop (safe inside a fresh process).
"""

from __future__ import annotations

import asyncio
import json
import random
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from paddleocr_mcp_controller import config
from paddleocr_mcp_controller.image_decode import scale_min_side


_ocr_proc: subprocess.Popen | None = None
_ocr_port: int | None = None
_structure_proc: subprocess.Popen | None = None
_structure_port: int | None = None
# Opt2: Structure MCP 池——(proc, port) 元组列表；与单例 _structure_proc 互斥使用。
_structure_pool: list[tuple[subprocess.Popen, int]] = []


def _port_free(port: int) -> bool:
    """True if 127.0.0.1 TCP port is bindable (free)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((config.MCP_HOST, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _port_open(port: int) -> bool:
    """True if a process is listening on the port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        sock.connect((config.MCP_HOST, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def pick_free_mcp_port(*, preferred: int | None = None, used: set[int] | None = None) -> int:
    """
    函数名: pick_free_mcp_port
    作用: 先试 preferred 五位数端口；占用则随机再试，直到空闲。避开 8000/9999。
    输入:
        preferred (int|None): 优先端口。
        used (set[int]|None): 本轮已分配、不可再用的端口。
    输出:
        int: 空闲端口。
    """
    blocked = set(config.MCP_RESERVED_PORTS)
    if used:
        blocked.update(used)
    candidates: list[int] = []
    if preferred is not None:
        candidates.append(int(preferred))
    rng = random.Random()
    for _ in range(64):
        port = rng.randint(config.MCP_PORT_MIN, config.MCP_PORT_MAX)
        if port not in candidates:
            candidates.append(port)
    for port in candidates:
        if port < config.MCP_PORT_MIN or port > config.MCP_PORT_MAX:
            continue
        if port in blocked:
            continue
        if _port_free(port):
            return port
    raise RuntimeError("no free 5-digit TCP port")


def _mcp_cmd(model: str, port: int) -> list[str]:
    """Build paddleocr-mcp HTTP launch command (local source, CPU)."""
    config.ensure_pdx_cache_env()
    return [
        sys.executable, "-m", "paddleocr_mcp_controller.mcp_entry",
        "--http",
        "--host", config.MCP_HOST,
        "--port", str(port),
        "--model", model,
        "--ppocr_source", "local",
        "--device", config.resolve_device(),
    ]


def _spawn_log_path(model: str) -> Path:
    suffix = "ocr" if model == "PP-OCRv6" else "structure"
    return config.PROJECT_ROOT / "temp" / f"paddleocr_mcp_{suffix}.log"


def _spawn_env() -> dict[str, str]:
    """build env for MCP subprocess: inherit + put controller src on PYTHONPATH.

    Works in dev (editable/unchecked) and installed mode; if the package is
    already importable, the extra PYTHONPATH entry is a harmless no-op.
    """
    import os
    env = dict(os.environ)
    src_dir = str(config.PACKAGE_ROOT.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_dir if not existing else f"{src_dir}{os.pathsep}{existing}"
    return env


def _spawn(model: str, port: int) -> subprocess.Popen:
    """
    函数名: _spawn
    作用: start paddleocr-mcp on the chosen port; stdout/stderr append to temp log.
    输入:
        model (str): PP-OCRv6 or PP-StructureV3.
        port (int): listen port.
    输出:
        subprocess.Popen: process handle.
    """
    log_path = _spawn_log_path(model)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    kwargs: dict[str, Any] = {
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
        "env": _spawn_env(),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(_mcp_cmd(model, port), cwd=str(config.PROJECT_ROOT), **kwargs)
    finally:
        log_fh.close()


def _wait_ready(proc: subprocess.Popen, port: int, *, timeout: int) -> None:
    """Wait until MCP port is connectable, or proc exits / timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"paddleocr-mcp exited early (code={proc.returncode})")
        if _port_open(port):
            return
        time.sleep(0.4)
    raise RuntimeError(f"timeout waiting for paddleocr-mcp port {port}")


def _stop_proc(proc: subprocess.Popen | None) -> None:
    """terminate subprocess, kill on timeout."""
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _ocr_alive() -> bool:
    if _ocr_proc is None or _ocr_port is None:
        return False
    if _ocr_proc.poll() is not None:
        return False
    return _port_open(_ocr_port)


def _structure_alive() -> bool:
    if _structure_proc is None or _structure_port is None:
        return False
    if _structure_proc.poll() is not None:
        return False
    return _port_open(_structure_port)


def is_mcp_running() -> bool:
    """OCR MCP subprocess alive."""
    return _ocr_alive()


def is_structure_mcp_running() -> bool:
    """Structure MCP subprocess alive."""
    return _structure_alive()


def ocr_mcp_url() -> str | None:
    if _ocr_port is None:
        return None
    return f"http://{config.MCP_HOST}:{_ocr_port}/mcp"


def structure_mcp_url() -> str | None:
    if _structure_port is None:
        return None
    return f"http://{config.MCP_HOST}:{_structure_port}/mcp"


def start_ocr_mcp() -> bool:
    """
    函数名: start_ocr_mcp
    作用: start PP-OCRv6 MCP slot; no-op if already alive. On failure only stop OCR.
    输入: none.
    输出:
        bool: OCR MCP ready.
    """
    global _ocr_proc, _ocr_port
    if _ocr_alive():
        return True
    _stop_proc(_ocr_proc)
    used = {_structure_port} if _structure_port is not None else set()
    port = pick_free_mcp_port(preferred=config.MCP_PREFERRED_OCR_PORT, used=used)
    proc = _spawn("PP-OCRv6", port)
    _ocr_proc = proc
    _ocr_port = port
    try:
        _wait_ready(proc, port, timeout=config.MCP_START_TIMEOUT_SEC)
    except Exception:
        stop_ocr_mcp()
        return False
    return _ocr_alive()


def ensure_ocr_mcp() -> bool:
    """lazy-start OCR if not running."""
    if _ocr_alive():
        return True
    return start_ocr_mcp()


def start_structure_mcp() -> bool:
    """
    函数名: start_structure_mcp
    作用: start PP-StructureV3 MCP slot; no-op if already alive.
    输入: none.
    输出:
        bool: Structure MCP ready.
    """
    global _structure_proc, _structure_port
    if _structure_alive():
        return True
    _stop_proc(_structure_proc)
    used = {_ocr_port} if _ocr_port is not None else set()
    port = pick_free_mcp_port(preferred=config.MCP_PREFERRED_STRUCTURE_PORT, used=used)
    proc = _spawn("PP-StructureV3", port)
    _structure_proc = proc
    _structure_port = port
    try:
        _wait_ready(proc, port, timeout=config.MCP_START_TIMEOUT_SEC)
    except Exception:
        stop_structure_mcp()
        return False
    return _structure_alive()


def stop_ocr_mcp() -> None:
    """stop OCR MCP subprocess and clear OCR port record."""
    global _ocr_proc, _ocr_port
    _stop_proc(_ocr_proc)
    _ocr_proc = None
    _ocr_port = None


def stop_structure_mcp() -> None:
    """stop Structure MCP subprocess and clear Structure port record."""
    global _structure_proc, _structure_port
    _stop_proc(_structure_proc)
    _structure_proc = None
    _structure_port = None


def stop_mcp() -> None:
    """stop both OCR and Structure MCP subprocesses (single + pool)."""
    stop_ocr_mcp()
    stop_structure_mcp()
    stop_structure_pool()


def _pool_alive() -> bool:
    """True if any Structure pool subprocess is alive."""
    for proc, _port in _structure_pool:
        if proc.poll() is None and _port_open(_port):
            return True
    return False


def start_structure_pool(k: int) -> list[int]:
    """
    函数名: start_structure_pool
    作用: 启动 k 个 PP-StructureV3 MCP 子进程（各占独立端口）并保持常驻；已存活则补齐到 k 个。返回端口列表。
    输入:
        k (int): 池大小；<=0 视为 1。
    输出:
        list[int]: 池中各 server 的监听端口（顺序即池内索引）。
    """
    if k <= 0:
        k = 1
    # 清理已死掉的槽位，保留存活槽位以复用（Opt1 常驻）
    alive: list[tuple[subprocess.Popen, int]] = []
    for proc, port in _structure_pool:
        if proc.poll() is None and _port_open(port):
            alive.append((proc, port))
        else:
            _stop_proc(proc)
    _structure_pool.clear()
    _structure_pool.extend(alive)
    # 补齐到 k 个
    used: set[int] = set()
    if _ocr_port is not None:
        used.add(_ocr_port)
    for _proc, port in _structure_pool:
        used.add(port)
    while len(_structure_pool) < k:
        idx = len(_structure_pool)
        preferred = config.STRUCTURE_MCP_PORT_BASE + idx
        port = pick_free_mcp_port(preferred=preferred, used=used)
        proc = _spawn("PP-StructureV3", port)
        _structure_pool.append((proc, port))
        used.add(port)
        try:
            _wait_ready(proc, port, timeout=config.MCP_START_TIMEOUT_SEC)
        except Exception:
            stop_structure_pool()
            raise
    return [port for _proc, port in _structure_pool]


def stop_structure_pool() -> None:
    """stop all Structure pool subprocesses and clear the pool."""
    for proc, _port in _structure_pool:
        _stop_proc(proc)
    _structure_pool.clear()


def pool_structure_urls() -> list[str]:
    """return /mcp URLs for all pool servers (alive ones only)."""
    urls: list[str] = []
    for _proc, port in _structure_pool:
        if _port_open(port):
            urls.append(f"http://{config.MCP_HOST}:{port}/mcp")
    return urls


def _write_temp_jpg(img) -> Path:
    """write BGR ndarray to temp jpg for MCP path-based read."""
    import cv2
    handle = tempfile.NamedTemporaryFile(suffix=".jpg", prefix="paddleocr_mcp_", delete=False)
    path = Path(handle.name)
    handle.close()
    if not cv2.imwrite(str(path), img):
        path.unlink(missing_ok=True)
        raise RuntimeError("cannot write temp jpg")
    return path


def _prepare_mcp_image(img) -> tuple[Any, int]:
    """scale min side to 2048 (no upscale); return (scaled, det_limit=max side)."""
    scaled = scale_min_side(img, config.OCR_PRESCALE_MIN_SIDE)
    height, width = scaled.shape[:2]
    return scaled, max(int(width), int(height))


def _run_async(coro):
    """asyncio.run when no loop; offload to thread when inside a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=config.MCP_START_TIMEOUT_SEC)


def _tool_text(result: Any) -> str:
    """extract text from FastMCP call_tool result."""
    data = getattr(result, "data", None)
    if isinstance(data, str) and data.strip():
        return data
    if isinstance(data, dict):
        return json.dumps(data, ensure_ascii=False)
    texts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            texts.append(str(text))
    return "\n".join(texts)


async def _call_tool_async(url: str, tool: str, arguments: dict[str, Any]) -> str:
    """call paddleocr-mcp tool via FastMCP Client."""
    from fastmcp import Client
    async with Client(url, timeout=float(config.MCP_START_TIMEOUT_SEC)) as client:
        result = await client.call_tool(tool, arguments)
        return _tool_text(result)


def call_ocr_mcp(img) -> dict[str, Any]:
    """
    函数名: call_ocr_mcp
    作用: send cropped image to PP-OCRv6 MCP tool ocr, map to string1 JSON.
    输入:
        img: BGR ndarray.
    输出:
        dict: OCR JSON.
    """
    from paddleocr_mcp_controller.postprocess import OcrMcpToStringJson
    if not ensure_ocr_mcp():
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"}
    url = ocr_mcp_url()
    if not url:
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"}
    img, det_limit = _prepare_mcp_image(img)
    path = _write_temp_jpg(img)
    try:
        raw = _run_async(_call_tool_async(url, "ocr", {
            "input_data": str(path.resolve()),
            "output_mode": "detailed",
            "file_type": "image",
            "runtime_params": {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "text_det_limit_side_len": det_limit,
                "text_det_limit_type": config.DEFAULT_TEXT_DET_LIMIT_TYPE,
            },
        }))
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": "fast", "engine": "ocr"}
    finally:
        path.unlink(missing_ok=True)
    result = OcrMcpToStringJson(raw)
    result["engine"] = "ocr"
    return result


def call_structure_mcp(img, *, mode: str = "fast") -> dict[str, Any]:
    """
    函数名: call_structure_mcp
    作用: send cropped image to PP-StructureV3 MCP tool pp_structurev3, map to string*/table* JSON.
    输入:
        img: BGR ndarray.
        mode (str): fast or structure.
    输出:
        dict: OCR JSON.
    """
    from paddleocr_mcp_controller.postprocess import MarkdownToOcrJson
    if not start_structure_mcp():
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": mode, "engine": "structure"}
    url = structure_mcp_url()
    if not url:
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": mode, "engine": "structure"}
    img, det_limit = _prepare_mcp_image(img)
    path = _write_temp_jpg(img)
    try:
        raw = _run_async(_call_tool_async(url, "pp_structurev3", {
            "input_data": str(path.resolve()),
            "output_mode": "simple",
            "file_type": "image",
            "return_images": False,
            "runtime_params": {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "use_seal_recognition": False,
                "use_formula_recognition": False,
                "use_chart_recognition": False,
                "use_region_detection": False,
                "text_det_limit_side_len": det_limit,
                "text_det_limit_type": config.DEFAULT_TEXT_DET_LIMIT_TYPE,
            },
        }))
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": mode, "engine": "structure"}
    finally:
        path.unlink(missing_ok=True)
    result = MarkdownToOcrJson(raw, mode=mode)
    result["engine"] = "structure"
    return result


def call_structure_markdown(img) -> str:
    """
    函数名: call_structure_markdown
    作用: send image to PP-StructureV3 MCP, return simple Markdown raw text (no JSON split).
    输入:
        img: BGR ndarray.
    输出:
        str: markdown text from MCP.
    """
    if not start_structure_mcp():
        raise RuntimeError(config.MSG_NOT_READY)
    url = structure_mcp_url()
    if not url:
        raise RuntimeError(config.MSG_NOT_READY)
    img, det_limit = _prepare_mcp_image(img)
    path = _write_temp_jpg(img)
    try:
        raw = _run_async(_call_tool_async(url, "pp_structurev3", {
            "input_data": str(path.resolve()),
            "output_mode": "simple",
            "file_type": "image",
            "return_images": False,
            "runtime_params": {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "use_seal_recognition": False,
                "use_formula_recognition": False,
                "use_chart_recognition": False,
                "use_region_detection": False,
                "text_det_limit_side_len": det_limit,
                "text_det_limit_type": config.DEFAULT_TEXT_DET_LIMIT_TYPE,
            },
        }))
    except Exception as exc:
        raise RuntimeError(config.MSG_INFER_FAIL) from exc
    finally:
        path.unlink(missing_ok=True)
    return str(raw or "")


def call_structure_mcp_on_port(port: int, img, *, mode: str = "structure") -> dict[str, Any]:
    """
    函数名: call_structure_mcp_on_port
    作用: 向指定端口上的 PP-StructureV3 MCP server 发送图片（用于 multiprocessing worker，不依赖单例 _structure_proc）。
    输入:
        port (int): 目标 Structure MCP server 监听端口。
        img: BGR ndarray。
        mode (str): fast 或 structure。
    输出:
        dict: OCR JSON。
    """
    from paddleocr_mcp_controller.postprocess import MarkdownToOcrJson
    url = f"http://{config.MCP_HOST}:{int(port)}/mcp"
    img, det_limit = _prepare_mcp_image(img)
    path = _write_temp_jpg(img)
    try:
        raw = _run_async(_call_tool_async(url, "pp_structurev3", {
            "input_data": str(path.resolve()),
            "output_mode": "simple",
            "file_type": "image",
            "return_images": False,
            "runtime_params": {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "use_seal_recognition": False,
                "use_formula_recognition": False,
                "use_chart_recognition": False,
                "use_region_detection": False,
                "text_det_limit_side_len": det_limit,
                "text_det_limit_type": config.DEFAULT_TEXT_DET_LIMIT_TYPE,
            },
        }))
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": mode, "engine": "structure"}
    finally:
        path.unlink(missing_ok=True)
    result = MarkdownToOcrJson(raw, mode=mode)
    result["engine"] = "structure"
    return result
