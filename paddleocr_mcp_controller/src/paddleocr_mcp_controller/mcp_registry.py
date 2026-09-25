"""跨进程共享注册表：协调多 controller 进程共享 paddleocr_mcp 守护进程与 Structure 池 server。

注册表文件（JSON）+ 跨进程文件锁：
- refcount: 全局活跃 job 计数。
- pids: 活跃 controller 进程列表 [{pid, kind, ts}]。
- servers: 活跃 Structure 池 server 列表 [{port, server_pid, owner_pid}]。

pdf2md（重）跨进程串行：新进程登记后等待先于自己登记的 pdf2md pid 全部退出，
然后采纳/复用注册表里仍存活的 server 端口（不重复 spawn）。
ocr（轻）不等待，并发运行。
所有进程都结束（refcount=0）时树杀所有 server 并清空注册表。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from paddleocr_mcp_controller import config


def _registry_path() -> Path:
    """
    函数名: _registry_path
    作用: 返回注册表 JSON 路径；确保 temp/ 存在。
    输入: 无。
    输出:
        Path: 注册表文件路径。
    """
    p = config.PROJECT_ROOT / "temp" / "mcp_registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _lock_path() -> Path:
    """
    函数名: _lock_path
    作用: 返回跨进程锁文件路径。
    输入: 无。
    输出:
        Path: 锁文件路径。
    """
    p = config.PROJECT_ROOT / "temp" / "mcp_registry.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def acquire_lock():
    """
    函数名: acquire_lock
    作用: 跨进程文件锁上下文管理器；Windows 用 msvcrt.locking，POSIX 用 fcntl.flock。
    输入: 无。
    输出:
        生成器：持锁期间执行 with 块。
    """
    path = _lock_path()
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if sys.platform == "win32":
            # 中文注释: Windows 用 msvcrt.locking 阻塞式排他锁
            import msvcrt
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            # 中文注释: POSIX 用 fcntl.flock 排他锁
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)


def _empty_registry() -> dict[str, Any]:
    """返回空注册表结构。"""
    return {"refcount": 0, "pids": [], "servers": []}


def _read_registry() -> dict[str, Any]:
    """
    函数名: _read_registry
    作用: 读注册表 JSON；缺失/损坏返回空注册表。
    输入: 无。
    输出:
        dict: 注册表数据。
    """
    path = _registry_path()
    if not path.exists():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("refcount", 0)
    data.setdefault("pids", [])
    data.setdefault("servers", [])
    return data


def _write_registry(data: dict[str, Any]) -> None:
    """
    函数名: _write_registry
    作用: 原子写注册表（写临时文件再 replace）。
    输入:
        data (dict): 注册表数据。
    输出: 无。
    """
    path = _registry_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _pid_alive(pid: int) -> bool:
    """
    函数名: _pid_alive
    作用: 进程存活检查；优先 psutil，Windows 退回 tasklist，其它退回 os.kill(pid,0)。不用 pywin32。
    输入:
        pid (int): 待检测 pid。
    输出:
        bool: 存活 True。
    """
    if not pid or pid <= 0:
        return False
    try:
        import psutil
        return bool(psutil.pid_exists(int(pid)))
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}", "/NH", "/FO", "CSV"],
                capture_output=True, timeout=5,
            )
            out = r.stdout.decode("utf-8", "ignore")
            # tasklist 无匹配会输出 "信息: 没有运行的任务匹配..."；有匹配则首列即 pid
            return str(int(pid)) in out and "没有运行" not in out
        except Exception:
            return False
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return False


def _tree_kill_pid(pid: int) -> None:
    """
    函数名: _tree_kill_pid
    作用: 树杀指定 pid；Windows taskkill /T /F，其它 psutil/killpg。不用 pywin32。
    输入:
        pid (int): 目标 pid。
    输出: 无。
    """
    if not pid or pid <= 0:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=15,
            )
            return
        try:
            import psutil
            parent = psutil.Process(int(pid))
            for child in parent.children(recursive=True):
                try:
                    child.kill()
                except Exception:
                    pass
            parent.kill()
            return
        except Exception:
            pass
        import signal
        try:
            os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
        except Exception:
            pass
    except Exception:
        pass


def _gc_stale_locked(data: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: _gc_stale_locked
    作用: 清理已死的 controller pid（修正 refcount）与已死的 server；若 refcount 归零，树杀所有 server 并清空。调用方必须持锁。
    输入:
        data (dict): 当前注册表数据（原地修改）。
    输出:
        dict: 清理后的注册表。
    """
    alive_pids: list[dict[str, Any]] = []
    dead_count = 0
    for entry in data.get("pids", []):
        pid = int(entry.get("pid", 0))
        if pid > 0 and _pid_alive(pid):
            alive_pids.append(entry)
        else:
            dead_count += 1
    data["pids"] = alive_pids
    if dead_count:
        data["refcount"] = max(0, int(data.get("refcount", 0)) - dead_count)
    # 清理已死 server
    alive_servers: list[dict[str, Any]] = []
    for s in data.get("servers", []):
        spid = int(s.get("server_pid", 0))
        if spid > 0 and _pid_alive(spid):
            alive_servers.append(s)
    data["servers"] = alive_servers
    # refcount 归零 -> 树杀所有 server 并清空
    if int(data.get("refcount", 0)) <= 0:
        for s in data.get("servers", []):
            _tree_kill_pid(int(s.get("server_pid", 0)))
        data["servers"] = []
        data["pids"] = []
        data["refcount"] = 0
    return data


