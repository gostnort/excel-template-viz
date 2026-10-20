"""单视口状态机动态画布。

自上而下三段：顶部横幅与常驻路径、中部互斥舞台、底部反馈流。
整帧用 \\x1b[H 回到左上角重画，每行 \\x1b[K，帧末 \\x1b[J。
"""

from __future__ import annotations

import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.core_registry import SortTemplates
from llm_cli.banner import (
    BootInfo,
    clip_plain,
    format_banner_lines,
    format_path_bar,
    strip_ansi,
)
from llm_cli.terminal_io import (
    enable_vt,
    read_key,
    set_feedback_hook,
)
from llm_cli.widgets import render_button_grid, render_single_input_box

HIDE = "\x1b[?25l"
DIM = "\x1b[90m"
RESET = "\x1b[0m"


class SessionContext:
    """会话上下文。注入 templates 时不触碰磁盘上的模板时间线。"""


    def __init__(self, info: BootInfo, *, templates: list[dict[str, Any]] | None = None) -> None:
        """
        函数名: __init__
        作用: 建立会话；仅在未注入模板时才加载真实注册表
        输入:
            info (BootInfo): 启动快照
            templates (list[dict] | None): 测试或调用方给定的模板；None 表示读注册表
        输出: 无
        """
        self.info = info
        self.templates = templates
        # 中文注释: 注入列表时跳过 SortTemplates，避免测试改写 sort_templates.json
        self.registry = None if templates is not None else SortTemplates()
        self.active_template_id: str | None = None
        self.active_template_name: str | None = None
        self.active_template_file: str | None = None
        self.active_template_path: Path | None = None
        self.feedbacks: list[str] = []


    @property
    def current_path(self) -> str:
        """
        函数名: current_path
        作用: 给出顶部常驻路径栏的文本
        输入: 无
        输出:
            str: 已选模板的文件名路径；未选时为 [未选择模板]
        """
        label = self.active_template_file or self.active_template_name
        if label:
            return f"模板 > {label}"
        return "[未选择模板]"


    def add_feedback(self, text: str) -> None:
        """
        函数名: add_feedback
        作用: 把一条反馈拆成纯文本行并追加，超长时只保留最近 300 行
        输入:
            text (str): 原文，可含 ANSI 颜色
        输出: 无
        """
        plain = strip_ansi(str(text or ""))
        for line in plain.splitlines():
            cleaned = line.rstrip()
            if not cleaned.strip():
                continue
            self.feedbacks.append(cleaned)
        if len(self.feedbacks) > 300:
            self.feedbacks = self.feedbacks[-300:]


    def get_recent_feedback(self, max_lines: int) -> list[str]:
        """
        函数名: get_recent_feedback
        作用: 取出反馈区放得下的最近若干行
        输入:
            max_lines (int): 最多返回的行数
        输出:
            list[str]: 从旧到新的反馈行
        """
        if not self.feedbacks or max_lines <= 0:
            return []
        return self.feedbacks[-max_lines:]



class CanvasState(ABC):
    """舞台状态。同一时刻只有一个状态占据中部。"""

    name: str = "base"


    @abstractmethod
    def enter(self, machine: CanvasStateMachine) -> None:
        """
        函数名: enter
        作用: 进入该状态时准备数据
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """


    @abstractmethod
    def render_content(self, machine: CanvasStateMachine, width: int) -> list[str]:
        """
        函数名: render_content
        作用: 生成中部舞台的行，不含顶部横幅和底部反馈
        输入:
            machine (CanvasStateMachine): 宿主状态机
            width (int): 终端列数
        输出:
            list[str]: 舞台行
        """


    @abstractmethod
    def handle_key(self, machine: CanvasStateMachine, key: str) -> bool:
        """
        函数名: handle_key
        作用: 处理一键
        输入:
            machine (CanvasStateMachine): 宿主状态机
            key (str): read_key 返回的键名或字符
        输出:
            bool: False 表示退出整个程序
        """


    @abstractmethod
    def exit(self, machine: CanvasStateMachine) -> None:
        """
        函数名: exit
        作用: 离开该状态时丢弃只属于本状态的缓冲
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """



