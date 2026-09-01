"""通用 Agent / Workflow（Quark 形状：tools、max_turns、>>、列表扇出）。"""

from __future__ import annotations

import inspect
import json
import typing
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from llm_cli.provider import get_provider


class Agent:
    """
    类名: Agent
    作用: 带 tools 的 LLM 节点，可用 >> 编进 Workflow；不绑定任何业务应用
    """

    def __init__(
        self,
        *,
        system: str = "You are a helpful assistant.",
        tools: dict[str, Callable[..., Any]] | list[Callable[..., Any]] | None = None,
        model: str = "",
        max_turns: int = 10,
        name: str = "agent",
        thinking: bool | str = False,
        stream: bool = False,
    ) -> None:
        self.name = name
        self.model = model
        self.max_turns = max_turns
        self.system = system
        self.stream = stream
        self.thinking_policy = _policy_from_thinking(thinking)
        self.thinking = self.thinking_policy == "always"
        self.on_tool: Callable[[str], None] | None = None
        raw = tools or {}
        self.tools: dict[str, Callable[..., Any]] = (
            {fn.__name__: fn for fn in raw} if isinstance(raw, list) else dict(raw)
        )
        self.schemas = [_tool_schema(key, fn) for key, fn in self.tools.items()]
        self.history: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self._session_id = f"agent_{name}"
        self.last_thought: str | None = None
        self.last_tokens_used: int | None = None
        self.last_context_limit: int | None = None


    def __rshift__(self, other: Any) -> "Workflow":
        """
        函数名: __rshift__
        作用: self >> other
        输入:
            other: Agent、Workflow、可调用或并行 list
        输出:
            Workflow
        """
        return Workflow([self, wrap_node(other)])


    def __rrshift__(self, other: Any) -> "Workflow":
        """
        函数名: __rrshift__
        作用: other >> self
        输入:
            other: 左侧节点
        输出:
            Workflow
        """
        return Workflow([wrap_node(other), self])


    def reset(self) -> None:
        """
        函数名: reset
        作用: 清历史，保留 system / tools
        输入: 无
        输出: 无
        """
        self.history = [{"role": "system", "content": self.system}]
        self.last_thought = None
        self.last_tokens_used = None
        self.last_context_limit = None
        self.thinking = self.thinking_policy == "always"


    def set_thinking(self, enabled: bool) -> None:
        """
        函数名: set_thinking
        作用: 开关本 Agent 的 reasoning；下一轮 complete 立即生效
        输入:
            enabled (bool): True 则 always，False 则 off
        输出: 无
        """
        self.thinking_policy = "always" if enabled else "off"
        self.thinking = bool(enabled)


    def set_stream(self, enabled: bool) -> None:
        """
        函数名: set_stream
        作用: 开关本 Agent 的 token 流式输出；默认关，调试时打开
        输入:
            enabled (bool): True 走 SSE 并按到达回调，False 等完整回复
        输出: 无
        """
        self.stream = bool(enabled)


    def _think_this_turn(self, turn: int) -> bool:
        """
        函数名: _think_this_turn
        作用: 按策略决定本轮 complete 是否开 thinking
        输入:
            turn (int): 0 起的 complete 次数
        输出:
            bool
        """
        if self.thinking_policy == "always":
            return True
        if self.thinking_policy == "after_tools":
            return turn > 0
        return False


    def run(self, user: str, history: list[dict[str, Any]] | None = None, on_delta: Callable[[str], None] | None = None, on_thought: Callable[[str], None] | None = None) -> str | tuple[str, list[dict[str, Any]]]:
        """
        函数名: run
        作用: Quark 式循环：complete → 若有 tool_calls 则执行 tools，最多 max_turns
        输入:
            user (str): 本轮用户文本
            history (list | None): 传入则为无状态，返回 (文本, 历史)
            on_delta (callable | None): stream 开启时把 message 增量交给 UI
            on_thought (callable | None): stream 开启时把 reasoning 增量交给 UI
        输出:
            str 或 (str, list)
        """
        stateless = history is not None
        if stateless:
            h = list(history)
            if not h or h[0].get("role") != "system":
                h = [{"role": "system", "content": self.system}] + h
            h.append({"role": "user", "content": user})
        else:
            h = self.history
            self.history.append({"role": "user", "content": user})
        last = ""
        cb = on_delta if self.stream else None
        thought_cb = on_thought if self.stream else None
        for turn in range(self.max_turns):
            last, calls = self._complete(h, turn, on_delta=cb, on_thought=thought_cb)
            if not calls:
                self._fill_usage_estimate(h)
                return (last, h) if stateless else last
            self._apply_tools(calls, h)
        fallback = last or "max turns reached"
        self._fill_usage_estimate(h)
        return (fallback, h) if stateless else fallback


    def _complete(
        self,
        history: list[dict[str, Any]],
        turn: int,
        on_delta: Callable[[str], None] | None = None,
        on_thought: Callable[[str], None] | None = None,
    ) -> tuple[str, list[dict[str, Any]] | None]:
        """
        函数名: _complete
        作用: 把完整 history + tools 交给提供方 complete
        输入:
            history (list): 当前消息列表（含本轮 user）
            turn (int): 本 run 内第几次 complete，0 起
            on_delta (callable | None): 流式 message 增量
            on_thought (callable | None): 流式 reasoning 增量
        输出:
            (文本, tool_calls 或 None)
        """
        think = self._think_this_turn(turn)
        self.thinking = think
        kwargs: dict[str, Any] = {"thinking": think, "model": self.model}
        if on_delta is not None:
            kwargs["on_delta"] = on_delta
        if on_thought is not None:
            kwargs["on_thought"] = on_thought
        result = get_provider().complete(
            history,
            tools=self.schemas or None,
            **kwargs,
        )
        self._remember_result(result)
        text = str(getattr(result, "text", None) or "")
        calls = _tool_calls_from_result(result)
        msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            msg["tool_calls"] = calls
        history.append(msg)
        return text, calls


    def _remember_result(self, result: Any) -> None:
        """
        函数名: _remember_result
        作用: 记下本轮 thought 与 API token 用量
        输入:
            result: GenerateResult 或同类
        输出: 无
        """
        thought = getattr(result, "thought", None)
        self.last_thought = str(thought).strip() if thought else None
        used = getattr(result, "tokens_used", None)
        self.last_tokens_used = int(used) if isinstance(used, int) and used > 0 else None
        limit = getattr(result, "context_limit", None)
        self.last_context_limit = int(limit) if isinstance(limit, int) and limit > 0 else None


    def _fill_usage_estimate(self, history: list[dict[str, Any]]) -> None:
        """
        函数名: _fill_usage_estimate
        作用: API 未给 usage 时用会话历史估算 token
        输入:
            history (list): 含本轮 assistant 的消息
        输出: 无
        """
        if self.last_tokens_used is not None:
            return
        blob = "\n".join(str(row.get("content") or "") for row in history)
        est = _estimate_tokens(blob)
        self.last_tokens_used = est if est > 0 else None


    def _apply_tools(self, tool_calls: list[dict[str, Any]], history: list[dict[str, Any]]) -> None:
        """
        函数名: _apply_tools
        作用: 并行执行 tools 并把 role=tool 消息追加进 history
        输入:
            tool_calls (list): OpenAI 风格 tool_calls
            history (list): 要写入的历史（已含 assistant+tool_calls）
        输出: 无
        """
        if self.on_tool is not None:
            for tc in tool_calls:
                fn_spec = tc.get("function") or {}
                self.on_tool(str(fn_spec.get("name") or ""))
        with ThreadPoolExecutor() as pool:
            rows = list(pool.map(lambda tc: _exec_tool(self.tools, tc), tool_calls))
        history.extend(rows)



