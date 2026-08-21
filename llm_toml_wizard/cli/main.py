"""llm_toml_wizard CLI：动态 agents 对话运行时（briefing / toml）。

用法:
  python -m llm_toml_wizard.cli dialog catalog --spec toml
  python -m llm_toml_wizard.cli dialog demo --spec toml --mock --stub
  python -m llm_toml_wizard.cli dialog run --spec toml --mock --stub
  python -m llm_toml_wizard.cli dialog repl --spec toml --mock --stub
"""

from __future__ import annotations

import argparse
import sys

from llm_toml_wizard.cli.dialog_cmds import cmd_catalog, cmd_dialog_demo, cmd_dialog_repl, cmd_dialog_run



def _build_parser() -> argparse.ArgumentParser:
    """
    函数名: _build_parser
    作用: 组装 dialog 子命令树
    输入: 无
    输出:
        argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="python -m llm_toml_wizard.cli",
        description="TOML wizard / dialog runtime (main session, intake, sub-agents).",
    )
    root = parser.add_subparsers(dest="group", required=True)
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
    run.add_argument("--mock", action="store_true", help="ScriptedBackend, no LM Studio")
    run.add_argument("--demo", action="store_true", help="prefill DEMO_FACTS / TOML_DEMO_AUTO")
    run.add_argument("--non-interactive", action="store_true")
    run.add_argument("--force-thinking-retry", action="store_true")
    run.add_argument("--release", action="store_true", help="unload LM Studio model after live run")
    run.add_argument("--live", action="store_true")
    run.add_argument("--write-toml", action="store_true", help="persist templates/{id}/{id}.toml (toml spec only)")
    run.set_defaults(func=cmd_dialog_run)
    demo = dcmd.add_parser("demo", help="non-interactive dialog; default --mock --stub")
    demo.add_argument("--spec", default="briefing", help="briefing (default) or toml")
    demo.add_argument("--live", action="store_true", help="use LM Studio instead of mock")
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
    repl.add_argument("--live", action="store_true", help="use LM Studio instead of mock+stub")
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
