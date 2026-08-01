# Gemma 4 E4B · TOML Configuration Wizard (Application Spec)

> Status: **v8.3** (Step 2 dialog: multi `input_area` + multi-select `move_to`; aligns UI with [`toml_config_design.md`](toml_config_design.md) list forms)  
> Date: 2026-07-31  
> Platform: [`embed_gemma4.md`](embed_gemma4.md) (`open_session` / `generate` / `StartGemma`)  
> Business: [`toml_config_design.md`](toml_config_design.md), [`connect_google.md`](connect_google.md), [`db_store.md`](db_store.md) §2.1 (runtime persist after wizard), `app/core_toml.py`, `app/core_split.py`

**Authority**: This document is the source of truth. Existing `toml_wizard.py` / `wizard/orchestrator.py` are prototypes with **no compatibility obligation**. Re-align implementation to this spec.

**v8.3 vs v8.2**: Step 2 layout dialog **must** let the user enter **multiple** `input_area` ranges (union) and **multi-select** `move_to` directions (1 or 2 axes), matching TOML list semantics in [`toml_config_design.md`](toml_config_design.md). Dialog copy must explain both capabilities; do not present layout as a single hardcoded range + single-direction radio only.

**v8.2 vs v8.1**: Step 3 reads **live** Input-tab field widgets via `read_field_drafts()` (not only stale `session.draft`). Empty-draft labels in 4.2 are set to `match_type=none`, `index=-1` so `generate_toml` / overlay **fully overwrites** prior sidecar indexes (do not keep old `index`). Step 7 CTA is「保存配置文件」; default `db_id=None` may be confirmed **without** opening the dropdown. Step 8 trial cancelled. Brace-JSON preprocess **keeps** empty `""` tokens in `indexed_segments`.

**v8.1 vs v8.0**: Insert **Step 2 · Input layout** (`input_area` / `move_to` / `offset`) **immediately after Google Sheet / data sources and before Input-tab testing data**. Ghost sample capture moves to Step 3; Ghost match phases become Step 4.x; Sheet / regex / db_id / trial shift to Steps 5–8. Layout writes TOML progressively and switches the user to the「输入」tab before sample paste.

**v8.0 vs v7.0**: Ghost matching is split into explicit phases (preprocess → plan FieldTasks → per-field index match). Each phase must emit user-visible feedback before the next begins. Determiners for plain text are inferred in a **one-shot session**, never via `wizard_main`. Index matching receives only a Python-built `dict[int, str]`, never raw Ghost text.

---

## 0. Document ownership

| Question | Owner |
|----------|--------|
| How does the model `generate` / `run_judgment`? | [`embed_gemma4.md`](embed_gemma4.md) |
| When to call main dialogue vs sub-agents, what UI shows, how TOML is written | **This file** |
| Field semantics in TOML | [`toml_config_design.md`](toml_config_design.md) |

---

## 1. Core architecture

### 1.1 Inference topology: 1 main dialogue + N field sub-agents

```
┌─────────────────────────────────────────────────────────────┐
│  Main dialogue  session_id = "wizard_main"                    │
│  · Persistent across steps 1–8; thinking=False               │
│  · Plans FieldTasks, records sources, summarizes results     │
│  · Optional: inject wizard/context summary before each turn  │
│  · MUST NOT run determiner inference (that is a one-shot)    │
└──────────────────────────┬──────────────────────────────────┘
                           │ FieldTask list (after step 4.2 / 5 plan)
              ┌────────────┴────────────┐
              ▼                         ▼
     sub-agent (field_A)         sub-agent (field_B)   … Semaphore(2)
     short-lived Conversation
     step 4.3: match index against indexed_segments
     step 5:   match Sheet column
     step 6:   regex (needs_regex only)
```

- **Main dialogue** keeps global continuity (labels, sample kind, which fields are done).
- **Sub-agents** isolate one field each; concurrency capped at 2 at the sub-agent layer only.

### 1.2 Field sub-agent two-pass retry

Each field task uses **two passes** (different `session_id` per pass; thinking is session-scoped — see embed §3.2):

| Pass | session example | thinking | Trigger |
|------|-----------------|----------|---------|
| **A · normal** | `field_{label}_pass1` | `False` | First attempt |
| **B · thinking** | `field_{label}_pass2` | `True` | Pass A JSON parse failed, or `re.search` validation failed |

