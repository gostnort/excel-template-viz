"""标准 OpenAI 兼容协议客户端，原生对接 LM Studio /v1 端点。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence

from llm_cli.lms.config import load_user_config, save_user_config
from llm_cli.lms.lms_cli import lms_load, lms_ps


class LmsError(RuntimeError):
    """LMS 通信与协议异常"""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class CompletionResult:
    """补全结果快照"""

    text: str
    tool_calls: list[dict[str, Any]] | None = None
    thought: str | None = None
    tokens_used: int | None = None
    context_limit: int | None = None
    raw: Any = None


@dataclass(frozen=True)
class HealthReport:
    """LMS 服务健康报告"""

    ok: bool
    api_url: str = ""
    model: str = ""
    vision: bool = False
    message: str = ""
    loaded_models: list[str] = field(default_factory=list)


def _headers(cfg: dict[str, Any], *, json_body: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json"
    token = str(cfg.get("api_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _extract_embedded_think(text: str) -> tuple[str, str | None]:
    """提取 <think>...</think> 标签里的内容"""
    if not text:
        return "", None
    match = re.search(r"<think>(.*?)</think>", text, flags=re.DOTALL)
    if match:
        thought = match.group(1).strip()
        cleaned = (text[:match.start()] + text[match.end():]).strip()
        return cleaned, thought
    return text, None


def _model_has_vision(item: dict[str, Any]) -> bool:
    """
    函数名: _model_has_vision
    作用: 从模型对象上读取视觉能力标记
    输入:
        item (dict): /v1/models 里的一条模型
    输出:
        bool: capabilities.vision 或 vision 为真时返回 True
    """
    if item.get("vision") is True:
        return True
    caps = item.get("capabilities")
    if isinstance(caps, dict):
        return bool(caps.get("vision"))
    return False


def _model_context_limit(item: dict[str, Any]) -> int | None:
    """
    函数名: _model_context_limit
    作用: 从模型对象上读取上下文长度
    输入:
        item (dict): /v1/models 里的一条模型
    输出:
        int | None: 正整数上限；字段缺失则为 None
    """
    for key in ("max_context_length", "context_length", "loaded_context_length"):
        raw = item.get(key)
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int) and raw > 0:
            return raw
        if isinstance(raw, str) and raw.isdigit() and int(raw) > 0:
            return int(raw)
    return None


class LmsClient:
    """与 LM Studio 交互的核心客户端"""

    def __init__(self) -> None:
        pass

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        cfg = load_user_config()
        root = str(cfg.get("api_url") or "http://127.0.0.1:1234").rstrip("/")
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
                if not raw:
                    return None
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise LmsError(
                f"LMS HTTP {exc.code} {method} {path}: {err_body[:300]}",
                status=exc.code,
                body=err_body,
            ) from exc
        except Exception as exc:
            raise LmsError(f"LMS request failed ({method} {path}): {exc}") from exc

    def health_check(self) -> HealthReport:
        cfg = load_user_config()
        api_url = str(cfg.get("api_url") or "").rstrip("/")
        expected_model = str(cfg.get("model") or "").strip()
        try:
            res = self.request_json("GET", "/v1/models", timeout=4.0)
            data = res.get("data") if isinstance(res, dict) else []
            models = [m for m in data if isinstance(m, dict) and m.get("id")] if isinstance(data, list) else []
            loaded = [str(m.get("id")) for m in models]
            if not loaded:
                # 兼容 lms ps 查显存中的模型
                loaded = lms_ps()
            if not loaded:
                return HealthReport(
                    ok=True,
                    api_url=api_url,
                    model=expected_model,
                    message="model not loaded",
                    loaded_models=[],
                )
            current_model = expected_model if expected_model in loaded else str(loaded[0])
            current = next((m for m in models if str(m.get("id")) == current_model), None)
            vision = _model_has_vision(current) if current is not None else False
            return HealthReport(
                ok=True,
                api_url=api_url,
                model=current_model,
                message="ok",
                vision=vision,
                loaded_models=loaded,
            )
        except Exception as exc:
            return HealthReport(
                ok=False,
                api_url=api_url,
                model=expected_model,
                message=f"down ({exc})",
                loaded_models=[],
            )

    def load_model(self, model_key: str, *, remember: bool = True) -> bool:
        if remember and model_key:
            save_user_config(model=model_key, remember_model=True)
        return lms_load(model_key)


    def context_limit_for(self, model_key: str) -> int | None:
        """
        函数名: context_limit_for
        作用: 查询指定模型的上下文长度
        输入:
            model_key (str): 模型 id
        输出:
            int | None: 正整数上限；查不到则为 None
        """
        key = str(model_key or "").strip()
        if not key:
            return None
        try:
            res = self.request_json("GET", "/v1/models", timeout=4.0)
        except Exception:
            return None
        data = res.get("data") if isinstance(res, dict) else []
        if not isinstance(data, list):
            return None
        for item in data:
            if isinstance(item, dict) and str(item.get("id") or "") == key:
                return _model_context_limit(item)
        return None


    def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
        model: str = "",
        thinking: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream: bool = False,
        on_delta: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
        timeout: float = 180.0,
    ) -> CompletionResult:
        cfg = load_user_config()
        model_name = model or str(cfg.get("model") or "").strip()
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": list(messages),
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = list(tools)

        if not stream:
            res = self.request_json("POST", "/v1/chat/completions", body=payload, timeout=timeout)
            if not isinstance(res, dict):
                return CompletionResult(text="", raw=res)
            choices = res.get("choices") or []
            first = choices[0] if choices else {}
            msg = first.get("message") or {}
            raw_text = str(msg.get("content") or "")
            tool_calls = msg.get("tool_calls")
            thought = msg.get("reasoning_content") or msg.get("thought")
            if not thought:
                raw_text, thought = _extract_embedded_think(raw_text)
            tokens_used = None
            usage = res.get("usage")
            if isinstance(usage, dict):
                tokens_used = usage.get("total_tokens")
            return CompletionResult(
                text=raw_text,
                tool_calls=tool_calls,
                thought=thought,
                tokens_used=tokens_used,
                raw=res,
            )

        # 流式处理
        root = str(cfg.get("api_url") or "http://127.0.0.1:1234").rstrip("/")
        url = root + "/v1/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers=_headers(cfg, json_body=True),
        )
        full_text: list[str] = []
        full_thought: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for line_bytes in resp:
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    # 捕获 reasoning / thought
                    reasoning = delta.get("reasoning_content") or delta.get("thought")
                    if reasoning:
                        full_thought.append(reasoning)
                        if on_thought:
                            on_thought(reasoning)
                    # 捕获 content
                    content = delta.get("content")
                    if content:
                        full_text.append(content)
                        if on_delta:
                            on_delta(content)
        except Exception as exc:
            raise LmsError(f"LMS streaming error: {exc}") from exc

        joined = "".join(full_text)
        joined_thought = "".join(full_thought) or None
        if not joined_thought:
            joined, joined_thought = _extract_embedded_think(joined)

        return CompletionResult(
            text=joined,
            tool_calls=tool_calls or None,
            thought=joined_thought,
            tokens_used=None,
        )
