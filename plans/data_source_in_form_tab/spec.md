# Paste-split YAML specification

## 1. Core relationship (required reading)

```
Form fields below (template columns)
        ↑ split & write
Pasted TSV row
        ↑ paste-split YAML (determiner + index + regex)
Paste-split YAML (only schema — see §4)
        ↑ Phi-3.5 multimodal model fills mapping ("vLLM" in docs)
「Paste mapping」tab: screenshot / text → generate & save YAML
「Data entry」tab: paste source → Parse & fill (requires saved YAML)
```

* **YAML is the only split authority**; replaces legacy `.paste.yaml` and `paste_mapping_infer`.
* **Phi-3.5 Vision** (`app/vllm/`, OpenVINO) is **vLLM** in this project: fills the YAML mapping from screenshots, not Excel.
* **「Paste mapping」** exists only to configure **「Data entry」→ source paste**.
* **「Data source」** tab still configures Google Sheet; `ID: true` in YAML triggers lookup when that field is filled.

### TSV fixture (Ginger source row)

```text
10073	GIN	Shandong Santao	S26167FG	EMCU5484116	140601104991	5/9	5/30	$2,612	rel	everport	6/2	6/1	600000 Fresh Ginger, China. (F7)	1780	57294
```

**0-based** columns: `0=PO, 2=Supplier, 4=Container#, 12=recv date (6/1), 13=Product, …`

See `implementation_context.md` for full column table and screenshot markdown.

---

## 2. User stories

### P1: Phi-3.5 generates paste-split YAML
* In **Paste mapping**, paste a screenshot; Phi-3.5 fills YAML describing how each template field maps to source columns.
* Output matches §4; `index` is **0-based**; unknown source header → `filed: "?"`; no mapping → omit or empty.

### P2: Split pasted TSV into form
* In **Data entry**, paste a TSV line, click **Parse & fill**.
* Regex runs on full cell text; no fixed prefix (e.g. `pickup`) required.
* Failed or empty extractions do **not** overwrite manual input.

### P3: ID field + data source
* `ID: true` on a template field triggers Google Sheet lookup (existing behavior).

---

## 3. Functional requirements

### FR-001: YAML structure (§4 is canonical)
* `determiner`: separator when no per-field `regex`; default `"tab"`.
* Optional `order`: discovered source headers (`filed` + `index`).
* Each **template field name** is a top-level key; rules contain `filed`, `index` (0-based), optional `regex`, optional `ID: true`.

### FR-002: Phi-3.5 fills YAML
* Input: template field list + screenshot (or text sample).
* Output: §4 structure only; model fills **mapping rules**, not business row values.
* Weights: `app/vllm/phi-3.5-vision-instruct-int4-ov`.

### FR-003: Split strategy
* Parse & fill disabled until YAML is saved.
* Success → write form cell; failure → warn, keep existing value.

### FR-004: Persistence
* `templates/<template_id>.paste.yaml` (new schema, same filename).

### FR-005: Dates
* `MM` / `DD` / `Receiving Date` / `YY` may share one source `index` with different `regex`.
* Multi-date cells: first regex match wins.

---

## 4. YAML sample (single reference)

```yaml
determiner: "tab"
order:
  - filed: "PO"
    index: 0

YY:
  - filed: "ETA"
    index: 7
    regex: "(\\d{2})\\/(\\d{2})"

MM:
  - filed: "Receiving Date"
    index: 12
    regex: "(\\d{1,2})(?=\\/\\d{1,2})"

DD:
  - filed: "Receiving Date"
    index: 12
    regex: "(?<=\\d{1,2}\\/)(\\d{1,2})"

P.O. No.:
  - ID: true
    filed: "PO"
    index: 0

Container No.:
  - filed: "Container#"
    index: 4

Container Seal No.:
  - filed: "BL#"
    index: 5

Lot No.:
  - filed: "Com. Inv #"
    index: 3

Receiving Date:
  - filed: "Receiving Date"
    index: 12
    regex: "(\\d{1,2}\\/\\d{1,2})"

Product Description:
  - filed: "Product"
    index: 13

Supplier:
  - filed: "Supplier"
    index: 2

Truck Line:
  - filed: "Terminal"
    index: 10
```

### Split example (fixture row → form)

| Template field | Rule | Result |
|----------------|------|--------|
| P.O. No. | index 0 | 10073 |
| Supplier | index 2 | Shandong Santao |
| Container No. | index 4 | EMCU5484116 |
| MM / DD | index 12 + regex | 06 / 01 |
| Receiving Date | index 12 + regex | 06/01 |
| Product Description | index 13 | 600000 Fresh Ginger, China. (F7) |

---

## 5. Non-functional

* **0-based** `index` everywhere; Phi-3.5 prompts in **English**, state index starts at 0.
* Paths: `pathlib.Path`.
* Model weights under `app/vllm/` only.

---

## 6. Decisions (final)

| Topic | Decision |
|-------|----------|
| vLLM | Local Phi-3.5 Vision multimodal |
| vs old paste YAML | **Replace** `fields/target/split/derive` |
| index | 0-based source column |
| `?` | Unknown source header |
| regex | Flexible; skip arbitrary prefix text |
| Tabs | Paste mapping = YAML; Data entry = TSV split |
| Missing split | Do not overwrite manual input |
| ID | `ID: true` in YAML |