def gc_stale() -> None:
    """
    函数名: gc_stale
    作用: 持锁执行一次 GC；清理已死 controller pid 与已死 server，refcount 归零则树杀所有 server。
    输入: 无。
    输出: 无。
    """
    with acquire_lock():
        data = _read_registry()
        _gc_stale_locked(data)
        _write_registry(data)


def register_job(kind: str) -> tuple[int, list[int]]:
    """
    函数名: register_job
    作用: 持锁 GC -> refcount+1 -> 追加 own pid -> 返回 (my_pid, prior_live_pdf2md_pids)。
        pdf2md 调用方用 prior 列表做串行等待；ocr 调用方忽略该列表。
    输入:
        kind (str): "pdf2md" 或 "ocr"。
    输出:
        tuple[int, list[int]]: (本进程 pid, 先于本进程登记且仍存活的 pdf2md pid 列表)。
    """
    my_pid = os.getpid()
    with acquire_lock():
        data = _read_registry()
        _gc_stale_locked(data)
        ts = time.time()
        data["refcount"] = int(data.get("refcount", 0)) + 1
        # 中文注释: 先收集先于本进程登记且仍存活的 pdf2md pid（按 ts 升序）
        prior_pdf2md: list[int] = []
        for entry in data["pids"]:
            if entry.get("kind") == "pdf2md":
                pid = int(entry.get("pid", 0))
                if pid > 0 and pid != my_pid and _pid_alive(pid):
                    prior_pdf2md.append(pid)
        # 追加本进程
        data["pids"].append({"pid": my_pid, "kind": kind, "ts": ts})
        _write_registry(data)
        return my_pid, prior_pdf2md


def wait_for_pids(pids: list[int], *, poll_interval: float = 0.5, timeout: float = 7200.0) -> None:
    """
    函数名: wait_for_pids
    作用: 轮询等待给定 pid 全部退出（不持锁）；超时后强制树杀剩余 pid 以防死锁。
    输入:
        pids (list[int]): 等待的 pid 列表。
        poll_interval (float): 轮询间隔秒。
        timeout (float): 总超时秒；超时强制树杀剩余。
    输出: 无。
    """
    remaining = [int(p) for p in pids if p and int(p) > 0]
    if not remaining:
        return
    deadline = time.time() + timeout
    while remaining:
        if time.time() > deadline:
            # 超时强制树杀剩余，避免后续进程永久等待
            for p in remaining:
                _tree_kill_pid(int(p))
            break
        remaining = [p for p in remaining if _pid_alive(p)]
        if remaining:
            time.sleep(poll_interval)


def _spawn_server(port: int) -> int:
    """
    函数名: _spawn_server
    作用: 调用 mcp_runtime._spawn 启动一个 PP-StructureV3 server 并等就绪；返回 server pid。
    输入:
        port (int): 监听端口。
    输出:
        int: server 子进程 pid。
    """
    from paddleocr_mcp_controller.mcp_runtime import _spawn, _wait_ready
    proc = _spawn("PP-StructureV3", int(port))
    _wait_ready(proc, int(port), timeout=int(config.MCP_START_TIMEOUT_SEC))
    return int(proc.pid)


