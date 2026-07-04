# connect_google — implementation contract

Coding spec only. Scope is limited to one new module and its callers. Do not import or extend legacy modules (`data_source`, `google_sheets`, `import_history`, `excel_parser`, etc.) except `core_*`.

**Deliverable:** `app/core_connect.py` — **three public classes** (`ConnectGoogle`, `SheetOperation`, `AutoConnect`) plus **payload dataclasses** and two module functions (`load_trash_history`, `save_trash_history`). See **Types: classes vs payloads** below.

## Types: classes vs payloads

| Kind | Examples | Role |
|------|----------|------|
| **Public class** (behavior) | `ConnectGoogle`, `SheetOperation`, `AutoConnect` | Own state + methods: OAuth, load sheets, query memory, orchestrate connect for UI |
| **Payload `@dataclass`** (data only) | `GoogleSessionBundle`, `GoogleIdSheetTable`, `IdRow`, `FieldRecord`, `TemplateTrashHistory`, … | **Records** passed between layers — like C++ `struct` / DTO; no network, no UI |
| **Module function** | `load_trash_history`, `save_trash_history` | Thin file I/O for `{id}.history.json`; not a fourth public class |

The three classes **already provide** all Google connect behavior. Dataclasses exist because:

1. **Return types** — `AutoConnect.run()` returns one `GoogleSessionBundle` instead of many loose values.
2. **UI contract** — `tab_google.py` reads `session.google_table` without calling gspread or `ConnectGoogle` internals.
3. **Documented shapes** — `IdRow`, `SpreadsheetMeta`, etc. type list items and intermediate results; they are not separate services.

Do **not** add a fourth public class for trash history or for each payload type.

**UI split (NiceGUI):**

| Layer | File | Responsibility |
|-------|------|----------------|
| Service | `app/core_connect.py` | OAuth, connect/disconnect, `SheetOperation`, **`AutoConnect`** (模板激活 / 手动连接) |
| View | `nicegui_ui/pages/tab_google.py` | **Only** HTML5 `<table class="t">` rendering, row checkbox UX, button clicks; reads prepared payloads from session; **no** gspread / coordinate / regex logic |
| Orchestration | Existing template pipeline + `tab_google` handlers | 模板激活后若已授权则 `AutoConnect(conn).run(cfg, verify_ok=…)`；「连接」按钮同一路径 |

Legacy `templates/{id}/*.datasource.json` is **not** read by `core_*`; URLs and field mapping come **only** from TOML `[[sources]]` + `[[fields]]`.

---

## Scope boundary

| In scope | Out of scope |
|----------|--------------|
| OAuth authorize / connect / disconnect | `.datasource.json`, import history registry (legacy) |
| Multi-source Google Sheet read into memory (TOML `[[sources]]`) | Persist sheet data, edit TOML, write DB |
| TOML-driven field mapping (`GetTomlValues`) | Local xlsx (`core_transform.Template2DB`) |
| Session sync + table/import **payload** for UI (`AutoConnect`, `prepare_id_sheet_table`, `build_import_rows`) | NiceGUI component wiring, HTML5 DOM |
| **`templates/{id}/{id}.history.json`** — `trash_ids` only（Google 连接 Tab「屏蔽所选数据」） | `processed_ids` in history file (derive from DB query instead) |

**Allowed imports:** `core_toml` (`GetTomlValues`, `TomlDefault`), stdlib, `gspread`, `google-auth`, `google-auth-oauthlib`, `polars` (optional; list[dict] acceptable).

---

## TOML contract (input to connect)

Configuration comes **only** from `GetTomlValues` (loaded elsewhere via `GetTomlValues.Load(template_id)` or constructed in memory).

```toml
[[sources]]
source1 = "https://docs.google.com/spreadsheets/d/1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c/edit?gid=0#gid=0"
source2 = "https://docs.google.com/spreadsheets/d/OTHER_SPREADSHEET_ID/edit"

[[fields]]
Input_label = "ID#"
field = "ID"
source_file = "source1"
source_sheet = "Sheet1"
id = true

[[fields]]
Input_label = "Name"
field = "Name"
source_file = "source1"
source_sheet = "Sheet2"
# no id = true → inherits Sheet1 ID column for row lookup on Sheet2

[[fields]]
Input_label = "Score"
field = "Score"
source_file = "source2"
source_sheet = "Scores"
# cross-spreadsheet: same id_value joins source1 Sheet1 ↔ source2 Scores
```