- Pass A: small `max_tokens` (e.g. 256).
- Pass B: `max_tokens` = profile `thinking_budget` (GPU 1024 / CPU·NPU 512). **Never hardcode** in orchestrator.

Steps 4.3 / 5 prefer pass A. Fuzzy matches go to step 6; step 6 may start at B or A→B.

### 1.3 In-process NiceGUI (no Playwright)

Wizard shares the NiceGUI process. State comes from:

- `SessionRegistry`: template, `Input_label` list
- Input tab Ghost textbox / OCR paste
- Google tab headers + sample rows (when configured)

Do **not** use `BrowserSession`, Playwright, or DOM screenshots in model context.

### 1.4 Engine lifecycle

- Wizard open: `StartGemma()` warm-up.
- Wizard close / fatal error: `EndGemma()`.
- May share Engine with Paddle-OCR under process policy.

### 1.5 Dynamic `thinking_budget`

Read from `health_check().litert_backend` or `profiles/{profile}.toml`:

| backend | `thinking_budget` |
|---------|-------------------|
| `gpu` | 1024 |
| `cpu` / `npu` | 512 |

### 1.6 In-memory vs on-disk TOML

`needs_regex`, `match_type`, etc. live only in `WizardState` / `FieldState`. On-disk `.toml` follows [`toml_config_design.md`](toml_config_design.md). Empty regex → `regex = ''` (TOML single-quoted literal).

### 1.7 Shared split logic (`app/core_split.py`)

Wizard, trial run, and `UiProvider.record_from_textbox` **must** share one implementation:

| Function | Role |
|----------|------|
| `is_brace_json(raw)` | After trim, sample contains both `{` and `}` |
| `json_to_indexed_dict(raw)` | Strip JSON structural chars → `dict[int, str]` |
| `split_by_determiner(raw, determiner)` | Split plain text by `str` or `list[str]` (longer delimiters first); **quoted spans are atomic** |
| `parts_to_indexed_dict(parts)` | Drop empty parts; assign contiguous indices |

**Forbidden**: duplicate `split_by_determiner` in `sample_analysis.py` / `trial_run.py` / `core_store.py` method bodies.

### 1.8 Why `dict[int, str]` (not flat_kv) for the wizard

| | flat_kv (runtime OCR shortcut) | `dict[int, str]` (wizard path) |
|--|--------------------------------|--------------------------------|
| Meaning | OCR table cells → key→value | Ordered tokens with integer indices |
| Match | Label vs key name; no TOML `index` | Model picks `index` → TOML `fields[].index` |
| Wizard | Gemma never sees numbered tokens; cannot emit stable `index` | Required for step 4.3 |

Wizard step 4 **must not** use flat_kv matching. After 4.1, `indexed_segments` is the only sample view for planning/matching/regex/trial.

Runtime `record_from_textbox` dual path: legacy OCR TOMLs with all `index < 0` may still use flat_kv; wizard-written configs with `index >= 0` use `json_to_indexed_dict` / determiner split + `rule.index`.

---

## 2. User journey (8 UI steps)

**Order is mandatory** (do not reorder):

| UI step | Tab focus | Business |
|---------|-----------|----------|
| 1 | Google 连接 | Data sources / Google Sheet (optional) |
| 2 | 输入配置 | `[[input_section]]`：多 `input_area` + 多选 `move_to` + `offset` →「下一步配置」→「输入」 |
| 3 | 输入 | Ghost / draft **testing data** |
| 4 | 输入配置 | Ghost field match (4.1 preprocess → 4.2 plan → 4.3 match) |
| 5 | Google 连接 | Sheet column match (skip if no Sheet) |
| 6 | 输入配置 | Regex for `needs_regex` |
| 7 | 输入配置 | Pick `db_id` or **None** →「保存配置文件」并退出 |
| 8 | — | **Cancelled**（原 trial；勿再阻断结束） |

UI Stepper maps 1:1 to business steps. UI calls `orchestrator.advance(step, payload)` when the user advances. Orchestrator **must not** silently advance across multiple Stepper steps.

**Feedback rule**: Every completed phase (including step 4 sub-phases) must push progress to the UI log **before** starting the next long LLM call. Users must never sit through preprocess + N field matches with only a busy spinner.

Recommended API shape:

```python
advance(step: int, payload: dict) -> WizardState
# Step 4 payload MUST include:
#   payload["phase"] in {"preprocess", "plan", "match"}
# UI: one FAB on step 4 auto-chains three run_step(4, phase=…)
# yielding between phases so logs refresh (not three manual FAB clicks).
```

---

### Step 1 · Data sources

Collect `[[sources]]` (local / Google Sheet).

- Record `template_id` / `template_path` early so Step 2 can load per-template layout hints.
- **Main dialogue**: record source types for later Sheet matching (step 5).
- **Progress**: `[Step 1/8] data sources recorded: …`
- Advances UI to step 2.

---

### Step 2 · Input layout (`[[input_section]]`) — **before testing data**

User opens the current Excel template and answers three questions from [`toml_config_design.md`](toml_config_design.md). Semantics of list vs scalar forms are owned by that guide; this step only collects them in the dialog and persists one `[[input_section]]`.

1. `input_area` — instance 0 **fill-value** region(s) for **this** template (**not** label cells; no global hardcoded skeleton such as only `A2:G2`).
2. `move_to` — next-instance pan direction(s): `up` / `down` / `left` / `right`.
3. `offset` — pan step as `int >= 1` (same step on each selected axis).

#### Dialog UI (normative)

The Step 2 dialog **must** make multi-region and multi-direction layout discoverable — not only a single range + single radio.

| Control | Behavior | User-facing guidance (dialog must say, Chinese OK) |
|---------|----------|-----------------------------------------------------|
| **`input_area`** | Allow **one or more** Excel range strings. Prefer a repeatable list editor (add/remove rows) or comma/newline multi-entry that normalizes to `list[str]`. A single continuous range remains valid. | Tell the user they **can assign multiple input areas**; non-contiguous blocks are a **union** (e.g. `A2` + `C2:G2` + `M2`). Values of instance 0 must fall in that union. |
| **`move_to`** | **Multi-select** among `up` / `down` / `left` / `right` (checkboxes or equivalent — **not** a single-choice radio that hides 2D layout). Selection count: **1** → single-axis pan; **2** → main axis then secondary axis (order = selection order or explicit primary/secondary); **0 or >2** → validation error. | Tell the user they **can multi-select moving directions**: one direction = rows/columns along that axis; two directions = 2D grid expand (first = main axis, second = secondary). |
| **`offset`** | One positive integer shared by every selected axis. | Explain: step size in cells per axis; labels do not move. |

**Defaults** when opening the dialog: load from existing sidecar / `CreateDefaultFromTemplate` for **this** template (may already be a list). Pre-fill controls so list `input_area` and list `move_to` round-trip visibly (do not collapse a two-direction TOML back to one radio).

**Normalization before persist:**

- One area string → may write scalar or one-element list (prefer matching existing TOML style; patcher may keep list when length > 1).
- One direction → scalar string or one-element list; two directions → `move_to = ["…","…"]` with order preserved.
- Reject empty `input_area` list; reject unknown direction tokens; reject 0 or >2 selected directions.

**Responsibilities:**

1. Read answers from the step dialog; validate; write into `WizardState.input_area` / `move_to` / `offset` (types allow `str | list[str]` for area and directions — see §4.1).
2. Persist sidecar TOML via `toml_patcher` (base = existing TOML or `CreateDefaultFromTemplate(xlsx)` for **this** template only). When the user changed `input_area`, rebuild `[[fields]]` so value cells stay consistent with the **union** (same rule as today’s single-area rebuild, applied to the union).
3. **`work_sheet` must exist in the template xlsx.** If the sidecar names a missing sheet (e.g. stale `Input_sheet`), patcher replaces it with the sheet resolved by `CreateDefaultFromTemplate` / active sheet that has header labels — never leave `work_sheet not found` after a wizard persist.
4. Apply TOML engines (`trigger_toml_save`) and switch Tab to「输入」.
5. Progress: `[Step 2/8] input_section areas=N move_to=[…] offset=…`

**Forbidden in step 2:**

- Ghost / draft sample capture.
- Gemma matching or determiner inference.
- Hardcoded cross-template layout defaults in the patcher skeleton.
- Keeping a `work_sheet` value that is not in `wb.sheetnames`.
- UI that **only** offers a single range textbox + single-direction radio with **no** copy explaining multi-area / multi-direction (spec violation even if TOML already supports lists).
- Silently dropping extra areas or a second `move_to` axis when loading an existing list-form sidecar.

Advances UI to step 3 (Input testing).

---

