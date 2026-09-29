"""desktop-commander MCP stdio（Wikipedia URL 与本地文件）。"""

from __future__ import annotations

import atexit
import json
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable


_START_TIMEOUT = 40.0
_CALL_TIMEOUT = 60.0
_SESSION: "McpSession | None" = None
_LOCK = threading.Lock()
status_hook: Callable[[str], None] | None = None


def emit_status(msg: str) -> None:
    """
    函数名: emit_status
    作用: 可选进度钩子
    输入:
        msg (str): 短状态
    输出: 无
    """
    hook = status_hook
    if hook is None:
        return
    try:
        hook(msg)
    except Exception:
        return


def _npm_global_dir() -> Path:
    """
    函数名: _npm_global_dir
    作用: Windows npm 全局目录
    输入: 无
    输出:
        Path
    """
    return Path.home() / "AppData" / "Roaming" / "npm"


def resolve_desktop_argv() -> list[str]:
    """
    函数名: resolve_desktop_argv
    作用: 尽量用 node 跑 js，避免 .cmd 破坏 stdio
    输入: 无
    输出:
        list[str]
    """
    node = shutil.which("node") or shutil.which("node.exe")
    npm = _npm_global_dir()
    candidates = [
        npm / "node_modules" / "@wonderwhy-er" / "desktop-commander" / "dist" / "index.js",
        npm / "node_modules" / "desktop-commander" / "dist" / "index.js",
        npm / "node_modules" / "@wonderwhy-er" / "desktop-commander" / "build" / "index.js",
    ]
    if node:
        for js in candidates:
            if js.is_file():
                return [node, str(js)]
    cmd = shutil.which("desktop-commander") or shutil.which("desktop-commander.cmd")
    if not cmd:
        npm_cmd = npm / "desktop-commander.cmd"
        if npm_cmd.is_file():
            cmd = str(npm_cmd)
    if not cmd:
        raise RuntimeError(
            "desktop-commander not found. Install the Desktop Commander MCP and ensure it is on PATH."
        )
    return [cmd]


class McpSession:
    """
    类名: McpSession
    作用: 单个 desktop-commander stdio 进程
    """

    def __init__(self) -> None:
        self.proc: subprocess.Popen[bytes] | None = None
        self._out: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._err: list[str] = []
        self._next_id = 1
        self._reader: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None


    def start(self) -> None:
        """
        函数名: start
        作用: 启动并 initialize
        输入: 无
        输出: 无
        """
        argv = resolve_desktop_argv()
        emit_status("desktop-commander: launching")
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()
        self._stderr_thread.start()
        self._rpc(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "mcp_desktop", "version": "0.1"},
            },
            timeout=_START_TIMEOUT,
        )
        self._notify("notifications/initialized", {})
        emit_status("desktop-commander: ready")


    def close(self) -> None:
        """
        函数名: close
        作用: 结束子进程
        输入: 无
        输出: 无
        """
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """
        函数名: call_tool
        作用: tools/call
        输入:
            name (str): 工具名
            arguments (dict | None): 参数
        输出:
            Any
        """
        return self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=_CALL_TIMEOUT,
        )


    def _rpc(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        """
        函数名: _rpc
        作用: JSON-RPC 请求
        输入:
            method (str): 方法
            params (dict): 参数
            timeout (float): 秒
        输出:
            Any
        """
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("desktop-commander session is not running")
        rid = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = timeout
        while True:
            try:
                msg = self._out.get(timeout=deadline)
            except queue.Empty:
                err = "".join(self._err[-8:]).strip()
                raise RuntimeError(f"MCP timeout on {method}: {err[:400]}")
            if msg is None:
                err = "".join(self._err[-8:]).strip()
                raise RuntimeError(f"MCP process ended during {method}: {err[:400]}")
            if msg.get("id") != rid:
                continue
            if "error" in msg:
                raise RuntimeError(str(msg.get("error")))
            return msg.get("result")


    def _notify(self, method: str, params: dict[str, Any]) -> None:
        """
        函数名: _notify
        作用: JSON-RPC 通知
        输入:
            method (str): 方法
            params (dict): 参数
        输出: 无
        """
        self._write({"jsonrpc": "2.0", "method": method, "params": params})


    def _write(self, obj: dict[str, Any]) -> None:
        """
        函数名: _write
        作用: 先写 JSON 行；多数 MCP 也能吃
        输入:
            obj (dict): JSON-RPC
        输出: 无
        """
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("desktop-commander session is not running")
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        frame = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw
        self.proc.stdin.write(frame)
        self.proc.stdin.flush()


    def _read_stdout(self) -> None:
        """
        函数名: _read_stdout
        作用: Content-Length 或 JSON 行
        输入: 无
        输出: 无
        """
        stdout = self.proc.stdout if self.proc is not None else None
        if stdout is None:
            self._out.put(None)
            return
        try:
            while True:
                line = stdout.readline()
                if not line:
                    self._out.put(None)
                    return
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                if text.lower().startswith("content-length:"):
                    length = int(text.split(":", 1)[1].strip() or "0")
                    while True:
                        more = stdout.readline()
                        if not more or more in (b"\r\n", b"\n"):
                            break
                    body = stdout.read(length) if length > 0 else b""
                    try:
                        parsed = json.loads(body.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        self._out.put(parsed)
                    continue
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    self._out.put(parsed)
        except Exception:
            self._out.put(None)


    def _read_stderr(self) -> None:
        """
        函数名: _read_stderr
        作用: 收集 stderr
        输入: 无
        输出: 无
        """
        stderr = self.proc.stderr if self.proc is not None else None
        if stderr is None:
            return
        try:
            for raw in stderr:
                self._err.append(raw.decode("utf-8", errors="replace"))
        except Exception:
            return


def ensure_session() -> McpSession:
    """
    函数名: ensure_session
    作用: 懒启动全局 desktop-commander
    输入: 无
    输出:
        McpSession
    """
    global _SESSION
    with _LOCK:
        if _SESSION is not None and _SESSION.proc is not None and _SESSION.proc.poll() is None:
            return _SESSION
        session = McpSession()
        session.start()
        _SESSION = session
        return session


def close_session() -> None:
    """
    函数名: close_session
    作用: 关掉全局会话
    输入: 无
    输出: 无
    """
    global _SESSION
    with _LOCK:
        if _SESSION is None:
            return
        _SESSION.close()
        _SESSION = None


atexit.register(close_session)
