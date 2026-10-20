"""CLI 声明式控件库。

序号写在左上角转角右侧。框内只放文本或输入值。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from llm_cli.banner import clip_plain, term_cols, vis_width

CYAN = "\x1b[36m"
BOLD_WHITE = "\x1b[1;37m"
GREEN = "\x1b[32m"
RESET = "\x1b[0m"



@dataclass
class InputField:
    """表单字段。label 画在顶边，value 画在框内。"""

    label: str
    value: str = ""
    multiline: bool = False
    lines: int = 1
    cursor_pos: int | None = None


def render_button_grid(
    buttons: dict[int | str, str],
    *,
    cols: int = 2,
    active_key: Any = None,
    total_width: int | None = None,
) -> list[str]:
    """
    函数名: render_button_grid
    作用: 按列数把按钮画成左上角带序号的方块
    输入:
        buttons (dict[int | str, str]): 序号到按钮文字
        cols (int): 期望列数
        active_key (Any): 高亮的序号；没有则为 None
        total_width (int | None): 终端列数；空则现场读取
    输出:
        list[str]: 可直接写入终端的行
    """
    if not buttons:
        return []
    width = total_width or term_cols()
    items = list(buttons.items())
    max_label_w = max(vis_width(str(val)) for _, val in items)
    max_tag_w = max(vis_width(f"┌[{k}]") for k, _ in items)
    btn_w = max(max_label_w + 4, max_tag_w + 6, 24)
    btn_w = min(btn_w, max(24, width - 6))
    actual_cols = max(1, min(cols, (width - 4) // (btn_w + 2)))
    cards: list[list[str]] = []
    for key, val in items:
        is_active = key == active_key
        border_color = GREEN if is_active else CYAN
        text_color = BOLD_WHITE if not is_active else GREEN
        tag = f"┌[{key}]"
        top = f"{border_color}{tag}{'─' * max(0, btn_w - vis_width(tag) - 1)}┐{RESET}"
        body_space = btn_w - 4
        clipped = clip_plain(str(val), body_space)
        pad = " " * max(0, body_space - vis_width(clipped))
        mid = f"{border_color}│{RESET} {text_color}{clipped}{pad}{RESET} {border_color}│{RESET}"
        bot = f"{border_color}└{'─' * max(0, btn_w - 2)}┘{RESET}"
        cards.append([top, mid, bot])
    rendered: list[str] = []
    for start in range(0, len(cards), actual_cols):
        chunk = cards[start:start + actual_cols]
        for row_idx in range(3):
            rendered.append("  " + "  ".join(card[row_idx] for card in chunk))
    return rendered


def _blank_input_row(card_w: int, border_color: str) -> str:
    """
    函数名: _blank_input_row
    作用: 生成一行与卡片同宽的空框体，用来垫高同一行里较矮的字段
    输入:
        card_w (int): 卡片可见列宽
        border_color (str): 边框 ANSI 色
    输出:
        str: 一行空框
    """
    return f"{border_color}│{' ' * max(0, card_w - 2)}│{RESET}"


def _input_card(
    key: int | str,
    field: InputField,
    *,
    card_w: int,
    active_key: Any,
) -> tuple[list[str], str]:
    """
    函数名: _input_card
    作用: 画出一张带序号和标签的输入卡片
    输入:
        key (int | str): 左上角序号
        field (InputField): 字段内容
        card_w (int): 卡片可见列宽
        active_key (Any): 当前焦点序号
    输出:
        tuple[list[str], str]: 卡片行，以及该卡片的边框色
    """
    is_active = key == active_key
    border_color = GREEN if is_active else CYAN
    label_color = BOLD_WHITE if not is_active else GREEN
    prefix = f"┌[{key}] "
    room = max(1, card_w - vis_width(prefix) - 2)
    label = clip_plain(field.label, room)
    tag = f"{prefix}{label_color}{label}{RESET}{border_color} "
    top = f"{border_color}{tag}{'─' * max(0, card_w - vis_width(tag) - 1)}┐{RESET}"
    body_space = card_w - 4
    line_count = max(1, field.lines if field.multiline else 1)
    val_lines = field.value.splitlines() if field.multiline else [field.value]
    while len(val_lines) < line_count:
        val_lines.append("")
    rows = [top]
    for line_val in val_lines[:line_count]:
        clipped = clip_plain(line_val, body_space)
        pad = " " * max(0, body_space - vis_width(clipped))
        rows.append(f"{border_color}│{RESET} {clipped}{pad} {border_color}│{RESET}")
    rows.append(f"{border_color}└{'─' * max(0, card_w - 2)}┘{RESET}")
    return rows, border_color


def render_input_grid(
    inputs: dict[int | str, InputField],
    *,
    cols: int = 1,
    active_key: Any = None,
    total_width: int | None = None,
) -> list[str]:
    """
    函数名: render_input_grid
    作用: 按列排出表单卡片；同一视觉行内才垫高，避免一个多行字段拉高全部卡片
    输入:
        inputs (dict[int | str, InputField]): 序号到字段
        cols (int): 期望列数
        active_key (Any): 焦点序号
        total_width (int | None): 终端列数
    输出:
        list[str]: 表单行
    """
    if not inputs:
        return []
    width = total_width or term_cols()
    items = list(inputs.items())
    card_w = max(28, (width - 4) // max(1, cols) - 2)
    actual_cols = max(1, min(cols, (width - 4) // (card_w + 2)))
    cards = [
        _input_card(key, field, card_w=card_w, active_key=active_key)
        for key, field in items
    ]
    rendered: list[str] = []
    for start in range(0, len(cards), actual_cols):
        chunk = cards[start:start + actual_cols]
        height = max(len(rows) for rows, _color in chunk)
        padded: list[list[str]] = []
        for rows, border_color in chunk:
            block = list(rows)
            while len(block) < height:
                block.insert(-1, _blank_input_row(card_w, border_color))
            padded.append(block)
        for row_idx in range(height):
            rendered.append("  " + "  ".join(block[row_idx] for block in padded))
    return rendered


def _fit_cursor_window(before: str, after: str, mark: str, budget: int) -> str:
    """
    函数名: _fit_cursor_window
    作用: 按可见列宽裁切输入，并让光标块留在窗口里
    输入:
        before (str): 光标之前的文本
        after (str): 光标之后的文本
        mark (str): 光标字符；不活跃时为空串
        budget (int): 可见列预算
    输出:
        str: 放得进预算的文本
    """
    if budget <= 0:
        return ""
    core = before + mark
    if vis_width(core) <= budget:
        return core + clip_plain(after, budget - vis_width(core))
    chars = list(before)
    while chars and vis_width("".join(chars) + mark) > budget:
        chars.pop(0)
    return "".join(chars) + mark


def render_single_input_box(
    *,
    label: str = "通用输入",
    value: str = "",
    cursor: int | None = None,
    hint: str = "输入 /menu 重开菜单 · exit 退出",
    total_width: int | None = None,
    is_active: bool = True,
) -> list[str]:
    """
    函数名: render_single_input_box
    作用: 画出中部通用单行输入框，光标用实心块
    输入:
        label (str): 顶边标签
        value (str): 当前缓冲
        cursor (int | None): 光标下标；空则在末尾
        hint (str): 顶边括号里的提示
        total_width (int | None): 终端列数
        is_active (bool): 是否使用焦点色并显示光标
    输出:
        list[str]: 顶边、内容行、底边
    """
    width = total_width or term_cols()
    box_w = min(width - 4, 78)
    inner_w = box_w - 4
    border_color = GREEN if is_active else CYAN
    label_color = BOLD_WHITE if is_active else CYAN
    plain_label = f"── {label}"
    tag = f"── {label_color}{label}{RESET}"
    # 中文注释: 顶边提示放不下时截断，避免窄终端把右边框顶出框外
    hint_room = box_w - 3 - vis_width(plain_label) - 3
    if hint and hint_room > 0:
        tag += f" ({clip_plain(hint, hint_room)})"
    bar_len = max(0, box_w - vis_width(tag) - 3)
    top = f"  {border_color}┌{tag} {border_color}{'─' * bar_len}┐{RESET}"
    cur = len(value) if cursor is None else max(0, min(cursor, len(value)))
    mark = "█" if is_active else ""
    # 中文注释: "> " 占两列，内容预算比内宽少 2，顶边与内容行才能对齐
    content_budget = max(1, inner_w - 2)
    shown = _fit_cursor_window(value[:cur], value[cur:], mark, content_budget)
    pad = " " * max(0, content_budget - vis_width(shown))
    mid = f"  {border_color}│{RESET} {GREEN}>{RESET} {shown}{pad} {border_color}│{RESET}"
    bot = f"  {border_color}└{'─' * max(0, box_w - 2)}┘{RESET}"
    return [top, mid, bot]
