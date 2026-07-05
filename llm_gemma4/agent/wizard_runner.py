"""CLI entry for wizard mode."""

from __future__ import annotations

from pathlib import Path

from llm_gemma4.backends.base import LlmBackend
from llm_gemma4.backends.factory import create_backend
from llm_gemma4.wizard.runner import WizardCallbacks, WizardRunner


def create_wizard_runner(
    template_id: str,
    *,
    profile: str | None = None,
    template_xlsx: Path | None = None,
    no_llm: bool = True,
    skip_google: bool = False,
    resume: bool = False,
    use_browser: bool = True,
    headless: bool = True,
    base_url: str = "http://127.0.0.1:8738/",
    backend: LlmBackend | None = None,
    callbacks: WizardCallbacks | None = None,
) -> WizardRunner:
    """Build ``WizardRunner`` for CLI or in-app UI."""
    prof = profile or "cpu"
    return WizardRunner(
        template_id,
        template_xlsx=template_xlsx,
        profile=prof,
        no_llm=no_llm,
        skip_google=skip_google,
        resume=resume,
        use_browser=use_browser,
        headless=headless,
        base_url=base_url,
        backend=backend,
        callbacks=callbacks,
    )


def run_wizard(
    template_id: str,
    *,
    profile: str | None = None,
    template_xlsx: Path | None = None,
    no_llm: bool = True,
    skip_google: bool = False,
    resume: bool = False,
    use_browser: bool = True,
    headless: bool = True,
    base_url: str = "http://127.0.0.1:8738/",
) -> int:
    """Run wizard state machine; optional backend load when LLM enabled."""
    prof = profile or "cpu"
    backend = None
    if not no_llm:
        backend = create_backend(prof)
        print(backend.health_check())
    runner = create_wizard_runner(
        template_id,
        profile=prof,
        template_xlsx=template_xlsx,
        no_llm=no_llm,
        skip_google=skip_google,
        resume=resume,
        use_browser=use_browser,
        headless=headless,
        base_url=base_url,
        backend=backend,
    )
    result = runner.run()
    for line in result.messages:
        print(line)
    print(f"[wizard] phase={result.state.phase} template={template_id}")
    print(f"[wizard] context_tokens~={runner.context.estimate_tokens()}")
    return 0
