"""Environment checks for wizard PRECHECK (no LLM)."""

from __future__ import annotations

import shutil
import subprocess
import urllib.request
from dataclasses import dataclass, field


@dataclass
class PrecheckReport:
    ok: bool
    node: str | None = None
    playwright: bool = False
    nicegui_url: str | None = None
    issues: list[str] = field(default_factory=list)


def run_precheck(nicegui_url: str = "http://127.0.0.1:8738/") -> PrecheckReport:
    issues: list[str] = []
    node_ver: str | None = None
    node_bin = shutil.which("node")
    if not node_bin:
        issues.append("Node.js not found (optional for some flows)")
    else:
        try:
            completed = subprocess.run(
                [node_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                node_ver = completed.stdout.strip()
            else:
                issues.append("node --version failed")
        except OSError as exc:
            issues.append(f"node probe error: {exc}")
    playwright_ok = False
    try:
        import playwright  # noqa: F401
        playwright_ok = True
    except ImportError:
        issues.append("playwright not installed: pip install playwright && playwright install")
    nicegui_status: str | None = None
    try:
        request = urllib.request.Request(nicegui_url, method="HEAD")
        with urllib.request.urlopen(request, timeout=3) as response:
            nicegui_status = str(response.status)
    except Exception:
        issues.append(
            f"NiceGUI not reachable at {nicegui_url} (start run.bat for GOOGLE_PROBE)"
        )
    hard_fail = any(
        text.startswith("playwright not installed") for text in issues
    )
    return PrecheckReport(
        ok=not hard_fail,
        node=node_ver,
        playwright=playwright_ok,
        nicegui_url=nicegui_status,
        issues=issues,
    )
