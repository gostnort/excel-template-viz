"""run_judgment: single-shot generate + parse + normalize (docs §3.6.2).

No `thinking`, no `ContextStore`, no `BrowserSession` involved here.
"""

from __future__ import annotations

from llm_gemma4.backends.base import JudgmentToolSpec, LlmBackend
from llm_gemma4.runtime.judgment import (
    DEFAULT_AFFIRMATIVE,
    DEFAULT_NEGATIVE,
    JudgmentDraft,
    JudgmentResult,
    JudgmentSpec,
    normalize_judgment,
    parse_judgment,
)


def run_judgment(backend: LlmBackend, spec: JudgmentSpec) -> JudgmentResult:
    messages = [{"role": "system", "content": spec.system}, {"role": "user", "content": spec.user}]
    judgment_tool = None
    if spec.use_constrained_decoding:
        judgment_tool = JudgmentToolSpec(
            name="report_verdict",
            description="Call this tool exactly once with your final verdict and a short reason.",
            verdict_key=spec.verdict_key,
            reason_key=spec.reason_key,
        )
    result = backend.generate(messages, thinking=False, max_tokens=spec.max_tokens, temperature=0.0, judgment_tool=judgment_tool)
    if result.tool_call_arguments is not None:
        # Structured tool-call path landed cleanly; values may still be
        # stringified booleans (§3.6.1a), normalize_judgment handles that.
        draft = JudgmentDraft(raw_text=str(result.raw), payload=dict(result.tool_call_arguments), parse_error=None)
    else:
        # Either use_constrained_decoding=False, or the tool call got
        # truncated before it parsed (§3.6.1a) — fall back to text parsing.
        draft = parse_judgment(result.text, verdict_key=spec.verdict_key)
    return normalize_judgment(
        draft,
        verdict_key=spec.verdict_key,
        reason_key=spec.reason_key,
        affirmative=DEFAULT_AFFIRMATIVE,
        negative=DEFAULT_NEGATIVE,
        default_on_ambiguous="unknown",
    )
