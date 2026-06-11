# YAML-Driven Google Sheet Lookup — Task List (tasks.md)

Priority: P0 = highest; blocking for core functionality.

---

## Phase 1: Mapping and Parsing Engine (P0)

### [ ] Task 1.1 — Core parse API
* In `app/services/paste_parse_config.py`, implement `id_column_from_config(config: PasteParseConfig) -> str | None`:
  - Iterate all `field_rules`.
  - Find the first rule with `id_flag=True` and `filed` not `None`, `""`, or `"?"`.
  - Return that rule’s `filed` value.

### [ ] Task 1.2 — Sheet row → form fields
* In `app/services/paste_parse_config.py`, implement `map_sheet_row_from_paste_config(row: dict[str, str], config: PasteParseConfig) -> dict[str, str]`:
  - Accept a Sheet row dict (e.g. `{"PO": "10073", "Supplier": "Shandong Santao"}`) and `PasteParseConfig`.
  - Build a loose-match index: normalize Sheet keys with `strip()` and lowercase.
  - For each form field:
    * Iterate rules; skip `filed == "?"` or `index == -1`.
    * Loose-match Sheet column names. If a non-empty value is found:
      + If `regex` is set, parse with `_extract_with_regex(raw_value, regex)`.
      + Otherwise use the raw value.
      + Format with `_format_field_value(field_name, extracted_value)`.
      + **Stop after first hit** for that field (first match wins).
  - Return the parsed form dict.

### [ ] Task 1.3 — Live header validation
* In `app/services/paste_parse_config.py`, implement `validate_yaml_against_sheet_headers(config: PasteParseConfig, sheet_headers: list[str]) -> dict[str, Any]`:
  - Build normalized header map: `{h.strip().lower(): h for h in sheet_headers}`.
  - For every non-`"?"` `filed` in YAML:
    * If matched, add to `matched`.
    * If not found, add to `missing`.
  - Special check: ID rule `filed` must be in headers; set `id_matched = False` if not.
  - Return: `{"matched": dict, "missing": list, "id_matched": bool}`.

---

## Phase 2: Data Entry Tab Wiring (P0)

### [ ] Task 2.1 — Refactor `_apply_sheet_lookup`
* In `app/components/template_form.py`, update `_apply_sheet_lookup`:
  - Load `.paste.yaml` via `load_paste_parse_config(config.id)`.
  - If present and ID rule exists, use its `filed` as `id_column`.
  - Otherwise fall back to `data_source.id_column`.
  - Call `fetch_row_by_id`.
  - On row `row`:
    * **Primary**: if YAML exists, `map_sheet_row_from_paste_config(row, paste_config)`.
    * **Fallback**: else `sheet_row_to_form_fields(row, id_column, mappings=mappings)`.
  - Merge with existing `merge_parsed_into_headers` and refresh session state.

### [ ] Task 2.2 — Auto-lookup hint copy
* In `app/components/template_form.py`, update `_render_form_entry_tab` caption:
  - Prefer YAML for trigger form field (`id_field`) and Sheet ID column.
  - Show an accurate linked description for user clarity.

---

## Phase 3: Online Header Validation UI (P1)

### [ ] Task 3.1 — Render validation table
* In `app/components/data_source_settings.py`, `render_data_sources_tab`:
  - After successful **Test connection** (headers cached in session state), load `.paste.yaml`.
  - If valid, call `validate_yaml_against_sheet_headers`.
  - Render with `st.table` or `st.dataframe`:
    * Matched: green **Aligned** + actual Sheet header.
    * Missing: yellow **Not found in Sheet**.
    * ID column: red blocking warning if ID `filed` is missing.

### [ ] Task 3.2 — Auto-select ID column
* In `data_source_settings.py`, ID column dropdown:
  - After test pass, if YAML defines ID `filed`, pre-select that column in the dropdown.

---

## Phase 4: Ginger Lots Template Config (P1)

### [ ] Task 4.1 — Complete Ginger Lots YAML
* Update `templates/Ginger_Lots.paste.yaml` per spec §4 for all core fields (truck line `Terminal`, supplier `Supplier`, product `Product`, etc.).
* Ensure Sheet-aligned `filed` names (`BL#`, `Com. Inv #`, `Terminal`, etc.).

### [ ] Task 4.2 — Default Ginger Lots sidecar
* Create `templates/Ginger_Lots.config.json`.
* Embed read-only test Sheet: `https://docs.google.com/spreadsheets/d/1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c/edit?gid=0#gid=0`.
* Default ID column: `PO`.

---

## Phase 5: Testing and Acceptance (P0)

### [ ] Task 5.1 — Engine unit/static checks
* Mock row data + YAML; offline exercise `map_sheet_row_from_paste_config` and `validate_yaml_against_sheet_headers` without live Google credentials.

### [ ] Task 5.2 — E2E with real network
* Run Streamlit; authorize Google (OAuth or service account).
* Ginger Lots **Data source**: **Test connection** — preview OK, YAML header validation all matched.
* Ginger Lots **Data entry**: enter `10073`, wait — full row filled correctly from Sheet via YAML parsing.

---

## Task dependency sketch

```
Phase 1 (parse/validate core) ──► Phase 2 (data entry) ──┐
          │                                               ├──► Phase 5 (acceptance)
          └──► Phase 3 (validation UI) ──► Phase 4 ───────┘
```
