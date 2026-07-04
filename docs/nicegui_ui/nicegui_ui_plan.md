# NiceGUI UI Implementation Constraints & Specifications (Based on core*.py)

This document is the canonical NiceGUI UI specification. It defines product behavior, wireframe layout, and `core*.py` boundaries using NiceGUI / Quasar patterns.

Wireframes in `docs/nicegui_ui/nicegui_ui_*.html` are layout references only. Runtime data must come from `templates/` via `core_registry`, never from documentation samples.

Gradio UI (`webui/`, `docs/gradio_ui/`) has been removed from the repository; do not reintroduce Gradio dependencies or components.

Context7 references used while drafting this plan: `/zauberzeug/nicegui` (splitter, drawer, table, storage, refreshable, download, `ui.run`) and `nicegui.io` (events, styling, download API).

---

## 1. Project Directory Structure

Unchanged from the Gradio plan. UI framework choice does not alter disk layout.

* **Project Root:** workspace root.
* **Templates Directory (`templates/`):**
  * Excel templates: `templates/*.xlsx`
  * TOML configs: `templates/{template_id}/{template_id}.toml`
  * Sort index: `templates/sort_templates.json` (from `core_registry.SortTemplates`)
* **Exports Directory (`exports/`):**
  * `exports/{template_id}/{template_id}_{db_suffix}_{YYYYMMDD}_{HHMMSS}.xlsx`
  * Create `exports/{template_id}/` automatically when missing.

Suggested NiceGUI code layout (sole UI package):

```text
nicegui_ui/
  app.py                 # ui.run(), page route, storage_secret
  pages/
    main.py              # splitter shell; wires sidebar + tab panels
    sidebar.py
    tab_input.py
    tab_google.py
    tab_toml.py
    tab_db.py
  components/
    auth.py              # default admin, principal, pref_key
    session.py           # SessionState, SessionRegistry
    activation.py        # template activation (Phase 2)
    style.css
```

---

## 2. Layout Parity & Splitter Constraints

The shell must match `docs/nicegui_ui/nicegui_ui_index.html`: left template sidebar, middle narrow resize rail, right tab workspace. The layout must occupy the **entire viewport with zero outer margins or paddings** (no blank spaces between the DOM and the browser edges). A single-column unstyled page is unacceptable.

```
+-----------------------------------------------------------------------------+
|  Sidebar (Left)    | R  |  Main Tabs Area (Right)                           |
|                    | a  |                                                   |
|  * Template Header | i  |  [ 输入 ] [ Google 连接 ] [ 输入配置 ] [ 存储配置 ]   |
|    (模板: ID)      | l  |  +---------------------------------------------+  |
|  * Template List   |    |  |              Tab Content Area               |  |
|    - ...           |    |  |                                             |  |
+-----------------------------------------------------------------------------+
```

### 2.0 Global Layout & Page Constraints (Zero Margins)
* **Zero Margins & Paddings:** Body, HTML, and Quasar `.q-page` / `.q-layout` must be stripped of all default margins and paddings (`p-0 m-0`, `overflow-hidden`).
* **Full-Width Shell:** The root container or splitter must be exactly `w-full h-screen` to stretch edge-to-edge of the browser window.

### 2.1 Left Sidebar: Template Selection

* **Presentation:** vertical list, not a dropdown. Data from `SortTemplates.UpdateJson()` → `TemplateIDs`, `template_display_names`, `sort_timeline`.
* **Interaction:** click item → run template activation → highlight active row.
* **Header:** `模板: {template_id}` when active; `模板: 未选择` otherwise.
* **Empty state:** if no `templates/*.xlsx`, show `templates/ 中没有可用模板`. No fallback demo templates.
* **Active tab reset:** template change switches right tabs back to `输入` (first tab).
* **NiceGUI approach:** render list inside `splitter.before` using `ui.column()` with `.classes('w-full h-full p-2 border-r overflow-x-hidden overflow-y-auto').style('will-change: width')`. Use `@ui.refreshable` for sidebar content.

