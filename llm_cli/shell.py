"""通用交互 CLI：欢迎框、提供方握手、方框 stdin。不绑定 toml 等应用。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from llm_cli.agent import Agent, MAIN_SYSTEM
from llm_cli.banner import BootInfo, print_boot, resolve_version
from llm_cli.terminal_io import (
    _show_cursor,
    emit_model,
    emit_model_delta,
    emit_model_end,
    emit_model_start,
    emit_system,
    emit_think,
    emit_think_delta,
    emit_think_end,
    emit_think_start,
    emit_user,
)

try:
    from llm_cli.lms import (
        LmsError as LmStudioError,
        get_backend,
        load_model,
        load_user_config,
        loaded_models_from,
        model_context_limit,
    )
except ImportError as exc:
    get_backend = None
    LmStudioError = RuntimeError
    load_user_config = None
    load_model = None
    model_context_limit = None
    loaded_models_from = None
    _IMPORT_ERR = str(exc)
else:
    _IMPORT_ERR = None


_MAIN_AGENT: Agent | None = None


def _empty_boot(*, model: str = "", detail: str = "", api_url: str = "") -> BootInfo:
    """
    函数名: _empty_boot
    作用: 组装未连通时的启动快照
    输入:
        model (str): 配置里的模型
        detail (str): 提供方说明
        api_url (str): API 地址
    输出:
        BootInfo
    """
    return BootInfo(
        cwd=str(Path.cwd()),
        session=f"session_{uuid.uuid4()}",
        model=model,
        version=resolve_version(),
        provider="lm_studio",
        provider_up=False,
        provider_detail=detail or "unavailable",
        api_url=api_url,
    )


def _preview_boot() -> BootInfo:
    """
    函数名: _preview_boot
    作用: 只读本地 toml 拼欢迎框，不访问 LM Studio
    输入: 无
    输出:
        BootInfo
    """
    model = ""
    api_url = ""
    if load_user_config is not None:
        try:
            cfg = load_user_config()
            model = str(cfg.get("model") or "")
            api_url = str(cfg.get("api_url") or "")
        except Exception:
            model = ""
    info = _empty_boot(model=model, detail="connecting", api_url=api_url)
    info.provider_up = True
    info.thinking = True
    return info


def _loaded_model_keys() -> list[str]:
    """
    函数名: _loaded_model_keys
    作用: 读当前 LM Studio 已加载模型 key；失败则空列表
    输入: 无
    输出:
        list[str]
    """
    if loaded_models_from is None:
        return []
    try:
        return loaded_models_from()
    except Exception:
        return []


def _model_is_vision(model_key: str, reported: bool = False) -> bool:
    """
    函数名: _model_is_vision
    作用: 判断模型是否带视觉能力；健康检查已标明时直接采用，否则询问 llm_lmstudio
    输入:
        model_key (str): 模型 key
        reported (bool): /v1/models 已经标成视觉模型时为 True
    输出:
        bool: 是视觉模型则为 True
    """
    if reported:
        return True
    key = str(model_key or "").strip()
    if not key:
        return False
    try:
        from llm_lmstudio.models import has_vision  # 可选依赖：原生列表才有 capabilities.vision
    except ImportError:
        return False
    try:
        return bool(has_vision(key))
    except Exception:
        return False


def _vision_note(model: str, *, vision: bool) -> str:
    """
    函数名: _vision_note
    作用: 视觉模型时给出一句说明；非视觉模型返回空串
    输入:
        model (str): 模型 key
        vision (bool): 是否带视觉
    输出:
        str: 要写进反馈区的说明；不需要说明时为空串
    """
    key = str(model or "").strip()
    if not key or not vision:
        return ""
    return (
        f"note: {key} has vision. LM Studio Chat with full MCP schemas is still slow. "
        "This CLI does not attach those schemas to /v1/chat/completions."
    )


def _remember_note(notes: list[str], text: str) -> None:
    """
    函数名: _remember_note
    作用: 握手期间先打印一行，并把同一句留到画布反馈区
    输入:
        notes (list[str]): BootInfo.startup_notes
        text (str): 说明文本
    输出: 无
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return
    notes.append(cleaned)
    print(cleaned, flush=True)


def print_banner(info: BootInfo | None = None, *, provider: str = "lms", model: str = "") -> None:
    """打印欢迎框"""
    print_boot(info, provider=provider, model=model)