class Workflow:
    """
    类名: Workflow
    作用: >> 步骤序列；list 步并行扇出
    """

    def __init__(self, steps: list[Any], name: str | None = None) -> None:
        self.steps = [s if isinstance(s, list) else wrap_node(s) for s in steps]
        self.name = name or " >> ".join(_step_label(s) for s in self.steps)


    def __rshift__(self, other: Any) -> "Workflow":
        """
        函数名: __rshift__
        作用: 管线尾部追加
        输入:
            other: 下一步
        输出:
            Workflow
        """
        return Workflow(self.steps + [wrap_node(other)])


    def __rrshift__(self, other: Any) -> "Workflow":
        """
        函数名: __rrshift__
        作用: 管线头部插入
        输入:
            other: 左节点
        输出:
            Workflow
        """
        return Workflow([wrap_node(other)] + self.steps)


    def run(self, payload: str) -> str:
        """
        函数名: run
        作用: 按序执行；并行步结果拼回下一输入
        输入:
            payload (str): 入口文本
        输出:
            str
        """
        current = payload
        for step in self.steps:
            if isinstance(step, list):
                with ThreadPoolExecutor() as pool:
                    parts = list(pool.map(lambda node: run_node(node, current), step))
                feedback = "\n\n---\n\n".join(
                    f"[{_node_name(node)}]:\n{text}" for node, text in zip(step, parts)
                )
                current = f"[original]:\n{current}\n\n---\n\n{feedback}"
                continue
            current = run_node(step, current)
        return current



