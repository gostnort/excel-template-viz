"""paddleocr-mcp HTTP 子进程：先占五位数空闲端口，再启动 MCP，再给引擎调工具。"""

from __future__ import annotations

import asyncio
import json
import random
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from paddle_ocr import config


_lock = threading.Lock()
_starting = False
_ocr_proc: subprocess.Popen | None = None
_structure_proc: subprocess.Popen | None = None
_ocr_port: int | None = None
_structure_port: int | None = None



def _port_free(port: int) -> bool:
    """
    函数名: _port_free
    作用: 探测 127.0.0.1 上该 TCP 端口能否 bind（未占用）。
    输入:
        port (int): 端口号。
    输出:
        bool: True=空闲。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((config.MCP_HOST, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()



def _port_open(port: int) -> bool:
    """
    函数名: _port_open
    作用: 探测端口是否已有进程在听（MCP 已起来）。
    输入:
        port (int): 端口号。
    输出:
        bool: True=可连接。
    """
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
    raise RuntimeError("无可用的五位数 TCP 端口")



def _mcp_cmd(model: str, port: int) -> list[str]:
    """
    函数名: _mcp_cmd
    作用: 组装 paddleocr-mcp HTTP 启动命令（local 源、当前 device）。
    输入:
        model (str): PP-OCRv6 或 PP-StructureV3。
        port (int): 已选定的空闲端口。
    输出:
        list[str]: subprocess 参数列表。
    """
    config.ensure_pdx_cache_env()
    return [
        sys.executable, "-m", "paddle_ocr.mcp_entry",
        "--http",
        "--host", config.MCP_HOST,
        "--port", str(port),
        "--model", model,
        "--ppocr_source", "local",
        "--device", config.resolve_device(),
    ]



def _spawn_log_path(model: str) -> Path:
    """
    函数名: _spawn_log_path
    作用: 按模型名返回 MCP 子进程 stdout/stderr 日志路径。
    输入:
        model (str): PP-OCRv6 或 PP-StructureV3。
    输出:
        Path: 日志文件路径。
    """
    suffix = "ocr" if model == "PP-OCRv6" else "structure"
    return config.PROJECT_ROOT / "temp" / f"paddleocr_mcp_{suffix}.log"



def _spawn(model: str, port: int) -> subprocess.Popen:
    """
    函数名: _spawn
    作用: 在已选定的空闲端口上启动 paddleocr-mcp；stdout/stderr 追加到 temp 日志。
    输入:
        model (str): PP-OCRv6 或 PP-StructureV3。
        port (int): 监听端口。
    输出:
        subprocess.Popen: 子进程句柄。
    """
    log_path = _spawn_log_path(model)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("ab")
    kwargs: dict[str, Any] = {
        "stdout": log_fh,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(_mcp_cmd(model, port), cwd=str(config.PROJECT_ROOT), **kwargs)
    finally:
        log_fh.close()



def _wait_ready(proc: subprocess.Popen, port: int, *, timeout: int) -> None:
    """
    函数名: _wait_ready
    作用: 等到 MCP 端口可连接，或子进程提前退出 / 超时则抛错。
    输入:
        proc (Popen): 子进程。
        port (int): 监听端口。
        timeout (int): 秒。
    输出:
        无。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"paddleocr-mcp 提前退出 (code={proc.returncode})")
        if _port_open(port):
            return
        time.sleep(0.4)
    raise RuntimeError(f"等待 paddleocr-mcp 端口 {port} 超时")



def _stop_proc(proc: subprocess.Popen | None) -> None:
    """
    函数名: _stop_proc
    作用: terminate 子进程，超时则 kill。
    输入:
        proc (Popen|None): 子进程。
    输出:
        无。
    """
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



def _ocr_alive_unlocked() -> bool:
    """
    函数名: _ocr_alive_unlocked
    作用: 无锁检查 OCR MCP 进程是否仍在听端口（调用方须持 _lock）。
    输入: 无。
    输出:
        bool: True=存活。
    """
    if _ocr_proc is None or _ocr_port is None:
        return False
    if _ocr_proc.poll() is not None:
        return False
    return _port_open(_ocr_port)



