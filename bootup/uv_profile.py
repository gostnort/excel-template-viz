"""从 bootup/.install_profile 解析 uv --extra（ocr / ocr-gpu），供 sync / run 共用。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


BOOTUP = Path(__file__).resolve().parent
PROFILE_PATH = BOOTUP / ".install_profile"
ROOT = BOOTUP.parent



def read_profile() -> dict[str, str]:
    """
    函数名: read_profile
    作用: 读取 bootup/.install_profile（key=value）；兼容仓库根目录旧文件。
    输入: 无。
    输出:
        dict[str, str]: 配置项；文件不存在则为空 dict。
    """
    legacy = ROOT / ".install_profile"
    if legacy.is_file() and not PROFILE_PATH.is_file():
        PROFILE_PATH.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
        legacy.unlink()
    if not PROFILE_PATH.is_file():
        return {}
    out: dict[str, str] = {}
    for line in PROFILE_PATH.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, val = text.partition("=")
        out[key.strip()] = val.strip()
    return out



def extra_name(*, ocr: bool | None = None, accelerator: str | None = None) -> str | None:
    """
    函数名: extra_name
    作用: 按 profile（或显式参数）返回应启用的 extra 名。ocr 与 ocr-gpu 互斥。
    输入:
        ocr (bool|None): True 启用 OCR extra；None 则读 profile（缺省视为启用）。
        accelerator (str|None): cpu|gpu；None 则读 profile。
    输出:
        str|None: "ocr" / "ocr-gpu"；跳过 OCR 时为 None。
    """
    profile = read_profile()
    if ocr is None:
        raw = str(profile.get("ocr") or "true").strip().lower()
        ocr = raw not in ("false", "0", "no")
    if not ocr:
        return None
    acc = (accelerator or profile.get("accelerator") or "cpu").strip().lower()
    if acc in ("gpu", "cuda"):
        return "ocr-gpu"
    return "ocr"



def extra_args(*, ocr: bool | None = None, accelerator: str | None = None) -> list[str]:
    """
    函数名: extra_args
    作用: 返回可直接拼进 uv sync / uv run 的 ["--extra", name]。
    输入:
        ocr (bool|None): 同 extra_name。
        accelerator (str|None): 同 extra_name。
    输出:
        list[str]: 空列表或 ["--extra", "ocr"|"ocr-gpu"]。
    """
    name = extra_name(ocr=ocr, accelerator=accelerator)
    if not name:
        return []
    return ["--extra", name]



def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: 打印 extra 名或 --extra 参数，供 PowerShell / bash 包装 uv run。
    输入:
        argv (list[str]|None): CLI 参数。
    输出:
        int: 退出码。
    """
    parser = argparse.ArgumentParser(description="Print uv extra flags from .install_profile")
    parser.add_argument("--flags", action="store_true", help="Print `--extra NAME` instead of NAME")
    args = parser.parse_args(argv)
    name = extra_name()
    if not name:
        return 0
    if args.flags:
        sys.stdout.write(f"--extra {name}\n")
    else:
        sys.stdout.write(f"{name}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
