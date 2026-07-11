"""parse_judgment / normalize_judgment: fuzzy LLM output -> stable three-state
JudgmentResult (docs/embed_gemma4.md §3.6). No business-domain field names here;
callers (e.g. paddle_ocr/runtime/semantic_gate.py) map JudgmentResult to bools.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal


DEFAULT_AFFIRMATIVE = frozenset({"true", "yes", "是", "有", "problem", "1", "affirmative"})
DEFAULT_NEGATIVE = frozenset({"false", "no", "否", "无", "ok", "0", "negative"})

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)



@dataclass(frozen=True)
class JudgmentSpec:
    """Caller-supplied judgment request; the base holds no domain wording."""
    system: str
    user: str
    # Alphabetical key order matters for the constrained-decoding path
    # (§3.6.1a): verdict_key must sort before reason_key or truncation can
    # drop the verdict field before the model reaches it.
    verdict_key: str = "has_problem"
    reason_key: str = "reason"
    max_tokens: int = 256
    use_constrained_decoding: bool = True



@dataclass(frozen=True)
class JudgmentDraft:
    """Parsed-but-not-yet-normalized result; may still be ambiguous."""
    raw_text: str
    payload: dict | None
    parse_error: str | None



@dataclass(frozen=True)
class JudgmentResult:
    """Stable base-level result; application layer maps this to bool/branch."""
    verdict: Literal["affirmative", "negative", "unknown"]
    reason: str
    raw_text: str
    normalized_from: Literal["json", "keyword", "default"]


def parse_judgment(text: str, *, verdict_key: str) -> JudgmentDraft:
    """Extract one JSON object from `text`, tolerant of markdown fences / prose."""
    stripped = text.strip()
    fenced = _FENCED_JSON_RE.search(stripped)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        bare = _BARE_JSON_RE.search(stripped)
        candidate = bare.group(0) if bare else None
    if candidate is None:
        return JudgmentDraft(raw_text=text, payload=None, parse_error="no JSON object found")
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        return JudgmentDraft(raw_text=text, payload=None, parse_error=str(exc))
    if not isinstance(payload, dict):
        return JudgmentDraft(raw_text=text, payload=None, parse_error="parsed JSON is not an object")
    if verdict_key not in payload:
        return JudgmentDraft(raw_text=text, payload=payload, parse_error=f"missing key {verdict_key!r}")
    return JudgmentDraft(raw_text=text, payload=payload, parse_error=None)


def normalize_judgment(
    draft: JudgmentDraft,
    *,
    verdict_key: str,
    reason_key: str = "reason",
    affirmative: frozenset[str] = DEFAULT_AFFIRMATIVE,
    negative: frozenset[str] = DEFAULT_NEGATIVE,
    default_on_ambiguous: Literal["affirmative", "negative", "unknown"] = "unknown",
) -> JudgmentResult:
    """Map booleans / stringified booleans / yes-no synonyms to the 3-state verdict.

    Constrained tool-call output still comes back stringified (e.g. `"true"`,
    not Python `True`) per §3.6.1a, so the synonym check always runs even on
    the "structured" path.
    """
    if draft.payload is None or verdict_key not in draft.payload:
        return JudgmentResult(verdict="unknown", reason="", raw_text=draft.raw_text, normalized_from="default")
    reason = str(draft.payload.get(reason_key, ""))
    raw_value = draft.payload[verdict_key]
    token = str(raw_value).strip().lower()
    is_affirmative = raw_value is True or token in affirmative
    is_negative = raw_value is False or token in negative
    if is_affirmative and not is_negative:
        return JudgmentResult(verdict="affirmative", reason=reason, raw_text=draft.raw_text, normalized_from="json")
    if is_negative and not is_affirmative:
        return JudgmentResult(verdict="negative", reason=reason, raw_text=draft.raw_text, normalized_from="json")
    return JudgmentResult(verdict=default_on_ambiguous, reason=reason, raw_text=draft.raw_text, normalized_from="default")
