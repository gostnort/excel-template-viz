# Phase C — Dynamic UX

> **Repo:** `excel-template-viz`  
> **Prerequisite:** [phase-b.md](phase-b.md) complete — Gemma `decide()` + IntakePlan + executor guards working  
> **Next phase:** [phase-d.md](phase-d.md)  
> **Do NOT in this phase:** delete `llm_gemma4/wizard/` (Phase D)

---

## 1. Mission

Remove fixed **8-step stepper** as workflow driver. UI becomes fully **interrupt + progress checklist** driven:

- User sees what is `pending` / `done` from `state.progress` and `state.history`
- Gemma may reorder `ask_user` steps (within executor preconditions)
- Rename wizard → workflow in user-facing flags (with backward compat)

Behavior must not regress Phase B acceptance.

---

## 2. Prerequisites (must exist after Phase B)

- `WorkflowOrchestrator.tick()` + `decide()` + `executor.py`
- `state.progress` initialized and updated
- `state.history` appended each tick
- Interrupt kinds: `ask_sources`, `ask_layout`, `ask_sample`, `ask_db_id`
- `intake_plan.py` + `design_doc.py` + `decision.py`

---

## 3. What to REMOVE as driver

### `nicegui_ui/components/wizard_ui.py`

**Remove or demote:**

```python
# REMOVE as workflow driver:
ui_step: int
_STEP_TABS: dict[int, str] = {1: "Google 连接", 2: "输入配置", ...}
_DIALOG_NEXT_STEPS = frozenset({2, 6, 7})

def enter_step(n: int): ...  # no longer called to advance FSM
def on_next_click(): ...     # replace with interrupt-centric flow
```

**Keep / refactor:**
- Layout dialog builders (`_layout_area_inputs`, `_layout_move_checks`, `_layout_offset`)
- db_id dialog (`_step7_db_id`, `_step7_select`,「保存配置文件」)
- `start_wizard()` / `stop_wizard()` entry points (rename optional)
- Shell FAB registration
- Chat sidebar refresh hooks

### `nicegui_ui/components/toml_wizard.py`

**Remove:**

```python
self.ui_step: int = 0
# run_step(step, payload) — deleted
```

**Keep:**

```python
async def run_turn(self, payload: dict | None = None) -> None: ...
def is_busy -> bool
orchestrator: WorkflowOrchestrator
```

---

## 4. What to ADD / CHANGE

### 4.1 Progress display (read-only)

New function in `wizard_ui.py` (or `workflow_ui.py` if renaming):

```python
def render_progress_summary(state: WorkflowState) -> str:
    """
    函数名: render_progress_summary
    作用: 从 progress + history 生成用户可见进度文本
    输入: state
    输出: multiline str for log or dialog
    """
    lines = []
    for key, status in state.progress.items():
        lines.append(f"[{status}] {key}")
  # append last 3 history decision reasons
    return "\n".join(lines)
```

**Log format change:**

| Old | New |
|-----|-----|
| `[Step 4.3/8] matching [Label] (2/5)` | `[field_match] matching [Label] (2/5)` |
| `[Step 2/8] input_section areas=2` | `[input_section] areas=2 move_to=[...]` |

Update `_progress` messages in `executor.py` to use progress key tags instead of `Step x/8`.

### 4.2 FAB label from decision

When interrupted:

```python
payload = orchestrator.pending_interrupt
fab_label = payload.expected_input or "继续配置"
```

When computing:

```python
fab_label = "处理中…" if ctrl.is_busy else "下一步"
```

### 4.3 Main loop UX — auto chain policy

```python
async def on_fab_click():
    ctrl = get_toml_wizard()
    if ctrl.orchestrator.is_interrupted():
        payload = collect_resume_payload()
        await ctrl.run_turn(payload)
    else:
        await ctrl.run_turn({})
    # Auto-chain compute-only ticks until interrupt or finished:
    while not ctrl.is_busy and not ctrl.orchestrator.is_interrupted() and not ctrl.orchestrator.state.is_finished:
        await ctrl.run_turn({})
        await asyncio.sleep(0.05)  # yield UI
    refresh_progress_display()
```