def handshake() -> BootInfo:
    """
    函数名: handshake
    作用: 探测提供方；已配置模型未加载则 load；说明写入 startup_notes
    输入: 无
    输出:
        BootInfo: 欢迎框与底栏用的快照
    """
    model = ""
    api_url = ""
    # 先读 user.toml，探测失败时欢迎框仍能显示模型名
    if load_user_config is not None:
        try:
            cfg = load_user_config()
            model = str(cfg.get("model") or "")
            api_url = str(cfg.get("api_url") or "")
        except Exception:
            model = ""
    notes: list[str] = []
    if _IMPORT_ERR is not None or get_backend is None:
        info = _empty_boot(model=model, detail=_IMPORT_ERR or "unavailable", api_url=api_url)
        _remember_note(notes, info.provider_detail)
        info.startup_notes = notes
        return info
    try:
        report = get_backend().health_check()
    except Exception as exc:
        info = _empty_boot(model=model, detail=str(exc), api_url=api_url)
        _remember_note(notes, info.provider_detail)
        info.startup_notes = notes
        return info
    model = report.model or model
    api_url = report.api_url or api_url
    if not report.ok:
        info = _empty_boot(model=model, detail=report.message or "down", api_url=api_url)
        _remember_note(notes, info.provider_detail)
        info.startup_notes = notes
        return info
    # 中文注释: API 可达；未加载则尝试 load，结果留在反馈区
    detail = report.message or "connected"
    if report.message == "model not loaded" and report.model and load_model is not None:
        _remember_note(notes, f"loading model {report.model} ...")
        try:
            load_model(report.model, remember=True)
            detail = "connected · model ready"
        except Exception as exc:
            detail = f"connected · load failed ({exc})"
            _remember_note(notes, detail)
    elif report.message == "ok":
        detail = "connected · model ready"
    loaded_names = _loaded_model_keys()
    if len(loaded_names) >= 2:
        detail = f"{detail} · {len(loaded_names)} models loaded"
        _remember_note(notes, f"{len(loaded_names)} models are loaded")
    vision = _model_is_vision(model, reported=bool(report.vision))
    _remember_note(notes, _vision_note(model, vision=vision))
    return BootInfo(
        cwd=str(Path.cwd()),
        session=f"session_{uuid.uuid4()}",
        model=model,
        version=resolve_version(),
        provider="lm_studio",
        provider_up=True,
        provider_detail=detail,
        api_url=api_url,
        thinking=True,
        startup_notes=notes,
    )


def cmd_help() -> None:
    """
    函数名: cmd_help
    作用: 打印通用壳命令
    输入: 无
    输出: 无
    """
    emit_system(
        "\n".join(
            [
                "Commands:",
                "  /menu          Open template selection button grid",
                "  health         Probe LMS and Playwright",
                "  load [model]   Load weights; omit model to use lms/user.toml",
                "  ask <text>     One main Agent completion, no tool loop",
                "  agents         Show the main Agent",
                "  tools          List tools registered on the main Agent",
                "  thinking       Show main Agent reasoning toggle",
                "  thinking on    Enable reasoning for main Agent (default)",
                "  thinking off   Disable reasoning",
                "  stream         Show main Agent stream toggle",
                "  stream on      Enable token streaming (debug)",
                "  stream off     Disable streaming (default)",
                "  reset          Clear main Agent history",
                "  help, /help    Show this help",
                "  exit, quit     Leave the shell",
                "Other lines are sent to the main Agent.",
                "A leading / is optional (e.g. /health, /thinking off, /stream).",
            ]
        )
    )


def cmd_health() -> None:
    """
    函数名: cmd_health
    作用: 打印提供方 health
    输入: 无
    输出: 无
    """
    if _IMPORT_ERR is not None or get_backend is None or load_user_config is None:
        emit_system(f"provider unavailable: {_IMPORT_ERR}")
        return
    try:
        cfg = load_user_config()
        report = get_backend().health_check()
    except Exception as exc:
        emit_system(f"provider health failed: {exc}")
        return
    loaded_names = _loaded_model_keys()
    model_key = str(cfg.get("model") or report.model or "")
    vision = _model_is_vision(model_key, reported=bool(report.vision))
    lines = [
        f"api_url={cfg.get('api_url', report.api_url)}",
        f"model={cfg.get('model', report.model)!r}",
        f"loaded={report.ok and report.message == 'ok'}",
        f"loaded_models={loaded_names or '(none)'}",
        f"vision={vision}",
        f"ok={report.ok}",
        f"message={report.message}",
    ]
    emit_system("\n".join(lines))
    note = _vision_note(model_key, vision=vision)
    if note:
        emit_system(note)
    try:
        from mcp_playwright.session import probe_playwright
        emit_system(str(probe_playwright().get("message") or "playwright: unknown"))
    except Exception as exc:
        emit_system(f"playwright: probe failed ({exc})")


