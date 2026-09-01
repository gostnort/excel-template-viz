"""用 npm npx 拉起 chrome-devtools-mcp（失败则短错误，不抛穿）。"""

from __future__ import annotations

import atexit
import json
import os
import queue
import shutil
import subprocess
import threading
from typing import Any
from urllib.parse import quote_plus


_START_TIMEOUT = 90.0
_CALL_TIMEOUT = 60.0
_SESSION: "McpSession | None" = None
_LOCK = threading.Lock()



class McpSession:
    """
    类名: McpSession
    作用: 单个 chrome-devtools-mcp stdio 进程
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
        作用: 启动 npx chrome-devtools-mcp 并 initialize
        输入: 无
        输出: 无
        """
        npx = shutil.which("npx") or shutil.which("npx.cmd")
        if not npx:
            raise RuntimeError("npx not found; install Node.js LTS to use Chrome DevTools MCP")
        env = os.environ.copy()
        env["CHROME_DEVTOOLS_MCP_NO_USAGE_STATISTICS"] = "1"
        env["CI"] = env.get("CI") or "1"
        # 中文注释: headless + isolated，避免动用户日常 Chrome 配置
        self.proc = subprocess.Popen(
            [npx, "-y", "chrome-devtools-mcp@latest", "--headless", "--isolated"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
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
                "clientInfo": {"name": "mcp_chrome", "version": "0.1"},
            },
            timeout=_START_TIMEOUT,
        )
        self._notify("notifications/initialized", {})


    def close(self) -> None:
        """
        函数名: close
        作用: 结束 MCP 子进程
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


    def list_tools(self) -> list[str]:
        """
        函数名: list_tools
        作用: tools/list 的名字
        输入: 无
        输出:
            list[str]
        """
        result = self._rpc("tools/list", {}, timeout=_CALL_TIMEOUT)
        tools = result.get("tools") if isinstance(result, dict) else None
        names: list[str] = []
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict):
                    name = str(item.get("name") or "").strip()
                    if name:
                        names.append(name)
        return names


    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """
        函数名: call_tool
        作用: tools/call
        输入:
            name (str): 工具名
            arguments (dict | None): 参数
        输出:
            Any: MCP result
        """
        return self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=_CALL_TIMEOUT,
        )


    def _rpc(self, method: str, params: dict[str, Any], *, timeout: float) -> Any:
        """
        函数名: _rpc
        作用: 发一条 JSON-RPC 并等 id 匹配的结果
        输入:
            method (str): 方法
            params (dict): 参数
            timeout (float): 秒
        输出:
            Any
        """
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("MCP session is not running")
        rid = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        self._write(payload)
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
        作用: 无 id 的 JSON-RPC 通知
        输入:
            method (str): 方法
            params (dict): 参数
        输出: 无
        """
        self._write({"jsonrpc": "2.0", "method": method, "params": params})


    def _write(self, obj: dict[str, Any]) -> None:
        """
        函数名: _write
        作用: Content-Length 帧写入 stdin
        输入:
            obj (dict): JSON-RPC 体
        输出: 无
        """
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("MCP session is not running")
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        self.proc.stdin.write(header + raw)
        self.proc.stdin.flush()


    def _read_stdout(self) -> None:
        """
        函数名: _read_stdout
        作用: 解析 stdout 的 Content-Length 帧
        输入: 无
        输出: 无
        """
        stdout = self.proc.stdout if self.proc is not None else None
        if stdout is None:
            self._out.put(None)
            return
        try:
            while True:
                headers: dict[str, str] = {}
                while True:
                    line = stdout.readline()
                    if not line:
                        self._out.put(None)
                        return
                    if line in (b"\r\n", b"\n"):
                        break
                    text = line.decode("utf-8", errors="replace").strip()
                    if ":" in text:
                        key, val = text.split(":", 1)
                        headers[key.strip().lower()] = val.strip()
                length = int(headers.get("content-length") or "0")
                if length <= 0:
                    continue
                body = stdout.read(length)
                if not body:
                    self._out.put(None)
                    return
                try:
                    parsed = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    self._out.put(parsed)
        except Exception:
            self._out.put(None)


    def _read_stderr(self) -> None:
        """
        函数名: _read_stderr
        作用: 收集 stderr 文本便于报错
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
    作用: 懒启动全局 MCP 会话
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
    作用: 关掉全局 MCP 会话
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



def google_url(query: str) -> str:
    """
    函数名: google_url
    作用: 组装谷歌搜索 URL
    输入:
        query (str): 查询串
    输出:
        str
    """
    return "https://www.google.com/search?q=" + quote_plus(query or "")
