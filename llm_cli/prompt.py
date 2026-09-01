"""方框 stdin：Windows msvcrt / Unix termios，不引入第三方库。"""

from __future__ import annotations

import atexit
import sys

from llm_cli.banner import (
    BootInfo,
    format_input_box,
    format_model_block,
    format_status_bar,
    format_system_block,
    format_think_block,
    format_user_block,
    model_box_body_row,
    model_box_bottom_row,
    model_box_header_rows,
    term_cols,
    think_line,
    think_wrap_room,
    wrap_block_lines,
    wrap_model_body,
)
from llm_cli.icon import enable_vt

try:
    import msvcrt
except ImportError:
    msvcrt = None  # 非 Windows，走 termios

try:
    import termios
    import tty
except ImportError:
    termios = None
    tty = None

HIDE = "\x1b[?25l"
SHOW = "\x1b[?25h"
_ACTIVE: BoxedPrompt | None = None


def _show_cursor() -> None:
    """
    函数名: _show_cursor
    作用: 恢复系统光标，避免退出后终端看不见插入符
    输入: 无
    输出: 无
    """
    try:
        sys.stdout.write(SHOW)
        sys.stdout.flush()
    except Exception:
        return


atexit.register(_show_cursor)


def _key_win() -> str:
    """
    函数名: _key_win
    作用: msvcrt 读一键，返回字符或逻辑键名
    输入: 无
    输出:
        str: 可打印字符，或 ENTER/BACKSPACE/LEFT/RIGHT/DELETE/HOME/END/CTRL_C/CTRL_D/CTRL_U/IGNORE
    """
    ch = msvcrt.getwch()
    if ch in ("\x00", "\xe0"):
        extra = msvcrt.getwch()
        mapped = {"K": "LEFT", "M": "RIGHT", "S": "DELETE", "G": "HOME", "O": "END", "H": "IGNORE", "P": "IGNORE"}
        return mapped.get(extra, "IGNORE")
    if ch in ("\r", "\n"):
        return "ENTER"
    if ch in ("\x08", "\x7f"):
        return "BACKSPACE"
    if ch == "\x03":
        return "CTRL_C"
    if ch in ("\x04", "\x1a"):
        return "CTRL_D"
    if ch == "\x15":
        return "CTRL_U"
    if ch == "\x1b":
        return "IGNORE"
    return ch


def _key_posix() -> str:
    """
    函数名: _key_posix
    作用: termios 原始模式读一键（含 ESC 方向键）
    输入: 无
    输出:
        str: 同 _key_win
    """
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            rest = sys.stdin.read(1)
            if rest == "[":
                code = sys.stdin.read(1)
                mapped = {"D": "LEFT", "C": "RIGHT", "A": "IGNORE", "B": "IGNORE", "H": "HOME", "F": "END"}
                if code == "3":
                    sys.stdin.read(1)
                    return "DELETE"
                return mapped.get(code, "IGNORE")
            return "IGNORE"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x08", "\x7f"):
            return "BACKSPACE"
        if ch == "\x03":
            return "CTRL_C"
        if ch == "\x04":
            return "CTRL_D"
        if ch == "\x15":
            return "CTRL_U"
        if ord(ch) < 32:
            return "IGNORE"
        # UTF-8 后续字节
        more = 0
        o = ord(ch)
        if 0xC0 <= o <= 0xDF:
            more = 1
        elif 0xE0 <= o <= 0xEF:
            more = 2
        elif 0xF0 <= o <= 0xF7:
            more = 3
        if more:
            ch += sys.stdin.read(more)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """
    函数名: read_key
    作用: 按平台读一键
    输入: 无
    输出:
        str: 字符或逻辑键名
    """
    if msvcrt is not None:
        return _key_win()
    if termios is not None and tty is not None and sys.stdin.isatty():
        return _key_posix()
    line = sys.stdin.readline()
    if line == "":
        return "CTRL_D"
    return "LINE:" + line.rstrip("\r\n")


def _rewind_footer(drawn: int) -> None:
    """
    函数名: _rewind_footer
    作用: 把光标移回已绘底栏首行并清除其下方，供就地重绘
    输入:
        drawn (int): 上次底栏占用的逻辑行数
    输出: 无
    """
    if drawn <= 0:
        return
    # 末行不换行，光标已在底栏最后一行上，只能上移 drawn-1 行
    up = drawn - 1
    if up > 0:
        sys.stdout.write(f"\x1b[{up}A")
    sys.stdout.write("\r\x1b[J")