def _policy_from_thinking(value: bool | str) -> str:
    """
    函数名: _policy_from_thinking
    作用: 把构造参数收成 always / after_tools / off
    输入:
        value (bool | str): True/always、after_tools、其余为 off
    输出:
        str
    """
    if value is True or value in ("always", "on"):
        return "always"
    if value == "after_tools":
        return "after_tools"
    return "off"



def tool(fn: Any = None, *, retries: int = 0, timeout: float | None = None) -> Any:
    """
    函数名: tool
    作用: 把函数变成可 >> 的管线节点（Quark @tool）
    输入:
        fn: 被装饰函数；None 则返回带 retries/timeout 的装饰器
        retries (int): 失败重试次数
        timeout (float | None): 单次超时秒
    输出:
        节点或装饰器
    """
    if fn is None:
        return lambda f: tool(f, retries=retries, timeout=timeout)

    class ToolNode:
        name = fn.__name__
        __name__ = fn.__name__
        __doc__ = fn.__doc__

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            """
            函数名: __call__
            作用: 按原函数调用
            输入:
                *args / **kwargs: 原参数
            输出:
                Any
            """
            return fn(*args, **kwargs)

        def run(self, payload: str) -> str:
            """
            函数名: run
            作用: 管线一步；支持 retries / timeout
            输入:
                payload (str): 上一步输出
            输出:
                str
            """
            last_exc: Exception | None = None
            for _attempt in range(retries + 1):
                try:
                    if timeout:
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            result = pool.submit(fn, payload).result(timeout=timeout)
                    else:
                        result = fn(payload)
                    return str(result)
                except Exception as exc:
                    last_exc = exc
            raise last_exc if last_exc is not None else RuntimeError("tool failed")

        def __rshift__(self, other: Any) -> Workflow:
            """
            函数名: __rshift__
            作用: 从本 tool 继续 >>
            输入:
                other: 下一步
            输出:
                Workflow
            """
            return Workflow([self, wrap_node(other)])

        def __rrshift__(self, other: Any) -> Workflow:
            """
            函数名: __rrshift__
            作用: 左侧接到本 tool
            输入:
                other: 左节点
            输出:
                Workflow
            """
            return Workflow([wrap_node(other), self])

    return ToolNode()



def wrap_node(fn: Any) -> Any:
    """
    函数名: wrap_node
    作用: 普通可调用变成带 run / >> 的节点
    输入:
        fn: Agent、Workflow、list 或 callable
    输出:
        节点或原 list
    """
    if isinstance(fn, list) or hasattr(fn, "run") or hasattr(fn, "__rshift__"):
        return fn

    class FnNode:
        name = getattr(fn, "__name__", str(fn))

        def run(self, payload: str) -> str:
            """
            函数名: run
            作用: 调用被包装函数
            输入:
                payload (str): 上一步输出
            输出:
                str
            """
            return str(fn(payload))

        def __rshift__(self, other: Any) -> Workflow:
            """
            函数名: __rshift__
            作用: 从本函数节点继续 >>
            输入:
                other: 下一步
            输出:
                Workflow
            """
            return Workflow([self, wrap_node(other)])

        def __rrshift__(self, other: Any) -> Workflow:
            """
            函数名: __rrshift__
            作用: 左侧接到本函数节点
            输入:
                other: 左节点
            输出:
                Workflow
            """
            return Workflow([wrap_node(other), self])

    return FnNode()