### 2.2 Splitter: Drag-Resize Rail

Gradio required a custom HTML rail inside flex wrappers. NiceGUI should use native layout:

* **Primary Layout:** `ui.splitter(value=240, limits=(150, 400)).props('unit=px').classes('w-full h-screen')` with `splitter.before` (sidebar) and `splitter.after` (main tabs). Do not use percentage values to avoid layout instability when resizing the browser window.
* **Collapse:** optional second control on the rail:
  * toggle `splitter.value` to minimum (collapsed), or
  * swap to `ui.left_drawer(value=True)` for collapse-only mode.
* **Persistence:** store splitter pixel width in `app.storage.user['sidebar_width']` and `app.storage.user['sidebar_collapsed']`. Requires `storage_secret` in `ui.run()`.
* **Throttle Writing:** To prevent heavy disk writes during continuous dragging, the callback saving the value to `app.storage.user` must be debounced/throttled (e.g. writing only after dragging stops, or throttled to at least 200ms).
* **Do not** inject mousemove listeners unless `ui.splitter` cannot meet wireframe behavior after spike validation.

### 2.3 Right Area: Tabs Layout & Spacing

* **Scrolling & Safety:** The right main container `splitter.after` and its active tab panels must have `.classes('w-full h-full overflow-y-auto')` to support vertical scrolling without page-level scrollbars.
* **Flex Shrinkage Safety:** Ensure all flex items inside the panels use `min-width: 0` or `overflow-hidden` so that wide elements (like `ui.table`) scroll horizontally internally instead of stretching the main panel width and breaking the splitter constraints.

Four tabs, fixed order:

| Code name       | Chinese label | Wireframe              |
|-----------------|---------------|------------------------|
| `data_input`    | 输入          | `nicegui_ui_index.html` |
| `google_config` | Google 连接   | `nicegui_ui_connect.html` |
| `toml_config`   | 输入配置      | `nicegui_ui_toml.html`  |
| `db_config`     | 存储配置      | `nicegui_ui_db.html`    |

* **NiceGUI:** `ui.tabs()` + `ui.tab_panels()` with `ui.tab(name='输入')` etc.
* **Density:** use `.classes('gap-1')`, `.props('dense')`, compact `ui.row` / `ui.card(flat bordered)` to match wireframe spacing. Prefer Quasar `dense` / `flat` props over fighting generated DOM.

---

## 3. Tab-Specific Functional & Layout Parity

### 3.1 Tab 1: Input (`data_input` / `输入`)

* **Ghost clipboard input**
  * `ui.input(placeholder='粘贴整行数据…')` with dashed-bottom styling via `.style()` or `.classes()`.
  * **Event:** `on('blur', handler)` — NiceGUI supports server-side blur without hidden bridge components.
  * **Behavior:** `ui_provider.record_from_textbox(raw)` → merge into `draft` → refresh dynamic fields → set `suppress_id_search = True`. Does not write DB directly.

* **Dynamic form fields**
  * **Forbidden:** hardcoded labels like `ID#` / `姓名`.
  * **Required:** rebuild from `ui.get_labels()` after each template activation or TOML save.
  * **Responsive Grid Layout:** Render inputs in a responsive grid container using Tailwind/Quasar column grid classes (e.g., `.classes('grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 w-full')`). Do not hardcode a fixed column count in Python (like `ui.grid(columns=4)`) which squeezes inputs on narrow panels.
  * **NiceGUI:** `@ui.refreshable def input_fields(): ...` creating one `ui.input` per label; call `input_fields.refresh()` when `draft` or template changes.
  * **Primary key:** field where `[[fields]].id = true` shows `★主键` in label.

* **ID blur lookup**
  * Only the primary-key `ui.input` gets `on('blur', on_id_blur)`.
  * If `suppress_id_search`: consume flag and return.
  * Else: `db.query_by_id` → if exists, open `ui.dialog` with:
    * `从数据源重新读取` → `t2db.fetch_row_by_id`
    * `从数据库读取` → `db.query_by_id`
  * No separate button required to start ID search.

