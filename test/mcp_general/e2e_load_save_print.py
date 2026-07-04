"""Playwright Firefox E2E: 装载文件 → 按表内序号新增 order → 另存为 → 打印区第 2 项.

Prerequisites:
  python -m nicegui_ui.app   # http://127.0.0.1:8738/
  Ginger_Lots template + at least one xlsx under exports/ginger_lots/ (seeded on first run)

Run:
  python test/mcp_general/e2e_load_save_print.py

Print UI expects deduped labels from ExcelWriter.get_print_areas (sheet: range preview).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = 'http://127.0.0.1:8738/'
TEMPLATE_ITEM = 'Ginger_Lots'
EXPORT_DIR = ROOT / 'exports' / 'ginger_lots'
SHOT_DIR = ROOT / 'test' / 'mcp_general' / '_screenshots'
SHOT_DIR.mkdir(parents=True, exist_ok=True)


def shot(page: Page, name: str) -> None:
    path = SHOT_DIR / f'{name}.png'
    page.screenshot(path=str(path), full_page=True)
    print(f'[screenshot] {path}', flush=True)


def wait_ui(page: Page, ms: int = 1200) -> None:
    page.wait_for_timeout(ms)


def click_text(page: Page, text: str) -> None:
    page.get_by_text(text, exact=True).first.click()
    wait_ui(page)


def scroll_input_tab(page: Page) -> None:
    page.evaluate(
        """() => {
            const body = document.querySelector('.tab-body');
            if (body) body.scrollTop = body.scrollHeight;
        }"""
    )
    wait_ui(page, 600)


def field_label(inp_locator) -> str:
    label_el = inp_locator.locator(
        'xpath=ancestor::div[contains(@class,"field-cell")]'
        '//div[contains(@class,"field-label")]'
    )
    if not label_el.count():
        return ''
    return label_el.inner_text().strip().replace('★主键', '').strip()


def fill_draft_fields(page: Page, order_value: str, yy: str = '26', other: str = 'test1234') -> None:
    inputs = page.locator('.field-cell .input-box input')
    for i in range(inputs.count()):
        inp = inputs.nth(i)
        label = field_label(inp)
        if label == 'order':
            inp.fill(order_value)
        elif label == 'YY':
            inp.fill(yy)
        elif not str(inp.input_value()).strip():
            inp.fill(other)
        inp.dispatch_event('change')
    wait_ui(page, 500)


def read_order_values(page: Page) -> list[int]:
    table = page.locator('.session-list .q-table')
    if table.count() == 0:
        return []
    headers = [h.inner_text().strip() for h in table.locator('thead th').all()]
    order_idx = headers.index('order') if 'order' in headers else 0
    rows = table.locator('tbody tr')
    values: list[int] = []
    for i in range(rows.count()):
        cell_text = rows.nth(i).locator('td').nth(order_idx).inner_text().strip()
        if not cell_text:
            continue
        m = re.search(r'\d+', cell_text)
        if m:
            values.append(int(m.group()))
    return values


def next_order_from_table(page: Page) -> str:
    vals = read_order_values(page)
    if not vals:
        return '1'
    return str(max(vals) + 1)


def seed_export_on_disk(page: Page) -> None:
    """Create one export xlsx when exports/ginger_lots is empty."""
    if list(EXPORT_DIR.glob('*.xlsx')):
        return
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    print('[seed] no export xlsx; creating one via UI', flush=True)
    fill_draft_fields(page, 'seed1')
    click_text(page, '下一行')
    click_text(page, '另存为')
    wait_ui(page, 4000)
    if not list(EXPORT_DIR.glob('*.xlsx')):
        raise RuntimeError('seed 另存为 failed: exports/ginger_lots still empty')
    click_text(page, '清空')


def load_export_via_dialog(page: Page) -> None:
    click_text(page, '装载文件')
    wait_ui(page, 800)
    dialog = page.locator('.q-dialog')
    dialog.wait_for(state='visible', timeout=5000)
    confirm = dialog.get_by_text('装载', exact=True)
    confirm.click()
    wait_ui(page, 2500)
    rows = page.locator('.session-list .q-table tbody tr').count()
    print(f'[check] rows after load={rows}', flush=True)
    if rows < 1:
        raise RuntimeError('装载文件后 session 表无数据行')


def select_print_area_index(page: Page, area_index: int) -> int:
    """Second q-select in .print-row is 打印区域 (first is 打印文件)."""
    scroll_input_tab(page)
    area_select = page.locator('.print-row .q-select').nth(1)
    area_select.click()
    wait_ui(page, 800)
    options = page.locator('.q-menu .q-item')
    count = options.count()
    print(f'[check] print area options={count}', flush=True)
    if count >= area_index + 1:
        options.nth(area_index).click()
        wait_ui(page, 800)
    return count


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.firefox.launch(headless=True)
        context = browser.new_context(viewport={'width': 1400, 'height': 900})
        page = context.new_page()
        page.goto(BASE_URL, wait_until='networkidle')
        wait_ui(page, 2000)
        shot(page, 'load_01_initial')
        page.locator('.q-item').filter(has_text=TEMPLATE_ITEM).first.click()
        wait_ui(page, 2500)
        shot(page, 'load_02_template')
        click_text(page, '输入')
        wait_ui(page, 1500)
        seed_export_on_disk(page)
        shot(page, 'load_03_before_load')
        load_export_via_dialog(page)
        rows_after_load = page.locator('.session-list .q-table tbody tr').count()
        shot(page, 'load_04_loaded')
        new_order = next_order_from_table(page)
        print(f'[check] next order={new_order}', flush=True)
        fill_draft_fields(page, new_order)
        shot(page, 'load_05_new_order_filled')
        click_text(page, '下一行')
        wait_ui(page, 2000)
        shot(page, 'load_06_after_next_row')
        click_text(page, '另存为')
        wait_ui(page, 4000)
        shot(page, 'load_07_save_as')
        area_count = select_print_area_index(page, min(1, 1))
        shot(page, 'load_08_print_area2')
        click_text(page, '打印')
        wait_ui(page, 2000)
        shot(page, 'load_09_print_clicked')
        table_orders = read_order_values(page)
        print(f'[check] table orders={table_orders}', flush=True)
        browser.close()
        print(
            f'[done] load({rows_after_load} rows)→order {new_order}→另存为→print (areas={area_count})',
            flush=True,
        )
        return 0


if __name__ == '__main__':
    sys.exit(main())