def _structure_alive_unlocked() -> bool:
    """
    函数名: _structure_alive_unlocked
    作用: 无锁检查 Structure MCP 进程是否仍在听端口（调用方须持 _lock）。
    输入: 无。
    输出:
        bool: True=存活。
    """
    if _structure_proc is None or _structure_port is None:
        return False
    if _structure_proc.poll() is not None:
        return False
    return _port_open(_structure_port)



def is_mcp_running() -> bool:
    """
    函数名: is_mcp_running
    作用: OCR MCP 子进程是否在听端口（顶栏开关 / 预加载状态）。
    输入: 无。
    输出:
        bool: True=已启动。
    """
    with _lock:
        return _ocr_alive_unlocked()



def ocr_mcp_url() -> str | None:
    """
    函数名: ocr_mcp_url
    作用: 返回 PP-OCRv6 Streamable HTTP MCP 地址。
    输入: 无。
    输出:
        str|None: http://host:port/mcp；未启动为 None。
    """
    with _lock:
        if _ocr_port is None:
            return None
        return f"http://{config.MCP_HOST}:{_ocr_port}/mcp"



def structure_mcp_url() -> str | None:
    """
    函数名: structure_mcp_url
    作用: 返回 PP-StructureV3 Streamable HTTP MCP 地址。
    输入: 无。
    输出:
        str|None: http://host:port/mcp；未启动为 None。
    """
    with _lock:
        if _structure_port is None:
            return None
        return f"http://{config.MCP_HOST}:{_structure_port}/mcp"



def _wait_not_starting() -> None:
    """
    函数名: _wait_not_starting
    作用: 若另一线程正在 start_mcp，则等到其结束，避免重复 spawn / 误杀。
    输入: 无。
    输出: 无。
    """
    while True:
        with _lock:
            if not _starting:
                return
        time.sleep(0.2)



def start_mcp(*, include_structure: bool = True) -> bool:
    """
    函数名: start_mcp
    作用: 选五位数空闲端口后启动 paddleocr-mcp（PP-OCRv6，可选 PP-StructureV3）。
        先确认端口空闲，再 spawn；等端口可连接才算启用。
    输入:
        include_structure (bool): True 时再拉起 Structure 进程。
    输出:
        bool: OCR MCP 是否就绪。
    """
    global _ocr_proc, _structure_proc, _ocr_port, _structure_port, _starting
    _wait_not_starting()
    ocr_proc = None
    ocr_port = None
    st_proc = None
    st_port = None
    need_ocr = False
    need_st = False
    with _lock:
        _starting = True
        if _ocr_alive_unlocked():
            ocr_port = _ocr_port
            need_st = include_structure and not _structure_alive_unlocked()
        else:
            _stop_proc(_ocr_proc)
            _stop_proc(_structure_proc)
            _ocr_proc = None
            _structure_proc = None
            _ocr_port = None
            _structure_port = None
            need_ocr = True
            need_st = include_structure
            ocr_port = pick_free_mcp_port(preferred=config.MCP_PREFERRED_OCR_PORT)
            ocr_proc = _spawn("PP-OCRv6", ocr_port)
            _ocr_proc = ocr_proc
            _ocr_port = ocr_port
        if need_st:
            used = {ocr_port} if ocr_port else set()
            st_port = pick_free_mcp_port(preferred=config.MCP_PREFERRED_STRUCTURE_PORT, used=used)
            st_proc = _spawn("PP-StructureV3", st_port)
            _structure_proc = st_proc
            _structure_port = st_port
    try:
        if need_ocr and ocr_proc is not None and ocr_port is not None:
            try:
                _wait_ready(ocr_proc, ocr_port, timeout=config.MCP_START_TIMEOUT_SEC)
            except Exception:
                stop_mcp()
                return False
        if need_st and st_proc is not None and st_port is not None:
            try:
                _wait_ready(st_proc, st_port, timeout=config.MCP_START_TIMEOUT_SEC)
            except Exception:
                with _lock:
                    _stop_proc(_structure_proc)
                    _structure_proc = None
                    _structure_port = None
        return is_mcp_running()
    finally:
        with _lock:
            _starting = False



def stop_mcp() -> None:
    """
    函数名: stop_mcp
    作用: 结束 paddleocr-mcp 子进程并清空端口记录。
    输入: 无。
    输出: 无。
    """
    global _ocr_proc, _structure_proc, _ocr_port, _structure_port
    with _lock:
        _stop_proc(_ocr_proc)
        _stop_proc(_structure_proc)
        _ocr_proc = None
        _structure_proc = None
        _ocr_port = None
        _structure_port = None



