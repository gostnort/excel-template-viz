# connect_google — implementation contract

Coding spec only. Scope is limited to one new module and its callers. Do not import or extend legacy modules (`data_source`, `google_sheets`, `import_history`, `excel_parser`, Gradio components, etc.) except `core_*`.

**Deliverable:** `app/services/core_connect.py` — contains exactly two public classes: `ConnectGoogle`, `SheetOperation`.

---

## Scope boundary

| In scope | Out of scope |
|----------|--------------|
| OAuth authorize / connect / disconnect | `.datasource.json`, import history, template registry |
| Multi-source Google Sheet read into memory (TOML `[[sources]]`) | Persist sheet data, edit TOML, write DB |
| TOML-driven field mapping (`GetTomlValues`) | Local xlsx (`core_transform.Template2DB`) |
| Return ID list + id-sheet shallow copy + TOML field data for UI | HTML5 UI implementation |

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
- `connect(cfg)` opens **every source alias** referenced by `field_rules`; different aliases may point to **different spreadsheets** (multi-source).
- Empty or missing URL for a used alias → `ConnectGoogleError` at `connect()`.
- Each `[[fields]]` row may set `source_file` (alias key in `[[sources]]`) and `source_sheet` (worksheet tab name).
- Data column lookup per field: try `field` first, then `Input_label` (same as `_column_names_for_rule` in `core_transform.py`).
- Apply `regex` on cell value when non-empty (same semantics as `Template2DB.apply_regex`).

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
| `app/oauth/oauth_client.json` | OAuth client JSON (`installed` or `web` key) |
| `app/oauth/authorized_user.json` | Authorized user token (written after first OAuth) |

Scope: `https://www.googleapis.com/auth/spreadsheets.readonly`

`authorize()` may write/read these files. `disconnect()` does **not** delete them.

---

## Class: `ConnectGoogle`

Owns credentials, gspread client, per-source spreadsheet handles, and in-memory sheet tables loaded during `connect()`.

### Public methods (only these three)

#### `authorize(self) -> None`

- Ensure OAuth client exists at `app/oauth/oauth_client.json`; if missing, raise `ConnectGoogleError`.
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

Primary UI payload after user multi-selects IDs.

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

---

## Exceptions

```python
class ConnectGoogleError(Exception):
    def __init__(self, message: str, hints: list[str] | None = None): ...
```

Use for: missing OAuth client, auth failure, bad URL, spreadsheet not found, permission denied, worksheet not found, TOML id rule invalid, connect while not authorized.

---

## Call sequence (reference for Gradio / CLI)

### Per template session

```
conn = ConnectGoogle()          # reuse same instance in gr.State across templates
conn.authorize()                # once per app session if needed
conn.connect(cfg)               # cfg for current template; URLs from cfg.sources only
op = SheetOperation(conn)
# ... list_ids / fetch_fields / import to DB ...
conn.disconnect()               # REQUIRED before switching template; token remains
```

### Template switch (UI orchestration)

```
on_template_change(new_template_id):
  connect_google.disconnect()           # always; drop old _tables / _spreadsheets
  sheet_operation = None
  google_connected = False
  cfg = Load(new_template_id)
  verify_toml(...)
  if authorized and cfg_has_google_sources(cfg):
      connect_google.connect(cfg)       # new TOML sources / sheets
      sheet_operation = SheetOperation(connect_google)
      google_connected = True
      render_google_tab_table()
  else:
      show_disconnected_state()
```

`cfg_has_google_sources(cfg)`: at least one `field_rules` entry references a `source_file` whose `[[sources]]` value looks like a Google Sheet URL (contains `docs.google.com/spreadsheets` or bare spreadsheet id). Local xlsx-only templates skip `connect()`.

Caller responsibility (out of scope for this module): UI writes Google URLs into TOML `[[sources]]` on the input-config tab before connect.

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
- Do not add a third public class. Helper dataclasses (`IdRow`, `FieldRecord`, `FetchFieldsResult`, `SpreadsheetMeta`) and private functions stay in the same file.

---

## File map

| File | Contents |
|------|----------|
| `app/services/core_connect.py` | `ConnectGoogle`, `SheetOperation`, `ConnectGoogleError`, `IdRow`, `FieldRecord`, `FetchFieldsResult`, `SpreadsheetMeta` |
| `app/services/core_toml.py` | TOML load/query (existing; import only) |

No other files are modified by this spec unless a caller wires Gradio later (out of scope here).