* **Session table ("本次已录入")**
  * **Do not** use Gradio `gr.Dataframe` or raw HTML + hidden textbox bridges.
  * **Preferred:** `ui.table(columns=..., rows=..., row_key=..., selection='single'|'multiple')` with columns for checkbox/labels.
  * **Interactions:** row click loads row into `draft` and refreshes `input_fields`; checkbox column for bulk delete; highlight selected row via `selected` binding or table API.
  * If `ui.table` selection API is insufficient, use `@ui.refreshable` HTML table inside `ui.card` — still wire clicks to Python handlers directly (`on_click` on row buttons), not JSON bridges.

* **Session list toolbar** (`.list-btns` under the table)
  * **Left:** `装载文件` — open dialog to pick an xlsx from `exports/{template_id}/`; parse rows via `ExcelWriter.read_instances(path)` into `session_rows` so users can edit multiple exported files in the UI and **另存为** as new files.
  * **Right:** `清空` then `单个删除` (adjacent).
  * **`装载文件` merge policy:** if `session_rows` is empty → **replace** (load into empty list). If non-empty → dialog offers **替换当前列表** or **追加到当前列表**; rows are capped at `input_capacity`; notify when truncated.
  * **`清空`:** clear `session_rows`, reset `current_instance_index = 0`, `selected_session_index = None`, reset `draft` from `template_defaults`, refresh table and fields.
  * **`单个删除`:** remove the single selected table row (former `删除`); recompute `current_instance_index = len(session_rows)`.

* **Toolbar**
  * Row 1: `另存为`, `下一行`, read-only label `当前 {current_instance_index + 1} / 容量 {input_capacity}`.
  * Row 2: `打印文件` (`ui.select`), `打印区域` (`ui.select`), `打印` (`ui.button`).
  * After successful 另存为, refresh print-file choices and select the new export.

* **下一行**
  * Check `verify_report.ok` and `current_instance_index < input_capacity`.
  * `ui.persist_fields(draft)`; `session_rows[current_instance_index] = draft`.
  * If at capacity: notify user, do not clear inputs.
  * Else: increment index, clear `draft`, refresh fields and table.

* **另存为**
  * Path: `exports/{template_id}/{template_id}_{db_suffix}_{YYYYMMDD}_{HHMMSS}.xlsx`
  * `ExcelWriter.write_back(template_path, output_path, session_rows, instance_k=0)` (or include current `draft` if `session_rows` empty).
  * Non-export actions disabled when `verify_report.ok` is false.

* **打印**
  * Windows: `os.startfile(path, 'print')` from Python after user picks exported file + print area.
  * Other OS: `ui.download.file(path)` as fallback.
  * Print areas from `writer.get_print_areas(selected_xlsx)` using TOML `print_sheet`; print logic must not participate in TOML定位.
  * Before Windows print, copy export to a temp xlsx with `print_sheet` set as the active sheet (Excel prints the active sheet by default). The dropdown `打印区域` shows `print_sheet` and its `print_area` when defined; `selected_area` is informational — OS print does not accept a per-invocation area override.

### 3.2 Tab 2: Google Connection (`google_config` / `Google 连接`)

* **OAuth:** `ui.upload` for `oauth_client.json`, status label, `授权 Google 账号` button → `ConnectGoogle` service.
* **Connection status:** label updated on template activation when OAuth active and TOML `[[sources]]` contains sheet URLs.
* **Auto-reconnect:** template switch disconnects previous sheet context; reconnect if new template TOML has URLs. Edit sources only in `输入配置` tab.
* **Main ID sheet table:** `ui.table` with multi-select; `全选` / `取消全选` / `导入选中行`.
* **Import:** selected rows → `ui.persist_fields` → append to Input tab `session_rows` → switch to `输入` tab.

### 3.3 Tab 3: Input Config (`toml_config` / `输入配置`)

