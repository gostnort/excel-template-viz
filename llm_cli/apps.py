"""应用注册口。本阶段为空；toml 等项目专用应用以后往这里挂。"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class AppSpec(Protocol):
    """
    类名: AppSpec
    作用: 可复用套件上的应用插件形状；内核不知道 toml
    """

    name: str

    def tools(self) -> dict[str, Callable[..., Any]]:
        """
        函数名: tools
        作用: 该应用要挂到 Agent 上的可调用工具
        输入: 无
        输出:
            dict: 名 → 函数
        """
        ...

    def build_workflow(self) -> Any:
        """
        函数名: build_workflow
        作用: 可选的 >> 管线；没有则返回 None
        输入: 无
        输出:
            Any
        """
        ...



_REGISTRY: dict[str, AppSpec] = {}



def register_app(spec: AppSpec) -> None:
    """
    函数名: register_app
    作用: 登记一个应用；同名覆盖
    输入:
        spec (AppSpec): 应用
    输出: 无
    """
    _REGISTRY[str(spec.name)] = spec



def list_apps() -> list[str]:
    """
    函数名: list_apps
    作用: 已登记应用名
    输入: 无
    输出:
        list[str]
    """
    return sorted(_REGISTRY)



def get_app(name: str) -> AppSpec | None:
    """
    函数名: get_app
    作用: 按名取应用
    输入:
        name (str): 应用名
    输出:
        AppSpec | None
    """
    return _REGISTRY.get(str(name))