Rules:

- `[[sources]]` is the **only** source of Google Sheet URLs. Each alias key (`source1`, `source2`, …) maps to a full URL (user-pasted elsewhere into TOML before `connect()`). Implementation parses spreadsheet id from URL internally; do not depend on `excel_parser`.
- the google sheet must start with `https://docs.google.com/spreadsheets/`, exclude other path or url.
- `connect(cfg)` opens **every source alias** referenced by `field_rules`; different aliases may point to **different spreadsheets** (multi-source).
- Empty or missing URL for a used alias → `ConnectGoogleError` at `connect()`.
- Each `[[fields]]` row may set `source_file` (alias key in `[[sources]]`) and `source_sheet` (worksheet tab name).
- Data column lookup per field: try `field` first, then `Input_label` (same as `_column_names_for_rule` in `core_transform.py`).
- Apply `regex` on cell value when non-empty (same semantics as `Template2DB.apply_regex`): use TOML **single-quoted** literal for patterns (e.g. `regex = '\d+/(\d+)'`); capture group 1 is returned when present.

### ID rules (per sheet)

Sheet key: `(source_file, source_sheet)`.

| Rule | Detail |
|------|--------|
| One ID per sheet | Each sheet has **at most one** `[[fields]]` row with `id = true`. More than one on the same sheet → `ConnectGoogleError` at `connect()`. |
| ID column name | On the `id=true` row: `field` if mapped, else `Input_label`. |
| Same ID value across sheets | One `id_value` may join rows on multiple sheets; lookup always uses the resolved ID column(s) for that sheet. |
| Inheritance | A sheet **without** its own `id=true` inherits ID lookup from all sheets that **do** have `id=true` (in TOML `field_rules` order, among sheets referenced by `field_rules`). |
| OR match | When a sheet inherits **multiple** ID columns (e.g. Sheet1 and Sheet2 both have `id=true`, Sheet3 has none), find a row where **any** inherited ID column equals `id_value`. First matching row wins. |
| Ambiguous source data | Duplicate IDs, OR matches multiple rows, or conflicting rows across sheets → **not** handled; treat as source-table design error. Implementation does not validate or dedupe. |
| At least one id | At least one sheet among all referenced `(source_file, source_sheet)` must have `id=true`; else `ConnectGoogleError` at `connect()`. |

**Inheritance example**

```
Sheet1  id=true  field="ID"     → defines ID column A
Sheet2  (no id)                 → lookup on Sheet2 uses column A
Sheet3  (no id)                 → lookup on Sheet3 uses column A

Sheet2  id=true  field="RefID"  → adds ID column B
Sheet3  (no id)                 → lookup on Sheet3: row where A=id_value OR B=id_value
```

**Private helper (same module)**

```python
def _resolve_id_columns(cfg, source_alias, source_sheet) -> list[str]:
    """Return ordered list of ID column names to try on this sheet (OR match)."""
```

Built once in `SheetOperation.__init__` or at `connect()` validation time → `dict[tuple[str,str], list[str]]` stored on `ConnectGoogle._id_columns_by_sheet`.

---

## OAuth persistence

Authorize **once**; reuse saved token on later runs. Only re-open browser when token missing, invalid without refresh, or revoked.

| File | Role |
|------|------|
| `credentials/oauth_client.json` | OAuth client JSON (`installed` or `web` key) |
| `credentials/authorized_user.json` | Authorized user token (written after first OAuth) |

Scope: `https://www.googleapis.com/auth/spreadsheets.readonly`

`authorize()` may write/read these files. `disconnect()` does **not** delete them.

### NiceGUI「Google 连接」tab controls

No separate「授权状态」readout; connection is implicit after「连接」or `AutoConnect.run()`.

| Control | Behavior |
|---------|----------|
| **选择授权文件** | Open OS file picker (`ui.upload` or native dialog); user picks OAuth client JSON → `ConnectGoogle.save_oauth_client(bytes)` → writes `credentials/oauth_client.json`. Enables「连接」. |
| **连接** | Disabled until `oauth_client.json` exists. On click: `authorize()` (browser OAuth on first run) → `AutoConnect(conn).run(session.cfg, verify_ok=…)` → refresh HTML5 id sheet table. |
| **删除** | `ConnectGoogle.cancel_auth()` — `disconnect()` + remove `oauth_client.json` and `authorized_user.json`; disable「连接」; clear table. |