Sections as `ui.card` or `ui.expansion`, matching `nicegui_ui_toml.html`:

1. **基础:** `determiner`, `work_sheet`, `print_sheet`, `保存`
2. **数据源:** editable table for `[[sources]]` keys/paths; `保存`
3. **输入区段:** single `input_section` row (`input_area`, `move_to`, `offset`); `校验配置` + report area
4. **字段映射:** table with `Input_label`, `value_from_label`, `value_offset`, `field`, `source_file`, `source_sheet`, `index`, `regex`, `id`; `生成骨架`, `保存`
5. **高级:** `ui.codemirror` or `ui.textarea` for raw TOML; `保存`, `重置`

**校验配置:** `verify_toml(template_path, cfg)` — show `missing_labels`, `duplicate_labels`, `out_of_area_labels`, `errors`.

**TOML save后必须:**

1. Reload cfg
2. Re-run `verify_toml`
3. On failure: disable 输入 write actions; show report
4. On success: rebuild `UiProvider`, `Template2DB`, `ExcelWriter`; recompute `input_capacity = writer.max_instance_count(template_path)`
5. Clear `draft`, `session_rows`, `current_instance_index = 0`
6. Refresh Input, DB, and TOML panels via `@ui.refreshable`

### 3.4 Tab 4: Storage Config (`db_config` / `存储配置`)

* **当前数据库:** `ui.select` of `list_db_paths(template_id)`; `切换` enabled only when selection ≠ `active_db_suffix`; `新建库` → `allocate_next_db_path`
* **全部数据:** `ui.table` of `ui.get_data()` with row selection
* **覆盖录入:** paste textbox + `覆盖保存` → `record_from_textbox` → overwrite selected row by ID

---

## 4. State & Dependency Separation

### 4.1 Session state model

Replace per-session state with an explicit **principal-scoped** session object. NiceGUI shares module-level state across all connected clients unless partitioned by `principal_id`.

**Required pattern:**

```python
@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str | None = None


```python
def resolve_principal() -> Principal:
    if login_required():
        username = app.storage.user.get('username')
        if username and username in known_usernames():
            return Principal(principal_id=f'user:{username}', display_name=username)
        return Principal(principal_id='user:unauthenticated', display_name=None)
    return Principal(principal_id='user:admin', display_name='admin')
```


class SessionRegistry:
    _sessions: dict[str, SessionState] = {}

    @classmethod
    def for_current(cls) -> SessionState:
        p = resolve_principal()
        return cls._sessions.setdefault(p.principal_id, SessionState())
```

```python
@dataclass
class SessionState:
    template_id: str | None = None
    template_path: Path | None = None
    cfg: GetTomlValues | None = None
    verify_report: dict | None = None
    located: dict | None = None
    db_path: Path | None = None
    db: SecureSQLite | None = None
    ui: UiProvider | None = None
    t2db: Template2DB | None = None
    writer: ExcelWriter | None = None
    input_capacity: int = 0
    current_instance_index: int = 0
    draft: dict = field(default_factory=dict)
    session_rows: list = field(default_factory=list)
    suppress_id_search: bool = False
    pending_id_value: int | None = None
    exported_files: list = field(default_factory=list)
    last_export_path: Path | None = None
    active_db_suffix: str | None = None
    # Google tab fields ...
```

**Storage scope:**

| Data | NiceGUI storage | Notes |
|------|-----------------|-------|
| `draft`, `session_rows`, engines | `SessionRegistry[principal_id]` (`SessionState`) | per principal; not in `app.storage.user` |
| Sidebar width / collapsed | `app.storage.user` (optionally `pref_key(name)`) | survives reload; needs `storage_secret` |
| Visit counters, global flags | `app.storage.general` | optional |
| Ephemeral UI flags | `app.storage.client` or local variables | lost on reload |

Do **not** store a single shared `SessionState` at module level. A `SessionRegistry` dict keyed by `principal_id` is allowed.

