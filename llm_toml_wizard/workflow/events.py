"""工作流事件：UI 入站 start/resume/stop，图出站 interrupt/finished/error。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_toml_wizard.workflow.state import InterruptPayload


EVENT_START = "start"
EVENT_RESUME = "resume"
EVENT_STOP = "stop"
EVENT_CONTINUE = "continue"
EVENT_INTERRUPT = "interrupt"
EVENT_FINISHED = "finished"
EVENT_ERROR = "error"

INBOUND_EVENTS = frozenset({EVENT_START, EVENT_RESUME, EVENT_STOP})
OUTBOUND_EVENTS = frozenset({EVENT_INTERRUPT, EVENT_FINISHED, EVENT_ERROR, EVENT_CONTINUE, EVENT_STOP})


@dataclass(frozen=True)
class WorkflowEvent:
    """
    类名: WorkflowEvent
    作用: 工作流入站/出站事件（冻结，避免循环中被原地改写）
    输入:
        type (str): 事件类型（start/resume/stop/continue/interrupt/finished/error）
        payload (dict): UI 恢复数据或错误原因等
        interrupt (InterruptPayload | None): 出站中断描述
    输出: 无
    """

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    interrupt: InterruptPayload | None = None