Template activation: when `is_authorized()` and TOML verify passed, caller invokes `AutoConnect(conn).run(cfg, verify_ok=True)` automatically (no extra button press).

---

## Class: `ConnectGoogle`

Owns credentials, gspread client, per-source spreadsheet handles, and in-memory sheet tables loaded during `connect()`.

### Public methods on `ConnectGoogle`

| Method | Role |
|--------|------|
| `authorize()` | Desktop OAuth once; persist token |
| `connect(cfg)` | Load all referenced worksheets into memory |
| `disconnect()` | Drop in-memory tables; keep token |
| `is_authorized()` | Whether `credentials/oauth_client.json` + valid token exist |
| `save_oauth_client(bytes)` | Write client JSON (UI upload) |
| `cancel_auth()` | `disconnect()` + remove token and client files |

#### `authorize(self) -> None`

- Ensure OAuth client exists at `credentials/oauth_client.json`; if missing, raise `ConnectGoogleError`.
- Load `authorized_user.json` if present and valid.
- If expired but refreshable, refresh and rewrite token file.
- If no valid credentials, run desktop OAuth (`InstalledAppFlow`, local server, open browser), then save token.
- Store credentials on `self._credentials`.

#### `connect(self, cfg: GetTomlValues) -> None`

Preconditions: `authorize()` has succeeded (or call `authorize()` internally if credentials absent).

All spreadsheet URLs come from `cfg.sources` (TOML only). No separate `sheet_url` argument.

Steps:

1. Validate `cfg` ID rules (see **ID rules**): per-sheet at most one `id=true`; at least one sheet has `id=true`; build `_id_columns_by_sheet` and `_primary_id_sheet`.
2. Collect unique `source_alias` values from all `field_rules` where both `source_file` and `source_sheet` are mapped.
3. For each `source_alias`, resolve URL via `cfg.sources`; parse spreadsheet id; open via gspread. Store in `self._spreadsheets`:

```python
# self._spreadsheets: dict[str, SpreadsheetMeta]
# key = source_alias (e.g. "source1")
@dataclass
class SpreadsheetMeta:
    source_alias: str
    url: str
    spreadsheet_id: str
    title: str
    handle: gspread.Spreadsheet  # or keep client + id only if preferred
```

4. Collect unique `(source_alias, source_sheet)` pairs from `field_rules`.
5. For each pair, load worksheet tab `source_sheet` from `self._spreadsheets[source_alias]` via `get_all_values()`.
6. Store rows in memory:

```python
# self._tables: dict[tuple[str, str], list[dict[str, str]]]
# key = (source_alias, source_sheet_name)
# value = rows as dicts; first row of sheet = column headers
```

7. Set `self._connected = True`, `self._cfg = cfg`.

Does **not** construct `SheetOperation`. Caller does that after `connect()`.

#### `disconnect(self) -> None`

- Clear `self._tables`, `self._spreadsheets`, `self._id_columns_by_sheet`, `self._primary_id_sheet`, `self._cfg`, connection flags.
- Keep `self._credentials` and token files intact.
- Set `self._connected = False`.
- **UI must call before every template switch** so the next `connect(cfg)` loads only the new template’s sources (no stale spreadsheet memory).

### Internal state (for `SheetOperation` read access)

| Attribute | Type | Meaning |
|-----------|------|---------|
| `_connected` | `bool` | Whether `connect()` completed |
| `_cfg` | `GetTomlValues \| None` | TOML used at connect |
| `_spreadsheets` | `dict[str, SpreadsheetMeta]` | One open spreadsheet per used source alias |
| `_tables` | `dict[tuple[str,str], list[dict[str,str]]]` | Loaded worksheet data |
| `_id_columns_by_sheet` | `dict[tuple[str,str], list[str]]` | Resolved ID column names per sheet (OR list) |
| `_primary_id_sheet` | `tuple[str, str]` | First `(source_file, source_sheet)` with own `id=true` in TOML order; used for `list_ids` / UI id sheet |

Expose read-only properties or package-private accessors for `SheetOperation` in the same module (no extra public methods on `ConnectGoogle`).

---

## Class: `SheetOperation`

Read-only view over `ConnectGoogle` memory. **No file I/O. No network.**

### Constructor

```python
def __init__(self, conn: ConnectGoogle) -> None
```

- Raise `ConnectGoogleError` if `not conn._connected` or `conn._cfg is None`.

### Public methods

#### `list_ids(self) -> list[IdRow]`

Build ID list for UI multi-select (HTML5 renders this; this class only returns data).

