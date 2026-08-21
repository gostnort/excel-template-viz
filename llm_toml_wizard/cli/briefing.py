"""任务简报域：展示动态需求采集与子代理分派，不含 TOML / Excel。"""

from __future__ import annotations

from llm_toml_wizard.dialog.spec import DialogSpec, SubagentJob
from llm_toml_wizard.dialog.state import DialogState, IntakeNeed

BRIEFING_MAIN_SYSTEM = (
    "你是对话主持人，不是字段配置器。"
    "你负责：理解用户目标、列出还缺哪些事实、在子代理完成后综合答复。"
    "不要编造用户没提供的事实。子代理的 JSON 结果以 artifacts 为准。"
)

BRIEFING_DECISION_SYSTEM = (
    "You route a briefing dialog. Output ONLY one JSON object with next_action and action_id. "
    "Never re-ask a captured fact. thinking=false."
)

DEMO_FACTS = {
    "goal": "把材料整理成可执行要点，并标出信息不足的条目",
    "material": (
        "项目下周要上线支付回调。目前只知道要对账失败发邮件，"
        "但没写清收件人、重试次数，也没说是否覆盖退款。"
        "另外希望有一份给值班同学的检查清单。"
    ),
    "constraints": "不超过5条要点；用中文；不要编造未给出的细节",
    "output_shape": "先列要点（标明完整/缺信息），再给一段总结",
}


class BriefingSpec(DialogSpec):
    """
    类名: BriefingSpec
    作用: CLI 展示用的简报域——intake 四件套 + extract / gap_check 两个子代理
    """

    def __init__(self) -> None:
        """
        函数名: __init__
        作用: 填入简报域的系统提示与初始 intake
        输入: 无
        输出: 无
        """
        super().__init__(
            name="briefing",
            main_system=BRIEFING_MAIN_SYSTEM,
            decision_system=BRIEFING_DECISION_SYSTEM,
            initial_intake=[
                IntakeNeed(key="goal", question="这次要完成什么？"),
                IntakeNeed(key="material", question="请贴上需要整理的材料原文。"),
                IntakeNeed(key="constraints", question="有哪些约束（篇幅、语气、禁止项）？"),
                IntakeNeed(key="output_shape", question="希望最终以什么形态交付？"),
            ],
        )

    def build_jobs(self, state: DialogState) -> list[SubagentJob]:
        """
        函数名: build_jobs
        作用: 材料抽取子代理 + 缺信息检查子代理
        输入:
            state (DialogState): 当前对话状态
        输出:
            list[SubagentJob]: 两个顺序子任务
        """
        material = state.facts.get("material") or ""
        constraints = state.facts.get("constraints") or ""
        extract_user = (
            f"Goal: {state.goal}\n"
            f"Constraints: {constraints}\n"
            f"Material:\n{material}\n"
            'Extract actionable points. JSON: {"items":[{"point":"...","complete":true}]}'
        )
        gap_user = (
            f"Goal: {state.goal}\n"
            f"Material:\n{material}\n"
            'List missing facts that block execution. JSON: {"gaps":["..."]}'
        )
        return [
            SubagentJob(
                job_id="extract_points",
                system="你是抽取子代理。只输出一个 JSON 对象，不要解释。",
                user=extract_user,
                parse_json=True,
                allow_thinking_retry=True,
            ),
            SubagentJob(
                job_id="gap_check",
                system="你是缺口检查子代理。只输出一个 JSON 对象，不要解释。",
                user=gap_user,
                parse_json=True,
                allow_thinking_retry=True,
            ),
        ]
