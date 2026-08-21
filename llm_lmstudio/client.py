"""LM Studio 原生 REST 的 urllib HTTP 封装。"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from llm_lmstudio.config import load_user_config


class LmStudioError(RuntimeError):
    """
    类名: LmStudioError
    作用: LM Studio HTTP 失败（连接、状态码、JSON）
    """

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body



def _headers(cfg: dict[str, Any], *, json_body: bool) -> dict[str, str]:
    """
    函数名: _headers
    作用: 组装请求头；token 为空则不带 Authorization
    输入:
        cfg (dict): load_user_config 结果
        json_body (bool): POST JSON 时加 Content-Type
    输出:
        dict[str, str]: 请求头
    """
    headers = {"Accept": "application/json"}
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