Future permission limits: adjust grants on `user:admin` (or other accounts), not global flags that bypass `principal_id`.

### 4.2 Core boundaries (unchanged)

| Module | UI may | UI must not |
|--------|--------|-------------|
| `core_registry.py` | list/switch templates | scan outside `templates/` |
| `core_toml.py` | Load/Save/`verify_toml` | scan xlsx labels, guess coordinates |
| `core_store.py` | DB CRUD, text split | merge legacy JSON |
| `core_transform.py` | `max_instance_count`, `write_back`, print areas, source fetch | compute Excel coordinates in UI |

### 4.3 Template activation flow (unchanged semantics)

On sidebar click or initial load:

1. Resolve `template_id`, `template_path` from `SortTemplates`
2. `ensure_exists(template_id, template_path)`
3. `load_toml(template_id)`
4. `verify_toml(template_path, cfg)`
5. If failed: show report; disable 输入/另存为/下一行/打印
6. If passed: open `default_db_path`, construct `SecureSQLite`, `UiProvider`, `Template2DB`, `ExcelWriter(cfg, located)`
7. `input_capacity = writer.max_instance_count(template_path)`
8. Reset `draft`, `session_rows`, `current_instance_index = 0`
9. Refresh all `@ui.refreshable` sections; switch to tab `输入`

### 4.4 TOML model (unchanged)

Must use: `work_sheet`, `print_sheet` (optional), single `[[input_section]]`, `Input_label`, `value_from_label`, `value_offset`, `index`, `id`.

Forbidden: old `sections` model, UI-maintained area lists, UI coordinate math.

---

## 5. NiceGUI Component Mapping (Gradio → NiceGUI)

| Requirement | Gradio (problematic) | NiceGUI (recommended) |
|-------------|----------------------|------------------------|
| App shell | `gr.Row` + CSS overrides on generated wrappers | `ui.splitter` or `ui.row` + `ui.column` |
| Sidebar list | `gr.HTML` + JS click bridge | `ui.list` / `ui.button` + Python `on_click` |
| Resize / collapse | custom `#resize-rail` + `localStorage` + inline `!important` | `ui.splitter` + `app.storage.user` |
| Tabs | `gr.Tabs` | `ui.tabs` + `ui.tab_panels` |
| Dynamic inputs | `@gr.render` | `@ui.refreshable` |
| Ghost / field blur | `.blur()` + `suppress_id_search` | `ui.input.on('blur', ...)` |
| ID conflict | `gr.HTML` hint | `ui.dialog` |
| Session / DB tables | `gr.HTML` + hidden `gr.Textbox` JSON bridge | `ui.table` selection + row actions |
| Notifications | `gr.Info` / `gr.Warning` | `ui.notify(...)` |
| TOML editor | `gr.Code` | `ui.codemirror` / `ui.textarea` |
| Export download fallback | file path only | `ui.download.file(path)` |
| Styling | `launch(css=...)` fighting Gradio DOM | `.props()`, `.classes()`, `ui.add_css()` |
| Local desktop | browser only | `ui.run(native=True, window_size=(...))` optional |

---

## 6. Why Migrate from Gradio (summary)

Observed Gradio blockers for this project:

1. Layout children (`gr.HTML`, `gr.Column`) receive independent flex wrappers → splitter rail consumed equal width.
2. Inline Quasar/flex styles on columns override CSS unless JS uses `setProperty(..., 'important')`.
3. Interactive tables require hidden-component JSON bridges.
4. Section borders break when HTML tags span multiple `gr.HTML` instances.
5. `blur`, CSS injection, and JS attachment vary across Gradio versions (4/5/6).

NiceGUI advantages for this app:

* Native `ui.splitter`, `ui.dialog`, `ui.table`, `ui.tabs`
* Direct Python event handlers (`on_click`, `on('blur')`)
* `@ui.refreshable` for dynamic fields without hidden bridges
* `app.storage.user` for sidebar persistence
* `ui.run(native=True)` fits a local Excel workstation tool

