# Phase D — Delete `wizard/` + Docs Cutover

> **Repo:** `excel-template-viz`  
> **Prerequisite:** [phase-c.md](phase-c.md) complete — dynamic UX, no step driver, `decide()` live  
> **This is the final phase**

---

## 1. Mission

1. Zero imports from `llm_gemma4.wizard`
2. **Delete** entire directory `llm_gemma4/wizard/` (11 modules)
3. Publish `docs/gemma4_dynamic_workflow.md` as authority
4. Deprecate `docs/gemma4_e4b_workflow.md`
5. Confirm `llm_gemma4/wizard/` does not exist on disk

---

## 2. Prerequisites (must exist after Phase C)

```
llm_gemma4/workflow/          # complete
llm_gemma4/toml_config/       # complete — all runtime imports point here
nicegui_ui/                   # uses WorkflowOrchestrator only
```

Workflow must pass full manual E2E (Phase B acceptance 1–9) **before** deletion.

---

## 3. Step D1 — Import audit

Run search (must return **zero** results before delete):

```
llm_gemma4.wizard
llm_gemma4/wizard
WizardOrchestrator
from llm_gemma4.wizard
```

### Known import sites to fix (grep each)

| File | Old import | New import |
|------|------------|------------|
| `nicegui_ui/components/toml_wizard.py` | `wizard.orchestrator` | `toml_config.workflow_orchestrator` |
| `nicegui_ui/components/wizard_ui.py` | `wizard.state`, `wizard.toml_patcher` | `workflow.state`, `toml_config.toml_patcher` |
| `nicegui_ui/components/toml_wizard.py` | `wizard.template_labels` | `toml_config.template_labels` |
| Any test files | `llm_gemma4.wizard.*` | `llm_gemma4.toml_config.*` / `workflow.*` |

### Internal `toml_config/` imports

All must use:

```python
from llm_gemma4.workflow.state import WorkflowState, FieldState
from llm_gemma4.toml_config.field_agent import run_field_agent
# etc. — never llm_gemma4.wizard
```

---

## 4. Step D2 — Delete legacy package

Delete these files (entire folder):

```
llm_gemma4/wizard/__init__.py          # if exists
llm_gemma4/wizard/context.py
llm_gemma4/wizard/field_agent.py
llm_gemma4/wizard/orchestrator.py
llm_gemma4/wizard/parse_field_json.py
llm_gemma4/wizard/prompts.py
llm_gemma4/wizard/sample_analysis.py
llm_gemma4/wizard/sample_preprocess.py
llm_gemma4/wizard/state.py
llm_gemma4/wizard/template_labels.py
llm_gemma4/wizard/toml_patcher.py
llm_gemma4/wizard/trial_run.py
```

**Remove completely:**
- `class WizardOrchestrator`
- `def advance(self, step: int, payload: dict) -> WizardState`

No thin adapter shim left in repo.

---

## 5. Step D3 — UI finalization

### `tab_input.py`

```python
from nicegui_ui.components.workflow_ui import is_workflow_active

# in on_ghost_blur:
if is_workflow_active():
    return
```

Remove `is_wizard_active` import if shim removed.

### Optional shim cleanup

If Phase C added `wizard_ui.py` re-export shim:
- Move all code to `workflow_ui.py`
- Delete `wizard_ui.py` OR keep minimal deprecated re-export with comment

### `toml_wizard.py` rename (if not done in Phase C)

- Rename to `toml_workflow_controller.py`
- Class `WorkflowController`
- Update `get_toml_wizard()` → `get_workflow_controller()` with alias

---

## 6. Step D4 — Documentation

### Create `docs/gemma4_dynamic_workflow.md`

Must document:

1. Architecture: decide → execute → interrupt loop
2. Packages: `llm_gemma4/workflow/`, `llm_gemma4/toml_config/`
3. IntakePlan / no duplicate input
4. Session table (thinking only pass2)
5. Executor action catalog (9 actions)
6. UI interrupt kinds
7. Input tab ghost guard
8. TOML invariants (index, determiner, multi input_area)
9. Multi-agent topology
10. Anti-patterns list (from e4b §6, updated for dynamic flow)

### Update `docs/gemma4_e4b_workflow.md`

Add at top:

```markdown
> **DEPRECATED** — superseded by [gemma4_dynamic_workflow.md](gemma4_dynamic_workflow.md). Fixed 8-step FSM removed.
```

### Update plan pointers

- `plans/toml-guide-2.md` — link to `plans/dynamic-wizard-runtime/`
- `plans/feature-gemma-toml-1/design.md` — add deprecated note if needed

---

## 7. Step D5 — Verify nothing references wizard folder

```powershell
# PowerShell from repo root
rg "llm_gemma4\.wizard" 
rg "llm_gemma4/wizard"
Test-Path llm_gemma4/wizard  # must be False
```

---

## 8. Final acceptance (all 10 items)

1. Start workflow from Input Config; FAB + sidebar chat appear
2. Layout: multi `input_area`, multi `move_to`; TOML persists; tab → 输入
3. Ghost paste does **not** auto-fill fields
4. One FAB captures ghost + field drafts
5. Log shows indexed_segments preview before matching
6. ≥3 fields: `(i/n)` progress, max 2 concurrent
7. Fuzzy → regex with pass2 thinking log
8. Save `db_id=None` without opening dropdown
9. Close workflow → `EndGemma()`; normal auto-split restored
10. **`llm_gemma4/wizard/` directory does not exist**

---

## 9. Rollback plan (if delete breaks build)

Phase D should be a single commit:

- If failure after delete: restore `llm_gemma4/wizard/` from git
- Fix imports before second attempt

Do not partial-delete — grep must be clean first.

---

## 10. Post-cutover architecture (reference for doc)

```
nicegui_ui/
  components/toml_workflow_controller.py  (or toml_wizard.py)
  components/workflow_ui.py
  pages/tab_input.py                     # is_workflow_active guard

llm_gemma4/
  workflow/                              # runtime only
  toml_config/                           # domain + orchestration
  wizard/                                # GONE
```

**No** `langgraph` in `bootup/pyproject.toml`.

---

## 11. `gemma4_dynamic_workflow.md` outline (write this file)

```markdown
# Gemma4 Dynamic TOML Workflow

## 1. Overview
## 2. tick() loop
## 3. IntakePlan
## 4. decide() JSON contract
## 5. Executor actions table
## 6. Sessions & thinking rules
## 7. preprocess / match / regex
## 8. UI interrupts
## 9. Input tab ghost guard
## 10. TOML persist rules
## 11. Anti-patterns
## 12. Related docs (embed_gemma4, toml_config_design, db_store)
```

Copy technical content from:
- `plans/dynamic-wizard-runtime/phase-a.md` §5
- `plans/dynamic-wizard-runtime/phase-b.md` §6–7
- `docs/gemma4_e4b_workflow.md` §1.7–1.8, §4, §6 (update wording for dynamic flow)

---

## 12. Phase D deliverables checklist

- [ ] `rg llm_gemma4.wizard` → 0 matches
- [ ] `llm_gemma4/wizard/` deleted
- [ ] `docs/gemma4_dynamic_workflow.md` created
- [ ] `gemma4_e4b_workflow.md` deprecated banner
- [ ] `tab_input.py` uses `is_workflow_active`
- [ ] Manual E2E 1–10 pass