- Use `_primary_id_sheet` → table in `conn._tables`.
- Use first ID column in `_id_columns_by_sheet[primary]` (the sheet’s own `id=true` column).
- For each data row with non-empty ID cell, append:

```python
@dataclass
class IdRow:
    id_value: str           # stripped string
    source_alias: str       # primary id sheet source_file
    source_sheet: str       # primary id sheet source_sheet
    row_index: int          # 0-based index in that sheet (excluding header)
```

- Skip blank ID cells. Keep duplicate `id_value` rows if present (source data issue).

#### `fetch_fields(self, id_values: list[str]) -> FetchFieldsResult`

Primary payload after user multi-selects IDs (import path).

**Step 0 — shallow copy primary id sheet**

Use `_primary_id_sheet` → `(source_alias, source_sheet)`. Shallow-copy that table for UI HTML5 display:

```python
sheet_rows = list(conn._tables[_primary_id_sheet])
```

**Steps 1–3 — per requested `id_value`**

1. Resolve row on primary id sheet using primary sheet’s own ID column (first in `_id_columns_by_sheet[primary]`). If not found → `FieldRecord.found = False`, empty `data`.
2. If found on primary sheet → for **every** mapped `field_rules` entry with `source_file` + `source_sheet`:
   - Target table: `conn._tables[(source_file, source_sheet)]`.
   - ID lookup on that sheet: `_id_columns_by_sheet[(source_file, source_sheet)]` — match row where **any** listed ID column equals `id_value` (OR). First matching row wins.
   - Map column → value using `field` then `Input_label`.
   - Apply `regex` if set.
   - Set `data[Input_label] = value`. Missing row on a sheet → leave that `Input_label` absent or empty string (do not fail whole record).

Return:

```python
@dataclass
class FieldRecord:
    id_value: str
    found: bool             # True if matched on primary id sheet
    source_alias: str       # _primary_id_sheet source_file
    source_sheet: str       # _primary_id_sheet source_sheet
    row_index: int | None   # index in sheet_rows (primary sheet)
    data: dict[str, Any]    # keys = Input_label only


@dataclass
class FetchFieldsResult:
    sheet_rows: list[dict[str, str]]   # shallow copy; primary id sheet; UI table
    source_alias: str
    source_sheet: str                  # primary id sheet name
    records: list[FieldRecord]
```

`fetch_fields` shallow-copies **only** the primary id sheet. Other sheets are read from `conn._tables` for field lookup only.

#### `prepare_id_sheet_table(self) -> GoogleIdSheetTable`

Prepare HTML5 table data for `tab_google.py` (no network).

- Shallow-copy primary id sheet rows from `conn._tables[_primary_id_sheet]`.
- `columns`: primary ID column first, then remaining header keys from row 0 (sheet column order).
- Return `GoogleIdSheetTable(columns, rows, id_column, source_alias, source_sheet)`.

#### `build_import_rows(self, id_values: list[str]) -> list[dict[str, Any]]`

Prepare DB import rows for the UI caller.

- Internally calls `fetch_fields(id_values)`.
- Return `[rec.data for rec in result.records if rec.found]` — keys are **Input_label** only; caller passes each dict to `UiProvider.persist_fields` and appends to `session_rows`.

---

## Class: `AutoConnect`

Template activation and manual「连接」orchestration. **All auto-connect logic lives in this class.**

### Constructor

```python
def __init__(self, conn: ConnectGoogle) -> None
```

### Public methods

#### `cfg_has_google_sources(cfg: GetTomlValues) -> bool` (static)

True when a `field_rules`-referenced alias has a `[[sources]]` URL starting with `https://docs.google.com/spreadsheets/`.

#### `run(self, cfg: GetTomlValues, *, verify_ok: bool) -> GoogleSessionBundle`

Single entry point. Called:

1. **Automatically** after template is activated, when `conn.is_authorized()`.
2. **Manually** when the user clicks「连接」on the Google 连接 tab.

Steps:

```
AutoConnect(conn).run(cfg, verify_ok):
  conn.disconnect()                                    # always drop stale _tables
  if not verify_ok or not conn.is_authorized():
      return disconnected_bundle
  if not AutoConnect.cfg_has_google_sources(cfg):
      return disconnected_bundle
  conn.connect(cfg)                                    # load all TOML-required worksheets
  op = SheetOperation(conn)
  table = op.prepare_id_sheet_table()                  # UI preview sheet (see below)
  return GoogleSessionBundle(status=..., table=table, operation=op)
```