**Yield rule:** between `preprocess_sample`, `plan_ghost_tasks`, `match_ghost_fields` — allow UI refresh (do not block all three in one tight loop without log updates). If auto-chain runs too fast, insert `await asyncio.sleep(0)` or split match into per-field ticks.

### 4.4 Rename `wizard_active` → `workflow_active`

```python
# workflow_ui.py
def _set_workflow_active(active: bool) -> None:
    app.storage.user["workflow_active"] = active
    app.storage.user["wizard_active"] = active  # backward compat alias

def is_workflow_active() -> bool:
    return bool(app.storage.user.get("workflow_active") or app.storage.user.get("wizard_active"))

def is_wizard_active() -> bool:
    return is_workflow_active()  # alias for tab_input.py
```

Update `tab_input.py` to import `is_workflow_active` (or keep `is_wizard_active` alias).

Update `main.py`, `model_runtime.py`, `tab_toml.py` imports if they reference wizard_active.

### 4.5 Optional file rename

| Old | New | When |
|-----|-----|------|
| `wizard_ui.py` | `workflow_ui.py` | optional; update all imports |
| `toml_wizard.py` | `toml_workflow_controller.py` | optional |

If renamed, provide re-export in old filename for one release:

```python
# wizard_ui.py — thin shim
from nicegui_ui.components.workflow_ui import *  # noqa
```

Phase D may remove shims.

### 4.6 Stepper UI element

If shell shows step numbers 1–8:

- Replace with progress checklist widget (read-only)
- Data source: `state.progress` sorted keys
- Highlight current: last `pending` key from IntakePlan

No code path should call `enter_step(n)` to advance workflow.

---

## 5. `route_key` handling

Executor already skips sheet when no Google source. Phase C documents UX:

When `decision.route_key == "skip_sheet"`:
- Log `[sheet_match] skipped — no Google source`
- Mark `progress["sheet_match"] = "skip"`

When `decision.route_key == "already_have"`:
- Log skip ask (from Phase B executor guard)

`decide()` prompt should prefer `skip_sheet` route_key when `data_sources` has no `google_sheet`.

---

## 6. Files to MODIFY (checklist)

| File | Changes |
|------|---------|
| `nicegui_ui/components/wizard_ui.py` | Remove ui_step driver; progress display; FAB from interrupt |
| `nicegui_ui/components/toml_wizard.py` | Remove ui_step, run_step |
| `nicegui_ui/pages/main.py` | FAB label; optional progress widget |
| `nicegui_ui/pages/tab_input.py` | import `is_workflow_active` |
| `nicegui_ui/components/model_runtime.py` | `is_workflow_active` on template switch |
| `llm_gemma4/toml_config/executor.py` | progress-key log messages |
| `llm_gemma4/toml_config/workflow_orchestrator.py` | expose `state` for UI progress |

---

## 7. Phase C acceptance

1. No code path calls `advance(step, int)` or `run_step(n, ...)`
2. No `enter_step(n)` to advance workflow
3. User can complete full config without seeing "Step 3/8" style strings
4. Progress panel/log shows `[pending]` / `[done]` / `[skip]` keys
5. `wizard_active` and `workflow_active` both work
6. All Phase B acceptance items still pass
7. Tab switch during interrupt preserves state (checkpoint still works)
8. After stop workflow, Input tab auto-split works

---

## 8. Out of scope for Phase C

- Deleting `llm_gemma4/wizard/`
- Writing `docs/gemma4_dynamic_workflow.md`
- Changing Gemma prompts in `field_agent.py`
- Sqlite checkpoint persistence

---

## 9. Reference

| Path | Purpose |
|------|---------|
| `nicegui_ui/components/wizard_ui.py` | current stepper + dialogs |
| `nicegui_ui/pages/main.py` | shell FAB |
| `llm_gemma4/toml_config/intake_plan.py` | progress keys |
| `llm_gemma4/toml_config/workflow_orchestrator.py` | state.history |