class TemplateMenuState(CanvasState):
    """模板按钮网格。中部只有按钮和一行说明，没有输入框。"""

    name = "template_menu"


    def __init__(self) -> None:
        """
        函数名: __init__
        作用: 建立空的选号缓冲
        输入: 无
        输出: 无
        """
        self._buf: list[str] = []
        self._error_hint = ""
        self._templates_cache: list[dict[str, Any]] = []


    def enter(self, machine: CanvasStateMachine) -> None:
        """
        函数名: enter
        作用: 打开菜单时清空选号并装载模板列表
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """
        enable_vt()
        self._buf = []
        self._error_hint = ""
        self._load_templates(machine)


    def exit(self, machine: CanvasStateMachine) -> None:
        """
        函数名: exit
        作用: 离开菜单时丢掉未提交的数字
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """
        self._buf = []
        self._error_hint = ""


    def _load_templates(self, machine: CanvasStateMachine) -> None:
        """
        函数名: _load_templates
        作用: 优先使用注入的模板；否则从注册表读取时间线
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """
        injected = machine.session.templates
        if injected is not None:
            self._templates_cache = [dict(item) for item in injected]
            return
        registry = machine.session.registry
        if registry is None:
            self._templates_cache = []
            return
        registry.UpdateJson()
        timeline = registry.sort_templates_timeline
        display_to_id = {v: k for k, v in registry.template_display_names.items()}
        loaded: list[dict[str, Any]] = []
        for name in timeline:
            tid = display_to_id.get(name)
            if not tid:
                continue
            raw_path = registry.TemplateIDs.get(tid)
            file_name = raw_path.name if isinstance(raw_path, Path) else f"{name}.xlsx"
            loaded.append({
                "id": tid,
                "display_name": name,
                "file_name": file_name,
                "path": raw_path if isinstance(raw_path, Path) else None,
            })
        self._templates_cache = loaded


    def render_content(self, machine: CanvasStateMachine, width: int) -> list[str]:
        """
        函数名: render_content
        作用: 画出双列模板按钮和选号说明
        输入:
            machine (CanvasStateMachine): 宿主状态机
            width (int): 终端列数
        输出:
            list[str]: 舞台行
        """
        if not self._templates_cache:
            self._load_templates(machine)
        templates = self._templates_cache
        if not templates:
            return [f"  {DIM}没有可用模板 · [ESC] 切换至输入框{RESET}"]
        btn_dict = {
            i: str(item.get("file_name", item.get("display_name", "")))
            for i, item in enumerate(templates, 1)
        }
        active_key = None
        for i, item in enumerate(templates, 1):
            if str(item.get("id", "")) == machine.session.active_template_id:
                active_key = i
                break
        lines = render_button_grid(btn_dict, cols=2, active_key=active_key, total_width=width)
        typed = "".join(self._buf)
        hint = f"{DIM}[1-{len(templates)}] 选号并回车 · [ESC] 切换至输入框"
        if typed:
            hint += f" · 已输入 {typed}"
        if self._error_hint:
            hint += f" · {self._error_hint}"
        lines.append(f"  {hint}{RESET}")
        return lines


    def handle_key(self, machine: CanvasStateMachine, key: str) -> bool:
        """
        函数名: handle_key
        作用: 只接受数字、退格、回车和 ESC
        输入:
            machine (CanvasStateMachine): 宿主状态机
            key (str): 键名或字符
        输出:
            bool: False 表示退出程序
        """
        templates = self._templates_cache
        if key == "CTRL_C":
            return False
        if key == "ESC":
            machine.session.add_feedback("已切换至通用输入模式 (输入 /menu 可重开模板菜单)")
            machine.pop_state()
            return True
        if key == "BACKSPACE":
            if self._buf:
                self._buf.pop()
                self._error_hint = ""
            return True
        if key == "ENTER":
            return self._commit(machine, templates)
        if len(key) == 1 and key.isdigit():
            self._buf.append(key)
            self._error_hint = ""
        return True


    def _commit(self, machine: CanvasStateMachine, templates: list[dict[str, Any]]) -> bool:
        """
        函数名: _commit
        作用: 把已输入的数字提交为模板选择
        输入:
            machine (CanvasStateMachine): 宿主状态机
            templates (list[dict]): 当前菜单项
        输出:
            bool: 继续运行则为 True
        """
        text = "".join(self._buf).strip()
        if not text:
            return True
        if not text.isdigit():
            self._error_hint = "请输入纯数字选号"
            self._buf = []
            return True
        idx = int(text)
        if idx < 1 or idx > len(templates):
            self._error_hint = f"请输入 1 至 {len(templates)} 的有效数字"
            self._buf = []
            return True
        self._apply_template(machine, templates[idx - 1])
        machine.pop_state()
        return True


    def _apply_template(self, machine: CanvasStateMachine, template: dict[str, Any]) -> None:
        """
        函数名: _apply_template
        作用: 记录选中模板、刷新路径，并在真实注册表可用时更新最近使用
        输入:
            machine (CanvasStateMachine): 宿主状态机
            template (dict): 含 id、file_name、path 的模板项
        输出: 无
        """
        fname = str(template.get("file_name", template.get("display_name", "")))
        tpath = template.get("path")
        machine.session.active_template_id = str(template["id"])
        machine.session.active_template_name = str(template.get("display_name", fname))
        machine.session.active_template_file = fname
        machine.session.active_template_path = tpath if isinstance(tpath, Path) else None
        registry = machine.session.registry
        if registry is not None and isinstance(tpath, Path) and tpath.exists():
            try:
                registry.LastUseTemplate = tpath
            except ValueError as exc:
                machine.session.add_feedback(f"模板已选中，但未能写入最近使用记录: {exc}")
        machine.session.add_feedback(f"已激活模板: {fname}")



