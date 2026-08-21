"""llm_gemma4 CLI：底座调用 + 通用对话运行时展示。

用法:
  python -m llm_gemma4.cli gemma ask "..."
  python -m llm_gemma4.cli gemma health
  python -m llm_gemma4.cli dialog catalog --spec briefing
  python -m llm_gemma4.cli dialog catalog --spec toml
  python -m llm_gemma4.cli dialog demo --spec toml --mock --stub
  python -m llm_gemma4.cli dialog run --spec toml --mock --stub
  python -m llm_gemma4.cli dialog repl --spec toml --mock --stub
"""

from __future__ import annotations

import argparse
import sys

from llm_gemma4.cli.dialog_cmds import cmd_catalog, cmd_dialog_demo, cmd_dialog_repl, cmd_dialog_run
from llm_gemma4.cli.gemma_cmds import (
    cmd_ask,
    cmd_health,
    cmd_judge,
    cmd_start,
    cmd_stop,
    cmd_vision,
)


def _build_parser() -> argparse.ArgumentParser:
    """
    函数名: _build_parser
    作用: 组装 gemma / dialog 两棵子命令树
    输入: 无
    输出:
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="python -m llm_gemma4.cli",
        description="Gemma4 base APIs + domain-agnostic dialog (main session, intake, sub-agents).",
    )
    root = parser.add_subparsers(dest="group", required=True)
    gemma = root.add_parser("gemma", help="ConversationOnce / Pic2Str / judgment / StartGemma")
    gcmd = gemma.add_subparsers(dest="command", required=True)
    ask = gcmd.add_parser("ask", help="stateless ConversationOnce")
    ask.add_argument("text")
    ask.add_argument("--system", default=None)
    ask.add_argument("--thinking", action="store_true")
    ask.add_argument("--release", action="store_true", help="EndGemma after the call")
    ask.set_defaults(func=cmd_ask)
    vision = gcmd.add_parser("vision", help="Pic2Str")
    vision.add_argument("image")
    vision.add_argument("--prompt", default="Describe this image.")
    vision.add_argument("--system", default=None)
    vision.add_argument("--release", action="store_true")
    vision.set_defaults(func=cmd_vision)
    health = gcmd.add_parser("health", help="model path + health_check (no warm)")
    health.set_defaults(func=cmd_health)
    start = gcmd.add_parser("start", help="StartGemma warm")
    start.set_defaults(func=cmd_start)
    stop = gcmd.add_parser("stop", help="EndGemma")
    stop.set_defaults(func=cmd_stop)
    judge = gcmd.add_parser("judge", help="run_judgment three-state verdict")
    judge.add_argument("--system", required=True)
    judge.add_argument("--user", required=True)
    judge.add_argument("--verdict-key", default="has_problem")
    judge.add_argument("--reason-key", default="reason")
    judge.add_argument("--release", action="store_true")
    judge.set_defaults(func=cmd_judge)
    dialog = root.add_parser("dialog", help="main session + dynamic intake + sub-agent dispatch")
    dcmd = dialog.add_subparsers(dest="command", required=True)
    catalog = dcmd.add_parser("catalog", help="print action catalog for --spec")
    catalog.add_argument("--spec", default="briefing", help="briefing (default) or toml")
    catalog.set_defaults(func=cmd_catalog)
    run = dcmd.add_parser("run", help="interactive dialog for --spec")
    run.add_argument("--spec", default="briefing", help="briefing (default) or toml")
    run.add_argument("--goal", default="")
    run.add_argument("--material", default="")
    run.add_argument("--constraints", default="")
    run.add_argument("--output-shape", default="")
    run.add_argument("--stub", action="store_true", help="fixed decide order, still uses backend for main/sub")
    run.add_argument("--mock", action="store_true", help="ScriptedBackend, no LiteRT")
    run.add_argument("--demo", action="store_true", help="prefill DEMO_FACTS / TOML_DEMO_AUTO")
    run.add_argument("--non-interactive", action="store_true")
    run.add_argument("--force-thinking-retry", action="store_true")
    run.add_argument("--release", action="store_true")
    run.add_argument("--live", action="store_true")
    run.add_argument("--write-toml", action="store_true", help="persist templates/{id}/{id}.toml (toml spec only)")
    run.set_defaults(func=cmd_dialog_run)
    demo = dcmd.add_parser("demo", help="non-interactive dialog; default --mock --stub")
    demo.add_argument("--spec", default="briefing", help="briefing (default) or toml")
    demo.add_argument("--live", action="store_true", help="use real Gemma instead of mock")
    demo.add_argument("--stub", action="store_true", default=True)
    demo.add_argument("--mock", action="store_true")
    demo.add_argument("--force-thinking-retry", action="store_true")
    demo.add_argument("--release", action="store_true")
    demo.add_argument("--goal", default="")
    demo.add_argument("--material", default="")
    demo.add_argument("--constraints", default="")
    demo.add_argument("--output-shape", default="")
    demo.add_argument("--non-interactive", action="store_true", default=True)
    demo.add_argument("--demo", action="store_true", default=True)
    demo.add_argument("--write-toml", action="store_true", help="persist sidecar TOML (off by default)")
    demo.set_defaults(func=cmd_dialog_demo)
    repl = dcmd.add_parser("repl", help="stdin FIFO queue + dispatch Resume (CLI only, toml)")
    repl.add_argument("--spec", default="toml", help="toml (repl is toml-only)")
    repl.add_argument("--stub", action="store_true")
    repl.add_argument("--mock", action="store_true")
    repl.add_argument("--force-thinking-retry", action="store_true")
    repl.add_argument("--release", action="store_true")
    repl.add_argument("--live", action="store_true", help="use real Gemma instead of mock+stub")
    repl.add_argument("--goal", default="")
    repl.add_argument("--write-toml", action="store_true")
    repl.set_defaults(func=cmd_dialog_repl)
    return parser


def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: CLI 入口
    输入:
        argv (list[str] | None): 参数；None 则用 sys.argv
    输出:
        int: 退出码
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return int(func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
