"""CLI: python -m llm_gemma4 probe | download | smoke."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llm_gemma4.agent.loop import run_chat
from llm_gemma4.agent.wizard_runner import run_wizard
from llm_gemma4.hf_download import DownloadError, download_gguf, download_openvino_int4
from llm_gemma4.runtime.hardware_probe import detect, format_report, report_to_json


def _cmd_probe(args: argparse.Namespace) -> int:
    report = detect()
    if args.json:
        print(report_to_json(report))
    else:
        print(format_report(report))
    return 0


def _cmd_download(args: argparse.Namespace) -> int:
    profile = args.profile
    try:
        if profile in {"cpu", "cuda", "all"}:
            path = download_gguf(force=args.force)
            print(f"GGUF: {path}")
        if profile in {"openvino", "all"}:
            path = download_openvino_int4(force=args.force)
            print(f"OpenVINO: {path}")
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_smoke(args: argparse.Namespace) -> int:
    profile = args.profile
    prompt = args.prompt
    if profile in {"cpu", "cuda"}:
        from llm_gemma4.backends.llamacpp.backend import smoke_generate
        from llm_gemma4.hf_download import gguf_present
        if not gguf_present():
            print("SKIP: GGUF missing. Run: python -m llm_gemma4 download --profile cpu")
            return 0
        try:
            smoke_generate(profile, prompt)
        except Exception as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        return 0
    if profile == "openvino":
        from llm_gemma4.backends.openvino.backend import smoke_generate as ov_smoke
        from llm_gemma4.hf_download import openvino_present
        if not openvino_present():
            print("SKIP: OpenVINO IR missing.")
            return 0
        try:
            ov_smoke(prompt)
        except ImportError as exc:
            print(f"SKIP: {exc}")
            return 0
        except Exception as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        return 0
    print(f"Unknown profile: {profile}", file=sys.stderr)
    return 2


def _cmd_wizard(args: argparse.Namespace) -> int:
    xlsx = Path(args.template_xlsx).resolve() if args.template_xlsx else None
    return run_wizard(
        args.template,
        profile=args.profile,
        template_xlsx=xlsx,
        no_llm=not args.llm,
        skip_google=args.skip_google,
        resume=args.resume,
        use_browser=not args.no_browser,
        headless=not args.headed,
        base_url=args.base_url,
    )


def _cmd_chat(args: argparse.Namespace) -> int:
    if not args.task and args.interactive:
        print("Enter task (empty line to cancel):")
        task = input("> ").strip()
        if not task:
            print("Cancelled.")
            return 0
    else:
        task = args.task or ""
    if not task:
        print("ERROR: --task required for non-interactive chat", file=sys.stderr)
        return 2
    xlsx = Path(args.template_xlsx).resolve() if args.template_xlsx else None
    return run_chat(
        task,
        profile=args.profile,
        template_id=args.template,
        template_xlsx=xlsx,
        interactive_profile=not args.no_menu,
        use_browser=not args.no_browser,
        headless=not args.headed,
        base_url=args.base_url,
    )


def _cmd_mcp(_args: argparse.Namespace) -> int:
    from llm_gemma4.mcp.server import main as mcp_main
    return mcp_main()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm_gemma4",
        description="Gemma 4 E4B local agent platform",
    )
    sub = parser.add_subparsers(dest="command")
    probe = sub.add_parser("probe", help="Hardware detection and profile menu")
    probe.add_argument("--json", action="store_true")
    probe.set_defaults(func=_cmd_probe)
    download = sub.add_parser("download", help="Download HF weights (§4.0)")
    download.add_argument(
        "--profile",
        choices=["cpu", "cuda", "openvino", "all"],
        default="all",
        help="cpu/cuda download GGUF; openvino downloads OV INT4",
    )
    download.add_argument("--force", action="store_true")
    download.set_defaults(func=_cmd_download)
    smoke = sub.add_parser("smoke", help="One-shot generate smoke test")
    smoke.add_argument("--profile", choices=["cpu", "cuda", "openvino"], required=True)
    smoke.add_argument("--prompt", default="Reply with one word: OK")
    smoke.set_defaults(func=_cmd_smoke)
    wizard = sub.add_parser("wizard", help="TOML first-config wizard")
    wizard.add_argument("--template", required=True, help="template_id e.g. ginger_lots")
    wizard.add_argument("--profile", choices=["cpu", "cuda", "openvino"], default=None)
    wizard.add_argument("--template-xlsx", default=None, help="override xlsx path")
    wizard.add_argument("--llm", action="store_true", help="enable LLM phases (W4+)")
    wizard.add_argument("--skip-google", action="store_true")
    wizard.add_argument("--no-browser", action="store_true", help="skip Playwright phases")
    wizard.add_argument("--headed", action="store_true", help="show Edge window")
    wizard.add_argument("--base-url", default="http://127.0.0.1:8738/")
    wizard.add_argument("--resume", action="store_true")
    wizard.set_defaults(func=_cmd_wizard)
    chat = sub.add_parser("chat", help="Short ReAct chat (max 8 steps)")
    chat.add_argument("--task", default=None, help="Single-shot task text")
    chat.add_argument("--profile", choices=["cpu", "cuda", "openvino"], default=None)
    chat.add_argument("--template", default=None, help="template_id for read_toml tools")
    chat.add_argument("--template-xlsx", default=None)
    chat.add_argument("--no-menu", action="store_true", help="fail if profile not passed")
    chat.add_argument("--no-browser", action="store_true")
    chat.add_argument("--headed", action="store_true")
    chat.add_argument("--base-url", default="http://127.0.0.1:8738/")
    chat.add_argument("--interactive", action="store_true", help="prompt for task on stdin")
    chat.set_defaults(func=_cmd_chat)
    mcp_cmd = sub.add_parser("mcp", help="Start MCP stdio server (narrow tools)")
    mcp_cmd.set_defaults(func=_cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
