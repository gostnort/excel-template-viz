"""MCP stdio server — narrow tool subset (embed_gemma4.md Phase 5)."""

from __future__ import annotations

import json
import sys
from typing import Any

from llm_gemma4.tools import file_config
from llm_gemma4.wizard import toml_io
from llm_gemma4.wizard.tools import dispatch as wizard_dispatch


_BROWSER = None
_BASE_URL = "http://127.0.0.1:8738/"


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _browser_session():
    """Lazy Playwright session for MCP tool calls."""
    global _BROWSER
    if _BROWSER is not None:
        return _BROWSER
    from llm_gemma4.tools.browser_playwright import NiceGuiBrowser
    browser = NiceGuiBrowser(base_url=_BASE_URL, headless=True)
    browser.start()
    _BROWSER = browser
    return _BROWSER


def browser_snapshot(template_id: str = "") -> str:
    """Capture NiceGUI page state (Playwright Edge)."""
    try:
        browser = _browser_session()
    except Exception as exc:
        return _json_text({"ok": False, "error": str(exc)})
    out = wizard_dispatch(
        {"action": "browser_snapshot"},
        template_id=template_id,
        browser=browser,
    )
    return _json_text(out)


def browser_click(text: str, template_id: str = "") -> str:
    """Click visible text on the NiceGUI page."""
    try:
        browser = _browser_session()
    except Exception as exc:
        return _json_text({"ok": False, "error": str(exc)})
    out = wizard_dispatch(
        {"action": "browser_click", "text": text},
        template_id=template_id,
        browser=browser,
    )
    return _json_text(out)


def read_toml_digest(template_id: str) -> str:
    """Return compact TOML digest (never full file text)."""
    out = toml_io.read_toml_digest(template_id)
    return _json_text(out)


def read_file(path: str, max_chars: int = 4000) -> str:
    """Read whitelisted repo file (truncated)."""
    return _json_text(file_config.read_file(path, max_chars=max_chars))


def list_files(path: str = "docs") -> str:
    """List whitelisted directory entries."""
    return _json_text(file_config.list_files(path))


def test_regex(pattern: str, sample: str, group: int | None = None) -> str:
    """Try regex against sample text."""
    out = toml_io.test_regex(pattern, sample, group)
    return _json_text(out)


def build_server():
    """Create FastMCP server with narrow tools."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        try:
            from fastmcp import FastMCP
        except ImportError as exc:
            raise ImportError(
                "MCP server requires: pip install mcp  (or fastmcp)"
            ) from exc
    mcp = FastMCP("llm_gemma4")
    mcp.tool()(browser_snapshot)
    mcp.tool()(browser_click)
    mcp.tool()(read_toml_digest)
    mcp.tool()(read_file)
    mcp.tool()(list_files)
    mcp.tool()(test_regex)
    return mcp


def main() -> int:
    try:
        mcp = build_server()
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    mcp.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
