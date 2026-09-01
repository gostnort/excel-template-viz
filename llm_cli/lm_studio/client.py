"""LM Studio 原生 REST 的 urllib HTTP 封装。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Iterator
from urllib.parse import quote

from llm_cli.lm_studio.config import load_user_config


class LmStudioError(RuntimeError):
    """
    类名: LmStudioError
    作用: LM Studio HTTP 失败（连接、状态码、JSON）
    """

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body



def _headers(cfg: dict[str, Any], *, json_body: bool, accept: str | None = None) -> dict[str, str]:
    """
    函数名: _headers
    作用: 组装请求头；token 为空则不带 Authorization
    输入:
        cfg (dict): load_user_config 结果
        json_body (bool): POST JSON 时加 Content-Type
        accept (str | None): 覆盖 Accept；空则 application/json
    输出:
        dict[str, str]: 请求头
    """
    headers = {"Accept": accept or "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = str(cfg.get("api_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers



def api_url() -> str:
    """
    函数名: api_url
    作用: 当前配置中的 LM Studio 根地址（无尾斜杠）
    输入: 无
    输出:
        str: 如 http://localhost:9999
    """
    return str(load_user_config()["api_url"])



def request_json(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Any:
    """
    函数名: request_json
    作用: 对 /api/v1 发请求并解析 JSON
    输入:
        method (str): GET / POST
        path (str): 以 / 开头的路径，已含编码
        body (dict | None): POST JSON 体
        timeout (float): 秒
    输出:
        Any: 解析后的 JSON；空响应为 None
    """
    cfg = load_user_config()
    root = str(cfg["api_url"]).rstrip("/")
    url = root + path
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method=method.upper(),
        headers=_headers(cfg, json_body=body is not None),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise LmStudioError(
            f"LM Studio HTTP {exc.code} {method} {path}: {err_body[:400]}",
            status=exc.code,
            body=err_body,
        ) from exc
    except urllib.error.URLError as exc:
        raise LmStudioError(f"无法连接 LM Studio ({root}): {exc}") from exc
    if not raw:
        return None
    text = raw.decode("utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LmStudioError(f"LM Studio 返回非 JSON: {text[:200]}", body=text) from exc


def _sse_flush(event_name: str, data_lines: list[str]) -> dict[str, Any] | None:
    """
    函数名: _sse_flush
    作用: 把已收集的 data 行解析成一条事件 dict
    输入:
        event_name (str): SSE event 字段
        data_lines (list): data: 后的文本行
    输出:
        dict | None: JSON 对象；空块或 [DONE] 为 None
    """
    raw = "\n".join(data_lines).strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    if event_name and "type" not in obj:
        obj = dict(obj)
        obj["type"] = event_name
    return obj


def _sse_feed_line(
    line: str,
    event_name: str,
    data_lines: list[str],
) -> tuple[str, list[str], dict[str, Any] | None]:
    """
    函数名: _sse_feed_line
    作用: 吃一行 SSE / NDJSON，空行则冲出事件
    输入:
        line (str): 不含换行
        event_name (str): 当前 event 名
        data_lines (list): 当前 data 缓冲
    输出:
        tuple: (新 event 名, 新 data 缓冲, 可选事件)
    """
    if not line:
        ev = _sse_flush(event_name, data_lines)
        return "", [], ev
    if line.startswith(":"):
        return event_name, data_lines, None
    if line.startswith("event:"):
        return line[6:].strip(), data_lines, None
    if line.startswith("data:"):
        data_lines.append(line[5:].lstrip())
        return event_name, data_lines, None
    # 中文注释: 无 SSE 前缀时把一整行当 JSON
    stripped = line.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            return event_name, data_lines, None
        if isinstance(obj, dict):
            return event_name, data_lines, obj
    return event_name, data_lines, None


def _read_sse_events(resp: Any) -> Iterator[dict[str, Any]]:
    """
    函数名: _read_sse_events
    作用: 从 HTTP 响应按块读 SSE，逐条 yield 事件
    输入:
        resp: urlopen 响应（有 read）
    输出:
        Iterator[dict]: 解析出的事件
    """
    leftover = b""
    event_name = ""
    data_lines: list[str] = []
    # 中文注释: 按 \n 切行，半包 UTF-8 留在 leftover
    while True:
        piece = resp.read(8192)
        if not piece:
            if leftover:
                line = leftover.decode("utf-8", errors="replace")
                leftover = b""
                event_name, data_lines, ev = _sse_feed_line(line, event_name, data_lines)
                if ev is not None:
                    yield ev
            ev = _sse_flush(event_name, data_lines)
            if ev is not None:
                yield ev
            return
        leftover += piece
        while True:
            idx = leftover.find(b"\n")
            if idx < 0:
                break
            raw = leftover[:idx]
            leftover = leftover[idx + 1:]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            line = raw.decode("utf-8", errors="replace")
            event_name, data_lines, ev = _sse_feed_line(line, event_name, data_lines)
            if ev is not None:
                yield ev


def iter_sse(
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> Iterator[dict[str, Any]]:
    """
    函数名: iter_sse
    作用: POST/GET 流式端点，解析 SSE（或 NDJSON）为事件 dict
    输入:
        method (str): GET / POST
        path (str): 以 / 开头的路径
        body (dict | None): POST JSON 体
        timeout (float): 秒
    输出:
        Iterator[dict]: 服务端事件
    """
    cfg = load_user_config()
    root = str(cfg["api_url"]).rstrip("/")
    url = root + path
    payload = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method=method.upper(),
        headers=_headers(cfg, json_body=body is not None, accept="text/event-stream"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            yield from _read_sse_events(resp)
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise LmStudioError(
            f"LM Studio HTTP {exc.code} {method} {path}: {err_body[:400]}",
            status=exc.code,
            body=err_body,
        ) from exc
    except urllib.error.URLError as exc:
        raise LmStudioError(f"无法连接 LM Studio ({root}): {exc}") from exc



def encode_model_path(model_key: str) -> str:
    """
    函数名: encode_model_path
    作用: 把模型 key（可含 /）编成 URL 路径段
    输入:
        model_key (str): 如 google/gemma-4-26b-a4b
    输出:
        str: 百分号编码后的一段
    """
    return quote(str(model_key).strip(), safe="")
