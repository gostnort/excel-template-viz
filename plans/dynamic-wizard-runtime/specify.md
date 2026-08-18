# Gemma4 Dynamic TOML Workflow — Specification

> **Spec-kit:** `user-spec-kit` MCP invoked (`speckit_specify` / `speckit_plan` / `speckit_tasks`); `commands/speckit.*` templates not in repo — **this folder is authoritative**  
> **Source:** [dynamic_wizard_runtime plan](../../../.cursor/plans/dynamic_wizard_runtime_22b6f6a5.plan.md)  
> **Replaces:** `llm_gemma4/wizard/` (entire folder deleted after cutover), fixed 8-step `WizardOrchestrator.advance()`  
> **Authority doc:** `docs/gemma4_dynamic_workflow.md` (the former `docs/gemma4_e4b_workflow.md` 8-step spec was deleted)

---

## 1. Problem

The current TOML wizard is a **fixed 8-step FSM**:

- Step order hard-coded in `orchestrator.py` and `wizard_ui.py`
- LLM used only for FieldTask planning and per-field matching — **not** for workflow routing
- Users may be asked for the same data twice (Ghost paste vs field drafts)
- `thinking` must stay off long-lived sessions (`wizard_main`) due to LiteRT KV cache limits ([`docs/embed_gemma4.md`](../../docs/embed_gemma4.md))

## 2. Goal

Build a **dynamic workflow engine** that:

1. Uses Gemma to emit `next_action` JSON and pick the next executor action
2. Runs on a **custom lite graph runtime** (LangGraph-inspired, **no** `langgraph` dependency)
3. **Plans intake before asking** — each datum captured once (IntakePlan)
4. Keeps **thinking only in field sub-agent pass2** (`field_{label}_pass2`)
5. Preserves proven TOML semantics from [`docs/toml_config_design.md`](../../docs/toml_config_design.md)
6. **Deletes** `llm_gemma4/wizard/` after migrating reusable code

## 3. Users

- Operator configuring a new Excel template sidecar TOML via NiceGUI「AI 智能配置向导」
- Same process shares NiceGUI process with Input / Google / TOML tabs (no Playwright)

## 4. Functional requirements

### FR-1 Dynamic routing

- `wizard_decision` calls Gemma (one-shot `wizard_decision_{uuid}`, `thinking=False`)
- Output strict JSON: `next_action`, `action_id`, `reason`, `expected_input`, `context_update`, `route_key`
- Executor runs deterministic `action_id` from allowlisted catalog

### FR-2 IntakePlan (no duplicate input)

- Before any `ask_user`, build IntakePlan from `design_doc` + template labels
- Each key (`ghost_sample`, `input_section`, `field_drafts`, `db_id`, …) has **one** canonical UI capture
- `capture_sample` reads Ghost + `read_field_drafts()` in **one** interrupt resume
- Executor skips `ask_user` when `progress[key] == done`

### FR-3 Input tab auto-split guard (preserve from current wizard)

- While workflow active, Ghost blur on Input tab **must not** call `ui_provider.record_from_textbox`
- Only cache paste (`_sync_ghost_paste`); sample consumed by workflow `capture_sample` action
- Implemented in [`nicegui_ui/pages/tab_input.py`](../../nicegui_ui/pages/tab_input.py) via `is_wizard_active()` — **keep this behavior**, wire to new `is_workflow_active()` if renamed

### FR-4 Field/index pipeline

- Plain text: one-shot determiner inference → `split_by_determiner` → `dict[int, str]`
- Brace JSON: Python-only tokenize (no determiner LLM)
- Per-field sub-agents pick `index`; empty drafts → `index = -1` on persist
- Progressive + final TOML write via migrated `toml_patcher`

### FR-5 Human-in-the-loop

- Lite runtime `WorkflowInterrupt` pauses graph; NiceGUI FAB/dialog resumes with payload
- Tab switch must not lose state (checkpoint keyed by `principal_id` + `thread_id`)

### FR-6 Multi-agent sessions

| Session | thinking | Role |
|---------|----------|------|
| `wizard_decision_{uuid}` | False | Route next action |
| `wizard_main` | False | Plan FieldTasks, summarize |
| `wizard_determiner_{uuid}` | False | Infer delimiters |
| `field_{label}_pass1` | False | First match attempt |
| `field_{label}_pass2` | True | Retry only; new session |

### FR-7 Wizard folder deletion

- After Phase D: **no** `llm_gemma4/wizard/` package
- All imports updated to `llm_gemma4.workflow` and `llm_gemma4.toml_config`

## 5. Non-functional requirements

- **NFR-1:** No `langgraph` / `langchain` in `bootup/pyproject.toml`
- **NFR-2:** Python style per `.cursor/rules/python-style.mdc` (Chinese docstrings, pathlib, no auto-formatters)
- **NFR-3:** LLM work on `run.io_bound` worker thread (NiceGUI)
- **NFR-4:** Field agent concurrency `Semaphore(2)` preserved
- **NFR-5:** `app/core_split.py` remains single source for `split_by_determiner`

## 6. Out of scope (v1)

- User-uploaded custom design doc (optional future)
- LangGraph as dependency
- Step-8 trial run gate (cancelled in e4b v8.3)
- LLM-generated graph topology per run (DynamicFlow style)

## 7. Acceptance (summary)

See [tasks.md](tasks.md) §Verification and plan §Success criteria.
