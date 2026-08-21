"""主对话每轮 user 消息前的极简上下文摘要（WorkflowState）。"""

from __future__ import annotations

from llm_toml_wizard.workflow.state import WorkflowState


def format_indexed_preview(indexed: dict[int, str], limit: int = 12) -> str:
    """
    函数名: format_indexed_preview
    作用: 将 indexed_segments 格式化为简短预览行
    输入:
        indexed (dict[int,str]): index 字典
        limit (int): 最多展示的 token 数
    输出:
        str: 预览文本
    """
    if not indexed:
        return "(empty)"
    items = sorted(indexed.items())[:limit]
    lines = [f"{idx}: {value}" for idx, value in items]
    if len(indexed) > limit:
        lines.append(f"... ({len(indexed) - limit} more)")
    return "\n".join(lines)


def build_main_turn_prefix(state: WorkflowState) -> str:
    """
    函数名: build_main_turn_prefix
    作用: 拼装 task_anchor、indexed 摘要、已完成/待处理字段，供主对话 send_turn 前缀
    输入:
        state (WorkflowState): 当前向导内存状态
    输出:
        str: 注入 user 消息开头的提醒文本（可为空）
    """
    lines: list[str] = []
    if state.template_id:
        lines.append(f"Template: {state.template_id}")
    if state.db_id:
        lines.append(f"Target db_id: {state.db_id}")
    if state.progress:
        pending = [k for k, v in state.progress.items() if v == "pending"]
        if pending:
            lines.append("Pending: " + ", ".join(pending[:8]))
    if state.sample_kind:
        lines.append(f"sample_kind: {state.sample_kind}")
    if state.determiner:
        lines.append(f"determiner: {state.determiner!r}")
    if state.indexed_segments:
        lines.append("Indexed segments (preview):")
        lines.append(format_indexed_preview(state.indexed_segments))
    if state.planned_labels:
        lines.append("Planned labels: " + ", ".join(state.planned_labels))
    done = [
        label for label, fs in state.fields.items()
        if fs.match_type not in ("unknown", "none", "") and not fs.error
    ]
    if done:
        lines.append("Fields done: " + ", ".join(done))
    pending_source = state.planned_labels or state.template_labels
    pending = [
        label for label in pending_source
        if label in state.fields and state.fields[label].match_type == "unknown"
    ]
    if pending:
        lines.append("Pending: " + ", ".join(pending))
    if not lines:
        return ""
    return "[Context]\n" + "\n".join(lines) + "\n\n"
