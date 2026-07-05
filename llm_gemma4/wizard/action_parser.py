"""Parse single action JSON from E4B output."""

from __future__ import annotations

import json
import re
from typing import Any


class ActionParseError(Exception):
    """Failed to parse wizard action JSON."""


_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def parse_action(text: str) -> dict[str, Any]:
    """Extract one JSON object with an 'action' key from model text."""
    cleaned = (text or "").strip()
    if not cleaned:
        raise ActionParseError("empty model output")
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "action" in data:
            return data
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(cleaned)
    if not match:
        raise ActionParseError("no JSON object found")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or "action" not in data:
        raise ActionParseError("JSON missing 'action' key")
    return data