### Step 3 · Sample collection (Input testing data)

User pastes into Ghost textbox or uses OCR / fills field drafts. Wizard reads from `SessionRegistry` plus **live** Input-tab widgets.

**Responsibilities (only):**

1. Store `ghost_text_sample`, `template_labels`, `user_draft`.
2. Build `user_draft` with `nicegui_ui.pages.tab_input.read_field_drafts(labels)` (current field control values), then merge into `session.draft`. Do **not** rely only on blur-synced `session.draft` (blur may not have fired).
3. Optionally notify main dialogue that a sample was captured (short note; **no structure analysis**).
4. Progress: `[Step 3/8] sample captured, N chars, M labels`

**Forbidden in step 3:**

- Calling Gemma to classify JSON vs plain text (`is_brace_json` is Python, done in 4.1).
- Inferring determiners.
- Building `indexed_segments`.
- Filling `flat_kv`.
- Changing `input_area` / `move_to` / `offset` (that is step 2 only).

If no Ghost sample **and** no Google source → end wizard.

Advances UI to step 4.

---

### Step 4 · Ghost field matching (three phases)

Step 4 is **one UI step** but **three orchestrator phases**. Do not collapse them into a single blocking `advance(4)` that runs preprocess + all field agents.

```
Step 4.1 preprocess  →  indexed_segments + determiner (if plain)
Step 4.2 plan        →  FieldTask list from non-empty drafts only
Step 4.3 match       →  sub-agents per field (input = dict only)
```

#### Phase 4.1 · Preprocess → `dict[int, str]`

**Goal**: Produce `state.indexed_segments: dict[int, str]` with Python. Gemma is used **only** for plain-text determiner discovery.

##### Branch A — brace JSON (Python only)

1. Trim leading/trailing whitespace and strip non-printable characters (`str.isprintable` or equivalent; **must preserve CJK** — do not use `string.printable`).
2. If `{` and `}` both present → treat as brace JSON.
3. Remove structural characters: `{`, `}`, `[`, `]`, `:`, `,`, `\n` (replace with space).
4. Tokenize quoted strings and bare tokens; **keep** empty `""` as empty-string tokens (do not drop — real OCR/JSON samples use blank cells).
5. Build contiguous `dict[int, str]` (quotes stripped from values; empty quoted → `""`).

Example input:

```json
{
"table1": [
    {
      "row": 1, "cells": [
        "日期", "7.5", "航班号", "CA987", "航段", "PEK - LAX"
      ]
    },
  ],
}
```

Example output:

```python
{
    0: "table1",
    1: "row",
    2: "1",
    3: "cells",
    4: "日期",
    5: "7.5",
    6: "航班号",
    7: "CA987",
    8: "航段",
    9: "PEK - LAX",
}
```

- `state.sample_kind = "brace_json"`
- `state.determiner = ""` (JSON path does not set TOML determiner from this branch)
- **No LLM call**

##### Branch B — plain text (Gemma determiner → Python split)

1. Open a **one-shot** session (not `wizard_main`), system/user = determiner prompt below.
2. Parse Gemma reply → determiner list (required) and optional cleaned string (logging only).
3. **Build the dict by splitting the original raw sample** with `split_by_determiner(raw, determiners)`, then `parts_to_indexed_dict`.
4. Write `state.determiner` (full list, not first element only) so TOML top-level `determiner` can be regenerated.

**Critical rules:**

| Rule | Detail |
|------|--------|
| Session | One-shot `session_id` e.g. `wizard_determiner_{uuid}`; close after use |
| Must not | Call `_main_turn` / pollute `wizard_main` with determiner chat |
| Must not | Build `indexed_segments` by tokenizing Gemma’s cleaned string as the primary path |
| Must | Use `determiners` + `split_by_determiner` on **raw** Ghost text |
| Cleaned string | Optional UI/log preview only |

Example raw input:

```text
 "日期", 	"7.5", "航班号", "CA987", 
"航段",[ "PEK - LAX"] 
```

Determiner prompt (canonical):

```
Task: Clean a raw string by removing structural symbols and non-printable characters while preserving the sequence of values.

## Instructions:
Identify Determiners: List all structural symbols and non-printable characters (e.g., \t, \n) found in the input string.

Clean the String: Provide a cleaned version of the string where:
  - Quoted strings remain exactly as they are (including the quotes).
  - Numbers remain as they are.
  - All commas, brackets, tabs, and extra whitespace are removed.
  - The values should be separated by a single space.

Output Determiners as a list, for example:

`[",","\t"]`

Also output:

**Cleaned String:**
<cleaned string here>

## Input data

```
 "日期", 	"7.5", "航班号", "CA987", 
