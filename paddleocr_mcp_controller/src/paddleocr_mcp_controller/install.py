"""paddleocr_mcp_controller installer: ensure paddleocr-mcp[local-cpu] is installed
and PP-OCRv6 / PP-StructureV3 weights are downloaded into ./models.

Usage:
    python -m paddleocr_mcp_controller.install
    python -m paddleocr_mcp_controller.install --no-warm    # skip warmup
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from paddleocr_mcp_controller import config
from paddleocr_mcp_controller.models_catalog import (
    prune_vl_official_models,
    required_models_present,
)


def _pip(args: list[str]) -> int:
    """
    函数名: _pip
    作用: prefer uv pip bound to current interpreter; fall back to python -m pip.
    输入:
        args (list[str]): pip subcommand args (install / uninstall ...).
    输出:
        int: process exit code.
    """
    uv = shutil.which("uv")
    if uv and args and args[0] in ("install", "uninstall"):
        cmd = [uv, "pip", args[0], "--python", sys.executable] + args[1:]
    elif uv:
        cmd = [uv, "pip"] + args
    else:
        cmd = [sys.executable, "-m", "pip"] + args
    print(f">>> {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd)


def _paddleocr_mcp_installed() -> bool:
    """True if paddleocr-mcp is importable (metadata check)."""
    try:
        import importlib.metadata as md
        md.version("paddleocr-mcp")
        return True
    except Exception:
        return False


def install_paddleocr_mcp() -> int:
    """
    函数名: install_paddleocr_mcp
    作用: install paddleocr-mcp[local-cpu] (CPU-only extra) via pip/uv.
    输入: none.
    输出:
        int: 0 on success, non-zero on failure.
    """
    if _paddleocr_mcp_installed():
        print("paddleocr-mcp 已安装，跳过库安装。", flush=True)
        return 0
    print("安装 paddleocr-mcp[local-cpu] ...", flush=True)
    args = ["install", "paddleocr-mcp[local-cpu]"]
    if not shutil.which("uv"):
        args.append("--default-timeout=300")
    return _pip(args)


def _append_log(line: str) -> None:
    """append one line to INSTALL_LOG."""
    try:
        path = config.INSTALL_LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def warm_models() -> tuple[bool, str]:
    """
    函数名: warm_models
    作用: start paddleocr-mcp and run a dummy OCR/Structure to download weights;
        prune VL residuals; check required_models_present.
    输入: none.
    输出:
        tuple[bool, str]: (ready, message).
    """
    config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
    config.ensure_pdx_cache_env()
    prune_vl_official_models()
    last_err: Exception | None = None
    import numpy as np
    from paddleocr_mcp_controller.mcp_runtime import (
        call_ocr_mcp,
        call_structure_mcp,
        start_structure_mcp,
        stop_mcp,
    )
    for attempt in range(2):
        try:
            sample = config.SAMPLE_IMAGE
            if sample.is_file():
                # 中文注释: 用样图跑 OCR；不需要 Structure
                strip = np.zeros((84, 1040, 3), dtype=np.uint8)
                call_ocr_mcp(strip)
            else:
                # 中文注释: 无样图，用空白图跑一次 OCR + Structure 触发权重下载
                strip = np.zeros((84, 1040, 3), dtype=np.uint8)
                call_ocr_mcp(strip)
                if start_structure_mcp():
                    page = np.zeros((960, 640, 3), dtype=np.uint8)
                    call_structure_mcp(page, mode="fast")
            prune_vl_official_models()
            if required_models_present():
                ok_msg = f"required models ready under {config.MODELS_DIR}"
                _append_log(ok_msg)
                stop_mcp()
                return True, ok_msg
            last_err = RuntimeError("warm predict not ok")
        except Exception as exc:
            last_err = exc
            _append_log(f"attempt {attempt + 1} failed: {exc}")
        finally:
            stop_mcp()
    msg = f"download failed after retry: {last_err}"
    _append_log(msg)
    return False, config.MSG_MODEL_MISSING


def main(argv: list[str] | None = None) -> int:
    """
    函数名: main
    作用: install paddleocr-mcp[local-cpu], then warm/dl models unless --no-warm.
    输入:
        argv (list[str] | None): args; None uses sys.argv[1:].
    输出:
        int: 0 success, 1 failure.
    """
    parser = argparse.ArgumentParser(prog="python -m paddleocr_mcp_controller.install")
    parser.add_argument("--no-warm", action="store_true", help="skip model warmup/download")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    rc = install_paddleocr_mcp()
    if rc != 0:
        print("paddleocr-mcp 安装失败。", flush=True)
        return rc
    if args.no_warm:
        print("已跳过模型预热。请稍后手动跑一次 OCR 触发下载。", flush=True)
        return 0
    ok, message = warm_models()
    print(message, flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
