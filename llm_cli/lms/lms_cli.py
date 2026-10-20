"""调用本地官方 `lms` CLI 工具的轻量封装。"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any


def is_lms_available() -> bool:
    """检查系统 PATH 中是否有 `lms` 命令行工具"""
    return shutil.which("lms") is not None


def run_lms_cmd(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    """执行 lms 命令并返回结果"""
    cmd = ["lms"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def lms_status() -> dict[str, Any]:
    """执行 `lms status` 获取服务状态"""
    if not is_lms_available():
        return {"available": False, "server_on": False, "raw": "lms not in PATH"}
    try:
        proc = run_lms_cmd(["status"], timeout=5.0)
        output = proc.stdout + proc.stderr
        server_on = "Server:  ON" in output or "Status: ON" in output or "running" in output.lower()
        return {
            "available": True,
            "server_on": server_on,
            "raw": output.strip(),
        }
    except Exception as exc:
        return {"available": True, "server_on": False, "error": str(exc)}


def lms_ps() -> list[str]:
    """执行 `lms ps` 列出当前在显存/内存中加载的模型"""
    if not is_lms_available():
        return []
    try:
        proc = run_lms_cmd(["ps"], timeout=8.0)
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        models: list[str] = []
        for line in lines:
            if line.startswith("-") or "IDENTIFIER" in line.upper() or "SIZE" in line.upper():
                continue
            parts = line.split()
            if parts:
                models.append(parts[0])
        return models
    except Exception:
        return []


def lms_load(model_key: str) -> bool:
    """执行 `lms load <model_key>`"""
    if not is_lms_available() or not model_key:
        return False
    try:
        proc = run_lms_cmd(["load", model_key], timeout=60.0)
        return proc.returncode == 0
    except Exception:
        return False


def lms_unload(model_key: str) -> bool:
    """执行 `lms unload <model_key>`"""
    if not is_lms_available() or not model_key:
        return False
    try:
        proc = run_lms_cmd(["unload", model_key], timeout=30.0)
        return proc.returncode == 0
    except Exception:
        return False


def lms_start_server() -> bool:
    """执行 `lms server start`"""
    if not is_lms_available():
        return False
    try:
        proc = run_lms_cmd(["server", "start"], timeout=15.0)
        return proc.returncode == 0
    except Exception:
        return False
