"""研发/调试版终端启动横幅与文本排版工具。"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# ANSI 基础配色
RESET = "\x1b[0m"
TITLE = "\x1b[1;38;2;64;156;255m"
BORDER = "\x1b[38;2;64;156;255m"
DIM = "\x1b[38;2;142;150;160m"
TEXT = "\x1b[38;2;228;232;240m"
OK = "\x1b[38;2;80;200;120m"
BOX = "\x1b[38;2;226;230;236m"
USER = "\x1b[1;38;2;90;220;235m"
USER_TEXT = "\x1b[1;38;2;245;248;255m"
MODEL_LABEL = "\x1b[1;38;2;80;200;120m"
MODEL_TEXT = "\x1b[38;2;156;196;164m"
MODEL_BOX = "\x1b[38;2;72;140;96m"
SYS = "\x1b[38;2;168;176;188m"
SYS_RULE = "\x1b[38;2;88;96;104m"
THINK_LABEL = "\x1b[38;2;120;128;140m"
THINK_TEXT = "\x1b[38;2;142;150;160m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """
    函数名: strip_ansi
    作用: 去掉 ANSI 颜色序列，留下可见字符
    输入:
        text (str): 可能带颜色的文本
    输出:
        str: 纯文本
    """
    return _ANSI_RE.sub("", text or "")


@dataclass
class BootInfo:
    """启动快照"""

    cwd: str
    session: str
    model: str = ""
    version: str = "0.1.0"
    provider: str = "lms"
    provider_up: bool = False
    provider_detail: str = ""
    api_url: str = ""
    activity: str = "idle"
    thinking: bool = False
    stream: bool = False
    context_used: int | None = None
    context_limit: int | None = None
    startup_notes: list[str] = field(default_factory=list)


def resolve_version() -> str:
    """版本号解析"""
    return "0.1.0-dev"


def term_cols() -> int:
    """当前终端宽度（默认 80）"""
    return max(40, shutil.get_terminal_size((80, 24)).columns)


def vis_width(text: str) -> int:
    """计算去除 ANSI 序列后的东亚可见字符宽度"""
    n = 0
    for ch in _ANSI_RE.sub("", text):
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def clip_plain(text: str, budget: int) -> str:
    """按可见列宽截断纯文本"""
    if budget <= 0:
        return ""
    if vis_width(text) <= budget:
        return text
    if budget == 1:
        return "…"
    out: list[str] = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > budget - 1:
            out.append("…")
            break
        out.append(ch)
        used += w
    return "".join(out)


def wrap_plain(text: str, budget: int) -> list[str]:
    """折行"""
    if budget <= 0:
        return [""]
    if not text:
        return [""]
    out: list[str] = []
    line: list[str] = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if used + w > budget and line:
            out.append("".join(line))
            line = []
            used = 0
        line.append(ch)
        used += w
    if line:
        out.append("".join(line))
    return out or [""]


def wrap_block_lines(text: str, budget: int) -> list[str]:
    """多行折行"""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        out.extend(wrap_plain(raw, budget))
    return out


def _box_row(inner: str, width: int, color: str) -> str:
    room = max(0, width - 2)
    extra = room - vis_width(inner)
    if extra < 0:
        inner = clip_plain(_ANSI_RE.sub("", inner), room)
        extra = room - vis_width(inner)
    return f"{color}│{RESET}{inner}{' ' * extra}{color}│{RESET}"


def _box_wrap(rows: list[str], width: int, color: str) -> list[str]:
    bar = "─" * max(0, width - 2)
    out = [f"{color}┌{bar}┐{RESET}"]
    for row in rows:
        out.append(_box_row(row, width, color))
    out.append(f"{color}└{bar}┘{RESET}")
    return out


def format_status_bar(info: BootInfo, width: int) -> str:
    """格式化单行底栏"""
    model = info.model or info.provider
    think = "on" if info.thinking else "off"
    stream = "on" if info.stream else "off"
    left = f"{model} think:{think} stream:{stream} {info.activity} {info.cwd}"
    right = format_context_label(info.context_used, info.context_limit)
    gap = max(1, width - vis_width(left) - vis_width(right))
    return f"{DIM}{left}{' ' * gap}{right}{RESET}"


def format_context_label(used: int | None, limit: int | None) -> str:
    """上下文用量提示"""
    if used is None or used < 0:
        return "context: —"
    if limit is not None and limit > 0:
        pct = max(0, min(100, int(round(100.0 * used / limit))))
        return f"context: {pct}%"
    return f"context: {used} tok"


def format_input_box(
    text: str,
    cursor: int,
    width: int,
    *,
    show_cursor: bool = True,
    hint: str = "",
) -> list[str]:
    """通用输入框"""
    budget = max(4, width - 6)
    if hint and not text:
        inner = f" {TEXT}>{RESET} {DIM}{clip_plain(hint, budget)}{RESET}"
        return _box_wrap([inner], width, BOX)
    cur = max(0, min(cursor, len(text)))
    prefix = text[:cur]
    suffix = text[cur:]
    mark = "█" if show_cursor else ""
    shown = prefix + mark + suffix
    if vis_width(shown) > budget:
        shown = clip_plain(shown, budget)
    inner = f" {TEXT}>{RESET} {shown}"
    return _box_wrap([inner], width, BOX)


def format_user_block(text: str, width: int) -> str:
    label = f"{USER} you {RESET}"
    pad = vis_width(" you ")
    room = max(8, width - pad)
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    first = True
    for raw in body.split("\n"):
        for chunk in wrap_plain(raw, room):
            if first:
                lines.append(f"{label}{USER_TEXT}{chunk}{RESET}")
                first = False
            else:
                lines.append(f"{' ' * pad}{USER_TEXT}{chunk}{RESET}")
    return "\n" + "\n".join(lines or [label]) + "\n"


def format_think_block(text: str, width: int) -> str:
    room = think_wrap_room(width)
    lines = [think_line(chunk, first=(i == 0)) for i, chunk in enumerate(wrap_block_lines(text, room))]
    return ("\n" + "\n".join(lines) + "\n") if lines else ""


def format_model_block(text: str, width: int, name: str = "model") -> str:
    inner_w = max(8, width - 2)
    title = clip_plain((name or "model").strip() or "model", max(4, inner_w - 1))
    rows = [f" {MODEL_LABEL}{title}{RESET}"]
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        for chunk in wrap_plain(raw, max(4, inner_w - 1)):
            rows.append(f" {MODEL_TEXT}{chunk}{RESET}")
    return "\n" + "\n".join(_box_wrap(rows, width, MODEL_BOX)) + "\n"


def format_system_block(text: str, width: int) -> str:
    bar = "─" * max(0, width)
    lines = [f"{SYS_RULE}{bar}{RESET}", f"{SYS} sys{RESET}"]
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        for chunk in wrap_plain(raw, width):
            lines.append(f"{SYS}{chunk}{RESET}")
    lines.append(f"{SYS_RULE}{bar}{RESET}")
    return "\n" + "\n".join(lines) + "\n"


def model_box_header_rows(name: str, width: int) -> list[str]:
    bar = "─" * max(0, width - 2)
    title = (name or "model").strip() or "model"
    return [f"{MODEL_BOX}┌{bar}┐{RESET}", _box_row(f" {MODEL_LABEL}{title}{RESET}", width, MODEL_BOX)]


def model_box_body_row(text: str, width: int) -> str:
    return _box_row(f" {MODEL_TEXT}{text}{RESET}", width, MODEL_BOX)


def model_box_bottom_row(width: int) -> str:
    return f"{MODEL_BOX}└{'─' * max(0, width - 2)}┘{RESET}"


def think_wrap_room(width: int) -> int:
    return max(8, width - 8)


def think_line(chunk: str, *, first: bool = False) -> str:
    tag = f"{THINK_LABEL}think:{RESET} " if first else "       "
    return f"{tag}{THINK_TEXT}{chunk}{RESET}"


def wrap_model_body(text: str, width: int) -> list[str]:
    return wrap_block_lines(text, max(4, width - 4))


def print_boot(info: BootInfo | None = None, *, provider: str = "lms", model: str = "") -> None:
    """打印研发调试版极简欢迎框"""
    from llm_cli.terminal_io import enable_vt
    enable_vt()

    width = term_cols()
    lines = format_banner_lines(info, width)
    print("\n" + "\n".join(lines) + "\n", flush=True)


def pad_columns(text: str, width: int) -> str:
    """
    函数名: pad_columns
    作用: 按可见列宽把文本补到指定宽度；超宽则按可见列截断
    输入:
        text (str): 纯文本
        width (int): 目标可见列数
    输出:
        str: 补齐或截断后的文本
    """
    if width <= 0:
        return ""
    clipped = clip_plain(text, width)
    return clipped + (" " * max(0, width - vis_width(clipped)))


def format_banner_lines(info: BootInfo | None = None, width: int = 80) -> list[str]:
    """
    函数名: format_banner_lines
    作用: 生成启动横幅的四行，中文按可见列宽对齐，避免把右边框顶出去
    输入:
        info (BootInfo | None): 启动快照
        width (int): 终端列数
    输出:
        list[str]: 顶边、两行正文、底边
    """
    box_w = min(width - 4, 78)
    inner_w = box_w - 4
    p_url = (info.api_url if info else "") or "http://127.0.0.1:9999"
    m_name = (info.model if info else "") or "(not loaded)"
    p_name = (info.provider if info else "") or "lms"
    title = "⚡ Excel Template Viz · CLI (Dev Mode)"
    row1 = f"Provider : {p_name} ({p_url}) · Model: {m_name}"
    row2 = "Commands : /menu (模板工作台) · /help (帮助) · exit (退出)"
    # 中文注释: ┌──、标题后的空格和 ┐ 一共占 6 个可见列
    dashes = max(0, box_w - vis_width(title) - 6)
    top = f"  {BORDER}┌── {TITLE}{title}{RESET}{BORDER} {'─' * dashes}┐{RESET}"
    mid1 = f"  {BORDER}│{RESET} {pad_columns(row1, inner_w)} {BORDER}│{RESET}"
    mid2 = f"  {BORDER}│{RESET} {pad_columns(row2, inner_w)} {BORDER}│{RESET}"
    bot = f"  {BORDER}└{'─' * max(0, box_w - 2)}┘{RESET}"
    return [top, mid1, mid2, bot]


def format_path_bar(path: str, width: int = 80) -> list[str]:
    """常驻当前选择路径跟随栏"""
    box_w = min(width - 4, 78)
    tag = f"  📍 当前路径: {TITLE}{path}{RESET}"
    rule = f"  {DIM}{'─' * max(0, box_w)}{RESET}"
    return [tag, rule]

