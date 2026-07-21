"""应用按钮：基于 NiceGUI/Quasar 原生 ui.button 的面向对象封装。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from nicegui import ui

BtnVariant = Literal["default", "excel", "db", "google", "danger"]


class AppBtn(ui.button):
    """
    类名: AppBtn
    作用: 应用统一样式按钮，继承自 ui.button，自动映射 variant 到 Quasar 主题色。
    """

    def __init__(
        self,
        text: str = '',
        *,
        on_click: Callable[..., Any] | None = None,
        variant: BtnVariant = "default",
        primary: bool = False,
        disabled: bool = False,
        extra_classes: str = "",
    ) -> None:
        """
        函数名: __init__
        作用: 初始化应用按钮
        输入:
            text (str): 按钮文案
            on_click: 点击回调，None 则不绑定
            variant (BtnVariant): 预设颜色变体
            primary (bool): 预留的主要按钮修饰（增加边距等）
            disabled (bool): 初始禁用状态
            extra_classes (str): 附加 CSS 类名
        输出: 
            无
        """
        super().__init__(text=text, color=None, on_click=on_click)
        
        # 基础样式与无阴影设计
        self.classes('app-btn')
        self.props('unelevated')
        
        if variant == "default":
            self.props('outline text-color="black" color="grey-8"')
        else:
            self.classes(f'app-btn-{variant}')

        if primary:
            self.classes('primary')
            
        if extra_classes.strip():
            self.classes(extra_classes)
            
        if disabled:
            self.disable()
