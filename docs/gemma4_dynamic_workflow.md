# Gemma4 Dynamic TOML Workflow

> Status: **v2.0** (CLI-first verification; LiteRT serial inference; NiceGUI as form adapter)  
> Date: 2026-08-18  
> Platform: [`embed_gemma4.md`](embed_gemma4.md) (`open_session` / `generate` / `StartGemma`)  
> Business: [`toml_config_design.md`](toml_config_design.md), [`connect_google.md`](connect_google.md), [`db_store.md`](db_store.md), `app/core_toml.py`, `app/core_split.py`

**Authority**: This document is the source of truth for the TOML configuration workflow. The former fixed 8-step FSM spec (`gemma4_e4b_workflow.md`) has been removed.

---

## 0. Read this first (mental model)

### 0.1 One model, one lane, many session hats

LiteRT-LM loads **one** `Engine` (`StartGemma`). All inference goes through `llm_gemma4/runtime/gemma_worker.py` — a **single worker thread FIFO queue**. At any instant only one `send_turn` runs.

Implication: there is **no parallel field matching**, no `cap=2` sub-agents, and no overlapping main + sub inference. Sub-agents run **one after another**; the graph may **Continue** through compute steps inside one `dispatch`, but everything is still serial on that lane.

### 0.2 CLI first, NiceGUI second

| Layer | Role |
|-------|------|
| **Orchestration** | `WorkflowOrchestrator` (TOML) / `DialogOrchestrator` + `TomlGuideSpec` (CLI) |
| **CLI** (`llm_gemma4/cli/`) | **Primary harness** — run the full workflow without NiceGUI; mock/stub for offline smoke |
| **NiceGUI** (`workflow_ui.py`) | **Same orchestration, different I/O** — forms/tabs supply interrupt payloads; sidebar is a **read-only log** |

Develop and regression-test on CLI (`dialog demo --spec toml --mock --stub`). Once CLI passes, NiceGUI is «CLI with widgets instead of stdin».

### 0.3 «Self-talk» vs real user input

The left sidebar chat is **not** a chat product. It is `on_chat` / `on_progress` telemetry.

- Log lines tagged `[user]` are **Python-constructed prompts** (`build_main_turn_prefix`, field-match instructions, determiner blocks) — not text the operator typed in the sidebar.
- Gemma sessions (`wizard_decision_*`, `wizard_main`, `field_{label}_pass*`, `wizard_determiner_*`) take turns on the single lane — it **looks** like the model talks to itself.
- **Real human input** happens only at **mandatory interrupts** (see §5): layout, sample, optional Google skip, `db_id`. CLI uses `stdin` / `TOML_DEMO_AUTO`; NiceGUI uses dialogs and Input-tab widgets.

Between interrupts, `decide → execute → Continue` runs without a person — same as CLI `--non-interactive --demo`.

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Entry A: CLI                                                     │
│  python -m llm_gemma4.cli dialog run|demo --spec toml             │
│  stdin / TOML_DEMO_AUTO → WorkflowEvent(Start|Resume)             │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────┴─────────────────────────────────────┐
│  Entry B: NiceGUI (variant of A)                                  │
│  FAB / dialogs / tab_input → _collect_resume_payload()            │
│  TomlWizardController.dispatch(Start|Resume|Stop)                 │
│  Sidebar = readonly log (no chat input)                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │ await_gemma_thread(dispatch)
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  gemma_worker (single LiteRT thread)                              │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│  WorkflowOrchestrator + CompiledWorkflow                          │
│  decide() → execute(action) → Continue | Interrupt | Finished     │
└────────────────────────────┬─────────────────────────────────────┘
                             ▼
        toml_config/: executor, field_agent, intake_plan, toml_patcher
