"""域无关对话运行时：主会话、动态 intake、子代理分派。

toml_config 是这一层的一种用途，不是依赖。CLI 与 NiceGUI 向导都应只通过本包
或 toml_config（域插件）使用 Graph，而不是把 TOML 字段写进底座。
"""

from llm_toml_wizard.dialog.actions import ACTION_HANDLERS
from llm_toml_wizard.dialog.decide import ACTION_CATALOG, ALLOWED_ACTION_IDS, decide, decide_stub
from llm_toml_wizard.dialog.orchestrator import DialogOrchestrator
from llm_toml_wizard.dialog.spec import DialogSpec, SubagentJob
from llm_toml_wizard.dialog.state import DialogState, IntakeNeed, pending_needs
from llm_toml_wizard.dialog.subagent import SubagentResult, run_subagent

__all__ = [
    "ACTION_CATALOG",
    "ACTION_HANDLERS",
    "ALLOWED_ACTION_IDS",
    "DialogOrchestrator",
    "DialogSpec",
    "DialogState",
    "IntakeNeed",
    "SubagentJob",
    "SubagentResult",
    "decide",
    "decide_stub",
    "pending_needs",
    "run_subagent",
]