def adopt_or_spawn_servers(needed_k: int) -> list[dict[str, int]]:
    """
    函数名: adopt_or_spawn_servers
    作用: 持锁采纳仍存活的 server 端口并选定需新建的端口；释放锁后在锁外 spawn（避免长 spawn 阻塞其它进程）；再持锁登记新建 server。返回 [{port, server_pid, owned}]。
        owned=1 表示本进程 spawn（注册表 owner_pid=本进程），0 表示采纳自其它进程。
    输入:
        needed_k (int): 期望 server 数。
    输出:
        list[dict]: [{port, server_pid, owned}, ...]。
    """
    if needed_k <= 0:
        return []
    # 中文注释: Phase1 持锁：GC + 采纳存活 server + 选定待 spawn 端口
    with acquire_lock():
        data = _read_registry()
        _gc_stale_locked(data)
        adopted: list[dict[str, int]] = []
        for s in list(data.get("servers", [])):
            if len(adopted) >= needed_k:
                break
            port = int(s.get("port", 0))
            spid = int(s.get("server_pid", 0))
            if port > 0 and spid > 0 and _pid_alive(spid):
                adopted.append({"port": port, "server_pid": spid, "owned": 0})
        need_spawn = needed_k - len(adopted)
        spawn_ports: list[int] = []
        if need_spawn > 0:
            from paddleocr_mcp_controller.mcp_runtime import pick_free_mcp_port
            used = {int(s["port"]) for s in data.get("servers", [])}
            used.update({int(o["port"]) for o in adopted})
            for i in range(need_spawn):
                idx = len(data.get("servers", [])) + i
                preferred = int(config.STRUCTURE_MCP_PORT_BASE) + idx
                port = pick_free_mcp_port(preferred=preferred, used=used)
                spawn_ports.append(int(port))
                used.add(int(port))
        _write_registry(data)
    # 中文注释: Phase2 锁外 spawn（spawn 慢——真实 paddleocr-mcp 模型加载可达数分钟；锁外执行不阻塞其它进程 register/release）
    spawned: list[dict[str, int]] = []
    for port in spawn_ports:
        try:
            spid = _spawn_server(int(port))
            spawned.append({"port": int(port), "server_pid": int(spid), "owned": 1})
        except Exception:
            continue
    # 中文注释: Phase3 持锁登记新建 server
    if spawned:
        with acquire_lock():
            data = _read_registry()
            for e in spawned:
                data.setdefault("servers", []).append({
                    "port": int(e["port"]),
                    "server_pid": int(e["server_pid"]),
                    "owner_pid": os.getpid(),
                })
            _write_registry(data)
    return adopted + spawned


def release_job(my_pid: int) -> int:
    """
    函数名: release_job
    作用: 持锁 refcount-1、移除 own pid；refcount<=0 则树杀所有注册的 server 并清空注册表。
    输入:
        my_pid (int): 本进程 pid。
    输出:
        int: 注销后的全局 refcount。
    """
    with acquire_lock():
        data = _read_registry()
        # 移除本进程 pid 并 -1
        new_pids = [e for e in data.get("pids", []) if int(e.get("pid", 0)) != int(my_pid)]
        removed = len(new_pids) < len(data.get("pids", []))
        data["pids"] = new_pids
        if removed:
            data["refcount"] = max(0, int(data.get("refcount", 0)) - 1)
        # 顺带 GC 已死 server
        alive_servers: list[dict[str, Any]] = []
        for s in data.get("servers", []):
            spid = int(s.get("server_pid", 0))
            if spid > 0 and _pid_alive(spid):
                alive_servers.append(s)
        data["servers"] = alive_servers
        # refcount 归零 -> 树杀所有 server 并清空
        if int(data.get("refcount", 0)) <= 0:
            for s in data.get("servers", []):
                _tree_kill_pid(int(s.get("server_pid", 0)))
            data["servers"] = []
            data["pids"] = []
            data["refcount"] = 0
        _write_registry(data)
        return int(data.get("refcount", 0))


def snapshot() -> dict[str, Any]:
    """
    函数名: snapshot
    作用: 持锁读注册表（含 GC）快照，用于诊断/测试。
    输入: 无。
    输出:
        dict: 注册表快照。
    """
    with acquire_lock():
        data = _read_registry()
        _gc_stale_locked(data)
        _write_registry(data)
        return data