class BoxedPrompt:
    """
    类名: BoxedPrompt
    作用: 在终端底画输入框与状态栏；打字只改框，底栏在提交或回复后刷新
    """

    def __init__(self, info: BootInfo) -> None:
        self.info = info
        self._drawn = 0
        # 会话内固定用方框，避免中途退回 input()
        self._boxed = sys.stdin.isatty() and sys.stdout.isatty()
        self._stream_name = "model"
        self._stream_text = ""
        self._stream_width = 80
        self._stream_committed = 0
        self._stream_live = ""
        self._stream_open = False
        self._think_text = ""
        self._think_width = 80
        self._think_committed = 0
        self._think_live: str | None = None
        self._think_open = False
        enable_vt()


    def _paint(
        self,
        text: str,
        cursor: int,
        *,
        show_cursor: bool,
        hint: str = "",
        status: bool = True,
    ) -> None:
        """
        函数名: _paint
        作用: 就地重绘输入框；status 为真时连底栏一起画
        输入:
            text (str): 缓冲
            cursor (int): 光标
            show_cursor (bool): 是否画块光标
            hint (str): 空缓冲时的忙时提示
            status (bool): 是否重绘底栏；打字时 False，仅提交/回复后 True
        输出: 无
        """
        width = term_cols()
        box = format_input_box(text, cursor, width, show_cursor=show_cursor, hint=hint)
        sys.stdout.write(HIDE)
        # 首次或明确要刷底栏时，清掉旧框+status 再整块画回
        if status or self._drawn <= 0:
            _rewind_footer(self._drawn)
            lines = list(box)
            lines.append(format_status_bar(self.info, width))
            last = len(lines) - 1
            for i, line in enumerate(lines):
                sys.stdout.write("\r")
                sys.stdout.write(line)
                if i < last:
                    sys.stdout.write("\n")
            sys.stdout.write("\r")
            sys.stdout.flush()
            self._drawn = len(lines)
            return
        # 打字只改输入框：从上往下覆盖三行，换行落回已有 status，不清屏
        box_n = len(box)
        up = box_n
        if up > 0:
            sys.stdout.write(f"\x1b[{up}A")
        last = box_n - 1
        for i, line in enumerate(box):
            sys.stdout.write("\r")
            sys.stdout.write(line)
            if i < last:
                sys.stdout.write("\n")
        sys.stdout.write("\n\r")
        sys.stdout.flush()


    def clear_footer(self) -> None:
        """
        函数名: clear_footer
        作用: 擦掉底部输入框和状态栏，光标留在 transcript 末
        输入: 无
        输出: 无
        """
        if self._drawn <= 0:
            return
        _rewind_footer(self._drawn)
        sys.stdout.flush()
        self._drawn = 0


    def write_above(self, block: str) -> None:
        """
        函数名: write_above
        作用: 先擦底栏，把文本写入 transcript，再把输入框画回底部
        输入:
            block (str): 已着色的多行块
        输出: 无
        """
        self.clear_footer()
        payload = block if block.endswith("\n") else block + "\n"
        sys.stdout.write(payload)
        sys.stdout.flush()
        hint = "busy…" if self.info.activity != "idle" else ""
        self._paint("", 0, show_cursor=False, hint=hint)


    def _busy_hint(self) -> str:
        """
        函数名: _busy_hint
        作用: 忙时输入框暗色提示
        输入: 无
        输出:
            str: busy… 或空串
        """
        return "busy…" if self.info.activity != "idle" else ""


    def begin_think_stream(self) -> None:
        """
        函数名: begin_think_stream
        作用: 开始灰色 thought 流；只追加行，不整块重绘
        输入: 无
        输出: 无
        """
        self._think_text = ""
        self._think_width = term_cols()
        self._think_committed = 0
        self._think_live = None
        self._think_open = True


    def append_think_stream(self, delta: str) -> None:
        """
        函数名: append_think_stream
        作用: 追加 reasoning 增量；只改最后一行或向下长一行
        输入:
            delta (str): 增量
        输出: 无
        """
        if not delta:
            return
        if not self._think_open:
            self.begin_think_stream()
        self._think_text += delta
        self._grow_think_stream()


    def end_think_stream(self) -> None:
        """
        函数名: end_think_stream
        作用: 结束 thought 流，已画灰字留在 transcript
        输入: 无
        输出: 无
        """
        self._think_open = False


    def _grow_think_stream(self) -> None:
        """
        函数名: _grow_think_stream
        作用: 按折行把新 thought 接到末行；CUU 最多 1 行
        输入: 无
        输出: 无
        """
        width = self._think_width
        lines = wrap_block_lines(self._think_text, think_wrap_room(width))
        committed = lines[:-1]
        live = lines[-1] if lines else ""
        extra = committed[self._think_committed:]
        first_draw = self._think_live is None
        if not first_draw and not extra and live == self._think_live:
            return
        sys.stdout.write(HIDE)
        _rewind_footer(self._drawn)
        self._drawn = 0
        if first_draw:
            # 中文注释: 首次只写下灰字，其后只覆盖末行
            sys.stdout.write("\n")
            first = True
            for chunk in extra:
                sys.stdout.write(think_line(chunk, first=first) + "\n")
                first = False
            sys.stdout.write(think_line(live, first=first) + "\n")
        else:
            sys.stdout.write("\x1b[1A\r")
            for i, chunk in enumerate(extra):
                labeled = (self._think_committed + i) == 0
                sys.stdout.write(think_line(chunk, first=labeled) + "\n")
            sys.stdout.write(think_line(live, first=len(committed) == 0) + "\n")
        sys.stdout.flush()
        self._think_committed = len(committed)
        self._think_live = live
        self._paint("", 0, show_cursor=False, hint=self._busy_hint())


    def begin_model_stream(self, name: str) -> None:
        """
        函数名: begin_model_stream
        作用: 打开一次绿框（顶边+标题+空正文+底边），之后只向下长
        输入:
            name (str): 框顶标签
        输出: 无
        """
        self._stream_name = (name or "model").strip() or "model"
        self._stream_text = ""
        self._stream_width = term_cols()
        self._stream_committed = 0
        self._stream_live = ""
        self._stream_open = True
        width = self._stream_width
        sys.stdout.write(HIDE)
        _rewind_footer(self._drawn)
        self._drawn = 0
        sys.stdout.write("\n")
        for row in model_box_header_rows(self._stream_name, width):
            sys.stdout.write(row + "\n")
        sys.stdout.write(model_box_body_row("", width) + "\n")
        sys.stdout.write(model_box_bottom_row(width) + "\n")
        sys.stdout.flush()
        self._paint("", 0, show_cursor=False, hint=self._busy_hint())


    def append_model_stream(self, delta: str) -> None:
        """
        函数名: append_model_stream
        作用: 追加模型增量；只覆盖末行与底边，永不整框重打
        输入:
            delta (str): 增量
        输出: 无
        """
        if not delta:
            return
        if not self._stream_open:
            self.begin_model_stream(self._stream_name)
        self._stream_text += delta
        self._grow_model_stream()


    def end_model_stream(self) -> None:
        """
        函数名: end_model_stream
        作用: 结束流式绿框，保留已画内容作为 transcript
        输入: 无
        输出: 无
        """
        self._stream_open = False


    def _grow_model_stream(self) -> None:
        """
        函数名: _grow_model_stream
        作用: 新折行从底边上方插入；CUU 固定 2 行，超屏只滚动不叠第二框
        输入: 无
        输出: 无
        """
        width = self._stream_width
        lines = wrap_model_body(self._stream_text, width)
        committed = lines[:-1]
        live = lines[-1] if lines else ""
        extra = committed[self._stream_committed:]
        if not extra and live == self._stream_live:
            return
        sys.stdout.write(HIDE)
        _rewind_footer(self._drawn)
        self._drawn = 0
        # 中文注释: 光标在底栏首行，上移 2 行落到当前正文末行（其下是底边）
        sys.stdout.write("\x1b[2A\r")
        for chunk in extra:
            sys.stdout.write(model_box_body_row(chunk, width) + "\n")
        sys.stdout.write(model_box_body_row(live, width) + "\n")
        sys.stdout.write(model_box_bottom_row(width) + "\n")
        sys.stdout.flush()
        self._stream_committed = len(committed)
        self._stream_live = live
        self._paint("", 0, show_cursor=False, hint=self._busy_hint())


    def show_busy(self, hint: str = "busy…") -> None:
        """
        函数名: show_busy
        作用: 底部保持输入框，框内与底栏显示等待状态
        输入:
            hint (str): 框内暗色提示
        输出: 无
        """
        self._paint("", 0, show_cursor=False, hint=hint)


    def _commit(self, text: str) -> None:
        """
        函数名: _commit
        作用: 提交时擦掉底栏，便于立刻把用户行写入 transcript
        输入:
            text (str): 已提交文本（仅占位，正文由调用方回显）
        输出: 无
        """
        del text
        self.clear_footer()


    def read(self) -> str:
        """
        函数名: read
        作用: 阻塞读一行；空回车留在框内；Ctrl+C/D 抛异常
        输入: 无
        输出:
            str: 用户输入
        """
        if not self._boxed:
            return input()
        buf: list[str] = []
        cur = 0
        self._paint("", 0, show_cursor=True)
        while True:
            key = read_key()
            # 管道整行 / 回车提交 / 中断
            if key.startswith("LINE:"):
                text = key[5:]
                return text
            if key == "ENTER":
                text = "".join(buf)
                if not text.strip():
                    continue
                return text
            if key == "CTRL_C":
                self._commit("".join(buf))
                _show_cursor()
                raise KeyboardInterrupt
            if key == "CTRL_D":
                if buf:
                    continue
                self._commit("")
                _show_cursor()
                raise EOFError
            # 编辑键：退格、方向、整行清除
            if key == "BACKSPACE":
                if cur > 0:
                    del buf[cur - 1]
                    cur -= 1
            elif key == "DELETE":
                if cur < len(buf):
                    del buf[cur]
            elif key == "LEFT":
                cur = max(0, cur - 1)
            elif key == "RIGHT":
                cur = min(len(buf), cur + 1)
            elif key == "HOME":
                cur = 0
            elif key == "END":
                cur = len(buf)
            elif key == "CTRL_U":
                buf = buf[cur:]
                cur = 0
            elif key == "IGNORE":
                pass
            elif len(key) >= 1 and key.isprintable():
                buf[cur:cur] = list(key)
                cur += len(key)
            # 按键只覆盖输入框，底栏留到回车或模型回复后再刷
            self._paint("".join(buf), cur, show_cursor=True, status=False)


