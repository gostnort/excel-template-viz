"""paddleocr-mcp HTTP subprocess: pick port, spawn, call tool, stop.

Residency model: intra-job resident, unload when all active jobs drain.
- A module-level refcount (_active_jobs) tracks active jobs; each run_ocr_job
  call and each PaddleOcr_PDF2MDs call counts as one job (begin_job/end_job).
- While refcount > 0, all MCP subprocesses stay resident (no per-call restart).
- When refcount reaches 0, unload_mcp() stops ALL MCP subprocesses (singleton
  OCR, singleton Structure, Structure dynamic pool) AND tree-kills them so
  paddleocr-mcp child processes do not linger. stop_mcp() (app exit) calls
  unload_mcp() too.

Concurrent OCR model (Opt2 dynamic pool):
- acquire_structure_worker(port) returns a port: reuse an idle server, else
  spawn a new one up to config.PDF2MD_PARALLEL_WORKERS, else wait for one to
  free (with timeout) or reuse the least-busy. release_structure_worker(port)
  marks it free. The pool persists across jobs while refcount > 0 (warm) and is
  torn down only at refcount 0.
- run_ocr_job acquires a pool worker, sends its single image via
  call_structure_mcp_on_port(port, img), then releases the worker. Concurrent
  run_ocr_job calls use different servers.
- PaddleOcr_PDF2MDs acquires k workers (ports), dispatches table pages to a
  multiprocessing Pool that calls call_structure_mcp_on_port(port, img), then
  releases the workers.
"""

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

from paddleocr_mcp_controller import config
from paddleocr_mcp_controller.image_decode import scale_min_side


_ocr_proc: subprocess.Popen | None = None
_ocr_port: int | None = None
_structure_proc: subprocess.Popen | None = None
_structure_port: int | None = None
# Opt2: Structure MCP 动态池——_PoolWorker 列表；refcount>0 期间常驻，refcount=0 时整体卸载。
_structure_pool: list["_PoolWorker"] = []
# 中文注释: refcount 跨 job 计数（run_ocr_job 与 PaddleOcr_PDF2MDs 各计一个）；run.io_bound 线程池调用，需线程安全。
_active_jobs: int = 0
_job_lock = threading.Lock()
# 中文注释: 动态池 acquire/release 用 Condition 等待空闲 worker。
_pool_lock = threading.Lock()
_pool_cond = threading.Condition(_pool_lock)
# 中文注释: 跨进程注册表状态——本进程登记的 pid 与 job kind；signal/atexit 用它做幂等清理。
_my_registry_pid: int | None = None
_my_registry_kind: str | None = None
_signal_cleaned: bool = False



class _PoolWorker:
    """
    函数名: _PoolWorker
    作用: 动态 Structure 池的单个 worker——持有子进程、端口、忙碌标志；owned=True 表示本进程 spawn（有 proc），False 表示采纳自其它进程（仅知 port/server_pid）。
    输入:
        proc (subprocess.Popen|None): paddleocr-mcp 子进程；采纳时为 None。
        port (int): 监听端口。
        server_pid (int): server 子进程 pid（采纳或 spawn 都有）。
        owned (bool): True=本进程 spawn，False=采纳自其它进程。
    输出: 无。
    """

    __slots__ = ("proc", "port", "busy", "server_pid", "owned")

    def __init__(self, proc: subprocess.Popen | None, port: int, server_pid: int = 0, owned: bool = True) -> None:
        self.proc = proc
        self.port = int(port)
        self.busy = False
        self.server_pid = int(server_pid) if server_pid else (proc.pid if proc is not None else 0)
        self.owned = bool(owned)


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
    """
    函数名: _stop_proc
    作用: 终止子进程并杀整棵进程树（paddleocr-mcp 可能 spawn 子进程，单 terminate 只杀直系子导致残留）。
    输入:
        proc (subprocess.Popen|None): 目标子进程；None 直接返回。
    输出: 无。
    """
    if proc is None:
        return
    if proc.poll() is not None:
        return
    # 中文注释: 先尝试树杀——Windows 用 taskkill /T /F，其它平台优先 psutil，再退回 process group
    _tree_kill(proc)
    try:
        proc.wait(timeout=8)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _tree_kill(proc: subprocess.Popen) -> None:
    """
    函数名: _tree_kill
    作用: 杀掉以 proc.pid 为根的整棵进程树；Windows 走 taskkill /T /F，其它平台优先 psutil，再退回 killpg。
    输入:
        proc (subprocess.Popen): 目标子进程。
    输出: 无。
    """
    pid = proc.pid
    try:
        if sys.platform == "win32":
            # 中文注释: Windows 用 taskkill /T /F 杀整树，不依赖 pywin32
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
            return
        # 中文注释: 非 Windows：优先 psutil 递归杀子
        try:
            import psutil
            parent = psutil.Process(pid)
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            parent.kill()
            return
        except Exception:
            pass
        # 中文注释: 最后退回 process group kill
        import os
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
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
    """stop both OCR and Structure MCP subprocesses (single + pool), tree-kill."""
    unload_mcp()