class PromptState(CanvasState):
    """通用单行输入。/menu 回到模板网格。"""

    name = "prompt"


    def __init__(self) -> None:
        """
        函数名: __init__
        作用: 建立空的输入缓冲和光标
        输入: 无
        输出: 无
        """
        self._buf: list[str] = []
        self._cursor: int = 0


    def enter(self, machine: CanvasStateMachine) -> None:
        """
        函数名: enter
        作用: 进入输入态时打开终端虚拟控制序列
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """
        enable_vt()


    def exit(self, machine: CanvasStateMachine) -> None:
        """
        函数名: exit
        作用: 离开输入态时清空未提交文本
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出: 无
        """
        self._buf = []
        self._cursor = 0


    def render_content(self, machine: CanvasStateMachine, width: int) -> list[str]:
        """
        函数名: render_content
        作用: 画出通用单行输入框
        输入:
            machine (CanvasStateMachine): 宿主状态机
            width (int): 终端列数
        输出:
            list[str]: 输入框行
        """
        return render_single_input_box(
            label="通用输入",
            value="".join(self._buf),
            cursor=self._cursor,
            hint="输入 /menu 重开菜单 · exit 退出",
            total_width=width,
            is_active=True,
        )


    def handle_key(self, machine: CanvasStateMachine, key: str) -> bool:
        """
        函数名: handle_key
        作用: 编辑一行文本，回车后交给命令分发
        输入:
            machine (CanvasStateMachine): 宿主状态机
            key (str): 键名或字符
        输出:
            bool: False 表示退出程序
        """
        if key == "CTRL_C":
            if self._buf:
                self._buf = []
                self._cursor = 0
                return True
            return False
        if key == "CTRL_D":
            return False
        if key == "BACKSPACE":
            if self._cursor > 0:
                del self._buf[self._cursor - 1]
                self._cursor -= 1
            return True
        if key == "DELETE":
            if self._cursor < len(self._buf):
                del self._buf[self._cursor]
            return True
        if key == "LEFT":
            self._cursor = max(0, self._cursor - 1)
            return True
        if key == "RIGHT":
            self._cursor = min(len(self._buf), self._cursor + 1)
            return True
        if key == "HOME":
            self._cursor = 0
            return True
        if key == "END":
            self._cursor = len(self._buf)
            return True
        if key == "CTRL_U":
            self._buf = self._buf[self._cursor:]
            self._cursor = 0
            return True
        if key == "ENTER":
            return self._submit(machine)
        if len(key) >= 1 and key.isprintable():
            self._buf[self._cursor:self._cursor] = list(key)
            self._cursor += len(key)
        return True


    def _submit(self, machine: CanvasStateMachine) -> bool:
        """
        函数名: _submit
        作用: 提交一行；/menu 相变回菜单，其余交给 shell.dispatch
        输入:
            machine (CanvasStateMachine): 宿主状态机
        输出:
            bool: False 表示退出程序
        """
        line = "".join(self._buf).strip()
        self._buf = []
        self._cursor = 0
        if not line:
            return True
        if line in ("/menu", "menu") or line.startswith("/menu "):
            machine.session.add_feedback("已呼出模板菜单")
            machine.push_state(TemplateMenuState())
            return True
        if line in ("exit", "/exit", "quit", "/quit"):
            machine.session.add_feedback("退出交互。")
            return False
        machine.session.add_feedback(f"you > {line}")
        machine.session.info.activity = "busy"
        machine.render()
        # 中文注释: shell 在 run_loop 里导入本模块，这里延后导入以打破环
        from llm_cli.shell import dispatch, _refresh_info
        cont = dispatch(line, machine.session.info)
        _refresh_info(machine.session.info)
        machine.session.info.activity = "idle"
        return bool(cont)