NiceGUI tradeoffs:

* Rewrite UI layer; reuse `core*` and activation logic only
* Must choose correct storage scope per field
* Multi-user deployment needs discipline (no module globals)
* Less Hugging Face Spaces / share-link ecosystem than Gradio

---

## 7. Implementation Order (NiceGUI greenfield)

1. **Spike shell:** `ui.splitter` + sidebar template list + four empty tabs; verify resize/collapse + `app.storage.user` persistence.
2. **Template activation:** port `activate_template()` logic; real data from `templates/*.xlsx` only.
3. **Input tab:** `@ui.refreshable` fields, ghost blur, ID dialog, session `ui.table`, 下一行 / 另存为.
4. **TOML tab:** five sections, 校验配置, save + full session reset.
5. **DB tab:** switch/create DB, full-data table, 覆盖保存.
6. **Google tab:** OAuth + import table (can follow after core four tabs work).
7. **Print / export polish:** print area dropdown, `ui.download.file` fallback, `native=True` evaluation on Windows.

Do not modify `app/services/*` during UI migration unless a missing core API is confirmed and documented first.

---

## 8. `ui.run()` Baseline

A CSS stylesheet (`style.css`) must be loaded to ensure the page utilizes the full width and height of the viewport with no margins, borders, or default Quasar page paddings:

```css
/* style.css */
html, body {
    margin: 0;
    padding: 0;
    width: 100vw;
    height: 100vh;
    overflow: hidden;
}

.q-page {
    padding: 0 !important;
    min-height: 100vh !important;
}

.q-layout {
    min-height: 100vh !important;
}
```

Baseline launch setup:

```python
from pathlib import Path
from nicegui import ui, app

ui.add_css(Path(__file__).parent.joinpath('style.css').read_text(encoding='utf-8'))

ui.run(
    title='Excel Template Viz',
    storage_secret='change-me-in-production',  # required for app.storage.user
    reload=True,                                # dev only
    native=False,                               # True for pywebview desktop window
    language='zh-CN',                           # Quasar locale if available in installed version
)
```

Use `ui.download.file` for exported xlsx when not printing. Use `ui.notify` for validation errors and capacity warnings.

---

## 9. Forbidden Actions

* No runtime fallback templates or doc wireframe samples as data
* No UI-side Excel coordinate calculation
* No module-level unpartitioned session globals (use `SessionRegistry` + `principal_id`)
* No hidden textbox / JSON event bridges unless `ui.table` proves insufficient after spike
* No Gradio components in the NiceGUI app
* No loading templates from outside `templates/`

---

## 10. Acceptance Criteria

1. Sidebar lists only `templates/*.xlsx` via `core_registry`; empty state when none.
2. `ui.splitter` (or approved equivalent) provides drag resize and collapse with persisted width.
3. Template activation always runs `verify_toml`; failure disables 输入 write/export/print.
4. Input fields are generated from `ui.get_labels()`; primary key uses blur + dialog flow.
5. Session table supports select, highlight, 单个删除, 清空, 装载文件 (from exports), load into `draft` without hidden JSON bridges.
6. 下一行 uses `input_capacity` from `writer.max_instance_count()` only.
7. 另存为 writes to `exports/{template_id}/...` and refreshes print-file list.
8. TOML save rebuilds engines and clears input session state.
9. DB tab switches DB only when 切换 is enabled; table shows live SQLite data.
10. All business rules delegate coordinate math to `core_transform` / `located`.

---

## 11. Relationship to Existing Artifacts

| Artifact | Status |
|----------|--------|
| `docs/nicegui_ui/nicegui_ui_plan.md` | canonical UI specification (this document) |
| `docs/nicegui_ui/nicegui_ui_*.html` | wireframes only |
| `plans/nicegui_ui_migration/` | Speckit plan / spec / tasks / constitution |
| `nicegui_ui/` | sole runtime UI package |
| `webui/`, `docs/gradio_ui/`, Gradio deps | removed — do not restore |