def bind_prompt(prompt: BoxedPrompt | None) -> None:
    """
    函数名: bind_prompt
    作用: 登记当前交互框，供 emit_* 写到输入框上方
    输入:
        prompt (BoxedPrompt | None): 活动提示符；None 表示解绑
    输出: 无
    """
    global _ACTIVE
    _ACTIVE = prompt


def emit_text(block: str) -> None:
    """
    函数名: emit_text
    作用: 有底栏则写到框上方并重绘，否则直接打印
    输入:
        block (str): 已着色多行块
    输出: 无
    """
    if _ACTIVE is not None and _ACTIVE._drawn > 0:
        _ACTIVE.write_above(block)
        return
    payload = block if block.endswith("\n") else block + "\n"
    sys.stdout.write(payload)
    sys.stdout.flush()


def emit_user(text: str) -> None:
    """
    函数名: emit_user
    作用: 把用户发言写入 transcript
    输入:
        text (str): 用户原文
    输出: 无
    """
    emit_text(format_user_block(text, term_cols()))


def emit_think(text: str) -> None:
    """
    函数名: emit_think
    作用: 把 reasoning 写成灰色 think 块（you 与绿框之间）
    输入:
        text (str): thought 原文
    输出: 无
    """
    payload = str(text or "").strip()
    if not payload:
        return
    emit_text(format_think_block(payload, term_cols()))


