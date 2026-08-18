# Gemma4 Dynamic TOML Workflow — Task Breakdown

> **Spec-kit:** `speckit_tasks` template not in repo — authoritative task list  
> **Plan:** [plan.md](plan.md)  
> **Live status:** [STATUS.md](STATUS.md) (reconciled 2026-08-16)

---

## Phase A — Runtime + executor parity

### A1 Workflow runtime (`llm_gemma4/workflow/`)

- [x] **A1.1** Create `workflow/state.py`: `WorkflowState`, `FieldState`, `Command`, `InterruptPayload`, `ExecutorResult`
- [x] **A1.2** Create `workflow/checkpoint.py`: `MemoryCheckpoint` with `save/load/is_interrupted` per `thread_id`
- [x] **A1.3** Create `workflow/graph.py`: `WorkflowGraph`, `CompiledWorkflow.dispatch`, `WorkflowInterrupt` (action nodes + Continue/Interrupt)
- [x] **A1.4** Create `workflow/parallel.py`: `map_send` + **`map_run_sequential`** (executor uses sequential for LiteRT)
- [x] **A1.5** Unit tests: interrupt → resume → state merge; single-interrupt-per-node rule (`test/workflow/`)

### A2 Migrate wizard modules → `toml_config/`

- [x] **A2.1** Copy `field_agent.py`, `prompts.py`, `parse_field_json.py`, `context.py`, `template_labels.py`, `toml_patcher.py`
- [x] **A2.2** Copy `sample_preprocess.py`; merge `sample_analysis.py` helpers
- [x] **A2.3** Fix all internal imports: `llm_gemma4.wizard.*` → `llm_gemma4.toml_config.*`
- [x] **A2.4** Update `toml_patcher` / state types to import `WorkflowState` from `workflow/state.py`

### A3 Executor + orchestrator

- [x] **A3.1** Create `executor.py`: `ACTION_HANDLERS` registry (9 actions from plan §4)
- [x] **A3.2** Lift logic from `orchestrator.py`: preprocess, plan, match, steps 1–7
- [x] **A3.3** Create `workflow_orchestrator.py`: `dispatch()` + Graph nodes; `tick()` single-cycle helper
- [x] **A3.4** `decide_stub()` via `WORKFLOW_DECIDE_STUB=1`; default is `decide()` (Phase B)

### A4 NiceGUI integration

- [x] **A4.1** Refactor `toml_wizard.py` → `dispatch(WorkflowEvent)` on `await_gemma_thread`
- [x] **A4.2** Refactor `workflow_ui.py` (was `wizard_ui.py`): map `InterruptPayload.kind` → dialogs
- [x] **A4.3** **Preserve** `tab_input.py` guard: `is_workflow_active()` skips `record_from_textbox`
- [x] **A4.4** Offload tick via **`gemma_worker` + `await_gemma_thread`** (replaces planned `run.io_bound`)
- [x] **A4.5** Mock dual-template E2E in `test/workflow/`; GPU E2E still manual — see [STATUS.md](STATUS.md) §4

---

## Phase B — Decision layer + IntakePlan

### B1 Intake and design doc

- [x] **B1.1** Create `intake_plan.py`: `build_intake_plan()`, `IntakeItem`, key satisfaction checks
- [x] **B1.2** Create `design_doc.py`: compose excerpt from `docs/toml_config_design.md` + template labels + sidecar hints (~8k cap)
- [x] **B1.3** Initialize `state.progress` from IntakePlan on workflow start
- [x] **B1.4** *(implementation extra)* `intake_seed.py` — sidecar `[[sources]]` hydration

### B2 Decision layer

- [x] **B2.1** Create `parse_decision_json.py` (pattern from `parse_field_json.py`)
- [x] **B2.2** Create `decision.py`: prompt with `ACTION_CATALOG`, `IntakePlan`, `already_captured`; `thinking=False`, `max_tokens≤512`
- [x] **B2.3** `decide()` default; `decide_stub` for tests via env
- [x] **B2.4** Executor: skip / `already_have` when progress key done; finalize fallbacks added in testing

### B3 Verification

- [x] **B3.1** Test: full run never double-asks same IntakePlan key
- [x] **B3.2** Test: grep/code review — `thinking=True` only in `field_agent` pass2 path
- [x] **B3.3** Test: decision JSON parse failure → deterministic re-prompt (not thinking on decision session)

---

## Phase C — Dynamic UX

- [x] **C1** Remove `ui_step` / `_STEP_TABS` as workflow driver (removed; no matches in `nicegui_ui`)
- [x] **C2** Migrate `app.storage.user["workflow_active"]` with `wizard_active` alias
- [x] **C3** Progress in sidebar via `sidebar_feed_text` (log + chat); FAB checklist removed
- [x] **C4** `route_key=skip_sheet` / executor skip when no Google source

**UX deltas not in original plan:** FAB moved to **bottom-left**; intake checklist removed from sidebar and FAB.

---

## Phase D — Delete `wizard/` + docs

### D1 Import cleanup

- [x] **D1.1** Grep: `llm_gemma4.wizard` → zero matches in **production code** (only plans/docs)
- [x] **D1.2** Update `nicegui_ui`, `tab_toml`, `main.py` imports → `workflow_ui` / `toml_config`

### D2 Delete legacy package

- [x] **D2.1** Delete directory `llm_gemma4/wizard/`
- [x] **D2.2** Remove `WizardOrchestrator`, `advance(step, payload)` — no adapters left

### D3 Documentation

- [x] **D3.1** Write `docs/gemma4_dynamic_workflow.md` (new authority)
- [x] **D3.2** Delete `docs/gemma4_e4b_workflow.md`; remaining pointers retargeted to `gemma4_dynamic_workflow.md`
- [x] **D3.3** Update `plans/toml-guide-2.md` pointer to Graph event runtime

---

## Post-plan (`feature-gemma-toml-3` only)

- [x] **P0** `llm_gemma4/runtime/gemma_worker.py` — single-thread LiteRT queue
- [x] Shutdown `release_all_models_sync` + `shutdown_gemma_worker`
- [x] Draft pollution / `db_id=None` / brace JSON index fixes (`6fd8dfe`)
- [x] Dropdown combobox + empty option (`tab_input.py`)
- [ ] Commit / push any uncommitted UI polish (FAB position, etc.)

---

## Verification checklist (manual)

1. [x] Start workflow from Input Config tab; FAB + sidebar chat appear
2. [x] Layout dialog: multi `input_area`, multi-select `move_to`; TOML persists; switches to Input tab
3. [x] Paste Ghost sample — **fields do not auto-fill** from paste
4. [x] FAB captures sample + field drafts in one step
5. [x] Preprocess log shows indexed_segments / token preview
6. [~] ≥3 fields: progress in sidebar log; **sequential** not parallel (2) agents
7. [~] Fuzzy → regex with pass2 thinking — works when haystack compatible
8. [x] Save with `db_id=None` (after `6fd8dfe`)
9. [x] Close workflow → `EndGemma()`; shutdown hook releases VRAM (`bc81197`)
10. [x] `llm_gemma4/wizard/` directory does not exist

---

## Dependency graph (implementation order)

```
A1 (workflow runtime)
  → A2 (copy modules)
    → A3 (executor + orchestrator)
      → A4 (UI)
        → B1 (intake + design_doc)
          → B2 (decision)
            → B3 (tests)          ← done (`test/workflow/`)
              → C (UX)            ← done
                → D (delete wizard/)  ← done
                  → P0 gemma_worker (feature-gemma-toml-3)
                    → Graph dispatch (start/resume/stop)
```
