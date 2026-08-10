"""路由模块：action 路由由 toml_config.decision.decide() 承担。"""

from __future__ import annotations


def route(action_id: str, state: dict | None = None) -> str:
    """
    函数名: route
    作用: Phase A 占位；Phase B 接入 Gemma decide()
    输入:
        action_id (str): 当前动作标识
        state (dict | None): 工作流状态（可选）
    输出:
        str: 下一步 action_id
    """
    return ""


def route_key_from_action(action_id: str) -> str:
    """
    函数名: route_key_from_action
    作用: 从 action_id 推导 route key
    输入:
        action_id (str): 动作标识
    输出:
        str: 路由键
    """
    return ""
