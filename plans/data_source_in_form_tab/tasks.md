# Paste-split YAML tasks (`data_source_in_form_tab`)

---

## Phase 1: Planning

### [x] Task 1.1 — Speckit docs
* Four files under `plans/data_source_in_form_tab/`, **English**.

### [x] Task 1.2 — Align on sample
* `implementation_context.md` + spec §4; Phi-3.5 = vLLM; 0-based index; tab roles.

---

## Phase 2: YAML split engine

### [x] Task 2.1 — Load / validate new YAML
* Keys: `determiner`, `filed`, `index`, `regex`, `ID`; index 0-based.

### [x] Task 2.2 — TSV splitter
* `determiner` → columns; `index` → pick column; `regex` → extract.
* **Acceptance**: fixture TSV line in `implementation_context.md` matches spec split table.

### [x] Task 2.3 — Parse & fill
* Wire **Data entry**; failures do not overwrite existing cells.

### [x] Task 2.4 — Remove legacy paste
* Drop `fields/target/split/derive` parser and old vision mapping prompt.

---

## Phase 3: Phi-3.5 fills YAML

### [x] Task 3.1 — English vision prompt
* Output §4 schema; index from 0; `filed: "?"` when unknown.
* **Acceptance**: `scripts/debug_vision_paste.py` validates against new schema.

### [x] Task 3.2 — Paste mapping UI
* Copy states: defines rules for source paste in Data entry.

### [x] Task 3.3 — ID + data source
* `ID: true` keeps auto Sheet lookup.

---

## Phase 4: Tests

### [x] Task 4.1 — Unit tests
* determiner, 0-based index, regex, multi-date, `?`.

### [x] Task 4.2 — Screenshot integration
* `tests/test_image.png` → YAML → split fixture TSV.

### [x] Task 4.3 — Browser check
* Ginger Lots tabs and buttons; record in `plan.md`.

---
