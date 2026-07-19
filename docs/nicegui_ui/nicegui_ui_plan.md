# NiceGUI UI Implementation Constraints & Specifications (Based on core*.py)

> 修订 2026-07-18：`use_independent_db` 落盘至模板 TOML（`GetTomlValues.Save`）；输入 Tab 工具栏与两步删除对齐实现；线框注明 `ui.splitter` 替代自定义 rail。
> 修订 2026-07-14：§2.2 侧栏 — **显示/存储分离** + **Quasar limits 宽松占位**（必传 `(0,1000)`，禁止省略 limits、禁止 `limits=(20,400)`）。

This document is the canonical NiceGUI UI specification. It defines product behavior, wireframe layout, and `core*.py` boundaries using NiceGUI / Quasar patterns.

Wireframes in `docs/nicegui_ui/nicegui_ui_*.html` are **layout references** for spacing and control grouping. Runtime uses NiceGUI / Quasar primitives (`ui.splitter`, `ui.textarea`, `ui.checkbox`, HTML `<table>` via `ui.element`) — wireframe class names (e.g. `.resize-rail`, `.btn`) map to CSS + label/button patterns, not necessarily identical DOM.

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
* **TLS Directory (`certs/`)** — runtime-generated; **gitignored** (§8.1):
  * `certs/server.crt`, `certs/server.key` — self-signed server certificate + private key
  * Optional `certs/san.txt` — SAN hostnames / LAN IPs for certificate generation

Suggested NiceGUI code layout (sole UI package):