**Which worksheet the HTML5 table shows** (`prepare_id_sheet_table`):

| TOML | Table source |
|------|----------------|
| At least one `id=true` | `_primary_id_sheet` — first `(source_file, source_sheet)` with own `id=true` in TOML order |
| No `id=true` (edge / future) | First `(source_file, source_sheet)` pair required by `field_rules` in TOML order |

`connect()` still loads **every** distinct `(source_alias, source_sheet)` referenced by `field_rules`; the table only previews one sheet (id sheet preferred).

#### `apply_bundle(session, bundle: GoogleSessionBundle) -> None` (static)

Copy `status` / `table` / `operation` onto NiceGUI `SessionState` fields (`google_connected`, `google_table`, `google_op`, `google_selected_ids`, …).

**NiceGUI caller** (after template pipeline sets `cfg` and `verify_ok`):

```
activator = AutoConnect(session.connect_google)
if session.connect_google.is_authorized():
    bundle = activator.run(session.cfg, verify_ok=session.verify_ok)
else:
    bundle = activator.run(session.cfg, verify_ok=False)
AutoConnect.apply_bundle(session, bundle)
```

`tab_google.py` **only** reads `session.google_status` and `session.google_table` to paint HTML5; it calls `session.google_op.build_import_rows(selected_ids)` on import, then `ui_provider.persist_fields` per row.

### Payload dataclasses (same module)

```python
@dataclass
class GoogleConnectionStatus:
    authorized: bool
    connected: bool
    status_text: str          # e.g. "已连接 · source1 / Containers · 12 行"
    primary_sheet_text: str   # e.g. "source1 / Containers"
    row_count: int
    error: str | None = None

@dataclass
class GoogleIdSheetTable:
    columns: list[str]
    rows: list[dict[str, str]]
    id_column: str
    source_alias: str
    source_sheet: str

@dataclass
class GoogleSessionBundle:
    status: GoogleConnectionStatus
    table: GoogleIdSheetTable | None
    operation: SheetOperation | None

@dataclass
class TemplateTrashHistory:
    template_id: str
    trash_ids: list[str]
    last_import: str | None = None
```

---

## Exceptions

```python
class ConnectGoogleError(Exception):
    def __init__(self, message: str, hints: list[str] | None = None): ...
```

Use for: missing OAuth client, auth failure, bad URL, spreadsheet not found, permission denied, worksheet not found, TOML id rule invalid, connect while not authorized.

---

## Call sequence (NiceGUI / CLI)

### Per template session

```
conn = ConnectGoogle()          # reuse on session.connect_google across template switches
conn.authorize()                # once per app session if needed
conn.connect(cfg)               # cfg for current template; URLs from cfg.sources only
op = SheetOperation(conn)
# ... list_ids / fetch_fields / import to DB ...
conn.disconnect()               # REQUIRED before switching template; token remains
```

### Template activation (auto-connect)

```
on_template_activated(cfg, verify_ok):
  # ... existing template pipeline (load TOML, verify, rebuild db/writer, etc.) ...
  activator = AutoConnect(conn)
  bundle = activator.run(cfg, verify_ok=verify_ok)
  AutoConnect.apply_bundle(session, bundle)
  render_google_tab.refresh()
```

Every template switch must `disconnect()` first (inside `AutoConnect.run()`), so the next connect never keeps the previous template's spreadsheet memory.

### Manual connect (`tab_google`「连接」button)

```
activator = AutoConnect(conn)
bundle = activator.run(session.cfg, verify_ok=session.verify_ok)
AutoConnect.apply_bundle(session, bundle)
render_google_tab.refresh()
```

`AutoConnect.cfg_has_google_sources(cfg)`: at least one `field_rules` entry references a `source_file` whose `[[sources]]` value starts with `https://docs.google.com/spreadsheets/`. Local xlsx-only templates skip `connect()`.

Caller responsibility: TOML `[[sources]]` URLs are edited on「输入配置」tab. **Do not** read `*.datasource.json`.

### Import selected rows (`tab_google` handler)

Each imported row must **start from template defaults** (`session.template_defaults`, read from the active xlsx template at activation), then overlay Google-fetched `Input_label` values. Fields present only in the template (no Google mapping) keep their default cell values.