```

**Packages:**

| Path | Role |
|------|------|
| `llm_gemma4/cli/` | `gemma` subcommands + `dialog` (briefing / toml specs); `ScriptedBackend` for `--mock` |
| `llm_gemma4/dialog/` | Generic dialog runtime (`DialogOrchestrator`, `SubagentJob`, actions) — CLI `briefing` spec |
| `llm_gemma4/toml_config/` | TOML domain: `decide`, `executor`, `intake_plan`, `field_agent`, `TomlGuideSpec` |
| `llm_gemma4/workflow/` | `WorkflowEvent`, `CompiledWorkflow`, `MemoryCheckpoint`, `map_run_sequential` |
| `llm_gemma4/runtime/gemma_worker.py` | Single LiteRT worker; all UI/CLI dispatch goes here |
| `nicegui_ui/components/workflow_ui.py` | Interrupt UI, FAB, sidebar log |
| `nicegui_ui/components/toml_wizard.py` | `TomlWizardController` — no chat input, only `dispatch` |

There is **no** `llm_gemma4/wizard/` package. No `langgraph` dependency.

**Dual facade note:** NiceGUI uses `WorkflowOrchestrator` directly; CLI TOML uses `DialogOrchestrator` + `TomlGuideSpec` (same nine actions and intake rules). Long-term these should merge; for now behavior must stay aligned — **verify on CLI first**.

---

## 2. Concurrency (what we do *not* do)

| Original design idea | Current reality |
|--------------------|-----------------|
| Up to 2 parallel field sub-agents (`map_send`, Semaphore) | **Removed** — LiteRT hangs on cross-thread inference |
| Main session while subs run in background | **Not supported** — one `dispatch` holds the lane until interrupt/finished/error |
| UI auto-chain via repeated `tick({})` polling | **Removed** — graph **Continue** inside one `dispatch` (cap 24) |
| Application-level main-turn queue (CLI or UI) | **Not implemented** — NiceGUI `_busy` drops concurrent FAB clicks |

**What we have:** sub-agents are a **sequence**: job A finishes → state patch → job B → … Field labels use `map_run_sequential` in `executor.py` and `dialog/actions.py`.

`parallel.py` still contains unused `map_send(cap=2)` — do not use on LiteRT; treat as dead code.

---

## 3. CLI reference

### 3.1 Commands

```bash
# Offline smoke (recommended in CI / every push)
python -m llm_gemma4.cli dialog demo --spec toml

# Same with explicit flags
python -m llm_gemma4.cli dialog run --spec toml --mock --stub --demo --non-interactive

# Inspect action catalog and intake keys
python -m llm_gemma4.cli dialog catalog --spec toml

# Live Gemma (local machine with model weights)
python -m llm_gemma4.cli dialog run --spec toml --live --release

# Generic briefing demo (non-TOML dialog runtime)
python -m llm_gemma4.cli dialog demo --spec briefing
```

| Flag | Meaning |
|------|---------|
| `--mock` | `ScriptedBackend` — no LiteRT load |
| `--stub` | Fixed `decide` order (`WORKFLOW_DECIDE_STUB` / `decide_stub`) |
| `--demo` | Prefill `TOML_DEMO_AUTO` interrupt payloads |
| `--write-toml` | Persist `templates/{id}/{id}.toml` (needs real template path) |
| `--live` | Real backend (demo defaults to mock+stub) |

### 3.2 CLI ↔ NiceGUI I/O mapping

| Interrupt `kind` | CLI (`dialog_cmds._prompt_toml_interrupt`) | NiceGUI (`_collect_resume_payload`) |
|------------------|--------------------------------------------|-------------------------------------|
| `ask_sources` | stdin or `data_sources_skipped` | Google tab / skip |
| `ask_layout` | `input_area move_to offset` line | Layout dialog |
| `ask_sample` | ghost line + demo drafts | Ghost textarea + `read_field_drafts()` |
| `ask_db_id` | stdin (empty = none) | db_id select (None allowed without opening) |

### 3.3 CLI loop (same event model as UI)

```text
dispatch(Start, payload)
loop:
  outbound = dispatch result
  if finished → exit 0
  if interrupt → read payload (human or TOML_DEMO_AUTO) → dispatch(Resume, payload)
  else → error