```text
nicegui_ui/
  app.py                 # ui.run(), page route, storage_secret, TLS ensure hook
  ssl_manager.py         # ensure_tls_certs(): OpenSSL 自签证书检测/生成（§8.1）
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

The shell must match `docs/nicegui_ui/nicegui_ui_index.html` (2026-07 wireframe refresh): **unified top bar** + **body row** (sidebar list | resize rail | tab workspace). The layout must occupy the **entire viewport with zero outer margins or paddings**. A single-column unstyled page is unacceptable.

```
+-----------------------------------------------------------------------------+
| shell-top (one row, full width)                                             |
|  [ 已选模板名  << ] | [ 输入 ] [ 输入配置 ] [ 存储配置 ] [ Google 连接 ]      |
+----------+---------------------------------------------------------------+
| Template | Tab body (scroll)                                               |
| list     |                                                                 |
| (splitter|                                                                 |
| .before) |                                                                 |
+----------+---------------------------------------------------------------+
```

Wireframe rules (canonical):

* **`shell-top`:** left `sidebar-header` (selected template display name + fold chevron `<<` / `>>`) and right `tabs` share **one horizontal bar** with the same height and bottom border. Tabs are **not** a separate row below the sidebar. Header width is **not** tied to `--sidebar-width` — it uses flex (`max-width: 40vw` on template name) so collapse does not hide the name.
* **`sidebar-header` collapse:** fold button sits **to the right of** the template name. On collapse: **entire template list disappears** (`splitter.before` + separator hidden via CSS); **the template name remains visible in the top bar**. Click again **pops out** the sidebar at the last persisted width (clamped). Do **not** drive collapse by setting `splitter.value` to 0.
* **`shell-body`:** contains `ui.splitter`. `splitter.before` holds the template list, and `splitter.after` holds the main content.
* **Resize:** handled by `ui.splitter` native separator (wireframe `.resize-rail` is a visual stand-in only). No custom dragging scripts.

### 2.0 Global Layout & Page Constraints (Zero Margins)
* **Zero Margins & Paddings:** Body, HTML, and Quasar `.q-page` / `.q-layout` must be stripped of all default margins and paddings (`p-0 m-0`, `overflow-hidden`).
* **Full-Width Shell:** The root container must be exactly `w-full h-screen` edge-to-edge.

### 2.1 Left Sidebar: Template Selection

* **Presentation:** vertical list below `shell-top`, not a dropdown. Data from `SortTemplates.UpdateJson()` → `TemplateIDs`, `template_display_names`, `sort_timeline`.
* **Interaction:** click item → run template activation → highlight active row → update **top-bar selected template name** (not a static “模板” label).
* **Header (top bar):** show `{template_display_name}` or `{template_id}` when active; `未选择` otherwise. No separate “模板:” prefix required if wireframe shows name only.
* **Empty state:** if no `templates/*.xlsx`, show `templates/ 中没有可用模板`. No fallback demo templates.
* **Active tab reset:** template change switches right tabs back to `输入` (first tab).
* **NiceGUI approach:** implement `shell-top` as `ui.row().classes('w-full')` with fixed-width left cell matching sidebar width and `ui.tabs()` filling the remainder; template list in `splitter.before` with `@ui.refreshable`.

### 2.2 Splitter: Drag-Resize Rail

* **Primary Layout:** `ui.splitter(value=initial, limits=(0, 1000)).props('unit=px')` in **`shell-body` only**. No custom `#resize-rail` scripts.

#### 三层宽度（必读 — 勿混为一谈）

| 层 | 机制 | 取值 | 作用 |
|----|------|------|------|
| **A. Quasar `limits`** | `ui.splitter(..., limits=(0, 1000))` | 0..1000 px | **仅**覆盖 QSplitter 默认 `[10, 90]`（`unit=px` 下会把 250 夹成 ≤90 甚至 0）。**不是**业务规则。 |
| **B. 显示** | `splitter.value`、拖拽跟手 | 默认 **250**；拖拽可 &lt;20 或 &gt;400（在层 A 内） | 用户眼前宽度。 |
| **C. 存储** | `sidebar_width` in `app.storage.user` | `clamp_store(raw)` → **20..400** | 折叠弹出、刷新恢复。 |

**禁止：**

* `limits=(20, 400)` — 会把**显示**锁在 20..400，与「拖 10 显示 10、存 20」矛盾。
* **省略** `limits` — Quasar 默认 `[10, 90]` + `unit=px` → 250/300 被夹到 ≤90，常见表现 **0px 或异常窄条**（见下节根因）。

#### Quasar 根因（2026-07-14 实测结论）

`nicegui_ui/pages/main.py` 若写 `kwargs = {}` 且不传 `limits`：

1. 底层 `QSplitter` 使用默认 **limits = [10, 90]**（百分比语义，但在 `unit=px` 下按像素解释）。
2. `value=250` 或 `300` **超出 90** → 内部裁剪/计算失败 → 渲染 **0px** 或卡在极小宽度。
3. 这与「存储 clamp」无关；必须在层 A 显式传 **宽松** `limits`。

**推荐常量：**

```python
SIDEBAR_DEFAULT = 250
SIDEBAR_STORE_MIN = 20
SIDEBAR_STORE_MAX = 400
SIDEBAR_QUASAR_LIMITS = (0, 1000)   # 层 A only
```

`clamp_store(raw) = max(20, min(int(raw), 400))` — **仅层 C**；**禁止**在 resize 回调里 `splitter.value = clamp_store(raw)`。

#### 两个概念（禁止混用）

* **显隐（折叠钮 `.sidebar-fold-btn`）**：CSS `.shell.is-sidebar-collapsed` 隐藏 `splitter.before` + `separator`。写入 `sidebar_collapsed`（bool）。**禁止** `splitter.value = 0` 折叠。
* **宽度**：
  * **显示**（`splitter.value`）：拖拽跟手，**允许** &lt; 20 或 &gt; 400。
  * **存储**（`sidebar_width`）：拖拽结束 / 收起前写入时 **只** `clamp_store(raw)`。

#### 存储（`app.storage.user` + `Auth.pref_key`）

* `sidebar_width`：int，**20..400**；无键表示「从未拖过或未落库」
* `sidebar_collapsed`：bool；仅折叠钮写入
* **允许**在代码中硬编码 `SIDEBAR_DEFAULT = 250`（仅此一处默认像素）

#### 验收用例

| 操作 | 显示 | 存储 | 折叠 → 弹出后显示 |
|------|------|------|-------------------|
| 首次（无存储） | 250 | （无键） | 250 |
| 拖至 200 | 200 | 200 | 200 |
| 拖至 10 | 10 | 20 | 20 |
| 拖至 600 | 600 | 400 | 400 |

#### 折叠钮

* **收起前**：`sidebar_width = clamp_store(splitter.value)`（防止 resize 未落库）
* **归一化**：若已有 `sidebar_width` 脏数据，clamp 后写回
* **收起**：`sidebar_collapsed = True`，加 hidden 类；**不改** `splitter.value`
* **展开**：去 hidden 类；`splitter.value = clamp_store(stored)` 若有键，否则 **`SIDEBAR_DEFAULT`（250）**
* 程序设置 `splitter.value` 时须 `programmatic_resize_count`（或等价）**跳过** resize 回调写存储

#### 拖拽 `on_splitter_resize`

* `raw` 来自 Quasar → **显示保持 raw**（勿 `splitter.value = clamp_store(raw)`）
* `_set_sidebar_pref('sidebar_width', clamp_store(raw))`
* 若当前折叠：清 `sidebar_collapsed` 并去 hidden（拖 separator = 要看见侧栏）
* **禁止**用 `is_loading` 长时间丢弃 resize（否则收起前无存储 → 弹出误为 20px）

#### Startup `initial`

```python
stored = pref("sidebar_width")
initial = clamp_store(stored) if stored is not None else SIDEBAR_DEFAULT
ui.splitter(value=initial, limits=SIDEBAR_QUASAR_LIMITS).props("unit=px")
```

* `sidebar_collapsed` 为 true 时仅加 hidden 类；`value` 仍按上式设置（**不要**为折叠改 `value=0`）。

### 2.3 Right Area: Tabs Layout & Spacing
> **CSS 约定（禁止全局冲突）**：业务横向工具行使用 `.form-row`，**禁止**在 `style.css` 中定义全局 `.row`，以免与 Quasar 的 `ui.splitter` 或原生的 `ui.row` 严重冲突（如破坏 splitter 拖拽）。
>
> **`!important` 政策**：不要随便在 CSS 中使用 `!important`。应先定位冲突根因（如全局类名与 Quasar 冲突）并修复；`!important` 仅作最后手段，且须用户明确同意。

* **Scrolling & Safety:** The right main container `splitter.after` and its active tab panels must have `.classes('w-full h-full overflow-y-auto')` to support vertical scrolling without page-level scrollbars.
* **Flex Shrinkage Safety:** Ensure all flex items inside the panels use `min-width: 0` or `overflow-hidden` so that wide elements (like `ui.table`) scroll horizontally internally instead of stretching the main panel width and breaking the splitter constraints.

Four tabs, fixed order:

| Code name       | Chinese label | Wireframe              |
|-----------------|---------------|------------------------|
| `data_input`    | 输入          | `nicegui_ui_index.html` |
| `google_config` | Google 连接   | `nicegui_ui_connect.html` |
| `toml_config`   | 输入配置      | `nicegui_ui_toml.html`  |
| `db_config`     | 存储配置      | `nicegui_ui_db.html`    |

* **NiceGUI:** `ui.tabs()` lives inside `shell-top` (right cell); `ui.tab_panels()` in `splitter.after` below. Tab labels: `输入`, `输入配置`, `存储配置`, `Google 连接`.
* **Density:** use `.classes('gap-1')`, `.props('dense')`, compact `ui.row` / `ui.card(flat bordered)` to match wireframe spacing.

### 2.4 Mobile / Portrait (垂直屏幕)

Target: phone browsers in **portrait**; same Python handlers as desktop.

* **Viewport:** add `<meta name="viewport" content="width=device-width, initial-scale=1.0">` equivalent via NiceGUI page head; no horizontal page scroll.
* **Shell:** keep `shell-top` (template name + fold + tabs). On narrow screens default **sidebar collapsed**; fold chevron is the primary navigation back to template list. This does not constitute a default `sidebar_width` value.
* **Tabs:** allow horizontal scroll (`overflow-x: auto`) or `dense` compact tabs so four labels remain reachable on ~360px width.
* **Field grid:** see §3.1 — **one field per row** on mobile (`grid-cols-1`); label above or label-left with full-width input.
* **Touch (拍照 / OCR 菜单):** see §3.1 — **do not** use double-tap or long-press on the textarea as the primary trigger (见 §3.1「移动端」).
  * **Camera:** use `<input type="file" accept="image/*" capture="environment">` hidden trigger; prefer rear camera on mobile.
  * **Secure context (HTTPS):** browsers allow `getUserMedia` on `http://localhost` / `127.0.0.1` only. Access via LAN IP (`http://192.168.x.x` with `host='0.0.0.0'`) **requires HTTPS** — see §8.1.
* **Session table:** `ui.table` horizontal scroll inside card; checkbox column retained; **`row_key` = `instance_k`** when sortable columns enabled.

Breakpoint suggestion (Tailwind): `max-width: 639px` → mobile rules; `sm:` and up → desktop field grid.

### 2.5 Wireframe file parity

All `docs/nicegui_ui/nicegui_ui_*.html` files must stay aligned with this plan:

| File | Shell | Tab active | Distinct content |
|------|-------|------------|------------------|
| `nicegui_ui_index.html` | full `shell-top` + fold + `ui.splitter` body | 输入 | `.field-grid`; toolbar 保存/刷新/删除 ‖ 添加数据；delete_mode 勾选列 |
| `nicegui_ui_toml.html` | same | 输入配置 | 校验并应用 + TOML 高级（含 `use_independent_db` 示例；无 AI 向导） |
| `nicegui_ui_db.html` | same | 存储配置 | §3.4 checkbox → `cfg.Save` / TOML `use_independent_db` |
| `nicegui_ui_connect.html` | same | Google 连接 | OAuth row + 主 ID 表 + 屏蔽所选数据 |

Sub-tab wireframes omit interactive fold JS unless noted; layout classes must match index.

---

## 3. Tab-Specific Functional & Layout Parity

### 3.1 Tab 1: Input (`data_input` / `输入`)

* **Ghost clipboard input**
  * `ui.textarea` with dashed-bottom styling (`.ghost-input`; `borderless autogrow`).
  * **Event:** `on('blur', handler)` — NiceGUI supports server-side blur without hidden bridge components.
  * **Behavior:** `ui_provider.record_from_textbox(raw)` → merge into `draft` → refresh dynamic fields → set `suppress_id_search = True`. Does not write DB directly.
  * **Context menu:** same「拍照」「OCR」as field cells (`nicegui_ui/components/ocr_menu.py`).

* **Dynamic form fields**
  * **Forbidden:** hardcoded labels like `ID#` / `姓名`.
  * **Required:** rebuild from `ui.get_labels()` after each template activation or TOML save.
  * **Wireframe class:** `.field-grid` + `.field-cell` (label left, input right) per `nicegui_ui_index.html`.

  **Desktop layout (≥640px):**
  * CSS Grid **auto-fill** using full tab-body width: e.g. `grid-template-columns: repeat(auto-fill, minmax(400px, 1fr))`.
  * Each logical input targets **~400px** minimum cell width; extra columns appear when space allows so each row uses the full `.field-grid` width.
  * Inside `.field-cell`, label column fixed (~100px); input stretches within the cell (`min-width: 0`).

  **Mobile portrait (<640px):**
  * **One input per row:** `grid-template-columns: 1fr` — each `.field-cell` spans full width.

  **Input control behavior (all breakpoints):**
  * Use `ui.textarea` (or Quasar `q-input` `type=textarea` with `autogrow`) — **multiline allowed**.
  * **Horizontal overflow:** long single-line text shows a **horizontal scrollbar** (`overflow-x: auto`; preserve newlines with `white-space: pre-wrap` or `pre` per line).
  * **Vertical growth:** as lines increase, control **height grows** to show every line; **no vertical scrollbar inside the field** (`overflow-y: hidden`). Parent `.tab-body` scrolls instead.
  * **NiceGUI:** `@ui.refreshable def input_fields(): ...` — one textarea per label; `input_fields.refresh()` when `draft` or template changes.
  * **Primary key:** field where `[[fields]].id = true` shows `★主键` in label.

* **Input context menu (右键 / 移动端按钮)** — canonical UI spec for camera / OCR; OCR API is [`embed_paddle_ocr.md`](../embed_paddle_ocr.md) **`PaddleOcr(pic, rectangle)`** only.

  * **Scope:** every dynamic input on the Input tab (including primary key). Track active field: `input_label`, `template_id`, `record_id` (from draft id when known), DOM ref via `SessionRegistry.for_current()`.

  **Desktop (≥640px):**
  * `ui.context_menu()` on `.field-cell` (or textarea wrapper); **`contextmenu`（右键）** opens「拍照」「OCR」.

  **Mobile portrait (<640px):**
  * **Do not** use **double-tap** on the textarea as the menu trigger. In browsers, double-tap inside editable text is reserved for **word selection / caret placement** (and on iOS often page zoom); it will fight OCR/camera UX and is unreliable for a custom menu.
  * **Do not** rely on **long-press** alone either — on textarea it commonly triggers text selection or the OS paste bar, not a stable custom menu across Safari / Chrome / WebView.
  * **Canonical mobile entry:** a small **`···` or 📷 button** at the end of each `.field-cell` row (outside the text baseline); **single tap** opens the **same** `ui.menu` / menu actions as desktop. Implement in Python (`ui.button` + `ui.menu`); no custom Vue required for v1.
  * Optional later: long-press on the **button** or label strip only (not on the textarea) if user testing asks for it.

  * **One photo per input (session buffer):** each `input_label` holds **at most one pending image** in `SessionState.field_images[input_label]` (bytes + optional preview). New **拍照** or OCR capture **replaces** the previous pending image for that field. SQLite persistence on **添加数据** / **保存** only. See [`db_store.md`](../db_store.md).

  * **Menu items:**

    | Item | Behavior | Calls |
    |------|----------|-------|
    | **拍照** | Camera / file picker → cache in `field_images[input_label]` only. Optional thumbnail on field. **Do not** OCR. | On commit → `core_store.save_image(...)` when `use_independent_db` (§3.4). |
    | **OCR** | If pending image exists → preview + crop rect (default full) → confirm. If **none** → open camera first, cache, then same flow. Fill active field from OCR text. 支持双模式回填：顶部粘贴（GHOST）回填全量 JSON，各独立字段（FIELD）回填单格可读文本。 | `paddle_ocr.main.PaddleOcr(pic_bytes, rectangle)` — `rectangle` is OpenCV `(x,y,w,h)` or `None`. Optional: `core_store.update_image_ocr` after `image_id` exists. |

  * **OCR mapping:** FIELD 模式下从结果 JSON 中抽取对应的 string/table 纯文本，组合填入单输入框。GHOST 模式回填整块 JSON 等待 `on_ghost_blur` 解析映射（见上方 Ghost clipboard input 段落）。

  * **Errors:** `ui.notify(result.get('message'))`; never HTTP codes or raw exceptions.

  * **Loading:** disable menu while capture / OCR runs.

  * **Gate:** after `python paddle_ocr/main.py` smoke. Import `PaddleOcr` from `paddle_ocr.main` only.

  * **Suggested code:** `nicegui_ui/components/ocr_menu.py` (`open_camera_dialog`, `run_ocr`); wired from `tab_input.py` / `tab_db.py`.

* **Input Tab Layout (tab_input.py)**
  * **Flex Container**: The root container uses `.tab-flex-container` (full height, hidden overflow, flex column).
  * **Fixed Areas**: The top (paste textbox, dynamic fields) and bottom (toolbar, print controls) sections use `shrink-0` to maintain their size and remain visible at all times.
  * **Scrollable Table**: The `.session-list` area takes `flex-1` with a `min-h-[150px]` (ensuring at least 2-3 rows are visible even when fields fill the screen). The inner table is wrapped in a container with `overflow-y-auto` and uses a `sticky top-0` header to keep column names visible while scrolling.

* **ID blur lookup**
  * Only the primary-key field (`ui.textarea` / input) gets `on('blur', on_id_blur)`.
  * If `suppress_id_search`: consume flag and return.
  * Else: `db.query_by_id` → if exists, open `ui.dialog` with:
    * `从数据源重新读取` → `t2db.fetch_row_by_id`
    * `从数据库读取` → `db.query_by_id`
  * No separate button required to start ID search.

* **Session table** — behavior splits by storage mode:

  | Mode | Table title | Data source on activate | Row click |
  |------|-------------|-------------------------|-----------|
  | **Independent DB** (`use_independent_db=true`) | **本次已录入** | Empty until user enters rows or **装载文件** / Google import | Load row into `draft` for editing |
  | **Template-as-DB** (`use_independent_db=false`) | **模板已存数据** | `session_rows ← read_instances(template_path, limit=input_capacity)`; `current_instance_index = len(session_rows)`; `draft` ← values at that instance (next line), with formula mask | Same; sync formula readonly state |

  * **Do not** use Gradio `gr.Dataframe` or raw HTML + hidden textbox bridges.
  * **Preferred:** `ui.table(columns=..., rows=..., row_key=..., selection='single'|'multiple')` with columns for checkbox/labels.
  * **Interactions:** row click loads row into `draft` and refreshes `input_fields` — resolve row by **`instance_k`**, never by sorted `tbody` index; checkbox column for bulk delete (delete by **`instance_k`**); highlight selected row via `selected` binding or table API.
  * If `ui.table` selection API is insufficient, use `@ui.refreshable` HTML table inside `ui.card` — still wire clicks to Python handlers directly (`on_click` on row buttons), not JSON bridges. Each `<tr>` must carry `data-instance-k` (or equivalent row key).

* **Stable `instance_k` (required for correct write-back)**
  * Every `session_rows` entry includes **`instance_k: int`** (0-based), assigned at load/append and **immutable** for that record.
  * `read_instances` → row `i` gets `instance_k = i`; new instance on **添加数据** uses **`current_instance_index`** as `instance_k` (sequential), not a scan for the next empty slot.
  * **`write_back`**, template-as-DB direct write, **保存** export, row edit, **删除选中**: always key off **`instance_k`**, not visual row order after sort.
  * `current_instance_index` / `selected_session_index` should resolve through **`instance_k`** (prefer storing `selected_instance_k` in `SessionState` when sort is enabled).

* **Sheet geometry vs UI table** (see [`toml_config_design.md`](../toml_config_design.md), [`excel_transform.md`](../excel_transform.md) §4.6.5):
  * UI table: **one row = one instance**; **one column = one `Input_label`**.
  * `move_to` is `down`/`up` → instances stack on sheet **rows** (table rows align with sheet row direction).
  * `move_to` is `left`/`right` → instances stack on sheet **columns** (each table row is a **column** of values on the sheet; labels stay fixed).
  * `value_from_label` `left`/`right` is **within** one instance only (label beside value), not the multi-instance direction.

* **Column-header sort (view-only) (已实现)**
  * **Supported:** click `Input_label` column headers to sort displayed rows (asc/desc).
  * **Not sortable:** checkbox column; **`#` / `instance_k` column** if shown.
  * **`删除选中`:** implements a two-step deletion. Click once to enter `delete_mode` (reveals checkbox column `chkcol` and turns button red/says "确认删除"). Click again to remove checked items in memory. If no rows are checked on the second click, it cancels `delete_mode`. **Note:** Deletion is purely in-memory within the UI session and does NOT automatically write back or delete physical rows from the `.xlsx` file.
  * Sorting **must not** reorder canonical `session_rows` used for `write_back`. It is purely a visual reordering on `tbody` rendering, keeping `instance_k` stable.
  * After sort: row click, delete, and commit still use **`instance_k`** so data is not written to the wrong instance/column on the sheet.
  * **State tracking:** Uses `sort_column` and `sort_descending` in `SessionState` (cleared on template/db switch).
  * Same rules apply to DB tab **全部数据 / 数据表已存数据** when using `ui.table` (§3.4).

* **Formula fields (template-as-DB only)**
  * Per `Input_label`, if template cell is an Excel formula (`data_only=False`, value starts with `=`): show **computed display value** in the field (`data_only=True`), set control **readonly**; do not write that label on `write_back` (transform layer also skips — see [`excel_transform.md`](../excel_transform.md) §4.6.2).
  * Optional UI hint on label (e.g. 「公式」) so users know why the field is locked.

* **Toolbar (`.toolbar-row`)** — single row, two `ui.row` groups (`justify-between` via parent flex):
  * **Left group:** `保存` · `刷新数据` · `删除选中`（两步：首次进入 `delete_mode` 并显示表内勾选列；再次为 `确认删除` 或空选取消）
  * **Right group:** `添加数据`
  * Status hints sit **above** the table (`.ghost-note` under session-list title), not in the toolbar row.
  * **Independent DB:** `当前 {current_instance_index + 1} / 容量 {input_capacity}`.
  * **Template-as-DB:** `当前将录入至第 {current_instance_index + 1} 行`（无容量分母）.
  * **Below toolbar:** `打印文件` (`ui.select`), `打印区域` (`ui.select`), `打印` — preview dialog + `window.print` / PNG download (`tab_input.py`).
  * After successful **保存** (independent-DB export path), refresh print-file choices and select the new export.
  * **Removed:** `清空` button; `装载文件` flow deferred / not in current toolbar.

* **添加数据**（原「下一行」；英文概念名 Add Data）
  * Commits the current `draft` at **`current_instance_index` / `instance_k`**. UI table always shows one row per instance; sheet geometry depends on TOML `move_to`:
    * `down` / `up` → each commit targets a **row-direction** instance (values stack on sheet rows).
    * `left` / `right` → each commit targets a **column-direction** instance (table row still represents one instance).
  * **No empty-slot detection:** the input fields already show whatever is at the active `instance_k` (from activation, row click, or prior `read_values`). If that instance already has data, the user sees it and may overwrite by editing and clicking **添加数据** again — the UI does not search for the next blank instance.
  * Always require `verify_report.ok`.
  * **Independent DB (`use_independent_db=true`):**
    * Require `current_instance_index < input_capacity`; if at capacity: `ui.notify` 「容量已满，无法继续添加数据」, do not clear inputs.
    * `ui.persist_fields(draft)` → SQLite `records` (see §3.4).
    * **Images on commit:** for each `input_label` in `field_images` with pending bytes, call `core_store.save_image(...)`. Clear `field_images` after save.
    * Append/update `session_rows`; increment `current_instance_index`; clear `draft` from `template_defaults`; refresh fields and table.
  * **Template-as-DB (`use_independent_db=false`):**
    * **No capacity check** — button always enabled when verify ok (no 「已满」 blocking).
    * **Skip** `ui.persist_fields` and **skip** `save_image`; discard pending `field_images` on commit.
    * `write_back` keyed by **`instance_k = current_instance_index`**, not table display order; refresh session table via `read_instances` / `load_template`.
    * After commit, advance `current_instance_index` (typically `+= 1` or `len(session_rows)` after reload); optional `read_values` for the new index so fields reflect sheet content — user may leave or overwrite.

* **保存**（原「另存为」）
  * **Independent DB:** write timestamped export — path `exports/{template_id}/{template_id}_{db_suffix}_{YYYYMMDD}_{HHMMSS}.xlsx`. Persist current row same as **添加数据** (text + images per rules above) before or as part of export transaction. `ExcelWriter.write_back(template_path, output_path, session_rows, instance_k=0)` (or include current `draft` if `session_rows` empty).
  * **Template-as-DB:** write **directly to the template workbook** (`templates/{template_id}/{template_id}.xlsx` on `work_sheet`) — not a separate “save as copy” dialog. Same persist rules as **添加数据** for the active `draft` / `session_rows` before `write_back`.
  * **Excel output never embeds images** (`export_attach_images=off` for NiceGUI product — text/cells only). Pending/committed photos remain in `core_store` for UI reload only when independent-DB mode is on.
  * Non-export actions disabled when `verify_report.ok` is false.

* **打印**
  * Windows: `os.startfile(path, 'print')` from Python after user picks exported file + print area.
  * Other OS: `ui.download.file(path)` as fallback.
  * Print areas from `writer.get_print_areas(selected_xlsx)` using TOML `print_sheet`; print logic must not participate in TOML定位.
  * Before Windows print, copy export to a temp xlsx with `print_sheet` set as the active sheet (Excel prints the active sheet by default). The dropdown `打印区域` shows `print_sheet` and its `print_area` when defined; `selected_area` is informational — OS print does not accept a per-invocation area override.

### 3.2 Tab 2: Google Connection (`google_config` / `Google 连接`)

* **OAuth:** `ui.upload` or file picker for `oauth_client.json`; **选择授权文件** / **连接** / **删除** (wireframe); status via `AutoConnect`.
* **Connection status:** label updated on template activation when OAuth active and TOML `[[sources]]` contains sheet URLs.
* **Auto-reconnect:** template switch disconnects previous sheet context; reconnect if new template TOML has URLs. Edit sources only in `输入配置` tab.
* **Main ID sheet table:** `ui.table` with multi-select; `全选` / `取消全选` / `导入选中行`.
* **屏蔽所选数据:** link-style control (wireframe bottom-right of table toolbar) appends selected visible row primary IDs to `trash_ids` in `templates/{id}/{id}.history.json` and hides rows from the sheet table (see `nicegui_ui_connect.html`).
* **Import:** selected rows → `ui.persist_fields` → append to Input tab `session_rows` → switch to `输入` tab.

### 3.3 Tab 3: Input Config (`toml_config` / `输入配置`)

Wireframe: `nicegui_ui_toml.html`. Same `shell-top` / `shell-body` as index.

**In scope (wireframe):**

1. **校验与应用:** `校验并应用配置` → `verify_toml` + on success rebuild engines.
2. **高级（TOML 全文）:** `ui.codemirror` or `ui.textarea` + `保存` / `重置`.

**Out of scope (removed from this plan):** Gemma4「AI 配置向导」、页内 stepper / 对话框 / `docs/gemma4_e4b_workflow.md` W5 UI — deferred to a **separate future doc**; do not implement in NiceGUI v1 wireframe.

Optional later: manual cards for 基础 / 数据源 / 输入区段 / 字段映射 if needed without LLM wizard.

**校验配置:** `verify_toml(template_path, cfg)` — show `missing_labels`, `duplicate_labels`, `out_of_area_labels`, `errors`.

**TOML save后必须:**

1. Reload cfg
2. Re-run `verify_toml`
3. On failure: disable 输入 write actions; show report
4. On success: rebuild `UiProvider`, `Template2DB`, `ExcelWriter`; recompute `input_capacity = writer.max_instance_count(template_path)` (used for **independent-DB** session cap and 装载文件 cap only)
5. Clear `draft`, `field_images`, `current_instance_index`; clear or reload `session_rows` per mode:
   * **Independent DB:** `session_rows.clear()`, `current_instance_index = 0`, `draft` from `template_defaults`
   * **Template-as-DB:** `session_rows ← read_instances(template_path)`, `current_instance_index = len(session_rows)`, `draft` from next instance + formula mask
6. Refresh Input, DB, and TOML panels via `@ui.refreshable`

### 3.4 Tab 4: Storage Config (`db_config` / `存储配置`)

Wireframe: `nicegui_ui_db.html`. Same `shell-top` / `shell-body` as index.

* **当前数据库** section title row (wireframe `.section-title` flex row):
  * Left: title text **当前数据库**
  * Right: checkbox **「使用独立数据库」**, **checked by default** (`use_independent_db = true`).

  **Persistence (implemented):** value lives in **template TOML** as top-level `use_independent_db` (bool). On toggle: `session.cfg.use_independent_db = e.value` → `GetTomlValues.Save(template_id)` → `ForMain.load_template(...)`. Loaded on every activation via `load_toml` → `state.use_independent_db = cfg.use_independent_db`. **Not** stored in `app.storage.user`. See [`toml_config_design.md`](../toml_config_design.md).

  | `使用独立数据库` | DB behavior | Images | 「全部数据」 table |
  |------------------|-------------|--------|-------------------|
  | **Checked (default)** | Normal suffix DB files (`sample_template.A2026`, …); `切换` / `新建库` enabled per existing rules. | On **添加数据** / **保存**, pending `field_images` → `core_store.save_image` keyed by `template_id + record_id + input_label`. Reload via `get_latest_image`. | Shows all rows in the **active suffix database**. |
  | **Unchecked** | **弃用 SQLite**：不再打开/写入后缀库文件；**添加数据** / **保存** 将数据**直接写入模板 xlsx**（`ExcelWriter.write_back` → `templates/{template_id}/{template_id}.xlsx` 的 `work_sheet`，不经 `SecureSQLite`）。`切换` / `新建库` **disabled**。 | **Not saved** — skip `save_image`; discard pending photos on commit. | Title **「数据表已存数据」**；表格数据 **从模板 xlsx 读取**（见下）。**无「容量已满」**——录入不受 `input_capacity` 阻断（见 §3.1 **添加数据**）。 |

* **当前数据库 controls (checked mode only):** `ui.select` of `list_db_paths(template_id)`; `切换` enabled only when selection ≠ `active_db_suffix`; `新建库` → `allocate_next_db_path`.

* **全部数据 / 数据表已存数据** (`ui.table`; columns = TOML `Input_label` keys; optional leading **`#`** column = `instance_k`):

  | `use_independent_db` | Table data source | API |
  |----------------------|-------------------|-----|
  | **true (default)** | Active suffix SQLite | `ui_provider.get_data()` |
  | **false** | **Template xlsx on disk** | `ExcelWriter.read_instances(session.template_path)` — same instance-group semantics as Input tab; path is the **template file**, not `exports/` |

  Column-header sort: **view-only**; row identity = **`instance_k`** (template-as-DB) or DB `records.id` (independent DB). Template-store **覆盖保存** must target the selected row’s **`instance_k`**, not sorted row index.

  After **添加数据** / **保存** in template-store mode, refresh this table from `read_instances(template_path)` so the grid reflects what was written into the workbook.

* **Toggle「使用独立数据库」:** besides `render_db_tab.refresh()`, reload Input tab — independent DB → clear `session_rows` / reset index; template-as-DB → `session_rows ← read_instances(template_path)`, `current_instance_index = len(session_rows)`, reload `draft` + formula mask; call `render_input_tab.refresh()`.

* **覆盖录入:**
  * **Independent DB:** paste textbox + `覆盖保存` → `record_from_textbox` → overwrite selected SQLite row by ID.
  * **Template-store:** `覆盖保存` → merge paste into `draft` → `write_back` updating the selected instance row in **template xlsx** (no SQLite).

**Cross-reference:** image commit semantics and `record_images` schema — [`db_store.md`](../db_store.md) §4.2, §6.1. Store APIs must exist before wiring UI commit; OCR inference does not require store.

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
    # each row: {instance_k: int, Input_label: value, ...} — instance_k immutable; write_back uses k not sort order
    selected_instance_k: int | None = None
    selected_instance_indices: set = field(default_factory=set)  # members are instance_k, not sorted row index
    suppress_id_search: bool = False
    pending_id_value: int | None = None
    exported_files: list = field(default_factory=list)
    last_export_path: Path | None = None
    active_db_suffix: str | None = None
    use_independent_db: bool = True
    field_images: dict = field(default_factory=dict)
    # field_images[input_label] → {bytes, mime, preview_path?} — one pending photo per field
    # Google tab fields ...
```

**Storage scope:**

| Data | NiceGUI storage | Notes |
|------|-----------------|-------|
| `draft`, `session_rows`, engines | `SessionRegistry[principal_id]` (`SessionState`) | per principal; not in `app.storage.user` |
| Sidebar width / collapsed | `app.storage.user` (`Auth.pref_key`) | survives reload; needs `storage_secret` |
| `use_independent_db` per template | **`templates/{id}/{id}.toml`** (`use_independent_db` key) | default `true` if key absent; `GetTomlValues.Save` on DB-tab toggle |
| Visit counters, global flags | `app.storage.general` | optional |
| Ephemeral UI flags | `app.storage.client` or local variables | lost on reload |

Do **not** store a single shared `SessionState` at module level. A `SessionRegistry` dict keyed by `principal_id` is allowed.

Future permission limits: adjust grants on `user:admin` (or other accounts), not global flags that bypass `principal_id`.

### 4.2 Core boundaries (unchanged)

| Module | UI may | UI must not |
|--------|--------|-------------|
| `core_registry.py` | list/switch templates | scan outside `templates/` |
| `core_toml.py` | Load/Save/`verify_toml` | scan xlsx labels, guess coordinates |
| `core_store.py` | DB CRUD, text split, `save_image` / `get_latest_image` on commit | merge legacy JSON |
| `core_transform.py` | `max_instance_count`, `write_back`, print areas, source fetch | compute Excel coordinates in UI; **embed images in xlsx** |
| `paddle_ocr/` (`main.py`) | `PaddleOcr` from Input context menu **OCR** item | camera UI, crop overlay, `save_image`, SQLite, Excel export |

### 4.3 Template activation flow (unchanged semantics)

On sidebar click or initial load:

1. Resolve `template_id`, `template_path` from `SortTemplates`
2. `ensure_exists(template_id, template_path)`
3. `load_toml(template_id)` → `cfg.use_independent_db` (default true)
4. `verify_toml(template_path, cfg)`
5. If failed: show report; disable 输入/保存/添加数据/打印
6. If passed: open `default_db_path`, construct `SecureSQLite`, `UiProvider`, `Template2DB`, `ExcelWriter(cfg, located)`
7. `input_capacity = writer.max_instance_count(template_path)` — **independent-DB mode only** for **添加数据** cap and 装载文件 limit; template-as-DB does not use it to block entry
8. Reset session per `use_independent_db`:
   * **Independent DB:** `draft` / `session_rows` / `field_images` cleared; `current_instance_index = 0`; `draft` ← `template_defaults`
   * **Template-as-DB:** `session_rows ← read_instances(template_path)`; `current_instance_index = total_instance_count`（下一顺序 instance，非空位扫描）；`draft` ← `read_values(template_path, current_instance_index)` + formula mask；已有数据会显示在文本框，用户可自行覆盖；clear `field_images`
9. Refresh all `@ui.refreshable` sections; switch to tab `输入`

### 4.4 TOML model (unchanged)

Must use: `work_sheet`, `print_sheet` (optional), single `[[input_section]]`, `Input_label`, `value_from_label`, `value_offset`, `index`, `id`.

Forbidden: old `sections` model, UI-maintained area lists, UI coordinate math.

---

## 5. NiceGUI Component Mapping (Gradio → NiceGUI)

| Requirement | Gradio (problematic) | NiceGUI (recommended) |
|-------------|----------------------|------------------------|
| App shell | `gr.Row` + CSS overrides | `shell-top` row + `ui.splitter` in `shell-body`; fold chevron in header |
| Sidebar list | `gr.HTML` + JS click bridge | `ui.list` / `ui.button` + Python `on_click` |
| Resize / collapse | custom `#resize-rail` + `localStorage` + inline `!important` | `ui.splitter`（显示可越界；存储 clamp 20..400；默认 250）+ CSS hidden fold + `app.storage.user` |
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

1. **Spike shell:** `shell-top` (template name + fold + tabs) + `shell-body` `ui.splitter`; sidebar collapse + width persistence.
2. **Template activation:** port `activate_template()` logic; real data from `templates/*.xlsx` only.
3. **Input tab:** responsive `.field-grid`, autogrow textareas, ghost blur, ID dialog, session `ui.table`, **添加数据** / **保存** (text only first).
4. **DB tab:** `使用独立数据库` checkbox, switch/create DB, data table modes, 覆盖保存.
5. **TOML tab:** five sections, 校验配置, save + full session reset.
6. **Mobile pass:** portrait breakpoints, long-press menu, camera capture.
7. **Google tab:** OAuth + import table (no Gemma TOML wizard in NiceGUI v1).
8. **Input context menu (拍照 / OCR):** after `paddle_ocr` CLI smoke — session `field_images`, commit images on 添加数据/保存 per §3.4; **OCR** → `PaddleOcr`.
9. **Print / export polish:** print area dropdown, `ui.download.file` fallback; confirm **no images in xlsx**.
10. **HTTPS / TLS (§8.1):** `ensure_tls_certs()` before `ui.run`; OpenSSL on PATH; `certs/` gitignored; LAN camera smoke on `https://<LAN-IP>:8738`.

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

Use `ui.download.file` for exported xlsx when not printing. Use `ui.notify` for validation errors. **Capacity warnings apply only in independent-DB mode** (`current_instance_index >= input_capacity`).

---

## 8.1 HTTPS / TLS — 自签证书，启动时自动管理（方案 B）

**目标：** 局域网或其它非 `localhost` 访问时，浏览器将页面视为 **Secure Context**，从而允许 **拍照**（`getUserMedia`）。不依赖作者定期向用户「下发授权」；证书由程序在启动前自动检测并生成/续期。

**非目标：** 不向操作系统或浏览器静默安装受信任根 CA（需管理员权限，超出应用范围）；不使用 Let's Encrypt（内网 IP 无公网域名）；不将 `mkcert` 作为运行时依赖。

### 8.1.1 何时启用 HTTPS

| 访问方式 | HTTP | HTTPS |
|----------|------|-------|
| `http://localhost` / `127.0.0.1` | 允许拍照 | 允许 |
| `http://<LAN-IP>`（`host='0.0.0.0'`） | **禁止拍照** | 允许（自签即可） |

生产默认：`host='0.0.0.0'`，`port=8738`，**在证书就绪时**以 HTTPS 对外服务。

### 8.1.2 证书文件与配置

| 路径 | 说明 |
|------|------|
| `certs/server.key` | RSA 私钥（**不得提交 git**） |
| `certs/server.crt` | 自签服务器证书（**不得提交 git**） |
| `certs/san.txt`（可选） | 生成 SAN 用，例如写入：`subjectAltName=DNS:localhost,IP:127.0.0.1,IP:192.168.12.198` |

`.gitignore` 必须包含 `certs/`（或至少 `certs/*.key`、`certs/*.crt`）。

### 8.1.3 `ensure_tls_certs()` 行为（`nicegui_ui/ssl_manager.py`）

在 `ui.run()` **之前**调用；返回 `(cert_path, key_path)` 或 `None`（见失败策略）。

1. **缺失：** `server.crt` 或 `server.key` 任一不存在 → 调用 **OpenSSL** 生成新密钥对 + 自签证书。
2. **即将过期：** 解析 `server.crt` 的 `notAfter`；若已过期或剩余有效期 **< 30 天** → 自动续期（重新签发，默认再延长 **3650 天** / 约 10 年）。
3. **SAN：** 证书必须包含 Subject Alternative Name：`DNS:localhost`、`IP:127.0.0.1`，以及 `certs/san.txt` 里的局域网 IP（用 IP 访问时避免名称不匹配）。
4. **实现方式：** 优先 `subprocess` 调用系统 `openssl`（方案 B）；可选后续用 `cryptography` 库替代，行为保持一致。
5. **依赖：** `openssl` 须在 **PATH** 中；缺失时记录明确日志，见 §8.1.5。

**续期与用户操作：** 自动续期由本机完成，**无需作者向用户重新分发证书**。浏览器对自签证书的「继续访问」为**每台设备、每个浏览器配置文件**的一次性操作；在证书有效期内通常不再提示。若续期时**更换了密钥对**且用户未安装私有 CA，个别浏览器可能在首次访问新证时再次出现警告——可接受，仍无需作者介入。

### 8.1.4 `ui.run()` 集成

```python
from nicegui_ui.tls import ensure_tls_certs

ssl = ensure_tls_certs()  # -> (cert, key) | None

ui.run(
    host='0.0.0.0',
    port=8738,
    storage_secret='...',
    ssl_certfile=str(ssl[0]) if ssl else None,
    ssl_keyfile=str(ssl[1]) if ssl else None,
    ...
)
```

当 `ssl_certfile` 与 `ssl_keyfile` 均提供时，Uvicorn 自动以 **HTTPS** 监听（NiceGUI 将参数转发给 Uvicorn）。

用户访问：`https://<本机局域网 IP>:8738`（非 `http://`）。

### 8.1.5 失败与降级策略

| 条件 | 行为 |
|------|------|
| OpenSSL 不可用或生成失败 | 记录 error；**仍启动 HTTP**（`ssl_*` 为 `None`），保证本机 `http://localhost` 可用 |
| 仅本机开发 | 可设环境变量 `ETV_TLS_DISABLE=1` 跳过 HTTPS（可选，文档化即可） |

不得因证书失败而阻止整个应用启动（除非未来增加显式 `--require-tls` 运维开关）。

### 8.1.6 验收（TLS）

1. 删除 `certs/` 后启动应用 → 自动生成 `server.crt` / `server.key`。
2. 将 `server.crt` 的 `notAfter` 改为已过期（或 mock）后重启 → 自动重新签发，进程正常启动。
3. `https://localhost:8738` 与 `https://<LAN-IP>:8738` 可打开 UI；控制台 `window.isSecureContext === true`。
4. 在 Secure Context 下，输入页 **拍照** 可弹出摄像头权限（与 §3.1 OCR 菜单一致）。
5. 仓库中无 `certs/*.key` 被跟踪。

---

## 9. Forbidden Actions

* No runtime fallback templates or doc wireframe samples as data
* No UI-side Excel coordinate calculation
* No module-level unpartitioned session globals (use `SessionRegistry` + `principal_id`)
* No hidden textbox / JSON event bridges unless `ui.table` proves insufficient after spike
* No Gradio components in the NiceGUI app
* No loading templates from outside `templates/`
* No committing TLS private keys or generated `certs/server.{key,crt}` to the repository

---

## 10. Acceptance Criteria

1. Sidebar lists only `templates/*.xlsx` via `core_registry`; top bar shows selected template name; collapse hides list, leaves template name and expand chevron.
2. `shell-top` + `shell-body` `ui.splitter`: drag **display** may exceed 20..400; **stored** width clamped 20..400; default **250**; fold CSS hidden; expand restores stored (or 250).
3. Mobile portrait: field grid one column; **per-field `···` button** opens camera/OCR menu (not double-tap/long-press on textarea).
4. Desktop field grid: `auto-fill` ~400px cells; textareas autogrow vertically, scroll horizontally when needed.
5. Template activation always runs `verify_toml`; failure disables 输入 write/export/print.
6. Input fields from `ui.get_labels()`; primary key blur + dialog flow.
7. Session table: select, highlight, 删除选中 (two-step mode), 刷新数据; column-header sort **view-only** with stable **`instance_k`**; row click / write-back / delete by **`instance_k`**, not sorted index; optional `#` column; `move_to=left/right` ⇒ table row = sheet **column** instance. **Template-as-DB:** table preloaded from `read_instances`; formula fields readonly.
8. **添加数据** / **保存** persist text per mode; images only when `use_independent_db` (see `db_store.md`). **Independent DB:** cap at `input_capacity`. **Template-as-DB:** no cap; always **添加数据** when verify ok; `write_back` to template xlsx at `current_instance_index` (no empty-slot scan).
9. **保存** (independent DB): path under `exports/{template_id}/...`; **保存** (template-as-DB): writes template xlsx in place; **xlsx has no embedded images**.
10. DB tab: **使用独立数据库** default checked; unchecked → template xlsx read/write, table **数据表已存数据**, no images, no capacity-full on Input tab.
11. TOML save rebuilds engines and resets/reloads input session per storage mode (§3.3 step 5).
12. All coordinate math delegated to `core_transform` / `located`.
13. Context menu: **拍照** caches one photo per field; **OCR** → `PaddleOcr`; desktop **右键**; mobile **字段行末按钮**（非 textarea 双击/长按）; errors via `ui.notify`.
14. **TLS (§8.1):** missing or near-expired certs auto-regenerated via OpenSSL before `ui.run`; HTTPS on `0.0.0.0` when certs exist; `getUserMedia` works on `https://<LAN-IP>:8738` after user accepts self-signed warning once per browser profile.

---

## 11. Relationship to Existing Artifacts

| Artifact | Status |
|----------|--------|
| `docs/nicegui_ui/nicegui_ui_plan.md` | canonical UI specification (this document) |
| `docs/nicegui_ui/nicegui_ui_*.html` | wireframes; all tabs use `shell-top` + `shell-body`; `index` = field-grid + session table; `db` = §3.4 checkbox in section title |
| `docs/db_store.md` | image commit API + `record_images` schema; **§2.1** template-as-DB bypasses store; UI defers `save_image` until 添加数据/保存 (independent DB only) |
| `docs/excel_transform.md` | **§4.6** template-as-DB read/write + formula protection; **§4.6.5** `instance_k` + sheet row/column geometry |
| `plans/nicegui_ui_migration/` | Speckit plan / spec / tasks / constitution |
| `nicegui_ui/` | sole runtime UI package |
| `docs/embed_paddle_ocr.md` | OCR platform API; UI menu spec is **here** (§3.1) |
| `paddle_ocr/` | self-contained OCR; no UI; called by NiceGUI after CLI smoke |
| `webui/`, `docs/gradio_ui/`, Gradio deps | removed — do not restore |
