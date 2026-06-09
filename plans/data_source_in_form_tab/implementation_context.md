# Implementation context (read this first in a new chat)

Handoff bundle for `data_source_in_form_tab`. All prompts to Phi-3.5 must be **English**.

## Data flow

```
Ginger Lots form fields (target)
        ↑ split & fill
Pasted TSV row (source)
        ↑ rules in paste YAML
Paste split YAML (only schema — see spec.md §4)
        ↑ Phi-3.5 Vision fills mapping (called "vLLM" in docs)
「Paste mapping」tab: screenshot → YAML → save templates/<id>.paste.yaml
「Data entry」tab: paste TSV →「Parse & fill」(requires saved YAML)
```

Phi-3.5 does **not** fill form values from a paste row. It fills the **YAML mapping**. A local parser splits paste rows using that YAML.

## Target form: Ginger Lots

Template file: `templates/Ginger_Lots.xlsx`  
Template id: `Ginger_Lots`

Form column headers (fill targets), in UI order:

```
order, YY, MM, DD, P.O. No., Container No., Container Seal No., Lot No.,
Receiving Date, Product Description, Supplier, Truck Line
```

Open the app → select **Ginger Lots** → **Data entry** tab to see these fields.

## Source A — TSV paste line (primary test fixture)

Tab-separated, **0-based column index** in parentheses:

```text
10073	GIN	Shandong Santao	S26167FG	EMCU5484116	140601104991	5/9	5/30	$2,612	rel	everport	6/2	6/1	600000 Fresh Ginger, China. (F7)	1780	57294
```

| index | value |
|------:|-------|
| 0 | 10073 |
| 1 | GIN |
| 2 | Shandong Santao |
| 3 | S26167FG |
| 4 | EMCU5484116 |
| 5 | 140601104991 |
| 6 | 5/9 |
| 7 | 5/30 |
| 8 | $2,612 |
| 9 | rel |
| 10 | everport |
| 11 | 6/2 |
| 12 | 6/1 |
| 13 | 600000 Fresh Ginger, China. (F7) |
| 14 | 1780 |
| 15 | 57294 |

Expected split examples after YAML is applied:

| Target field | Typical rule | Value |
|--------------|--------------|-------|
| P.O. No. | index 0 | 10073 |
| Supplier | index 2 | Shandong Santao |
| Container No. | index 4 | EMCU5484116 |
| Lot No. | index 3 | S26167FG |
| MM / DD | index 12 + regex | 06 / 01 |
| Receiving Date | index 12 + regex | 06/01 |
| Product Description | index 13 | 600000 Fresh Ginger, China. (F7) |

## Source B — screenshot table (what Phi-3.5 sees)

Markdown transcription of logistics spreadsheet (headers + one row). Column order defines **0-based index**:

| PO | Group | Supplier | Com. Inv# | Container# | BL# | ETD | ETA | freight | Status | Terminal | LFD | recv. date | Product | Pl. Qty. | weight | Destn. | Cust. | Cust. PO# |
|----|-------|----------|-----------|------------|-----|-----|-----|---------|--------|----------|-----|------------|---------|----------|--------|--------|-------|-----------|
| 10034 | BGIN | Shandong Santao | S26153WD | EMCU5939684 | 140600942984 | 5/2 | 5/23 | $2,862.0 | rel | apm | 5/28 | pickup 5/28, tdi 5/29 | Conv. Bag Ginger... | 1050, 300, 75, 25 | 56526 | LA | Royal Pacific | RP-22344 |

Image fixture (Phi-3.5 input): `tests/test_image.png`

Phi-3.5 task: map each **Ginger Lots form field** → `filed` (source header name), `index` (0-based), optional `regex`. Use `?` for unknown `filed`. Leave absent if no mapping.

## YAML schema (canonical — spec.md §4)

- Top: `determiner: "tab"` (or `/`, `,`, space)
- Optional `order:` list of source headers
- One key per **template field name**; value is a list of rules with `filed`, `index`, optional `regex`, optional `ID: true`
- Key spelling `filed` is intentional (matches sample)
- **index starts at 0**

## Phi-3.5 / vLLM

- Model: `OpenVINO/Phi-3.5-vision-instruct-int4-ov`
- Weights: `app/vllm/phi-3.5-vision-instruct-int4-ov`
- Code: `app/services/phi35_vision_model.py`, `phi35_vision_paste_infer.py`
- Debug: `python scripts/debug_vision_paste.py`
- Docs label "vLLM" = this local multimodal model, not a remote vLLM server

## Code to replace

- Old paste format: `delimiter`, `index_base`, `fields[].target` — **remove**
- Files: `paste_parse_config.py`, `paste_mapping_infer.py`, `phi35_vision_paste_infer.py`, `paste_parse_settings.py`
- Tests: `tests/test_paste_parse.py`, `tests/test_vision_screenshot_integration.py`

## New chat starter prompt (copy-paste)

```
Implement plans/data_source_in_form_tab/tasks.md Phase 2–4.
Read implementation_context.md and spec.md §4 first.
Replace old paste YAML parser with the new schema; Phi-3.5 prompts in English.
Use TSV fixture line and Ginger_Lots headers for tests.
```