def cmd_load(model_name: str) -> None:
    """
    函数名: cmd_load
    作用: 加载模型权重
    输入:
        model_name (str): 可选模型 key
    输出: 无
    """
    if _IMPORT_ERR is not None or load_model is None:
        emit_system(f"provider unavailable: {_IMPORT_ERR}")
        return
    key = model_name.strip()
    if not key and load_user_config is not None:
        try:
            key = str(load_user_config().get("model") or "").strip()
        except Exception:
            key = ""
    if not key:
        emit_system("usage: load [model]")
        return
    try:
        result = load_model(key, remember=True)
    except LmStudioError as exc:
        emit_system(f"load failed: {exc}")
        return
    except Exception as exc:
        emit_system(f"load failed: {exc}")
        return
    if isinstance(result, dict):
        emit_system(json.dumps(result, ensure_ascii=False, indent=2))
        return
    emit_system(str(result))


def _emit_tool_name(name: str) -> None:
    """
    函数名: _emit_tool_name
    作用: 主 Agent 执行 tool 时打一行系统提示
    输入:
        name (str): 工具名
    输出: 无
    """
    if name:
        emit_system(f"tool {name}")


def main_agent() -> Agent:
    """懒创建主 Agent"""
    global _MAIN_AGENT
    if _MAIN_AGENT is None:
        _MAIN_AGENT = Agent(
            system=MAIN_SYSTEM,
            thinking=True,
            name="main",
        )
        _MAIN_AGENT.on_tool = _emit_tool_name
    return _MAIN_AGENT


def cmd_ask(text: str, model: str = "model") -> None:
    """
    函数名: cmd_ask
    作用: 主 Agent.run，回复写入模型色块
    输入:
        text (str): 用户文本
        model (str): 框顶标签（模型名）
    输出: 无
    """
    if _IMPORT_ERR is not None:
        emit_system(f"provider unavailable: {_IMPORT_ERR}")
        return
    payload = text.strip()
    if not payload:
        emit_system("usage: ask <text>")
        return
    try:
        agent = main_agent()
        if agent.stream:
            think_open = False
            think_streamed = False
            model_open = False
            def on_thought(chunk: str) -> None:
                """
                函数名: on_thought
                作用: 先流式写出灰色 thought
                输入:
                    chunk (str): reasoning 增量
                输出: 无
                """
                nonlocal think_open, think_streamed
                if not chunk:
                    return
                if not think_open:
                    emit_think_start()
                    think_open = True
                    think_streamed = True
                emit_think_delta(chunk)
            def on_delta(chunk: str) -> None:
                """
                函数名: on_delta
                作用: thought 结束后再打开绿框并追加正文
                输入:
                    chunk (str): message 增量
                输出: 无
                """
                nonlocal think_open, model_open
                if not chunk:
                    return
                if think_open:
                    emit_think_end()
                    think_open = False
                if not model_open:
                    emit_model_start(model or "model")
                    model_open = True
                emit_model_delta(chunk)
            reply = ""
            try:
                reply = agent.run(payload, on_delta=on_delta, on_thought=on_thought)
            finally:
                if think_open:
                    emit_think_end()
                    think_open = False
                if model_open:
                    emit_model_end()
            if not model_open:
                if agent.last_thought and not think_streamed:
                    emit_think(agent.last_thought)
                emit_model(str(reply or ""), model or "model")
            return
        reply = agent.run(payload)
    except Exception as exc:
        emit_system(f"agent failed: {exc}")
        return
    if agent.last_thought:
        emit_think(agent.last_thought)
    emit_model(str(reply), model or "model")


def cmd_reset() -> None:
    """
    函数名: cmd_reset
    作用: 重置主 Agent
    输入: 无
    输出: 无
    """
    global _MAIN_AGENT
    if _MAIN_AGENT is None:
        emit_system("main agent is idle")
        return
    _MAIN_AGENT.reset()
    emit_system("main agent reset")


def cmd_agents() -> None:
    """列出 Agent 状态"""
    agent = main_agent()
    emit_system(f"agent: name={agent.name} thinking={agent.thinking} stream={agent.stream}")


def cmd_tools() -> None:
    """
    函数名: cmd_tools
    作用: 列出主 Agent 已挂 tools
    输入: 无
    输出: 无
    """
    agent = main_agent()
    names = sorted(agent.tools)
    emit_system("tools: " + (", ".join(names) if names else "(none)"))