"航段",[ "PEK - LAX"]
```
```

Example Gemma reply:

```text
**Determiners:**
`[" ", ",", "\t", "\n", "[", "]"]`

**Cleaned String:**
"日期" "7.5" "航班号" "CA987" "航段" "PEK - LAX"
```

Python then:

```python
parts = split_by_determiner(raw, [" ", ",", "\t", "\n", "[", "]"])
indexed = parts_to_indexed_dict(parts)
# expected tokens after strip/empty-drop, e.g.:
# {0: "日期", 1: "7.5", 2: "航班号", 3: "CA987", 4: "航段", 5: "PEK - LAX"}
```

**Normative**: `split_by_determiner` must treat `"..."` / `'...'` spans as atomic so `"PEK - LAX"` stays one token when quoted. trial_run and `record_from_textbox` must use the same function.

##### Phase 4.1 completion feedback (required)

```text
[Step 4.1/8] preprocess done: brace_json|plain_text, N tokens
[Step 4.1/8] determiner=…   (omit or show "" for brace_json)
[Step 4.1/8] indexed preview: 0:…, 1:…, … (first ~12 tokens)
```

Optionally show a TOML snippet preview of top-level `determiner` via `generate_toml(state)` (memory only; do not write disk yet).

Then return from `advance`; UI may auto-chain to phase `plan`.

---

#### Phase 4.2 · Plan FieldTasks (main dialogue)

**Goal**: Main dialogue sees the **already-built** `indexed_segments` and template labels, then emits / confirms the FieldTask list.

**Empty-draft labels (normative overwrite):**

- Labels with empty / missing draft are **not** FieldTasks (no Gemma match).
- For each skipped label, set `FieldState.match_type = "none"`, `index = -1`, clear `error`.
- On Step 7 persist, overlay **must write** `index = -1` into the sidecar for those labels — **full overwrite** of any previous `index` / match result. Do **not** preserve old TOML indexes for skipped fields.

**Input to Gemma (main dialogue) — required shape:**

```
Indexed segments:
0: table1
1: row
…
Template labels: ["Report Date", "Flight No", …]
User draft (optional): {…}

List which labels need ghost index matching as FieldTasks.
```

**Forbidden:**

- Sending raw Ghost paste as the primary matching context.
- Re-running preprocess.
- Spawning field sub-agents in this phase.
- Leaving skipped fields with stale `index >= 0` from a prior wizard / sidecar.

**Progress:**

```text
[Step 4.2/8] FieldTasks planned: K labels
[Step 4.2/8] skip empty draft (no Gemma): …
```

Return; UI chains to phase `match`.

---

#### Phase 4.3 · Per-field index match (sub-agents)

**Goal**: For each planned label, a sub-agent picks the index of the field’s **data value** in `indexed_segments`.

**Matching priority (normative):**

1. **Primary**: `user_draft[Input_label]` (what the user typed / OCR-filled for that field). Find the segment whose content matches that value.
2. **Secondary**: `Input_label` is only a semantic hint (e.g. nearby key in key/value OCR pairs). Prefer the **value** index, not the key token that equals the label string.
3. **Forbidden**: Selecting an index merely because `segments[i] == Input_label` when a draft value exists.

**Sub-agent user payload:**

```
Input_label (hint only): {Input_label}
User-provided value (primary signal): {draft or "(none)"}
Indexed segments:
0: …
1: …
Find the index of the DATA VALUE for this field.
```

Concurrency: `Semaphore(2)`.

| Result | Action |
|--------|--------|
| exact | `index = N`, `regex=""`, `needs_regex=False` |
| fuzzy | `index = N`, `needs_regex=True` → step 6 |
| none | set `error` (or clear error if label clearly absent — product choice must be documented) |

Sub-agent JSON (parsed by `wizard/parse_field_json.py`, **not** platform `ActionParser`):

```json
{"match_type": "exact"|"fuzzy"|"none", "index": 0, "reason": "..."}
```

**Progress (required, per field):**

```text
[Step 4.3/8] matching [Report Date] (2/5)…
[Step 4.3/8] [Report Date] exact index=4
[Step 4.3/8] done, F failed: …
```

