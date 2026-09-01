"""LlmBackend / LlmSession 协议与 LM Studio 适配器。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence
from pathlib import Path

from llm_cli.lm_studio.chat import chat_text, chat_vision
from llm_cli.lm_studio.complete import CompletionResult, complete as complete_chat
from llm_cli.lm_studio.config import load_user_config
from llm_cli.lm_studio.models import list_models, load_model, model_context_limit


@dataclass(frozen=True)
class SessionOptions:
    """会话级设置：system / thinking / max_tokens / temperature。"""

    system_message: str | None = None
    thinking: bool = False
    max_tokens: int | None = None
    temperature: float = 0.0



@dataclass(frozen=True)
class JudgmentToolSpec:
    """结构化判定工具描述（LM Studio 路径忽略约束解码，仅作协议兼容）。"""

    name: str
    description: str
    verdict_key: str
    reason_key: str



@dataclass(frozen=True)
class GenerateResult:
    """一次 generate / send_turn 的文本结果。"""

    text: str
    thought: str | None = None
    tool_call_arguments: Mapping[str, Any] | None = None
    raw: Any = None
    tokens_used: int | None = None
    context_limit: int | None = None



@dataclass(frozen=True)
class HealthReport:
    """连接与当前模型状态。"""

    ok: bool
    api_url: str = ""
    model: str = ""
    vision: bool = False
    message: str = ""
    profile: str = "lmstudio"
    litert_backend: str = ""
    mtp: bool = False
    model_path: str = ""



class LlmSession(Protocol):
    def send_turn(
        self, message: Mapping[str, Any], *, max_output_tokens: int | None = None, thinking: bool | None = None,
    ) -> GenerateResult: ...

    def close(self) -> None: ...

    @property
    def token_count(self) -> int: ...



class LlmBackend(Protocol):
    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool: JudgmentToolSpec | None = None,
    ) -> GenerateResult: ...

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        model: str = "",
        thinking: bool = False,
        **kwargs: Any,
    ) -> CompletionResult: ...

    def open_session(
        self, session_id: str, *, options: SessionOptions | None = None,
    ) -> LlmSession: ...

    def generate_vision(
        self,
        image: str | Path | bytes,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerateResult: ...

    def warm(self) -> None: ...

    def health_check(self) -> HealthReport: ...

    def close(self) -> None: ...



def _chat_result(payload: dict[str, Any], model_key: str = "") -> GenerateResult:
    """
    函数名: _chat_result
    作用: 把 chat() 字典收成 GenerateResult，并带上用量与上下文上限
    输入:
        payload (dict): chat() 返回值
        model_key (str): 用于查列表里的 context 上限
    输出:
        GenerateResult
    """
    usage = payload.get("usage") if isinstance(payload, dict) else None
    used = None
    if isinstance(usage, dict):
        n = usage.get("total_tokens")
        if isinstance(n, (int, float)) and int(n) > 0:
            used = int(n)
    key = str(model_key or load_user_config().get("model") or "").strip()
    limit = None
    if key:
        try:
            limit = model_context_limit(key)
        except Exception:
            limit = None
    thought = payload.get("thought") if isinstance(payload, dict) else None
    if thought is not None:
        thought = str(thought).strip() or None
    return GenerateResult(
        text=str((payload or {}).get("text") or ""),
        thought=thought,
        raw=(payload or {}).get("raw"),
        tokens_used=used,
        context_limit=limit,
    )



@dataclass
class LmStudioSession:
    """
    类名: LmStudioSession
    作用: 用 previous_response_id 模拟持久会话；一次性子代理 store=False
    """

    backend: "LmStudioBackend"
    session_id: str
    options: SessionOptions
    store: bool = False
    previous_response_id: str | None = None
    _closed: bool = field(default=False, repr=False)
    _tokens: int = field(default=0, repr=False)

    def send_turn(
        self, message: Mapping[str, Any], *, max_output_tokens: int | None = None, thinking: bool | None = None, on_delta: Callable[[str], None] | None = None, on_thought: Callable[[str], None] | None = None,
    ) -> GenerateResult:
        """
        函数名: send_turn
        作用: 发送一轮 user 文本
        输入:
            message (Mapping): 须含 content
            max_output_tokens (int | None): 覆盖会话默认
            thinking (bool | None): 覆盖会话 reasoning；空则用 options.thinking
            on_delta (callable | None): 流式 message 增量；有则走 SSE
            on_thought (callable | None): 流式 reasoning 增量
        输出:
            GenerateResult
        """
        if self._closed:
            raise RuntimeError(f"session closed: {self.session_id}")
        content = str(message.get("content") or "")
        budget = max_output_tokens if max_output_tokens is not None else self.options.max_tokens
        think = self.options.thinking if thinking is None else bool(thinking)
        result = chat_text(
            content,
            system_prompt=self.options.system_message,
            temperature=self.options.temperature,
            max_output_tokens=budget,
            thinking=think,
            store=self.store,
            previous_response_id=self.previous_response_id if self.store else None,
            on_delta=on_delta,
            on_thought=on_thought,
            stream=on_delta is not None or on_thought is not None,
        )
        if self.store:
            self.previous_response_id = result.get("response_id")
        packed = _chat_result(result)
        if packed.tokens_used:
            self._tokens = packed.tokens_used
        return packed

    def close(self) -> None:
        """
        函数名: close
        作用: 结束本会话（不卸载模型）
        输入: 无
        输出: 无
        """
        self._closed = True
        self.backend.drop_session(self.session_id)

    @property
    def token_count(self) -> int:
        return self._tokens



class LmStudioBackend:
    """
    类名: LmStudioBackend
    作用: 把 LlmBackend 协议接到 LM Studio REST
    """

    def __init__(self) -> None:
        self._sessions: dict[str, LmStudioSession] = {}
        self._lock = threading.Lock()

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool: JudgmentToolSpec | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> GenerateResult:
        """
        函数名: generate
        作用: 无状态单次文本推理
        输入:
            messages: OpenAI 风格消息；取最后一条 user 与可选 system
            thinking / max_tokens / temperature: 采样
            judgment_tool: 忽略（无约束解码）
            on_delta (callable | None): 流式 message 增量；有则走 SSE
            on_thought (callable | None): 流式 reasoning 增量
        输出:
            GenerateResult
        """
        _ = judgment_tool
        system = None
        user = ""
        for item in messages:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "")
            if role == "system" and content:
                system = content
            elif role == "user":
                user = content
        if not user and messages:
            user = str(messages[-1].get("content") or "")
        result = chat_text(
            user,
            system_prompt=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
            thinking=thinking,
            store=False,
            on_delta=on_delta,
            on_thought=on_thought,
            stream=on_delta is not None or on_thought is not None,
        )
        return _chat_result(result)

    def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        model: str = "",
        thinking: bool = False,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        stream: bool = False,
        on_delta: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> CompletionResult:
        """
        函数名: complete
        作用: 全历史 + tools 走 OpenAI 兼容 completions（Agent 工具循环用）
        输入:
            messages: OpenAI 风格消息
            tools: function schema 列表
            model (str): 空则 user.toml
            thinking / temperature / max_tokens / stream / on_delta / on_thought: 采样与预留流式
        输出:
            CompletionResult
        """
        packed_tools = None
        if tools:
            packed_tools = [dict(item) for item in tools]
        rows = [dict(item) for item in messages]
        return complete_chat(
            rows,
            tools=packed_tools,
            model=model,
            thinking=thinking,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            on_delta=on_delta,
            on_thought=on_thought,
        )


    def generate_vision(
        self,
        image: str | Path | bytes,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerateResult:
        """
        函数名: generate_vision
        作用: 读图 chat
        输入:
            image: 路径或字节
            prompt (str): 文本提示
            system / max_tokens / temperature: 采样
        输出:
            GenerateResult
        """
        result = chat_vision(
            image,
            prompt,
            system_prompt=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        return GenerateResult(
            text=str(result.get("text") or ""),
            thought=result.get("thought"),
            raw=result.get("raw"),
        )

    def open_session(
        self, session_id: str, *, options: SessionOptions | None = None,
    ) -> LmStudioSession:
        """
        函数名: open_session
        作用: 同 session_id 复用会话；wizard_main / dialog_main 开启 store
        输入:
            session_id (str): 会话 id
            options (SessionOptions | None): 创建时选项
        输出:
            LmStudioSession
        """
        with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None and not existing._closed:
                return existing
            opts = options or SessionOptions()
            store = True
            session = LmStudioSession(
                backend=self,
                session_id=session_id,
                options=opts,
                store=store,
            )
            self._sessions[session_id] = session
            return session

    def drop_session(self, session_id: str) -> None:
        """
        函数名: drop_session
        作用: 从缓存去掉已关闭会话
        输入:
            session_id (str): 会话 id
        输出: 无
        """
        with self._lock:
            self._sessions.pop(session_id, None)

    def warm(self) -> None:
        """
        函数名: warm
        作用: 按配置加载当前模型
        输入: 无
        输出: 无
        """
        cfg = load_user_config()
        name = str(cfg.get("model") or "").strip()
        if not name:
            raise ValueError("user.toml 未设置 model")
        load_model(name, remember=True)

    def health_check(self) -> HealthReport:
        """
        函数名: health_check
        作用: 探测 API 与当前模型（不强制 load）
        输入: 无
        输出:
            HealthReport
        """
        cfg = load_user_config()
        url = str(cfg.get("api_url") or "")
        name = str(cfg.get("model") or "")
        try:
            catalog = list_models()
        except Exception as exc:
            return HealthReport(
                ok=False,
                api_url=url,
                model=name,
                vision=False,
                message=str(exc),
                profile="lmstudio",
                litert_backend=name,
                model_path=url,
            )
        vision = False
        loaded = False
        if name:
            info = None
            for item in catalog:
                if str(item.get("key") or item.get("id") or "") == name:
                    info = item
                    break
            if info is not None:
                caps = info.get("capabilities") or {}
                if isinstance(caps, dict):
                    vision = bool(caps.get("vision"))
                instances = info.get("loaded_instances") or []
                loaded = bool(instances)
        msg = "ok"
        if name and not loaded:
            msg = "model not loaded"
        return HealthReport(
            ok=True,
            api_url=url,
            model=name,
            vision=vision,
            message=msg,
            profile="lmstudio",
            litert_backend=name,
            model_path=url,
        )

    def close(self) -> None:
        """
        函数名: close
        作用: 关闭本地会话缓存，不卸载远端权重
        输入: 无
        输出: 无
        """
        with self._lock:
            self._sessions.clear()



_backend: LmStudioBackend | None = None
_backend_lock = threading.Lock()



def get_backend() -> LmStudioBackend:
    """
    函数名: get_backend
    作用: 进程内单例 LmStudioBackend
    输入: 无
    输出:
        LmStudioBackend
    """
    global _backend
    if _backend is None:
        with _backend_lock:
            if _backend is None:
                _backend = LmStudioBackend()
    return _backend



def reset_backend() -> None:
    """
    函数名: reset_backend
    作用: 清空单例（不 unload 模型）
    输入: 无
    输出: 无
    """
    global _backend
    with _backend_lock:
        if _backend is not None:
            _backend.close()
            _backend = None
