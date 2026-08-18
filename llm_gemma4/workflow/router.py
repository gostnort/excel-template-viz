"""路由模块：动态边由 Graph.set_router(decide) 承担，本文件不再维护静态下一跳。"""

from __future__ import annotations


def route(action_id: str, state: dict | None = None) -> str:
    """
    函数名: route
    作用: 兼容占位；动态路由由 Graph.set_router 注入（dialog.decide 或 toml_config.decision）
    输入:
        action_id (str): 当前动作标识
        state (dict | None): 工作流状态（可选）
    输出:
        str: 原样返回 action_id（无静态边）
    """
    return action_id


def route_key_from_action(action_id: str) -> str:
    """
    函数名: route_key_from_action
    作用: 默认 route_key 与 action_id 相同
    输入:
        action_id (str): 动作标识
    输出:
        str: 路由键
    """
    return action_id
