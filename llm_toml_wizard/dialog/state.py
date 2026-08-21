"""通用对话状态：目标、已采集事实、子代理产物。不含 TOML / Excel 字段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntakeNeed:
    """
    类名: IntakeNeed
    作用: 一条待向用户采集的需求（动态 intake 的最小单元）
    """

    key: str
    question: str
    required: bool = True


@dataclass
class DialogState:
    """
    类名: DialogState
    作用: 域无关的对话工作流状态（facts / progress / artifacts）
    """

    domain: str = ""
    goal: str = ""
    facts: dict[str, str] = field(default_factory=dict)
    intake: list[IntakeNeed] = field(default_factory=list)
    intake_planned: bool = False
    progress: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_interrupt: dict[str, Any] | None = None
    is_finished: bool = False
    route_key: str = ""
    last_summary: str = ""
    user_inputs: dict[str, Any] = field(default_factory=dict)


def init_progress(needs: list[IntakeNeed]) -> dict[str, str]:
    """
    函数名: init_progress
    作用: 按 intake 列表初始化 progress
    输入:
        needs (list[IntakeNeed]): 需求条目
    输出:
        dict[str, str]: key → pending
    """
    return {item.key: "pending" for item in needs}


def upsert_intake(state: DialogState, needs: list[IntakeNeed]) -> None:
    """
    函数名: upsert_intake
    作用: 合并动态 intake；已有 key 保留原 question，新 key 追加
    输入:
        state (DialogState): 对话状态
        needs (list[IntakeNeed]): 本轮规划出的需求
    输出: 无
    """
    known = {item.key: item for item in state.intake}
    for item in needs:
        key = str(item.key or "").strip()
        if not key:
            continue
        if key not in known:
            state.intake.append(item)
            known[key] = item
        if key not in state.progress:
            state.progress[key] = "pending"
        # 中文注释: 已采集的事实不因重新规划而被打回 pending
        if key in state.facts and str(state.facts.get(key) or "").strip():
            state.progress[key] = "done"


def pending_needs(state: DialogState) -> list[IntakeNeed]:
    """
    函数名: pending_needs
    作用: 返回仍需向用户询问的 required intake
    输入:
        state (DialogState): 对话状态
    输出:
        list[IntakeNeed]: 未完成的必填项
    """
    pending: list[IntakeNeed] = []
    for item in state.intake:
        if not item.required:
            continue
        if state.progress.get(item.key) in ("done", "skip"):
            continue
        if str(state.facts.get(item.key) or "").strip():
            continue
        pending.append(item)
    return pending
