"""主 Agent 的 ask_worker：工人 >> 压缩，只把短摘要交回主 history。"""

from __future__ import annotations

from llm_cli.agent import Agent, _estimate_tokens
from llm_cli.prompts import COMPRESSOR_SYSTEM, WORKER_SYSTEM


_SKIP_COMPRESS_TOKENS = 240



def ask_worker(task: str) -> str:
    """
    函数名: ask_worker
    作用: 派工人子代理（可 google_search），再经压缩子代理，返回短摘要
    输入:
        task (str): 主对话交给工人的任务
    输出:
        str: 压缩后的摘要；失败为 Error: 前缀
    """
    payload = str(task or "").strip()
    if not payload:
        return "Error: empty worker task"
    try:
        from mcp_chrome import google_search
    except Exception as exc:
        return f"Error: mcp_chrome unavailable ({exc})"
    worker = Agent(
        system=WORKER_SYSTEM,
        tools={"google_search": google_search},
        thinking="after_tools",
        name="worker",
        max_turns=8,
    )
    try:
        raw = str(worker.run(payload) or "")
    except Exception as exc:
        return f"Error: worker failed ({exc})"
    if not raw.strip():
        return "Error: empty worker result"
    if _estimate_tokens(raw) < _SKIP_COMPRESS_TOKENS:
        return raw
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