After all fields finish → UI advances to step 5.

---

### Step 5 · Google Sheet field matching (per field)

If step 1 has a Sheet source: load headers + top 3–5 sample rows.

1. **Main dialogue** plans FieldTasks (column-match tasks).
2. **Sub-agents** (≤2 concurrent) match each label to a column.

| Result | Action |
|--------|--------|
| exact | bind `source_file`, `source_sheet`, `field` / `column_name` |
| fuzzy | same + `needs_regex=True` |
| none | `error` |

If no Sheet source / empty headers: skip with progress and advance to step 6.

**Progress:** `[Step 5/8] matching [label] (i/n)…`

---

### Step 6 · Regex inference

Only fields with `needs_regex=True`.

- Sub-agent + pass A/B (§1.2); emit Python `re` syntax.
- **Input to Gemma (per field):** the **single** indexed segment at that field’s `index`, plus the user draft value that must be captured.
- Validate: `re.search(regex, segment)`; when draft is present, prefer `group(1)` matching the draft. On failure → pass B or `error`.
- Do **not** dump the full `indexed_segments` dict as the regex haystack.

```json
{"regex": "...", "reason": "..."}
```

**Progress:** `[Step 6/8] [Invoice No] regex failed, starting Thinking retry…`

---

### Step 7 · Primary key + write TOML (final)

Show field list in the **step dialog**; user picks `db_id` (`Input_label`) or **`None`** (reject assigning a primary key → all `FieldState.id = false`, omit top-level `db_id`).

- Confirm with **「保存配置文件」inside the dialog** (not only the Shell FAB). Default is `None`; user may click save **without** opening or touching the dropdown.
- On confirm: `generate_toml` / overlay writes **all** `FieldState.index` values (including `-1` for skipped) → persist sidecar → `trigger_toml_save` / `verify_toml` → end wizard.
- Preserve unrelated top-level keys already on disk (e.g. `use_independent_db`) unless this step explicitly edits them.
- **No trial run** after this step.

After the wizard exits, **runtime** text persistence (Input「保存」/「添加数据」) follows `use_independent_db` — see [`db_store.md`](db_store.md) §2.1 and [`excel_transform.md`](excel_transform.md) §4.6. The wizard itself does not write session rows into the template xlsx.

---

### Step 8 · (removed) Trial run

Trial / mismatch gate is **cancelled**. Step 7 writes TOML and exits. Do not block finish on regex trial parse failures.

---

## 3. UI layer (`nicegui_ui/components/toml_wizard.py` + `wizard_ui.py`)

### 3.1 Controller singleton

- Module-level singleton controller; **never** `new TomlWizard()` on every button click.
- In-process wizard chrome (dialogs + FAB); survive Tab switches.
- Non-modal: user may use Input / Google tabs while wizard stays active.

### 3.2 Progress and chat

Real-time log examples:

```text
[Step 4.1/8] preprocess done: plain_text, 6 tokens
[Step 4.1/8] determiner=[" ", ",", "\t", "\n", "[", "]"]
[Step 4.2/8] FieldTasks planned: 5 labels
[Step 4.3/8] matching [Report Date] (2/5)…
[Step 6/8] [Invoice No] regex failed, starting Thinking retry…
```

Sidebar chat shows program ↔ Gemma turns for main dialogue and (tagged) field agents.

### 3.3 Async scheduling

- LLM work runs in a worker thread (`run.io_bound` around **sync** `advance`).
- Do **not** put bare `async def` into `io_bound` without awaiting.
- Prefer **yielding between step 4 phases** so `_busy` clears and the log refreshes (three `run_step(4, phase=…)` calls or equivalent).

### 3.4 Step 4 UI contract

| Phase | User action | After return |
|-------|-------------|--------------|
| preprocess | FAB / auto | Show dict + determiner; unlock next |
| plan | FAB / auto | Show FieldTask count |
| match | FAB / auto | Show per-field progress; then enter step 5 |

Collapsing all three into one `await run_step(3)` without intermediate UI updates is a **spec violation**.

---

## 4. Engine layer (`llm_gemma4/wizard/`)