def run_node(node: Any, payload: str) -> str:
    """
    函数名: run_node
    作用: 执行单步
    输入:
        node: 管线节点
        payload (str): 输入
    输出:
        str
    """
    if hasattr(node, "run"):
        return str(node.run(payload))
    return str(node(payload))



def _node_name(node: Any) -> str:
    """
    函数名: _node_name
    作用: 节点显示名
    输入:
        node: 管线节点
    输出:
        str
    """
    return str(getattr(node, "name", getattr(node, "__name__", str(node))))



def _step_label(step: Any) -> str:
    """
    函数名: _step_label
    作用: Workflow 名称里的一步标签
    输入:
        step: 单步或并行 list
    输出:
        str
    """
    if isinstance(step, list):
        inner = ", ".join(_node_name(item) for item in step)
        return f"[{inner}]"
    if isinstance(step, Workflow):
        return f"({step.name})"
    return str(_node_name(step))



def _tool_schema(name: str, fn: Callable[..., Any]) -> dict[str, Any]:
    """
    函数名: _tool_schema
    作用: 从函数签名生成 OpenAI function schema（Quark 同款）
    输入:
        name (str): 工具名
        fn (callable): 实现
    输出:
        dict
    """
    sig = inspect.signature(fn)
    type_map = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}

    def _resolve(annotation: Any) -> str:
        origin = getattr(annotation, "__origin__", None)
        if origin is typing.Union:
            args = [item for item in annotation.__args__ if item is not type(None)]
            if args:
                return _resolve(args[0])
        return type_map.get(annotation, "string")

    properties = {key: {"type": _resolve(param.annotation)} for key, param in sig.parameters.items()}
    required = [key for key, param in sig.parameters.items() if param.default is inspect.Parameter.empty]
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": fn.__doc__ or "",
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }



def _estimate_tokens(text: str) -> int:
    """
    函数名: _estimate_tokens
    作用: 无 API usage 时按字符粗估 token（全角约 1，其余约 4 字 1 token）
    输入:
        text (str): 会话拼接文本
    输出:
        int: 估算 token 数
    """
    if not text:
        return 0
    wide = 0
    other = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            wide += 1
        else:
            other += 1
    return wide + (other + 3) // 4



def _tool_calls_from_result(result: Any) -> list[dict[str, Any]] | None:
    """
    函数名: _tool_calls_from_result
        作用: 从 complete 结果抽出 OpenAI 风格 tool_calls
    输入:
        result: GenerateResult 或同类
    输出:
        list | None
    """
    calls = getattr(result, "tool_calls", None)
    if isinstance(calls, list) and calls:
        return [item for item in calls if isinstance(item, dict)]
    raw = getattr(result, "tool_call_arguments", None)
    if not raw:
        return None
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [{"id": "call_0", "type": "function", "function": {"name": str(raw.get("name") or ""), "arguments": json.dumps(raw)}}]
    return None



def _exec_tool(tools: dict[str, Callable[..., Any]], tc: dict[str, Any]) -> dict[str, Any]:
    """
    函数名: _exec_tool
    作用: 执行一次 tool_call
    输入:
        tools (dict): 名 → 函数
        tc (dict): 单条 tool_call
    输出:
        dict: role=tool 消息
    """
    fn_spec = tc.get("function") or {}
    name = str(fn_spec.get("name") or "")
    cid = str(tc.get("id") or "")
    args_raw = fn_spec.get("arguments") or "{}"
    try:
        parsed = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        result = tools[name](**parsed)
    except Exception as exc:
        result = f"Error: {exc}"
    return {"role": "tool", "tool_call_id": cid, "content": str(result)}