def _signal_cleanup(signum: int | None = None, frame: Any = None) -> None:
    """
    函数名: _signal_cleanup
    作用: signal/atexit 回调——幂等调用 release_job 清理本进程注册表条目；避免 Ctrl-C 后注册表残留。重入保护。
    输入:
        signum (int|None): 信号编号；atexit 调用时为 None。
        frame: 信号帧；忽略。
    输出: 无。
    """
    global _signal_cleaned, _my_registry_pid
    if _signal_cleaned:
        return
    _signal_cleaned = True
    pid_to_release = _my_registry_pid
    if pid_to_release is not None:
        try:
            from paddleocr_mcp_controller import mcp_registry
            mcp_registry.release_job(int(pid_to_release))
        except Exception:
            pass
        _my_registry_pid = None
    # 中文注释: signal 触发时重新抛出默认行为（SIGINT/SIGTERM），保证进程退出
    if signum is not None:
        try:
            import signal
            # 恢复默认处理并重抛
            signal.signal(signum, signal.SIG_DFL)
            if sys.platform == "win32":
                # Windows: SIGTERM 没有，SIGINT 直接退出
                raise KeyboardInterrupt
            else:
                import os
                os.kill(os.getpid(), signum)
        except Exception:
            raise KeyboardInterrupt if signum == 2 else SystemExit(0)


def _install_signal_cleanup() -> None:
    """
    函数名: _install_signal_cleanup
    作用: 注册 SIGINT/SIGTERM 与 atexit 回调到 _signal_cleanup；幂等。
    输入: 无。
    输出: 无。
    """
    global _signal_cleaned
    if _signal_cleaned:
        return
    try:
        import signal
        import atexit
        # 中文注释: 仅注册一次；signal handler 仅在主线程有效
        atexit.register(_signal_cleanup, None, None)
        try:
            signal.signal(signal.SIGINT, _signal_cleanup)
        except (ValueError, OSError):
            pass
        try:
            signal.signal(signal.SIGTERM, _signal_cleanup)
        except (ValueError, OSError):
            pass
    except Exception:
        pass


def begin_job(kind: str = "ocr") -> None:
    """
    函数名: begin_job
    作用: 登记一个活跃 job——跨进程注册表 refcount+1、登记本进程 pid；pdf2md 还要等待先于自己登记的 pdf2md pid 全部退出（跨进程串行）。本地 _active_jobs 同步+1。
    输入:
        kind (str): "pdf2md" 或 "ocr"；pdf2md 触发串行等待。
    输出: 无。
    """
    global _active_jobs, _my_registry_pid, _my_registry_kind
    from paddleocr_mcp_controller import mcp_registry
    # 中文注释: 跨进程登记 -> refcount+1；pdf2md 返回先于本进程的存活 pdf2md pid
    my_pid, prior_pids = mcp_registry.register_job(kind)
    _my_registry_pid = my_pid
    _my_registry_kind = kind
    # 注册 signal/atexit 清理（幂等）
    _install_signal_cleanup()
    # 中文注释: pdf2md 跨进程串行：等待先于自己登记的 pdf2md pid 全部退出
    if kind == "pdf2md" and prior_pids:
        mcp_registry.wait_for_pids(prior_pids)
    with _job_lock:
        _active_jobs += 1


