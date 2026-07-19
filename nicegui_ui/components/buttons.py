"""应用按钮：Python 只组合类名，颜色与尺寸由 style.css 变量控制。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from nicegui import ui
from nicegui.elements.label import Label as NiceLabel

BtnVariant = Literal["default", "excel", "db", "google", "danger"]

_VARIANT_CLASS: dict[BtnVariant, str] = {
    "default": "",
    "excel": "excel",
    "db": "db",
    "google": "google",
    "danger": "danger",
}


def _build_btn_classes(
    variant: BtnVariant = "default",
    *,
    primary: bool = False,
    disabled: bool = False,
    extra_classes: str = "",
) -> str:
    # 只输出类名，不含任何颜色或尺寸字面量
    parts = ["btn"]
    variant_cls = _VARIANT_CLASS.get(variant, "")
    if variant_cls:
        parts.append(variant_cls)
    if primary:
        parts.append("primary")
    if disabled:
        parts.append("disabled")
    if extra_classes.strip():
        parts.extend(extra_classes.split())
    return " ".join(parts)


def app_btn(
    text: str,
    *,
    on_click: Callable[..., Any] | None = None,
    variant: BtnVariant = "default",
    primary: bool = False,
    disabled: bool = False,
    extra_classes: str = "",
) -> NiceLabel:
    """
    函数名: app_btn
    作用: 创建应用统一样式按钮（ui.label + .btn 变体类）
    输入:
        text (str): 按钮文案
        on_click: 点击回调，None 则不绑定
        variant: default | excel | db | google | danger
        primary (bool): 加宽内边距修饰符
        disabled (bool): 禁用修饰符
        extra_classes (str): 布局类（如 toolbar-trash-anchor）
    输出:
        NiceLabel: NiceGUI 元素
    """
    cls = _build_btn_classes(
        variant,
        primary=primary,
        disabled=disabled,
        extra_classes=extra_classes,
    )
    el = ui.label(text).classes(cls)
    if on_click is not None:
        el.on("click", on_click)
    return el


def app_btn_set_disabled(el: NiceLabel, disabled: bool) -> None:
    """
    函数名: app_btn_set_disabled
    作用: 切换按钮 .disabled 修饰类
    输入:
        el (NiceLabel): app_btn 返回值
        disabled (bool): 是否禁用
    输出: 无
    """
    if disabled:
        el.classes("disabled")
    else:
        el.classes(remove="disabled")
