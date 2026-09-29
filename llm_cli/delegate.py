"""主 Agent 的 ask_worker：工人 >> 压缩，只把短摘要交回主 history。"""

from __future__ import annotations

from llm_cli.agent import Agent, _estimate_tokens
from llm_cli.prompt import emit_system
from llm_cli.prompts import COMPRESSOR_SYSTEM, WORKER_SYSTEM


_SKIP_COMPRESS_TOKENS = 240



def ask_worker(task: str) -> str:
    """
    函数名: ask_worker
    作用: 派工人子代理（Wikipedia / 本地文件 / Bing 备选），再经压缩子代理，返回短摘要
    输入:
        task (str): 主对话交给工人的任务
    输出:
        str: 压缩后的摘要；失败为 Error: 前缀
    """
    payload = str(task or "").strip()
    if not payload:
        return "Error: empty worker task"
    try:
        from mcp_desktop import read_local_file, wikipedia_lookup
        from mcp_playwright import web_search
        import mcp_desktop.session as desktop_session
        import mcp_playwright.session as browser_session
    except Exception as exc:
        return f"Error: worker tools unavailable ({exc})"
    desktop_session.status_hook = emit_system
    browser_session.status_hook = emit_system
    emit_system("worker: calling LM Studio (OpenAI chat + tool_calls; tools run in Python)")
    worker = Agent(
        system=WORKER_SYSTEM,
        tools={
            "wikipedia_lookup": wikipedia_lookup,
            "read_local_file": read_local_file,
            "web_search": web_search,
        },
        thinking="after_tools",
        name="worker",
        max_turns=8,
    )
    worker.on_tool = lambda name: emit_system(f"worker tool {name}") if name else None
    try:
        raw = str(worker.run(payload) or "")
    except Exception as exc:
        return f"Error: worker failed ({exc})"
    if not raw.strip():
        return "Error: empty worker result"
    emit_system(f"worker: got {len(raw)} chars")
    if raw.lstrip().startswith("Error:"):
        emit_system(raw[:800])
    if _estimate_tokens(raw) < _SKIP_COMPRESS_TOKENS:
        return raw
    emit_system("compress: summarizing worker output for main chat")
    compressor = Agent(
        system=COMPRESSOR_SYSTEM,
        thinking=False,
        name="compress",
        max_turns=1,
    )
    try:
        digest, _hist = compressor.run(raw, history=[])
    except Exception as exc:
        return f"Error: compressor failed ({exc})"
    text = str(digest or "").strip()
    if not text:
        return "Error: compressor returned empty"
    return text