| Module | Responsibility |
|--------|----------------|
| `sample_preprocess.py` | Phase 4.1: brace-JSON tokenize; plain-text one-shot determiner session; `split_by_determiner` → `indexed_segments` |
| `orchestrator.py` | 8-step machine; phase-aware step 4; `wizard_main`; sub-agent pool + Semaphore(2); A/B retry |
| `prompts.py` | Main system; DETERMINER (one-shot); PLAN_GHOST_TASKS; field systems for Ghost/Sheet/regex |
| `context.py` | Main-turn prefix: task_anchor / fields_done / pending |
| `parse_field_json.py` | Extract one JSON object; `ParseError` → pass B |
| `field_agent.py` | Per-field ghost/sheet/regex; ghost path **requires** `indexed_segments` |
| `toml_patcher.py` | `WizardState` → TOML text; strip memory-only flags |
| `trial_run.py` | Step 8 trial using `app.core_split` |
| `state.py` | `WizardState` / `FieldState` |

### 4.1 Memory state (sketch)

```python
@dataclass
class FieldState:
    input_label: str
    match_type: str = "unknown"      # exact | fuzzy | none
    index: int = -1
    column_name: str = ""
    needs_regex: bool = False
    regex: str = ""
    source_file: str = ""
    source_sheet: str = ""
    id: bool = False
    error: str = ""
    used_thinking: bool = False

@dataclass
class WizardState:
    current_step: int = 1
    data_sources: list[dict]
    template_id: str = ""
    template_path: Path | None = None
    input_area: str | list[str] = ""   # step 2; "" / [] = unset; list = union of ranges
    move_to: str | list[str] = ""      # step 2; one dir or [main, secondary]; empty = unset
    offset: int = 0                  # 0 = unset; persist only when >= 1
    ghost_text_sample: str
    sample_kind: str = ""            # brace_json | plain_text
    determiner: str | list[str] = "" # full list for plain_text
    indexed_segments: dict[int, str] = field(default_factory=dict)
    preprocess_done: bool = False
    field_tasks_planned: bool = False
    planned_labels: list[str] = field(default_factory=list)
    template_labels: list[str]
    fields: dict[str, FieldState]
    db_id: str = ""
```

`flat_kv` / `ghost_json_sample` may remain for transitional callers but **must not** drive step 4 matching.

### 4.2 Sub-agent call template

```python
opts = SessionOptions(system_message=STEP3_SYSTEM, thinking=False, max_tokens=256)
session = backend.open_session(f"field_{label}_pass1", options=opts)
# user content: Target Field + Indexed segments only
result = session.send_turn({"role": "user", "content": user_payload})
session.close()
payload = parse_field_json(result.text)  # fail → pass2 thinking session
```

### 4.3 Determiner one-shot template

```python
opts = SessionOptions(system_message=DETERMINER_PROMPT, thinking=False, max_tokens=512)
sid = f"wizard_determiner_{uuid4().hex[:8]}"
session = backend.open_session(sid, options=opts)
reply = session.send_turn({"role": "user", "content": raw_sample[:4000]})
session.close()
determiners, cleaned = parse_determiner_reply(reply.text)
indexed = parts_to_indexed_dict(split_by_determiner(raw_sample, determiners))
```

---

## 5. Boundary with the runtime

| Need | Source |
|------|--------|
| `open_session` + `SessionOptions` | embed §3.2 |
| `StartGemma` / `EndGemma` | embed §3.3 |
| `run_judgment` | **Wizard does not use** |
| Full `ContextStore` layers | **Deprecated**; use `wizard/context.py` |
| `BrowserSession` | **Deprecated** |
| Platform `ActionParser` | **Deprecated**; use `parse_field_json.py` |
| Input「保存」/「添加数据」text persist | [`db_store.md`](db_store.md) §2.1 — independent DB → SQLite; `use_independent_db=false` → `write_back` template by `instance_k` |
| Live draft for Step 3 | `tab_input.read_field_drafts` |

---

## 6. Anti-patterns (do not reintroduce)