```

Future: optional **CLI input queue** (multiple resume lines buffered) — does not require NiceGUI changes; not implemented yet.

---

## 4. Graph dispatch loop

Inbound: `start` | `resume` | `stop`  
Outbound: `interrupt` | `finished` | `error`  
Internal: `continue` (max 24 cycles per inbound event)

1. `resume` (or start with pending checkpoint) → merge payload, clear interrupt flag
2. Each cycle: `decide()` → one executor node → patch `WorkflowState`
3. Node returns `interrupt` → `MemoryCheckpoint.save_interrupt`, **return to caller immediately** (one interrupt per inbound dispatch)
4. Compute succeeds → internal Continue (no extra FAB click)
5. `is_finished` → `finished`; decision `error` → `error`
6. `stop` → close `wizard_main`, no decide/execute

`tick(payload)` = `dispatch` with `max_cycles=1` for unit-style probes. Production UI uses full `dispatch`.

**Stub:** `WORKFLOW_DECIDE_STUB=1` → `decide_stub()` fixed order (tests / CLI `--stub`).

**Threading:** `TomlWizardController.dispatch` → `await_gemma_thread(orchestrator.dispatch, event)`. Never run LiteRT on a `ThreadPoolExecutor`.

---

## 5. Mandatory intake & interrupts (human or scripted)

`intake_plan.INTAKE_KEYS` defines what the workflow must collect:

`data_sources` → `input_section` → `ghost_sample` / `field_drafts` → `ghost_preprocess` → `field_match` → `sheet_match` → `regex_infer` → `db_id`

### 5.1 Must stop and wait (interrupt)

These cannot be invented by Gemma; executor emits `InterruptPayload` when data is missing:

| kind | Intake keys | What must be supplied | TOML / product rule |
|------|-------------|----------------------|---------------------|
| `ask_sources` | `data_sources` | Google URL or explicit skip | Optional Google; sidecar may pre-seed via `intake_seed.sidecar_data_sources` |
| `ask_layout` | `input_section` | `input_area`, `move_to`, `offset ≥ 1` | **Required** before sample; multi-area union, 1–2 move axes — see [`toml_config_design.md`](toml_config_design.md) |
| `ask_sample` | `ghost_sample`, `field_drafts` | Ghost paste **and** per-label drafts in one resume | **Required** exemplar for preprocess + field match; workflow blocks Input-tab auto-split until stopped |
| `ask_db_id` | `db_id` | Primary key label or empty (none) | **Required confirmation** before finalize; empty is valid |

`already_captured(state, key)` + `_should_skip_interrupt` prevent re-asking when sidecar or a prior resume already filled the slot.

### 5.2 Auto-run (no human at keyboard)

After sample is captured, one `dispatch(Resume)` may chain internally:

`preprocess_sample` → `plan_ghost_tasks` → `match_ghost_fields` (serial per label) → `match_sheet_columns` (skip if no Google) → `infer_regex` → approach `finalize_toml`

Gemma «self-talk» happens here: synthetic `[user]` prompts in the sidebar log; operator only waits (FAB shows「处理中…」).

### 5.3 `progress` map

`state.progress`: `pending` | `done` | `skip`, plus `field:{label}` during match. Used by `decide` prompts and CLI dumps — not a separate NiceGUI checklist widget in v2.

---

## 6. decide() JSON contract

**Session:** `wizard_decision_{uuid}`, `thinking=False`, `max_tokens=512`, closed after each call. **Never** route via `wizard_main`.

**Required:** `next_action`, `action_id`  
**Optional:** `reason`, `expected_input`, `context_update`, `route_key`

**`next_action`:** `ask_user` | `compute` | `validate` | `finalize` | `error`

Prompt inputs: `design_doc`, IntakePlan, `already_captured` summary, `build_main_turn_prefix(state)` — not full `indexed_segments`.

Parse failure: one re-prompt; then `next_action=error`. Deterministic fallbacks in `decision.py` cover common misroutes on the compute chain.

---

## 7. Executor actions

| action_id | Stops for human? | Effect |
|-----------|------------------|--------|
| `capture_sources` | Yes (`ask_sources`) | Record or skip Google |
| `record_sources` | No | Persist sources to state/TOML |
| `capture_layout` | Yes (`ask_layout`) | Require layout fields |
| `capture_sample` | Yes (`ask_sample`) | Ghost + field drafts |
| `preprocess_sample` | No | `indexed_segments`, determiner one-shot |
| `plan_ghost_tasks` | No | `wizard_main` → `planned_labels` |
| `match_ghost_fields` | No | **Sequential** `run_field_agent` per label |
| `match_sheet_columns` | No | Skip if no `google_sheet` |
| `infer_regex` | No | Regex for `needs_regex` fields |
| `finalize_toml` | Yes (`ask_db_id`) then write | `db_id` confirm, persist, `is_finished` |

Handlers: `llm_gemma4/toml_config/executor.py` (`ACTION_HANDLERS`).

---

## 8. Sessions & thinking

| Session | thinking | Role |
|---------|----------|------|
| `wizard_decision_{uuid}` | **False** | Route next action |
| `wizard_main` | **False** | Plan field tasks |
| `wizard_determiner_{uuid}` | **False** | Plain-text delimiters (one-shot) |
| `field_{label}_pass1` | **False** | First match attempt |
| `field_{label}_pass2` | **True** | Retry only; **new** session id |

- `thinking_budget` from hardware profile — not hardcoded in orchestrator
- **Forbidden:** `thinking=True` on decision or `wizard_main`
- All sessions share one Engine; execution order is strict FIFO on `gemma_worker`

---

## 9. preprocess / match / regex

### 9.1 Shared split (`app/core_split.py`)

| Function | Role |
|----------|------|
| `is_brace_json(raw)` | Sample contains `{` and `}` |
| `json_to_indexed_dict(raw)` | Structural tokens; **keep** empty `""` |
| `split_by_determiner(raw, determiner)` | Plain text; quoted spans atomic |
| `parts_to_indexed_dict(parts)` | Drop empty parts |

### 9.2 Preprocess

- Brace JSON: Python-only — no determiner LLM
- Plain text: one-shot `wizard_determiner_{uuid}` — never `wizard_main`

### 9.3 Ghost match

- Labels with non-empty drafts in `planned_labels` only
- Per label: pass1 → pass2 on parse/validation failure (**sequential** across labels)
- Empty draft → `index = -1` on persist
- Progressive TOML after batch

### 9.4 Sheet / regex

- `match_sheet_columns`: skipped when no Google source
- `infer_regex`: `re.search` validation

---

## 10. NiceGUI specifics

| Concern | Behavior |
|---------|----------|
| Sidebar | Readonly `textarea` — log only, not user chat |
| FAB | Bottom-left; collects resume payload, calls `dispatch(Resume)` |
| Ghost guard | `tab_input` blur skips `record_from_textbox` while `workflow_active` |
| Stop | `stop_async()` waits for dispatch, flushes TOML, `EndGemma()` |
| Busy | Concurrent FAB ignored (`_busy`) — not queued |

Interrupt → tab routing: `ask_layout` / `ask_db_id` → 输入配置; `ask_sample` → 输入; `ask_sources` → Google 连接.

---

## 11. TOML persist

- `persist_wizard_toml(state, template_id)` in `toml_config/toml_patcher.py`
- Memory-only flags stripped per [`toml_config_design.md`](toml_config_design.md)
- Multi `input_area`, multi `move_to` (1–2 axes)
- `index` base 0; `-1` = no segment match
- Layout before ghost sample (intake order)
- `work_sheet` must exist in template xlsx
- Stop / template switch: best-effort flush before `EndGemma()`

---

## 12. Anti-patterns

1. **Fixed `ui_step` driver** — use `dispatch(Start|Resume|Stop)` + IntakePlan
2. **Parallel field agents (`map_send`, thread pool)** — LiteRT serial only
3. **Determiner via `wizard_main`** — one-shot determiner session
4. **flat_kv / OCR matching in field_match** — `indexed_segments` indices only
5. **Draft shortcut** skipping sub-agent
6. **UI-polled auto-chain / `run.io_bound(tick)` loops** — graph Continue inside `dispatch`
7. **Treating sidebar as user chat** — prompts are orchestrator-generated
8. **Skipping CLI before NiceGUI changes** — run `dialog demo --spec toml` first
9. **Importing `llm_gemma4.wizard`** — deleted
10. **Docs claiming «max 2 concurrent» field agents** — obsolete

---

## 13. Verification checklist

### 13.1 CLI (do this first)

```bash
python -m llm_gemma4.cli dialog demo --spec toml          # expect exit 0
python -m llm_gemma4.cli dialog catalog --spec toml     # nine actions listed
```

With `--live` on a machine with weights + real `templates/{id}/`:

1. All four interrupts can be satisfied (or pre-seeded)
2. Log shows `indexed_segments` before field match
3. Field lines show `(i/n)` **sequential** progress
4. `finalize_toml` accepts empty `db_id`
5. `--write-toml` produces valid sidecar

### 13.2 NiceGUI (after CLI)

1. Start from 输入配置; FAB + sidebar log appear (no checklist widget)
2. Layout dialog → TOML save → 输入 tab
3. Ghost paste does not auto-fill fields during workflow
4. One FAB captures ghost + drafts
5. Compute phases auto-chain inside one dispatch; FAB shows busy
6. `db_id=None` without opening dropdown
7. Stop → `EndGemma()`; ghost auto-split restored

---

## 14. Related docs

- [`embed_gemma4.md`](embed_gemma4.md) — LiteRT runtime, `SessionOptions`, `gemma_worker`
- [`toml_config_design.md`](toml_config_design.md) — on-disk TOML semantics
- [`connect_google.md`](connect_google.md) — Google Sheet source
- [`db_store.md`](db_store.md) — runtime persist after workflow
- [`plans/dynamic-wizard-runtime/HANDOFF.md`](plans/dynamic-wizard-runtime/HANDOFF.md) — v2 engineering handoff, tasks, file map

---

## 15. Operator journey (one paragraph)

Operator starts workflow (CLI `dialog run` or NiceGUI「启动配置向导」). The graph runs until it **must** have layout, a **real sample**, or **db_id** — then it interrupts. The operator supplies those via terminal or forms (not via sidebar chat). Each resume may trigger a long **serial** Gemma chain visible in the log as scripted user/assistant turns. When `is_finished`, TOML is written and the model may be released. **CLI proves the chain; NiceGUI is the same chain with richer interrupt widgets.**
