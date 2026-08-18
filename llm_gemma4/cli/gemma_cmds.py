"""Gemma4 底座能力展示：一次性问答、视觉、判定、预热。"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from llm_gemma4 import config
from llm_gemma4.runtime.hardware_probe import planned_backend_hint
from llm_gemma4.runtime.judgment import JudgmentSpec


def cmd_ask(args: Namespace) -> int:
    """
    函数名: cmd_ask
    作用: 无状态 ConversationOnce
    输入:
        args (Namespace): text / system / thinking
    输出:
        int: 进程退出码
    """
    from llm_gemma4.__main__ import ConversationOnce, EndGemma
    try:
        text = ConversationOnce(
            args.text,
            system=args.system,
            thinking=bool(args.thinking),
        )
        print(text)
        return 0
    finally:
        if args.release:
            EndGemma()


def cmd_vision(args: Namespace) -> int:
    """
    函数名: cmd_vision
    作用: Pic2Str 读图
    输入:
        args (Namespace): image / prompt / system
    输出:
        int: 退出码
    """
    from llm_gemma4.__main__ import EndGemma, Pic2Str
    path = Path(args.image)
    if not path.is_file():
        print(f"image not found: {path}")
        return 1
    try:
        print(Pic2Str(path, args.prompt, system=args.system))
        return 0
    finally:
        if args.release:
            EndGemma()


def cmd_health(args: Namespace) -> int:
    """
    函数名: cmd_health
    作用: 打印模型路径、profile 提示、health_check（不强制 warm）
    输入:
        args (Namespace): 未使用
    输出:
        int: 退出码
    """
    profile = config.resolve_profile()
    print(f"profile={profile}")
    print(f"planned_backend={planned_backend_hint(profile)}")
    print(f"model_path={config.model_path()}")
    print(f"model_exists={config.model_exists()}")
    from llm_gemma4.backends.factory import create_backend
    backend = create_backend()
    report = backend.health_check()
    print(
        f"health ok={report.ok} litert={report.litert_backend} "
        f"message={report.message}"
    )
    return 0 if report.ok else 2


def cmd_start(args: Namespace) -> int:
    """
    函数名: cmd_start
    作用: StartGemma 预热 Engine
    输入:
        args (Namespace): 未使用
    输出:
        int: 退出码
    """
    from llm_gemma4.__main__ import StartGemma
    StartGemma()
    print("StartGemma: engine warm")
    return 0


def cmd_stop(args: Namespace) -> int:
    """
    函数名: cmd_stop
    作用: EndGemma 释放显存
    输入:
        args (Namespace): 未使用
    输出:
        int: 退出码
    """
    from llm_gemma4.__main__ import EndGemma
    EndGemma()
    print("EndGemma: released")
    return 0


def cmd_judge(args: Namespace) -> int:
    """
    函数名: cmd_judge
    作用: run_judgment 三态判定
    输入:
        args (Namespace): system / user / verdict_key / reason_key
    输出:
        int: 退出码
    """
    from llm_gemma4.__main__ import EndGemma, _get_backend
    from llm_gemma4.runtime.judge import run_judgment
    spec = JudgmentSpec(
        system=args.system,
        user=args.user,
        verdict_key=args.verdict_key,
        reason_key=args.reason_key,
    )
    try:
        result = run_judgment(_get_backend(), spec)
        print(f"verdict={result.verdict}")
        print(f"normalized_from={result.normalized_from}")
        print(f"reason={result.reason}")
        print(f"raw={result.raw_text[:500]}")
        return 0
    finally:
        if args.release:
            EndGemma()
