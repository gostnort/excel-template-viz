"""终端启动画面：欢迎框、提供方状态、方框输入与底栏。"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from llm_cli.icon import enable_vt, render_grid

# 半块 ▀ = 1 列 × 2 纵向像素。N×N 像素 → N 列 × ceil(N/2) 字符行。
# 最大横向像素 = 欢迎框与间隙之后剩余的 term_cols（每列 1 像素）。
# 最大纵向像素 = 可用字符行 × 2（半块叠两行）。启动方图受剩余列宽约束。
ART_PX = 16  # 够宽时的目标像素边长（16 列 × 8 半块行）
MIN_ART_PX = 4  # 合理下限；再窄则不在右侧画标
ART_STEPS = (16, 8, 5)  # 窄屏按整数缩小的档位（16/2、16/3）
ART_W = ART_PX
ART_H = ART_PX
MIN_BOX = 40
LOGO_GAP = 1
INK = 18
RESET = "\x1b[0m"
TITLE_FG = "\x1b[1;38;2;152;220;147m"
META_FG = "\x1b[38;2;152;220;147m"
BORDER = "\x1b[38;2;64;156;255m"
TITLE = "\x1b[1;38;2;64;156;255m"
DIM = "\x1b[38;2;142;150;160m"
TEXT = "\x1b[38;2;228;232;240m"
OK = "\x1b[38;2;80;200;120m"
BAD = "\x1b[38;2;220;96;96m"
BOX = "\x1b[38;2;226;230;236m"
TIP = "\x1b[38;2;64;156;255m"
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
_PYPROJECT = Path(__file__).resolve().parent.parent / "bootup" / "pyproject.toml"


def _is_ink(rgb: tuple[int, int, int]) -> bool:
    """
    函数名: _is_ink
    作用: 判断像素是否相对黑底可见
    输入:
        rgb (tuple[int, int, int]): RGB
    输出:
        bool: 有墨则 True
    """
    return max(rgb) > INK


def _fg(rgb: tuple[int, int, int]) -> str:
    """
    函数名: _fg
    作用: 24-bit 前景 ANSI
    输入:
        rgb (tuple[int, int, int]): RGB
    输出:
        str: CSI 序列
    """
    return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def _bg(rgb: tuple[int, int, int]) -> str:
    """
    函数名: _bg
    作用: 24-bit 背景 ANSI
    输入:
        rgb (tuple[int, int, int]): RGB
    输出:
        str: CSI 序列
    """
    return f"\x1b[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"


def load_art_pixels(width: int = ART_PX, height: int = ART_PX) -> list[list[tuple[int, int, int]]]:
    """
    函数名: load_art_pixels
    作用: 从 icon_512.png 缩到正方形终端像素网格
    输入:
        width (int): 列像素
        height (int): 行像素（与列相同则不变形）
    输出:
        list: [行][列] RGB
    """
    # 宽高等比 contain 缩小，不分别拉 X/Y
    small = render_grid(width, height)
    rows: list[list[tuple[int, int, int]]] = []
    for y in range(height):
        row: list[tuple[int, int, int]] = []
        for x in range(width):
            pix = small.getpixel((x, y))
            row.append((int(pix[0]), int(pix[1]), int(pix[2])))
        rows.append(row)
    return rows


def _half_cell(top: tuple[int, int, int], bot: tuple[int, int, int]) -> str:
    """
    函数名: _half_cell
    作用: 一格终端用 ▀/▄ 表示上下两像素
    输入:
        top (tuple): 上像素 RGB
        bot (tuple): 下像素 RGB
    输出:
        str: 带色的一个字符
    """
    top_on = _is_ink(top)
    bot_on = _is_ink(bot)
    if not top_on and not bot_on:
        return " "
    if top_on and bot_on:
        return f"{_fg(top)}{_bg(bot)}▀{RESET}"
    if top_on:
        return f"{_fg(top)}▀{RESET}"
    return f"{_fg(bot)}▄{RESET}"


def render_ansi_icon(width: int = ART_PX, height: int = ART_PX) -> list[str]:
    """
    函数名: render_ansi_icon
    作用: 把图标画成若干行半块像素
    输入:
        width (int): 列数（= 横向像素）
        height (int): 像素行；奇数则末行下半格垫黑，不重新加高采样
    输出:
        list[str]: 每行已着色文本
    """
    # 先按给定宽高等比缩小（调用方传正方形）；奇数行只垫黑，避免变成 N×(N+1) 拉长
    pixels = load_art_pixels(width, height)
    if height % 2:
        blank = (0, 0, 0)
        pixels = pixels + [[blank] * width]
        height += 1
    lines: list[str] = []
    for y in range(0, height, 2):
        cells = [_half_cell(pixels[y][x], pixels[y + 1][x]) for x in range(width)]
        lines.append("".join(cells))
    return lines


@dataclass
class BootInfo:
    """
    类名: BootInfo
    作用: 启动画面与底栏所需的会话快照
    """

    cwd: str
    session: str
    model: str
    version: str
    provider: str = "lm_studio"
    provider_up: bool = False
    provider_detail: str = ""
    api_url: str = ""
    activity: str = "idle"
    thinking: bool = False
    stream: bool = False
    context_used: int | None = None
    context_limit: int | None = None


def term_cols() -> int:
    """
    函数名: term_cols
    作用: 取终端列宽，留一列避免自动换行撑破方框
    输入: 无
    输出:
        int: 可用列数
    """
    cols = shutil.get_terminal_size((80, 24)).columns
    # 不得超过真实列宽-1，否则底栏折行会让 CUU 行数对不上
    return max(2, cols - 1)



def resolve_version() -> str:
    """
    函数名: resolve_version
    作用: 读 bootup/pyproject.toml 的 version，缺省 0.1.1
    输入: 无
    输出:
        str: 版本号
    """
    if _PYPROJECT.is_file():
        for raw in _PYPROJECT.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("version"):
                _, _, rest = line.partition("=")
                ver = rest.strip().strip("\"'")
                if ver:
                    return ver
    return "0.1.1"


def vis_width(text: str) -> int:
    """
    函数名: vis_width
    作用: 可见列宽（去 ANSI，全角计 2）
    输入:
        text (str): 可能含 CSI 的文本
    输出:
        int: 列数
    """
    n = 0
    for ch in _ANSI_RE.sub("", text):
        if unicodedata.combining(ch):
            continue
        n += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return n


def clip_plain(text: str, budget: int) -> str:
    """
    函数名: clip_plain
    作用: 按可见列宽截断纯文本，末尾加省略号
    输入:
        text (str): 无 ANSI 的字符串
        budget (int): 最大列宽
    输出:
        str: 截断结果
    """
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
    """
    函数名: wrap_plain
    作用: 按可见列宽把纯文本拆成多行
    输入:
        text (str): 无 ANSI 的字符串
        budget (int): 每行最大列宽
    输出:
        list[str]: 折行后的纯文本
    """
    limit = max(1, budget)
    if vis_width(text) <= limit:
        return [text]
    out: list[str] = []
    current: list[str] = []
    used = 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if current and used + w > limit:
            out.append("".join(current))
            current = [ch]
            used = w
            continue
        current.append(ch)
        used += w
    if current:
        out.append("".join(current))
    return out or [""]



def wrap_block_lines(text: str, budget: int) -> list[str]:
    """
    函数名: wrap_block_lines
    作用: 按段落把文本折成若干纯文本行
    输入:
        text (str): 原文
        budget (int): 每行最大列宽
    输出:
        list[str]: 折行；至少一行
    """
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw in body.split("\n"):
        lines.extend(wrap_plain(raw, budget))
    return lines or [""]



def model_box_header_rows(name: str, width: int) -> list[str]:
    """
    函数名: model_box_header_rows
    作用: 流式绿框的顶边与标题行（不重绘已滚动正文）
    输入:
        name (str): 框顶标签
        width (int): 整框列宽
    输出:
        list[str]: 顶边、标题两行
    """
    inner_w = max(8, width - 2)
    title = clip_plain((name or "model").strip() or "model", max(4, inner_w - 1))
    bar = "─" * max(0, width - 2)
    top = f"{MODEL_BOX}╭{bar}╮{RESET}"
    title_row = _box_row(f" {MODEL_LABEL}{title}{RESET}", width, MODEL_BOX)
    return [top, title_row]



def model_box_body_row(chunk: str, width: int) -> str:
    """
    函数名: model_box_body_row
    作用: 绿框一行正文
    输入:
        chunk (str): 已折行的纯文本
        width (int): 整框列宽
    输出:
        str: 带左右框线的一行
    """
    return _box_row(f" {MODEL_TEXT}{chunk}{RESET}", width, MODEL_BOX)



def model_box_bottom_row(width: int) -> str:
    """
    函数名: model_box_bottom_row
    作用: 绿框底边
    输入:
        width (int): 整框列宽
    输出:
        str: 底边一行
    """
    bar = "─" * max(0, width - 2)
    return f"{MODEL_BOX}╰{bar}╯{RESET}"



def wrap_model_body(text: str, width: int) -> list[str]:
    """
    函数名: wrap_model_body
    作用: 按绿框内宽把模型正文折行
    输入:
        text (str): 累计模型原文
        width (int): 整框列宽
    输出:
        list[str]: 框内纯文本行
    """
    inner_w = max(8, width - 2)
    return wrap_block_lines(text, max(4, inner_w - 1))



def think_line(chunk: str, *, first: bool) -> str:
    """
    函数名: think_line
    作用: 灰色 thought 的一行（首行带 think 标签）
    输入:
        chunk (str): 已折行纯文本
        first (bool): 是否为首行
    输出:
        str: 已着色一行
    """
    if first:
        return f"{THINK_LABEL} think {RESET}{THINK_TEXT}{chunk}{RESET}"
    pad = vis_width(" think ")
    return f"{' ' * pad}{THINK_TEXT}{chunk}{RESET}"



def think_wrap_room(width: int) -> int:
    """
    函数名: think_wrap_room
    作用: thought 正文可用列宽
    输入:
        width (int): 终端列宽
    输出:
        int: 折行预算
    """
    return max(8, width - vis_width(" think "))



def _header_badge() -> tuple[str, str]:
    """
    函数名: _header_badge
    作用: 欢迎框标题左侧两行绿色小标
    输入: 无
    输出:
        tuple[str, str]: 上下两行已着色块
    """
    top = f"{_bg((152, 220, 147))}{_fg((220, 245, 220))}▀▀{RESET}"
    bot = f"{_bg((4, 108, 60))}{_fg((152, 220, 147))}▄▄{RESET}"
    return top, bot


def _box_row(inner: str, width: int, color: str) -> str:
    """
    函数名: _box_row
    作用: 画一行带左右框线的内容
    输入:
        inner (str): 已含颜色的框内文本（不含边框）
        width (int): 整行列宽
        color (str): 边框色 CSI
    输出:
        str: 完整一行
    """
    room = max(0, width - 2)
    extra = room - vis_width(inner)
    if extra < 0:
        inner = clip_plain(_ANSI_RE.sub("", inner), room)
        extra = room - vis_width(inner)
    return f"{color}│{RESET}{inner}{' ' * extra}{color}│{RESET}"


def _box_wrap(rows: list[str], width: int, color: str) -> list[str]:
    """
    函数名: _box_wrap
    作用: 用圆角单线把若干行包成方框
    输入:
        rows (list[str]): 框内行
        width (int): 整框列宽
        color (str): 边框色
    输出:
        list[str]: 含顶底边的行
    """
    bar = "─" * max(0, width - 2)
    out = [f"{color}╭{bar}╮{RESET}"]
    for row in rows:
        out.append(_box_row(row, width, color))
    out.append(f"{color}╰{bar}╯{RESET}")
    return out


def _beside(left: list[str], right: list[str], gap: int = 1) -> list[str]:
    """
    函数名: _beside
    作用: 左右两列按行拼接，短侧用空格补齐
    输入:
        left (list[str]): 左列（蓝框）
        right (list[str]): 右列（像素标）
        gap (int): 中间空列
    输出:
        list[str]: 拼好的行
    """
    rows = max(len(left), len(right))
    left_w = 0
    for row in left:
        w = vis_width(row)
        if w > left_w:
            left_w = w
    out: list[str] = []
    for i in range(rows):
        # 左列不足则垫空格，右列不足则留空
        if i < len(left):
            l = left[i]
        else:
            l = " " * left_w
        extra = left_w - vis_width(l)
        r = right[i] if i < len(right) else ""
        out.append(f"{l}{' ' * extra}{' ' * gap}{r}")
    return out


def _trim_logo(lines: list[str]) -> list[str]:
    """
    函数名: _trim_logo
    作用: 去掉像素标上下全空行，让可见点阵贴着蓝框
    输入:
        lines (list[str]): 半块像素行
    输出:
        list[str]: 去掉上下空白后的行
    """
    start = 0
    end = len(lines)
    while start < end and not _ANSI_RE.sub("", lines[start]).strip():
        start += 1
    while end > start and not _ANSI_RE.sub("", lines[end - 1]).strip():
        end -= 1
    return lines[start:end]


def _pick_art_px(cols: int) -> int:
    """
    函数名: _pick_art_px
    作用: 按欢迎框后剩余列宽选取正方形像素边长
    输入:
        cols (int): 终端可用列宽（已减 1）
    输出:
        int: 像素边长；0 表示不画右侧标
    """
    # 半块 ▀ = 1 列 × 2 纵向像素。N×N 像素占 N 列 × ceil(N/2) 字符行。
    # 最大横向像素 = term_cols 减去欢迎框 MIN_BOX 与间隙 LOGO_GAP 后的剩余列。
    # 最大纵向像素 = 可用字符行 × 2（半块把两行像素叠进一格）。
    # 方图 N = min(目标 16, 剩余列宽)；不够则按整数档 8/5… 缩小，或贴合剩余宽度，不分别拉 X/Y。
    room = cols - MIN_BOX - LOGO_GAP
    if room < MIN_ART_PX:
        return 0
    if room >= ART_PX:
        return ART_PX
    for size in ART_STEPS:
        if size <= room:
            # 剩余宽度大于该档则用满剩余列，仍保持正方形
            if size < room:
                return room
            return size
    n = room - (room % 2)
    if n < MIN_ART_PX:
        return 0
    return n


def _choose_logo(cols: int) -> list[str]:
    """
    函数名: _choose_logo
    作用: 终端够宽则在蓝框右侧画正方形像素标；默认 16×16，不够则缩小
    输入:
        cols (int): 可用列宽
    输出:
        list[str]: 半块像素行；并排放不下则空列表
    """
    size = _pick_art_px(cols)
    if size < MIN_ART_PX:
        return []
    cand = render_ansi_icon(size, size)
    if not cand:
        return []
    need = MIN_BOX + LOGO_GAP + vis_width(cand[0])
    if cols < need:
        return []
    return _trim_logo(cand)


def _meta_row(label: str, value: str, width: int, value_ansi: str = TEXT) -> str:
    """
    函数名: _meta_row
    作用: 欢迎框内标签/值对齐行
    输入:
        label (str): 左侧标签（不含冒号）
        value (str): 右侧纯文本值
        width (int): 整框列宽
        value_ansi (str): 值的前景色
    输出:
        str: 框内一行
    """
    head = f" {label}:"
    pad = max(1, 13 - vis_width(head))
    prefix = f"{DIM}{head}{' ' * pad}{RESET}"
    room = max(4, width - 2 - vis_width(prefix))
    body = clip_plain(value, room)
    return f"{prefix}{value_ansi}{body}{RESET}"


def format_launch(info: BootInfo, width: int | None = None) -> str:
    """
    函数名: format_launch
    作用: 拼欢迎框（左）与像素标（右）+ 提示 + 提供方状态行
    输入:
        info (BootInfo): 会话快照
        width (int | None): 列宽；空则取终端
    输出:
        str: 多行启动画面
    """
    cols = width if width is not None else term_cols()
    # 宽度够则 16×16 点阵贴在蓝框右侧；列不够则按剩余宽度缩小
    logo = _choose_logo(cols)
    logo_w = vis_width(logo[0]) if logo else 0
    box_w = cols - LOGO_GAP - logo_w if logo else cols
    badge_top, badge_bot = _header_badge()
    head = [
        f" {badge_top} {TITLE}Welcome to llm_cli!{RESET}",
        f" {badge_bot} {DIM}Send /help for help information.{RESET}",
        "",
        _meta_row("Directory", info.cwd, box_w),
        _meta_row("Model", info.model or "—", box_w),
        _meta_row("Version", info.version, box_w),
    ]
    # 提供方值：短名 + 绿/红 up/down
    flag = "up" if info.provider_up else "down"
    flag_cs = OK if info.provider_up else BAD
    prov_head = f"{DIM} Provider:{' ' * 3}{RESET}"
    name = clip_plain(info.provider, max(4, box_w - 2 - vis_width(prov_head) - vis_width(flag) - 1))
    head.append(f"{prov_head}{TEXT}{name} {flag_cs}{flag}{RESET}")
    box = _box_wrap(head, box_w, BORDER)
    hero = _beside(box, logo, gap=LOGO_GAP) if logo else box
    tip = f"{TIP}✦{RESET} {TITLE}Type /help for commands{RESET}{DIM}  · /health /reset /thinking on /stream /exit{RESET}"
    detail = info.provider_detail.strip() or ("connected" if info.provider_up else "down")
    extra = f" ({info.api_url})" if info.api_url else ""
    status_plain = f"{info.provider} {detail}{extra}"
    hue = OK if info.provider_up else BAD
    status = f"{hue}{clip_plain(status_plain, cols)}{RESET}"
    parts = [""]
    parts.extend(hero)
    parts.append("")
    parts.append(tip)
    parts.append(status)
    return "\n".join(parts)


def format_boot(*, provider: str = "lm_studio", model: str = "") -> str:
    """
    函数名: format_boot
    作用: 兼容旧签名，用当前目录拼一版启动画面
    输入:
        provider (str): 提供方短名
        model (str): 模型 key，可空
    输出:
        str: 多行文本
    """
    info = BootInfo(
        cwd=str(Path.cwd()),
        session="",
        model=model,
        version=resolve_version(),
        provider=provider or "lm_studio",
    )
    return format_launch(info)


def format_input_box(
    text: str,
    cursor: int,
    width: int,
    *,
    show_cursor: bool = True,
    hint: str = "",
) -> list[str]:
    """
    函数名: format_input_box
    作用: 全宽白灰框输入行，内含 > 与可选块光标或忙时提示
    输入:
        text (str): 当前缓冲
        cursor (int): 光标下标
        width (int): 整框列宽
        show_cursor (bool): 是否画 █
        hint (str): 空缓冲时的暗色提示（如 busy…）
    输出:
        list[str]: 顶/中/底三行
    """
    # 框内：空格 > 空格 + 正文；超宽则从左侧裁到光标仍可见
    budget = max(4, width - 2 - 4)
    if hint and not text:
        inner = f" {TEXT}>{RESET} {DIM}{clip_plain(hint, budget)}{RESET}"
        return _box_wrap([inner], width, BOX)
    cur = max(0, min(cursor, len(text)))
    prefix = text[:cur]
    suffix = text[cur:]
    mark = "█" if show_cursor else ""
    start = 0
    while start < len(prefix) and vis_width(prefix[start:] + mark + suffix) > budget:
        start += 1
    shown = prefix[start:] + mark + suffix
    while shown and vis_width(shown) > budget:
        if suffix:
            suffix = suffix[:-1]
            shown = prefix[start:] + mark + suffix
            continue
        if mark:
            shown = prefix[start:] + mark
            if vis_width(shown) > budget and start < len(prefix):
                start += 1
                shown = prefix[start:] + mark
            continue
        break
    inner = f" {TEXT}>{RESET} {shown}"
    return _box_wrap([inner], width, BOX)


def format_status_bar(info: BootInfo, width: int) -> str:
    """
    函数名: format_status_bar
    作用: 底栏：模型 · think 开关 · stream 开关 · idle/busy · 目录
    输入:
        info (BootInfo): 会话快照
        width (int): 列宽
    输出:
        str: 一行底栏
    """
    model = info.model or info.provider
    think = "on" if info.thinking else "off"
    stream = "on" if info.stream else "off"
    left = f"{model} think: {think} stream: {stream}  {info.activity}  {info.cwd}"
    right = format_context_label(info.context_used, info.context_limit)
    if vis_width(left) + 1 + vis_width(right) > width:
        left = clip_plain(left, max(8, width - vis_width(right) - 1))
    gap = max(1, width - vis_width(left) - vis_width(right))
    return f"{DIM}{left}{' ' * gap}{right}{RESET}"



def format_context_label(used: int | None, limit: int | None) -> str:
    """
    函数名: format_context_label
    作用: 底栏右侧 context 文案；有内容却算不出用量时不假装 0%
    输入:
        used (int | None): 已用 token；未知为 None
        limit (int | None): 上下文上限；未知为 None
    输出:
        str: 如 context: 12% / context: <1% / context: 320 tok / context: —
    """
    if used is None or used < 0:
        return "context: —"
    if limit is not None and limit > 0:
        pct = int(round(100.0 * used / limit))
        if used > 0 and pct < 1:
            return "context: <1%"
        if pct < 0:
            pct = 0
        if pct > 100:
            pct = 100
        return f"context: {pct}%"
    return f"context: {used} tok"


def format_user_block(text: str, width: int) -> str:
    """
    函数名: format_user_block
    作用: 回显用户发言：青色 you 标签 + 近白正文
    输入:
        text (str): 用户原文
        width (int): 终端列宽
    输出:
        str: 多行 transcript 块（首尾带空行）
    """
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
                continue
            lines.append(f"{' ' * pad}{USER_TEXT}{chunk}{RESET}")
    if not lines:
        lines.append(f"{label}{RESET}")
    return "\n" + "\n".join(lines) + "\n"



def format_think_block(text: str, width: int) -> str:
    """
    函数名: format_think_block
    作用: 灰色 thought 块：think 标签 + 暗色正文，夹在 you 与绿框之间
    输入:
        text (str): reasoning 原文
        width (int): 终端列宽
    输出:
        str: 多行 transcript 块（首尾带空行）
    """
    room = think_wrap_room(width)
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    first = True
    for raw in body.split("\n"):
        for chunk in wrap_plain(raw, room):
            lines.append(think_line(chunk, first=first))
            first = False
    if not lines:
        return ""
    return "\n" + "\n".join(lines) + "\n"



def format_model_block(text: str, width: int, name: str = "model") -> str:
    """
    函数名: format_model_block
    作用: 模型回复：绿色方框 + 名称标签，与用户行硬分隔
    输入:
        text (str): 模型原文
        width (int): 终端列宽
        name (str): 框顶标签（模型名或 model）
    输出:
        str: 多行方框块
    """
    inner_w = max(8, width - 2)
    title = clip_plain((name or "model").strip() or "model", max(4, inner_w - 1))
    rows = [f" {MODEL_LABEL}{title}{RESET}"]
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    if not body.strip():
        rows.append(f" {MODEL_TEXT}(empty){RESET}")
    else:
        for raw in body.split("\n"):
            for chunk in wrap_plain(raw, max(4, inner_w - 1)):
                rows.append(f" {MODEL_TEXT}{chunk}{RESET}")
    boxed = _box_wrap(rows, width, MODEL_BOX)
    return "\n" + "\n".join(boxed) + "\n"


def format_system_block(text: str, width: int) -> str:
    """
    函数名: format_system_block
    作用: 命令/系统输出：横线 + sys 标签 + 暗色正文
    输入:
        text (str): 系统原文
        width (int): 终端列宽
    输出:
        str: 带上下横线的多行块
    """
    bar = "─" * max(0, width)
    lines = [f"{SYS_RULE}{bar}{RESET}", f"{SYS} sys{RESET}"]
    body = text.replace("\r\n", "\n").replace("\r", "\n")
    for raw in body.split("\n"):
        for chunk in wrap_plain(raw, width):
            lines.append(f"{SYS}{chunk}{RESET}")
    lines.append(f"{SYS_RULE}{bar}{RESET}")
    return "\n" + "\n".join(lines) + "\n"


def print_boot(info: BootInfo | None = None, *, provider: str = "lm_studio", model: str = "") -> None:
    """
    函数名: print_boot
    作用: 打开 VT 后打印欢迎框启动画面
    输入:
        info (BootInfo | None): 完整快照；空则用 provider/model 现拼
        provider (str): 无 info 时的提供方
        model (str): 无 info 时的模型
    输出: 无
    """
    enable_vt()
    payload = info if info is not None else BootInfo(
        cwd=str(Path.cwd()),
        session="",
        model=model,
        version=resolve_version(),
        provider=provider or "lm_studio",
    )
    print(format_launch(payload), flush=True)
    print()