0. **Putting Input layout (`input_area` / `move_to` / `offset`) after Ghost matching** — layout is Step 2, immediately after Google / sources and before Input testing data.
0b. **Persisting a `work_sheet` that is not in the template xlsx** (e.g. copying sample `Input_sheet` into a workbook that only has `Sheet1`) — patcher must sync from `CreateDefaultFromTemplate` / real sheet names.
0c. **Step 2 UI limited to one range + one-direction radio** without explaining multi-area union / multi-select directions — dialog must teach and collect list forms per [`toml_config_design.md`](toml_config_design.md).
0d. **Collapsing list `input_area` / two-axis `move_to` when reopening Step 2** — round-trip existing list-form sidecars.
1. **Single blocking `advance(4)`** that preprocess + match all fields without intermediate user feedback.
2. **Determiner inference via `_main_turn` / `wizard_main`**.
3. **Building index dict from cleaned string tokenization** instead of `split_by_determiner(raw, determiners)`.
4. **`coerce_determiner` keeping only the first list element**.
5. **Step 4 OCR / flat_kv key matching** instead of index dict.
6. **Field agent falling back to raw Ghost text** when `indexed_segments` is missing.
7. **Step 3 LLM sample_kind classification** (Python `is_brace_json` belongs in 4.1).
8. **Draft-value shortcut** that marks `exact` and skips the sub-agent.
9. **Triplicated `split_by_determiner`** outside `app/core_split.py`.
10. **Preserving old sidecar `index` for empty-draft / skipped labels** instead of writing `index = -1`.
11. **Requiring the Step 7 dropdown to be opened** before「保存配置文件」when default is already `None`.
12. **Dropping empty JSON `""` tokens** in `json_to_indexed_dict` / brace preprocess (shifts later indexes).

---

## 7. Suggested implementation order

1. Spec-align `app/core_split.py` + `sample_preprocess.py` (4.1 rules above; keep empty `""`).
2. Orchestrator: `advance(4, phase=…)` + one-shot determiner session + plan phase (`index=-1` on skip).
3. `field_agent`: ghost path requires `indexed_segments` only.
4. UI: three-phase step 4 feedback + `(i/n)` progress; Step 3 `read_field_drafts`.
5. Align `record_from_textbox` / `trial_run` with the same split rules.
6. Step 7「保存配置文件」writes TOML (full index overlay) and ends the wizard (no step-8 trial).

---

## 8. Acceptance criteria

1. Opening the wizard from Input Config; Tab switches keep wizard chrome alive.
2. After Step 1, Step 2 asks `input_area` / `move_to` / `offset` **before** any Input testing data; dialog states that **multiple input areas** and **multi-select move directions** are allowed; TOML persists and UI switches to「输入」.
3. Step 2 layout defaults come from **this template** only (existing TOML or `CreateDefaultFromTemplate`); no global hardcoded skeleton; list-form sidecar values reopen as multi-entry area + multi-select directions (not collapsed to one radio).
3b. Saving Step 2 with two areas + `move_to=["right","down"]` writes list forms into `[[input_section]]` and still passes `verify_toml` when value cells sit in the union.
4. Step 3 reads real Ghost paste and **live** field widget values via `read_field_drafts`, without an LLM structure call.
5. Step 4.1 shows token dict (and determiner for plain text) **before** field matching starts; empty `""` tokens appear in the dict when present in the sample.
6. Step 4.2 plans only non-empty drafts; empty drafts skip Gemma and get `index=-1` in memory and on disk after save.
7. Step 4.3 shows concurrent progress for ≥3 fields (at most 2 running); every planned field runs a sub-agent (no draft exact-match shortcut).
8. Plain-text path writes full determiner list into wizard state used by `generate_toml`.
9. Fuzzy fields produce regex in step 6 with `re.search` success; failed first try shows Thinking retry in the log.
10. Step 6 regex uses the **matched index segment** + user draft (not the full index dump).
11. Wizard finish is step 7「保存配置文件」with default `None` without opening the dropdown (no trial gate); legacy OCR flat_kv templates still work when all `index < 0`.
12. Wizard close calls `EndGemma()`; OCR can `StartGemma` again afterward.
13. Desktop shell: `.shell` / `.main` / `.field-grid` fill the viewport right column (`auto-fill` ~400px cells per `nicegui_ui` plan).

---

## 9. Related docs

- [`embed_gemma4.md`](embed_gemma4.md) — LiteRT runtime  
- [`toml_config_design.md`](toml_config_design.md) — TOML field semantics (incl. `use_independent_db`)  
- [`db_store.md`](db_store.md) §2.1 — runtime Input「保存」/「添加数据」when template-as-DB vs independent DB  
- [`excel_transform.md`](excel_transform.md) §4.6 — template-as-DB `write_back` / `instance_k`  
- [`connect_google.md`](connect_google.md) — Google Sheet OAuth  
- [`app/core_split.py`](../app/core_split.py) — shared tokenization / determiner split  