class CanvasStateMachine:
    """三段式视口的状态机。"""


    def __init__(self, info: BootInfo, *, templates: list[dict[str, Any]] | None = None) -> None:
        """
        函数名: __init__
        作用: 建立会话、默认输入态，并把外部 emit 接到反馈流
        输入:
            info (BootInfo): 启动快照
            templates (list[dict] | None): 注入模板时不读注册表
        输出: 无
        """
        self.session = SessionContext(info, templates=templates)
        self._stack: list[CanvasState] = []
        self._default_state = PromptState()
        self._running = True
        set_feedback_hook(self._handle_external_feedback)


    def _handle_external_feedback(self, text: str) -> None:
        """
        函数名: _handle_external_feedback
        作用: 接收 emit_* 转发来的文本并写入反馈流
        输入:
            text (str): 系统、思考或模型输出
        输出: 无
        """
        self.session.add_feedback(text)


    @property
    def current_state(self) -> CanvasState:
        """
        函数名: current_state
        作用: 返回栈顶状态；栈空时返回默认输入态
        输入: 无
        输出:
            CanvasState: 当前占据中部的状态
        """
        return self._stack[-1] if self._stack else self._default_state


    def push_state(self, state: CanvasState) -> None:
        """
        函数名: push_state
        作用: 退出当前状态并让新状态接管中部
        输入:
            state (CanvasState): 要压入的状态
        输出: 无
        """
        if self._stack:
            self._stack[-1].exit(self)
        self._stack.append(state)
        state.enter(self)


    def pop_state(self) -> CanvasState | None:
        """
        函数名: pop_state
        作用: 弹出栈顶；栈空后进入默认输入态
        输入: 无
        输出:
            CanvasState | None: 被弹出的状态；栈本来就是空则为 None
        """
        if not self._stack:
            return None
        popped = self._stack.pop()
        popped.exit(self)
        if self._stack:
            self._stack[-1].enter(self)
        else:
            self._default_state.enter(self)
        return popped


    def compose_frame(self, *, cols: int | None = None, rows: int | None = None) -> list[str]:
        """
        函数名: compose_frame
        作用: 合成一整帧三段式文本，行数不超过视口
        输入:
            cols (int | None): 列数；空则读终端
            rows (int | None): 行数；空则读终端
        输出:
            list[str]: 自上而下的帧行
        """
        if cols is None or rows is None:
            size = shutil.get_terminal_size((80, 24))
            cols = size.columns if cols is None else cols
            rows = size.lines if rows is None else rows
        cols = max(40, cols)
        rows = max(12, rows)
        top: list[str] = []
        top.extend(format_banner_lines(self.session.info, cols))
        top.extend(format_path_bar(self.session.current_path, cols))
        top.append("")
        # 中文注释: 给反馈标题和至少一行反馈留位，舞台放不下就裁掉底部按钮行
        stage_budget = max(1, rows - len(top) - 3)
        stage = self.current_state.render_content(self, cols)[:stage_budget]
        frame: list[str] = []
        frame.extend(top)
        frame.extend(stage)
        frame.append("")
        box_w = min(cols - 4, 78)
        frame.append(f"  {DIM}── 反馈信息 ─{'─' * max(0, box_w - 14)}{RESET}")
        feed_budget = max(1, rows - len(frame))
        if not self.session.feedbacks:
            frame.append(f"    {DIM}(就绪。输入 /menu 选择模板，输入 /help 查看命令){RESET}")
        else:
            for line in self.session.get_recent_feedback(feed_budget):
                frame.append(f"    {clip_plain(line, box_w)}")
        if len(frame) > rows:
            frame = frame[:rows]
        return frame


    @staticmethod
    def frame_payload(lines: list[str]) -> str:
        """
        函数名: frame_payload
        作用: 把帧行编码成回到原点、逐行擦除、最后清掉下方残影的控制序列
        输入:
            lines (list[str]): compose_frame 的结果
        输出:
            str: 写入 stdout 的一整段
        """
        body = "".join(f"{line}\x1b[K\n" for line in lines)
        return "\x1b[H" + body + "\x1b[J"


    def render(self) -> None:
        """
        函数名: render
        作用: 在真实终端上重画整帧；非交互 stdout 不写，避免测试污染控制台
        输入: 无
        输出: 无
        """
        if not sys.stdout.isatty():
            return
        sys.stdout.write(HIDE)
        sys.stdout.write(self.frame_payload(self.compose_frame()))
        sys.stdout.flush()


    def handle_key(self, key: str) -> bool:
        """
        函数名: handle_key
        作用: 把一键交给当前状态，并在退出时停下循环
        输入:
            key (str): 键名或字符
        输出:
            bool: False 表示程序该退出
        """
        cont = self.current_state.handle_key(self, key)
        if not cont:
            self._running = False
        return cont


    def run_turn(self) -> bool:
        """
        函数名: run_turn
        作用: 重画一帧并读取一键
        输入: 无
        输出:
            bool: False 表示退出循环
        """
        self.render()
        return self.handle_key(read_key())


    def is_running(self) -> bool:
        """
        函数名: is_running
        作用: 报告主循环是否还应继续
        输入: 无
        输出:
            bool: 仍在运行则为 True
        """
        return self._running
