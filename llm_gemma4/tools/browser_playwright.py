"""Playwright Edge driver for NiceGUI (embed_gemma4.md §7)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llm_gemma4.agent.context_config import ContextConfig
from llm_gemma4.models_catalog import repo_root
from llm_gemma4.tools.browser_state import PageState, build_page_state, format_page_state


DEFAULT_BASE_URL = "http://127.0.0.1:8738/"
SHOT_DIR = repo_root() / "test" / "llm_gemma4" / "_shots"


class BrowserPlaywrightError(Exception):
    """Playwright browser failure."""


class NiceGuiBrowser:
    """Sync Playwright session against local NiceGUI.

    WizardRunner keeps one instance from GOOGLE_PROBE through COLLECT_PASTE and
    only calls stop() when the wizard reaches DONE (or the user closes the
    wizard dialog). Do not use as a short ``with`` block during WAIT_USER steps.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        headless: bool = True,
        channel: str = "msedge",
        context_config: ContextConfig | None = None,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.headless = headless
        self.channel = channel
        self.config = context_config or ContextConfig()
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        SHOT_DIR.mkdir(parents=True, exist_ok=True)


    def __enter__(self) -> "NiceGuiBrowser":
        self.start()
        return self


    def __exit__(self, *args: object) -> None:
        self.stop()


    def start(self) -> None:
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserPlaywrightError(
                "playwright not installed: pip install playwright && playwright install"
            ) from exc
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                channel=self.channel,
                headless=self.headless,
            )
        except Exception as exc:
            self.stop()
            raise BrowserPlaywrightError(f"launch failed: {exc}") from exc
        self._context = self._browser.new_context(viewport={"width": 1400, "height": 900})
        self._page = self._context.new_page()
        self._page.goto(self.base_url, wait_until="networkidle", timeout=60000)


    def stop(self) -> None:
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None


    @property
    def page(self) -> Any:
        if self._page is None:
            raise BrowserPlaywrightError("browser not started")
        return self._page


    def click_tab(self, tab_label: str) -> bool:
        loc = self.page.get_by_text(tab_label, exact=True)
        if loc.count() == 0:
            return False
        loc.first.click()
        self.page.wait_for_timeout(600)
        return True


    def snapshot(
        self,
        *,
        template_id: str | None = None,
        active_tab: str | None = None,
        screenshot: bool = False,
    ) -> PageState:
        shot_path = None
        if screenshot:
            shot_path = str(SHOT_DIR / "wizard_snapshot.png")
            self.page.screenshot(path=shot_path, full_page=True)
        return build_page_state(
            self.page,
            template_id=template_id,
            active_tab=active_tab,
            config=self.config,
            screenshot_path=shot_path,
        )


    def snapshot_text(self, **kwargs: object) -> str:
        state = self.snapshot(**kwargs)
        return format_page_state(state)


    def probe_google_tab(self, template_id: str | None = None) -> PageState:
        self.click_tab("Google 连接")
        return self.snapshot(template_id=template_id, active_tab="Google 连接", screenshot=True)


    def collect_input_tab(self, template_id: str | None = None) -> PageState:
        self.click_tab("输入")
        return self.snapshot(template_id=template_id, active_tab="输入", screenshot=True)


    def click_text(self, text: str) -> bool:
        loc = self.page.get_by_text(text, exact=False)
        if loc.count() == 0:
            return False
        loc.first.click()
        self.page.wait_for_timeout(400)
        return True