def end_job() -> None:
    """
    函数名: end_job
    作用: 注销一个活跃 job——跨进程注册表 refcount-1、移除本进程 pid；refcount 归零则树杀所有注册的 server 并清空注册表，同时卸载本地 owned worker。本地 _active_jobs 同步-1。全局 refcount>0 时：杀本进程单例（OCR/Structure 单例是 per-process，不共享，必须杀否则本进程退出后变孤儿），但保留 owned pool worker（留给其它进程经注册表采纳），仅清本地池引用。
    输入: 无。
    输出: 无。
    """
    global _active_jobs, _my_registry_pid, _my_registry_kind
    from paddleocr_mcp_controller import mcp_registry
    with _job_lock:
        _active_jobs -= 1
        local_zero = (_active_jobs <= 0)
        if local_zero:
            _active_jobs = 0
    # 中文注释: 跨进程注销；若全局 refcount 归零，release_job 会树杀所有注册的 server
    pid_to_release = _my_registry_pid
    global_refcount = -1
    if pid_to_release is not None:
        try:
            global_refcount = int(mcp_registry.release_job(int(pid_to_release)))
        except Exception:
            global_refcount = -1
    _my_registry_pid = None
    _my_registry_kind = None
    # 中文注释: 本地无活跃 job：全局 refcount 归零 -> 整体卸载（单例+池）；>0 -> 仅杀本进程单例（per-process，不共享），owned pool worker 留给其它进程采纳
    if local_zero:
        if global_refcount <= 0:
            unload_mcp()
        else:
            # 全局仍有活跃 job：单例是 per-process，本进程退出前必须杀，否则变孤儿
            stop_ocr_mcp()
            stop_structure_mcp()
            # owned pool worker 不杀——留给其它进程经注册表采纳；仅清本地池引用
            with _pool_cond:
                _structure_pool.clear()
                _pool_cond.notify_all()


def unload_mcp() -> None:
    """
    函数名: unload_mcp
    作用: 强制整体卸载——停 OCR 单例、Structure 单例、Structure 动态池，全部树杀，确保无残留 python/paddleocr-mcp。
    输入: 无。
    输出: 无。
    """
    stop_ocr_mcp()
    stop_structure_mcp()
    stop_structure_pool()


def active_jobs() -> int:
    """return current refcount (mainly for diagnostics/tests)."""
    with _job_lock:
        return _active_jobs


def _pool_alive() -> bool:
    """True if any Structure pool subprocess is alive."""
    for w in _structure_pool:
        if w.proc.poll() is None and _port_open(w.port):
            return True
    return False


def _reap_dead_workers_locked() -> None:
    """drop dead pool workers (caller holds _pool_cond)."""
    alive: list["_PoolWorker"] = []
    for w in _structure_pool:
        # 中文注释: owned worker 靠 proc.poll()；采纳 worker 靠端口探测
        if w.proc is not None:
            is_alive = (w.proc.poll() is None) and _port_open(w.port)
        else:
            is_alive = _port_open(w.port)
        if is_alive:
            alive.append(w)
        else:
            # 中文注释: 仅 owned worker 需要 _stop_proc；采纳 worker 不归本进程管
            if w.owned:
                _stop_proc(w.proc)
    _structure_pool.clear()
    _structure_pool.extend(alive)