def ensure_mcp_started(*, include_structure: bool = False) -> bool:
    """
    函数名: ensure_mcp_started
    作用: 若 MCP 未运行则启动（PaddleOcr 懒加载）。
    输入:
        include_structure (bool): 是否同时拉起 Structure。
    输出:
        bool: OCR MCP 是否就绪。
    """
    if is_mcp_running():
        if include_structure:
            return start_mcp(include_structure=True)
        return True
    return start_mcp(include_structure=include_structure)



def _write_temp_jpg(img) -> Path:
    """
    函数名: _write_temp_jpg
    作用: 把 BGR ndarray 写成临时 jpg，供 MCP 按路径读图。
    输入:
        img: OpenCV BGR ndarray。
    输出:
        Path: 临时文件路径（调用方负责删除）。
    """
    import cv2
    handle = tempfile.NamedTemporaryFile(suffix=".jpg", prefix="paddleocr_mcp_", delete=False)
    path = Path(handle.name)
    handle.close()
    if not cv2.imwrite(str(path), img):
        path.unlink(missing_ok=True)
        raise RuntimeError("无法写出临时 jpg")
    return path



def _run_async(coro):
    """
    函数名: _run_async
    作用: 在无事件循环时 asyncio.run；NiceGUI 已有 loop 时丢到新线程跑。
    输入:
        coro: 协程。
    输出:
        Any: 协程返回值。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # 已在事件循环内：丢到新线程跑 asyncio.run，避免嵌套 loop。
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=config.MCP_START_TIMEOUT_SEC)



def _tool_text(result: Any) -> str:
    """
    函数名: _tool_text
    作用: 从 FastMCP call_tool 结果取出文本（data 或 content[].text）。
    输入:
        result: FastMCP CallToolResult。
    输出:
        str: 工具返回文本。
    """
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
    """
    函数名: _call_tool_async
    作用: 用 FastMCP Client 调 paddleocr-mcp 工具。
    输入:
        url (str): Streamable HTTP MCP 地址。
        tool (str): ocr 或 pp_structurev3。
        arguments (dict): 工具参数。
    输出:
        str: 工具文本结果。
    """
    from fastmcp import Client
    async with Client(url, timeout=float(config.MCP_START_TIMEOUT_SEC)) as client:
        result = await client.call_tool(tool, arguments)
        return _tool_text(result)



def call_ocr_mcp(img) -> dict[str, Any]:
    """
    函数名: call_ocr_mcp
    作用: 把裁剪图发给 PP-OCRv6 MCP 工具 ocr，映射为 §3.3 string* JSON。
    输入:
        img: BGR ndarray。
    输出:
        dict: OCR JSON。
    """
    from paddle_ocr.runtime.postprocess import OcrMcpToStringJson
    if not ensure_mcp_started(include_structure=False):
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"}
    url = ocr_mcp_url()
    if not url:
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": "fast", "engine": "ocr"}
    path = _write_temp_jpg(img)
    try:
        raw = _run_async(_call_tool_async(url, "ocr", {
            "input_data": str(path.resolve()),
            "output_mode": "detailed",
            "file_type": "image",
            "runtime_params": {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
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
    作用: 把裁剪图发给 PP-StructureV3 MCP 工具 pp_structurev3，映射为 §3.3 JSON。
    输入:
        img: BGR ndarray。
        mode (str): fast 或 structure。
    输出:
        dict: OCR JSON。
    """
    from paddle_ocr.runtime.postprocess import MarkdownToOcrJson
    if not ensure_mcp_started(include_structure=True):
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": mode, "engine": "structure"}
    url = structure_mcp_url()
    if not url:
        return {"ok": False, "message": config.MSG_NOT_READY, "mode": mode, "engine": "structure"}
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
            },
        }))
    except Exception:
        return {"ok": False, "message": config.MSG_INFER_FAIL, "mode": mode, "engine": "structure"}
    finally:
        path.unlink(missing_ok=True)
    result = MarkdownToOcrJson(raw, mode=mode)
    result["engine"] = "structure"
    return result