def cmd_thinking(arg: str, info: BootInfo | None = None) -> None:
    """
    函数名: cmd_thinking
    作用: 显示或设置主 Agent 的 reasoning 开关，默认开启
    输入:
        arg (str): 空则显示；on / off 则设置
        info (BootInfo | None): 同步底栏 think: 状态
    输出: 无
    """
    agent = main_agent()
    token = arg.strip().lower()
    if not token:
        state = "on" if agent.thinking else "off"
        emit_system(f"thinking is {state}")
        return
    if token in ("on", "true", "1"):
        agent.set_thinking(True)
        if info is not None:
            info.thinking = True
        emit_system("thinking on")
        return
    if token in ("off", "false", "0"):
        agent.set_thinking(False)
        if info is not None:
            info.thinking = False
        emit_system("thinking off")
        return
    emit_system("usage: thinking [on|off]")


def cmd_stream(arg: str, info: BootInfo | None = None) -> None:
    """
    函数名: cmd_stream
    作用: 显示或设置主 Agent 的 token 流式开关，默认关闭
    输入:
        arg (str): 空则显示；on / off 则设置
        info (BootInfo | None): 同步底栏 stream: 状态
    输出: 无
    """
    agent = main_agent()
    token = arg.strip().lower()
    if not token:
        state = "on" if agent.stream else "off"
        emit_system(f"stream is {state}")
        return
    if token in ("on", "true", "1"):
        agent.set_stream(True)
        if info is not None:
            info.stream = True
        emit_system("stream on")
        return
    if token in ("off", "false", "0"):
        agent.set_stream(False)
        if info is not None:
            info.stream = False
        emit_system("stream off")
        return
    emit_system("usage: stream [on|off]")


def dispatch(line: str, info: BootInfo | None = None) -> bool:
    """
    函数名: dispatch
    作用: 解析一行 stdin
    输入:
        line (str): 用户输入
        info (BootInfo | None): 用于模型名标签
    输出:
        bool: False 表示退出
    """
    raw = line.strip()
    if raw.startswith("/"):
        raw = raw[1:].lstrip()
    parts = raw.split()
    if not parts:
        return True
    cmd = parts[0].lower()
    model = (info.model if info is not None else "") or "model"
    if cmd in ("exit", "quit"):
        return False
    if cmd == "help":
        cmd_help()
        return True
    if cmd == "health":
        cmd_health()
        return True
    if cmd == "load":
        cmd_load(" ".join(parts[1:]))
        return True
    if cmd == "ask":
        cmd_ask(" ".join(parts[1:]), model=model)
        return True
    if cmd == "reset":
        cmd_reset()
        return True
    if cmd == "agents":
        cmd_agents()
        return True
    if cmd == "tools":
        cmd_tools()
        return True
    if cmd == "thinking":
        cmd_thinking(" ".join(parts[1:]), info)
        return True
    if cmd == "stream":
        cmd_stream(" ".join(parts[1:]), info)
        return True
    cmd_ask(raw, model=model)
    return True


def _refresh_info(info: BootInfo) -> None:
    """
    函数名: _refresh_info
    作用: 命令后同步底栏模型名、开关与 context 用量（每轮结束后，非逐键）
    输入:
        info (BootInfo): 可变快照
    输出: 无
    """
    if load_user_config is not None:
        try:
            info.model = str(load_user_config().get("model") or info.model)
        except Exception:
            pass
    agent = _MAIN_AGENT
    if agent is not None:
        info.thinking = agent.thinking
        info.stream = agent.stream
        info.context_used = agent.last_tokens_used
        info.context_limit = agent.last_context_limit
    if info.context_limit is None and model_context_limit is not None:
        try:
            info.context_limit = model_context_limit(info.model)
        except Exception:
            return


def run_loop(info: BootInfo) -> None:
    """
    函数名: run_loop
    作用: 动态画布状态机循环：启动默认进入模板按钮网格；按 ESC 退出至通用输入框；输入 /menu 重新呼出菜单
    输入:
        info (BootInfo): 启动快照（底栏会读模型/路径）
    输出: 无
    """
    from llm_cli.canvas import CanvasStateMachine, TemplateMenuState
    machine = CanvasStateMachine(info)
    for note in info.startup_notes:
        machine.session.add_feedback(note)
    machine.push_state(TemplateMenuState())
    try:
        while machine.is_running():
            machine.run_turn()
    finally:
        _show_cursor()


def main() -> int:
    """进入 CLI 动态画布"""
    info = handshake()
    try:
        run_loop(info)
    finally:
        _show_cursor()
    return 0
