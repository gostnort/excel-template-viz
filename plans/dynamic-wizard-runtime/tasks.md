# Gemma4 Dynamic TOML Workflow — Task Breakdown

> **Spec-kit:** `speckit_tasks` template not in repo — authoritative task list  
> **Plan:** [plan.md](plan.md)

---

## Phase A — Runtime + executor parity

### A1 Workflow runtime (`llm_gemma4/workflow/`)

- [ ] **A1.1** Create `workflow/state.py`: `WorkflowState`, `FieldState`, `Command`, `InterruptPayload`, `ExecutorResult`
- [ ] **A1.2** Create `workflow/checkpoint.py`: `MemoryCheckpoint` with `save/load/is_interrupted` per `thread_id`
- [ ] **A1.3** Create `workflow/graph.py`: `WorkflowGraph`, `CompiledWorkflow`, `WorkflowInterrupt`
- [ ] **A1.4** Create `workflow/parallel.py`: `map_send(fn, items, cap=2)` with `ThreadPoolExecutor` + `Semaphore`
- [ ] **A1.5** Unit tests: interrupt → resume → state merge; single-interrupt-per-node rule

### A2 Migrate wizard modules → `toml_config/`

- [ ] **A2.1** Copy `field_agent.py`, `prompts.py`, `parse_field_json.py`, `context.py`, `template_labels.py`, `toml_patcher.py`
- [ ] **A2.2** Copy `sample_preprocess.py`; merge `sample_analysis.py` helpers
- [ ] **A2.3** Fix all internal imports: `llm_gemma4.wizard.*` → `llm_gemma4.toml_config.*`
- [ ] **A2.4** Update `toml_patcher` / state types to import `WorkflowState` from `workflow/state.py`

### A3 Executor + orchestrator

- [ ] **A3.1** Create `executor.py`: `ACTION_HANDLERS` registry (9 actions from plan §4)
- [ ] **A3.2** Lift logic from `orchestrator.py`: `_phase_preprocess`, `_phase_plan_ghost`, `_phase_match_ghost`, steps 1–7
- [ ] **A3.3** Create `workflow_orchestrator.py`: `tick()`, callbacks (`on_progress`, `on_chat`), `close()`
- [ ] **A3.4** Phase A: hard-coded `decide_stub()` returning fixed action sequence (no Gemma routing)

### A4 NiceGUI integration

- [ ] **A4.1** Refactor `toml_wizard.py` → `WorkflowController.run_turn()` calling `tick()`
- [ ] **A4.2** Refactor `wizard_ui.py`: map `InterruptPayload.kind` → dialogs (`ask_layout`, `ask_sample`, `ask_db_id`, `ask_sources`)
- [ ] **A4.3** **Preserve** `tab_input.py` guard: skip `record_from_textbox` when workflow active (rename import when `is_workflow_active` lands)
- [ ] **A4.4** Wire `run.io_bound` around sync `tick()`; yield between long compute phases
- [ ] **A4.5** Manual E2E: full template config path matches v8.3 acceptance (layout → sample → match → save)

---

## Phase B — Decision layer + IntakePlan

### B1 Intake and design doc

- [ ] **B1.1** Create `intake_plan.py`: `build_intake_plan()`, `IntakeItem`, key satisfaction checks
- [ ] **B1.2** Create `design_doc.py`: compose excerpt from `docs/toml_config_design.md` + template labels + sidecar hints (~8k cap)
- [ ] **B1.3** Initialize `state.progress` from IntakePlan on workflow start

### B2 Decision layer

- [ ] **B2.1** Create `parse_decision_json.py` (pattern from `parse_field_json.py`)
- [ ] **B2.2** Create `decision.py`: prompt with `ACTION_CATALOG`, `IntakePlan`, `already_captured`; `thinking=False`, `max_tokens≤512`
- [ ] **B2.3** Replace `decide_stub()` with `decide()`; allowlist `action_id`
- [ ] **B2.4** Executor: skip `ask_user` when `progress[key]==done`

### B3 Verification

- [ ] **B3.1** Test: full run never double-asks same IntakePlan key
- [ ] **B3.2** Test: grep/code review — `thinking=True` only in `field_agent` pass2 path
- [ ] **B3.3** Test: decision JSON parse failure → deterministic re-prompt (not thinking on decision session)

---

## Phase C — Dynamic UX

- [ ] **C1** Remove `ui_step` / `_STEP_TABS` as workflow driver; keep as read-only progress display from `history`
- [ ] **C2** Migrate `app.storage.user["wizard_active"]` → `workflow_active` (alias old key during transition)
- [ ] **C3** Progress log format from `history` entries (replace `[Step x/8]` tags)
- [ ] **C4** Gemma may emit `route_key=skip_sheet` when no Google source (executor still enforces skip)

---

## Phase D — Delete `wizard/` + docs

### D1 Import cleanup

- [ ] **D1.1** Grep: `llm_gemma4.wizard` → zero matches
- [ ] **D1.2** Update `nicegui_ui`, `tab_toml`, `main.py`, any test imports

### D2 Delete legacy package

- [ ] **D2.1** Delete directory `llm_gemma4/wizard/` (all 11 modules)
- [ ] **D2.2** Remove `WizardOrchestrator`, `advance(step, payload)` — no adapters left

### D3 Documentation

- [ ] **D3.1** Write `docs/gemma4_dynamic_workflow.md` (new authority)
- [ ] **D3.2** Add deprecation banner to `docs/gemma4_e4b_workflow.md`
- [ ] **D3.3** Update `plans/toml-guide-2.md` pointer to new spec folder

---

## Verification checklist (manual)

1. Start workflow from Input Config tab; shell FAB + sidebar chat appear
2. Layout dialog: multi `input_area`, multi-select `move_to`; TOML persists; switches to Input tab
3. Paste Ghost sample on Input tab — **fields do not auto-fill** from paste
4. FAB captures sample + field drafts in one step
5. Preprocess log shows `indexed_segments` preview before field matching
6. ≥3 fields: concurrent progress, max 2 running
7. Fuzzy field → regex step with pass2 thinking log line
8. Save with default `db_id=None` without opening dropdown
9. Close workflow → `EndGemma()`; normal Input paste auto-split works again
10. `llm_gemma4/wizard/` directory does not exist

---

## Dependency graph (implementation order)

```
A1 (workflow runtime)
  → A2 (copy modules)
    → A3 (executor + orchestrator)
      → A4 (UI)
        → B1 (intake + design_doc)
          → B2 (decision)
            → B3 (tests)
              → C (UX)
                → D (delete wizard/)
```
