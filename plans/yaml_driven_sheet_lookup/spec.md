# YAML-Driven Google Sheet Lookup — Technical Specification (spec.md)

## 1. Core Mapping Logic and Data Parsing

We upgrade Google Sheet row mapping from relying on sidecar `column_mappings` to being fully driven by `*.paste.yaml` (spec §4 schema).

### 1.1 Extracting Lookup Parameters from YAML

Via a `paste_parse_config` instance:

1. **Form trigger field**
   The top-level YAML key whose rule includes `ID: true`. For example, `P.O. No.` has `ID: true`, so when the user types in the form’s `P.O. No.` input, automatic lookup is triggered.

2. **Sheet ID column**
   The `filed` property on the rule for that trigger field. For example, when YAML declares:

   ```yaml
   P.O. No.:
     - ID: true
       filed: "PO"
       index: 0
   ```

   the app searches Google Sheet column `PO` for the user-entered PO value.

### 1.2 Map Sheet Row to Form Fields

Given a Google Sheet row dict `row` (keys = column names, values = cell strings), convert it to form key/value pairs using rules in `.paste.yaml`:

```python
def map_sheet_row_from_paste_config(
    row: dict[str, str],
    config: PasteParseConfig,
) -> dict[str, str]:
```

For each form field (e.g. `Supplier`), iterate its rule list:

* Read the rule’s `filed` property (e.g. `"Supplier"`).
* Find a matching key in the Sheet `row` dict (loose match: ignore case and leading/trailing whitespace; prefer exact match first).
* If the Sheet `row` contains that key and the cell value is non-empty:
  * If the rule defines `regex`, extract with `_extract_with_regex(raw_value, regex)`.
  * Otherwise use the cell value as-is.
  * Format the result with `_format_field_value` (e.g. zero-pad MM/DD).
  * **Stop iterating rules for that field after the first successful extraction (first match wins).**

### 1.3 Dates and Special Formats

In the Ginger Lots scenario, the Sheet header is `"recv. date"` and the cell value may look like `"6/1"`.
The corresponding YAML rules are:

```yaml
MM:
  - filed: "recv. date"
    index: 12
    regex: '(\d{1,2})(?=\/\d{1,2})'
DD:
  - filed: "recv. date"
    index: 12
    regex: '(?<=\d{1,2}\/)(\d{1,2})'
Receiving Date:
  - filed: "recv. date"
    index: 12
    regex: '(\d{1,2}\/\d{1,2})'
```

* **MM** regex `(\d{1,2})(?=\/\d{1,2})` → matches `"6"` → formatted as `"06"`.
* **DD** regex `(?<=\d{1,2}\/)(\d{1,2})` → matches `"1"` → formatted as `"01"`.
* **Receiving Date** regex `(\d{1,2}\/\d{1,2})` → matches `"6/1"` → zero-padded to `"06/01"` (auto-combined as `"06/01/26"` in `template_form`, or year filled via `YY` rules).

## 2. Live Online Header Validation

To improve configuration robustness and catch Sheet header changes that break lookup, implement online validation in the **Data source** tab.

### 2.1 Validation Algorithm

```python
def validate_yaml_against_sheet_headers(
    config: PasteParseConfig,
    sheet_headers: list[str],
) -> dict[str, Any]:
```

1. Normalize all Sheet column names `sheet_headers` into a set `normalized_sheet` (strip + lowercase).
2. Iterate every top-level YAML field:
   * Skip manual fields where `filed` is `"?"` or `index` is `-1`.
   * For each `filed` that must match, normalize to lowercase and strip.
   * If found in `normalized_sheet`, mark as **Matched**.
   * If not found, mark as **Missing**.
3. Check whether the ID rule’s `filed` exists in `normalized_sheet`:
   * If not, show a strong warning that this Sheet cannot be used for ID lookup.

### 2.2 Online Validation UI

In the **Data source** tab:

* After the user clicks **Test connection** and preview data returns, load the current template’s `.paste.yaml` (if present).
* If YAML exists, call the validation method and show results via `st.dataframe` or `st.table`:
  * **Matched**: green check or “Match OK” plus the actual Sheet column name.
  * **Missing**: red warning or “Column not found in Sheet”.
* Before saving, if the YAML ID field (e.g. `"PO"`) is missing from Sheet headers, block **Save data source config** or show a strong warning so a broken lookup config is not persisted.

## 3. Canonical Ginger Lots Configuration

Complete and align Ginger Lots YAML mapping and sidecar lookup files with spec §4:

### 3.1 `templates/Ginger_Lots.paste.yaml`

```yaml
determiner: "tab"
order:
  - filed: "?"
    index: -1
YY:
  - filed: "?"
    index: -1
MM:
  - filed: "recv. date"
    index: 12
    regex: '(\d{1,2})(?=\/\d{1,2})'
DD:
  - filed: "recv. date"
    index: 12
    regex: '(?<=\d{1,2}\/)(\d{1,2})'
P.O. No.:
  - ID: true
    filed: "PO"
    index: 0
Container No.:
  - filed: "Container#"
    index: 4
Container Seal No.:
  - filed: "?"
    index: -1
Lot No.:
  - filed: "?"
    index: -1
Receiving Date:
  - filed: "recv. date"
    index: 12
    regex: '(\d{1,2}\/\d{1,2})'
Product Description:
  - filed: "?"
    index: -1
Supplier:
  - filed: "?"
    index: -1
Truck Line:
  - filed: "?"
    index: -1
```

### 3.2 `templates/Ginger_Lots.config.json`

Default Google Sheet connection for out-of-the-box use:

```json
{
  "display_name": "Ginger Lots",
  "description": "Ginger lots visualization entry template",
  "sheet_name": "",
  "header_row": 0,
  "data_start_row": 1,
  "data_source": {
    "sheet_url": "https://docs.google.com/spreadsheets/d/1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c/edit?gid=0#gid=0",
    "spreadsheet_id": "1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c",
    "worksheet_name": "",
    "id_column": "PO"
  }
}
```

*(Note: `spreadsheet_id` is extracted from the URL as `1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c`; empty worksheet uses the first worksheet, `gid=0`.)*
