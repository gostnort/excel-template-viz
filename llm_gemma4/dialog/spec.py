"""对话域插件：只提供 prompt 与子任务形状，不碰 LiteRT / Graph。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_gemma4.dialog.state import DialogState, IntakeNeed
from llm_gemma4.workflow.state import Decision, ExecutorResult


@dataclass
class SubagentJob:
    """
    类名: SubagentJob
    作用: 一次子代理调用的会话描述（独立 session_id，可选 thinking 重试）
    """

    job_id: str
    system: str
    user: str
    parse_json: bool = True
    allow_thinking_retry: bool = True


@dataclass
class DialogSpec:
    """
    类名: DialogSpec
    作用: 一个对话域的全部业务注入点（analogous to 权重；运行时是 LiteRT）
    """

    name: str
    main_system: str
    decision_system: str
    initial_intake: list[IntakeNeed] = field(default_factory=list)
    plan_intake_user: str = (
        "根据当前目标，列出你还需要向用户采集的事实。"
        "只输出 JSON：{\"needs\":[{\"key\":\"...\",\"question\":\"...\",\"required\":true}]}"
        " key 用英文蛇形；不要重复已经 captured 的 key。"
    )
    synthesize_user: str = "根据已采集事实与子代理产物，给出最终答复。"

    def main_prefix(self, state: DialogState) -> str:
        """
        函数名: main_prefix
        作用: 主对话每轮 user 消息前的极简摘要（不重放 KV 历史）
        输入:
            state (DialogState): 当前对话状态
        输出:
            str: 前缀文本，可为空
        """
        lines: list[str] = [f"[Context] domain={self.name}"]
        if state.goal:
            lines.append(f"goal: {state.goal}")
        captured = [f"{k}={v}" for k, v in state.facts.items() if str(v or "").strip()]
        if captured:
            lines.append("facts: " + "; ".join(captured[:12]))
        pending = [k for k, v in state.progress.items() if v == "pending"]
        if pending:
            lines.append("pending: " + ", ".join(pending[:12]))
        if state.artifacts:
            lines.append("artifacts: " + ", ".join(sorted(state.artifacts.keys())))
        return "\n".join(lines) + "\n\n"

    def build_jobs(self, state: DialogState) -> list[SubagentJob]:
        """
        函数名: build_jobs
        作用: 按当前 facts 生成要分派的子代理任务；默认不分派
        输入:
            state (DialogState): 当前对话状态
        输出:
            list[SubagentJob]: 子任务列表
        """
        return []

    def parse_plan_needs(self, payload: dict[str, Any]) -> list[IntakeNeed]:
        """
        函数名: parse_plan_needs
        作用: 从主对话 JSON 解析动态 intake
        输入:
            payload (dict): 模型输出对象
        输出:
            list[IntakeNeed]: 需求列表
        """
        raw = payload.get("needs")
        if not isinstance(raw, list):
            return []
        needs: list[IntakeNeed] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            question = str(item.get("question") or key).strip()
            if not key:
                continue
            required = item.get("required", True)
            needs.append(IntakeNeed(key=key, question=question or key, required=bool(required)))
        return needs


    def get_action_handlers(self) -> dict[str, Callable[..., ExecutorResult]] | None:
        """
        函数名: get_action_handlers
        作用: 域自定义 Graph 节点；None 表示使用 dialog 通用五动作
        输入: 无
        输出:
            dict | None: action_id → handler；None 为通用表
        """
        return None


    def get_decision_catalog(self) -> str:
        """
        函数名: get_decision_catalog
        作用: decide 提示里的动作表；空字符串表示使用通用 catalog
        输入: 无
        输出:
            str: Markdown 表或空
        """
        return ""


    def get_allowed_action_ids(self) -> frozenset[str] | None:
        """
        函数名: get_allowed_action_ids
        作用: 覆盖通用 action_id 白名单
        输入: 无
        输出:
            frozenset[str] | None: None 表示通用五动作
        """
        return None


    def get_allowed_next_actions(self) -> frozenset[str] | None:
        """
        函数名: get_allowed_next_actions
        作用: 覆盖通用 next_action 白名单
        输入: 无
        输出:
            frozenset[str] | None: None 表示 ask_user/compute/finalize/error
        """
        return None


    def get_interrupt_kinds(self) -> frozenset[str]:
        """
        函数名: get_interrupt_kinds
        作用: 本域会发出的中断 kind（CLI / UI 映射）
        输入: 无
        输出:
            frozenset[str]: 默认 ask_fact
        """
        return frozenset({"ask_fact"})


    def merge_resume(self, state: DialogState, payload: dict[str, Any]) -> None:
        """
        函数名: merge_resume
        作用: 在通用 facts 合并之后写入域载荷（布局 / 样本等）
        输入:
            state (DialogState): 对话状态
            payload (dict): start/resume 字典
        输出: 无
        """
        return None


    def route_decision(
        self,
        state: DialogState,
        backend: Any,
        user_input: dict[str, Any] | None,
        *,
        stub: bool = False,
    ) -> Decision | None:
        """
        函数名: route_decision
        作用: 域自定义 decide；返回 None 则走通用 dialog.decide
        输入:
            state (DialogState): 对话状态
            backend: LlmBackend
            user_input (dict | None): 本轮恢复数据
            stub (bool): 固定顺序
        输出:
            Decision | None: 自定义决策或 None
        """
        return None


    def stub_decide(self, state: DialogState) -> Decision | None:
        """
        函数名: stub_decide
        作用: 覆盖通用 decide_stub；None 表示五动作顺序
        输入:
            state (DialogState): 对话状态
        输出:
            Decision | None
        """
        return None


    def handler_ctx(
        self,
        backend: Any,
        *,
        on_chat: Callable[[str, str], None] | None,
        on_progress: Callable[[str], None] | None,
        thinking_budget: int,
    ) -> dict[str, Any]:
        """
        函数名: handler_ctx
        作用: 注入动作 ctx（如 determiner_one_shot）；通用域返回空
        输入:
            backend: LlmBackend
            on_chat / on_progress: 日志回调
            thinking_budget (int): pass2 token 预算
        输出:
            dict: 合并进 orchestrator ctx
        """
        return {}


    def execute_action(
        self,
        decision: Decision,
        state: DialogState,
        backend: Any,
        *,
        on_progress: Any,
        on_chat: Any,
        ctx: dict[str, Any],
    ) -> ExecutorResult | None:
        """
        函数名: execute_action
        作用: 域自己执行 action_id；None 表示用通用 ACTION_HANDLERS
        输入:
            decision (Decision): 本轮决策
            state (DialogState): 对话状态
            backend: LlmBackend
            on_progress / on_chat / ctx: 与通用 handler 相同
        输出:
            ExecutorResult | None
        """
        return None


    def after_result(
        self,
        state: DialogState,
        decision: Decision,
        result: ExecutorResult,
        *,
        stub: bool = False,
    ) -> None:
        """
        函数名: after_result
        作用: 动作结束后的域钩子（stub 游标、同步 artifacts）
        输入:
            state (DialogState): 对话状态
            decision (Decision): 本轮决策
            result (ExecutorResult): 节点结果
            stub (bool): 是否 stub 路由
        输出: 无
        """
        return None