def emit_think_start() -> None:
    """
    函数名: emit_think_start
    作用: 开始流式灰色 thought
    输入: 无
    输出: 无
    """
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.begin_think_stream()
        return
    sys.stdout.write(f"{think_line('', first=True)}")
    sys.stdout.flush()


def emit_think_delta(chunk: str) -> None:
    """
    函数名: emit_think_delta
    作用: 追加一段 reasoning token
    输入:
        chunk (str): 增量文本
    输出: 无
    """
    if not chunk:
        return
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.append_think_stream(chunk)
        return
    sys.stdout.write(chunk)
    sys.stdout.flush()


def emit_think_end() -> None:
    """
    函数名: emit_think_end
    作用: 结束流式 thought；已画灰字保留
    输入: 无
    输出: 无
    """
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.end_think_stream()
        return
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_model(text: str, name: str = "model") -> None:
    """
    函数名: emit_model
    作用: 把模型回复写成绿色方框块
    输入:
        text (str): 模型原文
        name (str): 框顶标签
    输出: 无
    """
    emit_text(format_model_block(text, term_cols(), name))


def emit_model_start(name: str = "model") -> None:
    """
    函数名: emit_model_start
    作用: 开始把模型回复流式写入 transcript 方框
    输入:
        name (str): 框顶标签
    输出: 无
    """
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.begin_model_stream(name)
        return
    sys.stdout.write(f"{name}: ")
    sys.stdout.flush()


def emit_model_delta(chunk: str) -> None:
    """
    函数名: emit_model_delta
    作用: 追加一段已到达的模型 token
    输入:
        chunk (str): 增量文本
    输出: 无
    """
    if not chunk:
        return
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.append_model_stream(chunk)
        return
    sys.stdout.write(chunk)
    sys.stdout.flush()


def emit_model_end() -> None:
    """
    函数名: emit_model_end
    作用: 结束流式模型块；方框模式保留已画内容
    输入: 无
    输出: 无
    """
    if _ACTIVE is not None and _ACTIVE._boxed:
        _ACTIVE.end_model_stream()
        return
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_system(text: str) -> None:
    """
    函数名: emit_system
    作用: 把命令/系统输出写成横线块
    输入:
        text (str): 系统原文
    输出: 无
    """
    emit_text(format_system_block(text, term_cols()))


def read_boxed_line(info: BootInfo) -> str:
    """
    函数名: read_boxed_line
    作用: 用方框提示读一行
    输入:
        info (BootInfo): 底栏用的会话快照
    输出:
        str: 用户输入
    """
    return BoxedPrompt(info).read()