def _spawn_pool_worker_locked() -> "_PoolWorker":
    """
    函数名: _spawn_pool_worker_locked
    作用: 在已持 _pool_cond 的前提下新建一个 Structure MCP worker 并等就绪；失败抛异常。端口避开 OCR/已用。仅本地 spawn，不登记注册表（注册表路径走 adopt_or_spawn_servers）。
    输入: 无（读模块全局）。
    输出:
        _PoolWorker: 新建并就绪的 worker。
    """
    used: set[int] = set()
    if _ocr_port is not None:
        used.add(_ocr_port)
    if _structure_port is not None:
        used.add(_structure_port)
    for w in _structure_pool:
        used.add(w.port)
    idx = len(_structure_pool)
    preferred = config.STRUCTURE_MCP_PORT_BASE + idx
    port = pick_free_mcp_port(preferred=preferred, used=used)
    proc = _spawn("PP-StructureV3", port)
    try:
        _wait_ready(proc, port, timeout=config.MCP_START_TIMEOUT_SEC)
    except Exception:
        _stop_proc(proc)
        raise
    w = _PoolWorker(proc, port, server_pid=proc.pid, owned=True)
    _structure_pool.append(w)
    return w


def start_structure_pool(k: int) -> list[int]:
    """
    函数名: start_structure_pool
    作用: 兼容旧接口——确保动态池至少有 k 个存活 worker 并全部标记忙碌返回端口；调用方需用 release_structure_workers 释放。
    输入:
        k (int): 期望池大小；<=0 视为 1。
    输出:
        list[int]: 拿到的 worker 监听端口列表。
    """
    if k <= 0:
        k = 1
    return acquire_structure_workers(k)


def stop_structure_pool() -> None:
    """stop all owned Structure pool subprocesses (tree-kill) and clear the pool; adopted workers are left alive (managed by registry)."""
    with _pool_cond:
        for w in _structure_pool:
            # 中文注释: 仅 owned worker 本进程树杀；采纳 worker 由注册表统一树杀
            if w.owned:
                _stop_proc(w.proc)
        _structure_pool.clear()
        _pool_cond.notify_all()


def pool_structure_urls() -> list[str]:
    """return /mcp URLs for all pool servers (alive ones only)."""
    urls: list[str] = []
    for w in _structure_pool:
        if _port_open(w.port):
            urls.append(f"http://{config.MCP_HOST}:{w.port}/mcp")
    return urls


def acquire_structure_worker(*, timeout: float = float(config.MCP_START_TIMEOUT_SEC)) -> int:
    """
    函数名: acquire_structure_worker
    作用: 从动态 Structure 池取一个空闲 worker 端口；无空闲且未达上限则通过跨进程注册表采纳/新建；已满则等待释放，超时回退复用任一存活 worker。
    输入:
        timeout (float): 等待空闲 worker 的最长时间（秒）。
    输出:
        int: 拿到的 worker 监听端口。
    """
    deadline = time.time() + timeout
    with _pool_cond:
        while True:
            # 中文注释: 1) 复用空闲且存活的 worker
            for w in _structure_pool:
                if not w.busy and w.proc is not None and w.proc.poll() is None and _port_open(w.port):
                    w.busy = True
                    return w.port
            # 中文注释: 1b) 复用空闲且存活的采纳 worker（无 proc，靠端口探测）
            for w in _structure_pool:
                if not w.busy and w.proc is None and _port_open(w.port):
                    w.busy = True
                    return w.port
            # 中文注释: 2) 清理已死 worker
            _reap_dead_workers_locked()
            # 中文注释: 3) 未达上限则通过注册表采纳/新建（跨进程共享）
            if len(_structure_pool) < int(config.PDF2MD_PARALLEL_WORKERS):
                port = _adopt_or_spawn_via_registry_locked()
                if port is not None:
                    return port
            # 中文注释: 4) 已满 -> 等待释放
            remaining = deadline - time.time()
            if remaining <= 0:
                # 超时回退：强制复用第一个存活 worker
                for w in _structure_pool:
                    if w.proc is not None and w.proc.poll() is None and _port_open(w.port):
                        w.busy = True
                        return w.port
                    if w.proc is None and _port_open(w.port):
                        w.busy = True
                        return w.port
                raise RuntimeError("structure pool acquire timeout")
            _pool_cond.wait(timeout=remaining)


