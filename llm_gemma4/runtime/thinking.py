"""Split thought/answer out of a raw `send_message` response (docs §3.3).

No tag regex needed: when the conversation was opened with
`extra_context={"enable_thinking": True}`, litert_lm already returns the
reasoning trace under a top-level `channels["thought"]` key, separate from
`content` (verified against real `gemma-4-E4B-it.litertlm` on 2026-07-11).
"""

from __future__ import annotations

from typing import Any, Mapping


def content_text(response: Mapping[str, Any]) -> str:
    parts = response.get("content") or []
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def split_thought_answer(response: Mapping[str, Any]) -> tuple[str | None, str]:
    thought = (response.get("channels") or {}).get("thought")
    return thought, content_text(response)