```
defaults = dict(session.template_defaults)   # writer.read_values(template_path, 0)
ids = session.google_selected_ids
rows = session.google_op.build_import_rows(list(ids))
for incoming in rows:
    merged = {**defaults, **incoming}       # Google values override same keys
    session.ui_provider.persist_fields(merged)
    session.session_rows.append(dict(merged))
render_input_tab.refresh()
```

`build_import_rows` returns only TOML-mapped keys from Sheets; **caller** (`tab_google` handler) is responsible for merging `template_defaults` before persist.

### 屏蔽列表 (`trash_ids` / `{template_id}.history.json`)

`trash_ids` 用于**避免大量无关数据涌入**主 ID 工作表：用户将不需要的主 ID 记入此列表后，对应行不再显示（与已入库 ID 的隐藏规则并列）。

Path: `templates/{template_id}/{template_id}.history.json`

```json
{
  "template_id": "Ginger_Lots",
  "trash_ids": ["10034"],
  "last_import": "2026-06-15T07:56:43.810003"
}
```

| Field | Rule |
|-------|------|
| `trash_ids` | 用户屏蔽的主 ID 列表；表中这些 ID 的行**不显示**，避免无关 Sheet 行占用界面 |
| `processed_ids` | **Removed** — do not read or write;「已导入」IDs come from `session.db.query_by_id()` at render time |
| `last_import` | Optional ISO timestamp; updated when「导入选中行」succeeds |

**UI** (`tab_google.py`, bottom-right of 主 ID 工作表 section): button **屏蔽所选数据** — 将当前勾选的可见行主 ID **追加**到 `trash_ids`，经 `load_trash_history` / `save_trash_history` 写回 JSON，并刷新表（已屏蔽行隐藏）。须先勾选至少一行。

Row visibility when rendering `session.google_table`:

```
visible_row(id) =
    id not in trash_ids
    and session.db.query_by_id(normalize(id)) is None   # already in DB → hide
```

---

## UI behavior (implemented targets)

| Item | Behavior |
|------|----------|
| Google row checkbox | On check: merge `template_defaults` + `build_import_rows([id])` into `session.draft`; refresh「输入」Tab |
| Section title | User label **主 ID 工作表** only; not draggable |
| Import | `{**template_defaults, **incoming}` before persist |
| Block selected | Bottom-right **屏蔽所选数据** → append checked IDs to `trash_ids` in `{id}.history.json` |

---

---

## Implementation notes

- Parse spreadsheet id locally: `re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", url)` or accept bare id string.
- `_resolve_source_url(cfg, source_alias) -> str` — lookup alias in `cfg.sources`; raise if empty/missing.
- `_open_spreadsheet(client, url) -> SpreadsheetMeta` — parse id, open, return meta.
- Header row: first row of `get_all_values()`; remaining rows are data.
- Cell values: keep as strings (strip for ID compare); match ID with string equality after strip (optional numeric normalization same as `core_transform._find_row_by_id`).
- `_find_row_by_id_columns(rows, id_columns, id_value)` — OR match across `id_columns`; first row wins.
- `_resolve_id_columns(cfg)` — build `_id_columns_by_sheet` and `_primary_id_sheet`.
- `connect()` opens **all** distinct source aliases referenced by `field_rules`, then loads **all** distinct `(source_alias, source_sheet)` worksheets. Same alias → one gspread open; different aliases → different spreadsheets concurrently in memory.
- Cross-spreadsheet join: `fetch_fields` uses `(source_alias, source_sheet)` on each field rule; ID inheritance is per sheet key, not per spreadsheet.
- Public classes: `ConnectGoogle`, `SheetOperation`, **`AutoConnect`**. Payload dataclasses are not public classes.
- `tab_google.py` must not call gspread, parse URLs, or apply regex; only render `GoogleIdSheetTable` as HTML5 `<table class="t">`.
- Section user title: **主 ID 工作表** only (no parenthetical dev notes in the label).
- Import: merge `session.template_defaults` before `persist_fields` (see **Import selected rows**).

---

## File map

| File | Contents |
|------|----------|
| `app/core_connect.py` | `ConnectGoogle`, `SheetOperation`, **`AutoConnect`**, `load_trash_history`, `save_trash_history`, payload dataclasses |
| `app/core_toml.py` | TOML load/query (existing; import only) |
| `nicegui_ui/pages/tab_google.py` | 授权按钮 + HTML5 表 + 屏蔽所选数据 + import；consumes `SessionState.google_*` |
| `templates/{id}/{id}.history.json` | `trash_ids` only（「屏蔽所选数据」写入）；`processed_ids` 废弃 |