def _adopt_or_spawn_via_registry_locked() -> int | None:
    """
    函数名: _adopt_or_spawn_via_registry_locked
    作用: 调用跨进程注册表采纳/新建一个 server，加入本地池并标记忙碌；返回端口；失败返回 None。调用方持 _pool_cond。
    输入: 无。
    输出:
        int|None: 端口；失败 None。
    """
    try:
        from paddleocr_mcp_controller import mcp_registry
        # 释放 _pool_cond 期间调用注册表（注册表内部有自己的跨进程锁，避免嵌套锁等待）
        _pool_cond.release()
        try:
            entries = mcp_registry.adopt_or_spawn_servers(1)
        finally:
            _pool_cond.acquire()
        if not entries:
            return None
        e = entries[0]
        port = int(e["port"])
        server_pid = int(e.get("server_pid", 0))
        owned = bool(e.get("owned", 0))
        # 避免重复加入本地池
        for w in _structure_pool:
            if w.port == port:
                w.busy = True
                return port
        # 中文注释: owned=True -> 本进程 spawn，proc 由 _spawn_pool_worker_locked 持有；这里 owned 来自注册表 spawn，proc 用 None（生命周期由注册表 tree-kill 管理）
        w = _PoolWorker(None, port, server_pid=server_pid, owned=owned)
        w.busy = True
        _structure_pool.append(w)
        return port
    except Exception:
        # 注册表路径失败 -> 回退本地 spawn（并登记注册表）
        try:
            w = _spawn_pool_worker_locked()
            w.busy = True
            _register_local_spawn_locked(w)
            return w.port
        except Exception:
            return None


def _register_local_spawn_locked(worker: "_PoolWorker") -> None:
    """
    函数名: _register_local_spawn_locked
    作用: 把本地 spawn 的 worker 登记到跨进程注册表（best-effort），供其它进程采纳。调用方持 _pool_cond。
    输入:
        worker (_PoolWorker): 本地 spawn 的 worker。
    输出: 无。
    """
    try:
        from paddleocr_mcp_controller import mcp_registry
        import os as _os
        _pool_cond.release()
        try:
            with mcp_registry.acquire_lock():
                data = mcp_registry._read_registry()
                data.setdefault("servers", [])
                data["servers"].append({
                    "port": int(worker.port),
                    "server_pid": int(worker.server_pid),
                    "owner_pid": _os.getpid(),
                })
                mcp_registry._write_registry(data)
        finally:
            _pool_cond.acquire()
    except Exception:
        pass


def release_structure_worker(port: int) -> None:
    """
    函数名: release_structure_worker
    作用: 释放指定端口对应的 worker（标记空闲并唤醒等待者）。
    输入:
        port (int): 之前 acquire 返回的端口。
    输出: 无。
    """
    with _pool_cond:
        for w in _structure_pool:
            if w.port == int(port):
                w.busy = False
                break
        _pool_cond.notify_all()


def acquire_structure_workers(k: int, *, timeout: float = float(config.MCP_START_TIMEOUT_SEC)) -> list[int]:
    """
    函数名: acquire_structure_workers
    作用: 一次性获取 k 个 worker 端口；部分失败时回滚已获取的。k<=0 视为 1。
    输入:
        k (int): 需要的 worker 数。
        timeout (float): 单次 acquire 超时。
    输出:
        list[int]: k 个端口。
    """
    if k <= 0:
        k = 1
    ports: list[int] = []
    try:
        for _ in range(k):
            ports.append(acquire_structure_worker(timeout=timeout))
    except Exception:
        release_structure_workers(ports)
        raise
    return ports


def release_structure_workers(ports) -> None:
    """
    函数名: release_structure_workers
    作用: 批量释放 worker 端口；None/空安全。
    输入:
        ports (Iterable[int]|None): acquire 返回的端口列表。
    输出: 无。
    """
    if not ports:
        return
    for p in ports:
        release_structure_worker(int(p))


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
