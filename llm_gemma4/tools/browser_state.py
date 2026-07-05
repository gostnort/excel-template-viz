"""PageState builder for Playwright observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm_gemma4.agent.context_config import ContextConfig


@dataclass
class PageState:
    url: str
    title: str
    active_tab: str | None
    template_id: str | None
    form_fields: list[dict[str, str]] = field(default_factory=list)
    session_table_summary: str = ""
    interactive_refs: list[dict[str, str]] = field(default_factory=list)
    dom_excerpt: str = ""
    screenshot_path: str | None = None
    google_connected_hint: str | None = None
    paste_ghost_value: str = ""


def truncate_middle(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max(1, max_chars // 2)
    return f"{text[:half]}\n…[{len(text) - max_chars} chars omitted]…\n{text[-half:]}"


def infer_google_connected(body_text: str) -> str:
    """Heuristic from Google tab visible text."""
    if "尚未连接或无数据" in body_text:
        return "disconnected"
    if "无可见行" in body_text:
        return "connected_no_visible_rows"
    if "主 ID 工作表" in body_text and "授权与连接" in body_text:
        if "—" in body_text and "尚未连接" not in body_text:
            return "maybe_connected"
    return "unknown"


def extract_form_fields(page: Any) -> list[dict[str, str]]:
    """Read NiceGUI input tab field-grid labels and values."""
    fields: list[dict[str, str]] = []
    cells = page.locator(".field-cell")
    count = cells.count()
    for index in range(min(count, 60)):
        cell = cells.nth(index)
        label_loc = cell.locator(".field-label")
        if label_loc.count() == 0:
            continue
        label = label_loc.first.inner_text(timeout=2000).strip()
        inp = cell.locator("input").first
        value = ""
        if inp.count() > 0:
            try:
                value = inp.input_value(timeout=2000)
            except Exception:
                value = ""
        if label:
            fields.append({"label": label, "value": value})
    return fields


def extract_paste_ghost(page: Any) -> str:
    loc = page.locator("input.ghost-input").first
    if loc.count() == 0:
        return ""
    try:
        return loc.input_value(timeout=2000)
    except Exception:
        return ""


def build_page_state(
    page: Any,
    *,
    template_id: str | None = None,
    active_tab: str | None = None,
    config: ContextConfig | None = None,
    screenshot_path: str | None = None,
) -> PageState:
    cfg = config or ContextConfig()
    body_text = page.locator("body").inner_text(timeout=10000)
    dom_excerpt = truncate_middle(body_text.replace("\r", ""), cfg.dom_excerpt_max_chars)
    refs: list[dict[str, str]] = []
    for tab_name in ("输入", "输入配置", "存储配置", "Google 连接"):
        if tab_name in body_text:
            refs.append({"kind": "tab", "text": tab_name})
    refs = refs[: cfg.interactive_refs_max]
    google_hint = None
    if active_tab == "Google 连接":
        google_hint = infer_google_connected(body_text)
    form_fields: list[dict[str, str]] = []
    paste_val = ""
    if active_tab == "输入":
        form_fields = extract_form_fields(page)
        paste_val = extract_paste_ghost(page)
    return PageState(
        url=page.url,
        title=page.title(),
        active_tab=active_tab,
        template_id=template_id,
        form_fields=form_fields,
        session_table_summary="",
        interactive_refs=refs,
        dom_excerpt=dom_excerpt,
        screenshot_path=screenshot_path,
        google_connected_hint=google_hint,
        paste_ghost_value=paste_val,
    )


def format_page_state(state: PageState) -> str:
    lines = [
        f"url={state.url}",
        f"title={state.title!r}",
        f"active_tab={state.active_tab!r}",
        f"template_id={state.template_id!r}",
    ]
    if state.google_connected_hint:
        lines.append(f"google_hint={state.google_connected_hint}")
    if state.paste_ghost_value:
        lines.append(f"paste_ghost={state.paste_ghost_value[:200]!r}")
    if state.form_fields:
        preview = state.form_fields[:12]
        pairs = [f"{row['label']}={row['value']!r}" for row in preview]
        lines.append("form_fields: " + "; ".join(pairs))
    if state.interactive_refs:
        lines.append("tabs: " + ", ".join(r["text"] for r in state.interactive_refs))
    lines.append("dom_excerpt:")
    lines.append(state.dom_excerpt)
    if state.screenshot_path:
        lines.append(f"screenshot_path={state.screenshot_path}")
    return "\n".join(lines)
