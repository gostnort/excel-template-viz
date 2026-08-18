# Gemma4 Dynamic TOML Workflow — Coding Handoff (all phases)

> **Superseded for tracking:** use [STATUS.md](STATUS.md) + [tasks.md](tasks.md). Phases A–D are largely implemented; `wizard/` deleted.

> **Audience:** small coding LLM implementing this repo  
> **Repo:** `excel-template-viz`  
> **Do NOT add:** `langgraph`, `langchain`  
> **End state:** delete `llm_gemma4/wizard/` entirely; all imports → `llm_gemma4.workflow` + `llm_gemma4.toml_config`

---

## 0. What you are building

Replace fixed 8-step `WizardOrchestrator.advance(step, payload)` with:

```
tick(user_input) → build_intake_plan → decide() → execute(action_id) → checkpoint / interrupt
```

- **decide()**: Gemma emits JSON `next_action` + `action_id` (Phase B; stub in Phase A)
- **execute()**: deterministic Python; calls field sub-agents where needed
- **Runtime**: custom graph with `WorkflowInterrupt` + `resume()` (LangGraph-inspired, no dependency)

---

## 1. Hard rules (never violate)

### 1.1 No duplicate user input

Before `ask_user`, check `IntakePlan`. Each datum captured **once**:

| Key | UI source | State field |
|-----|-----------|-------------|
| `data_sources` | Google tab / dialog | `data_sources` |
| `input_section` | layout dialog | `input_area`, `move_to`, `offset` |
| `ghost_sample` | Input tab Ghost textarea | `ghost_text_sample` |
| `field_drafts` | **same interrupt** as ghost | `user_draft` via `read_field_drafts()` |
| `db_id` | finalize dialog | `db_id` |

Executor: if `progress[key] == "done"` → skip ask.

### 1.2 Thinking ONLY on field pass2

| Session ID pattern | thinking | max_tokens |
|--------------------|----------|------------|
| `wizard_decision_{uuid}` | **False** | 256–512 |
| `wizard_main` | **False** | 512 |
| `wizard_determiner_{uuid}` | **False** | 512 |
| `field_{label}_pass1` | **False** | 256 |
| `field_{label}_pass2` | **True** | `load_thinking_budget(profile)` |

Forbidden: `thinking=True` on decision or main session; pass2 must use **new** session_id.

### 1.3 Input tab: no auto-split while workflow active

**Keep existing behavior** in `nicegui_ui/pages/tab_input.py` ~L726–728:

```python
if is_wizard_active():  # rename to is_workflow_active() in Phase C/D
    return  # do NOT call record_from_textbox
```

Wizard captures sample only via `capture_sample` action.

### 1.4 TOML / split invariants (from e4b v8.3)

- `dict[int, str]` for wizard matching — not flat_kv
- Determiner: one-shot session, **not** `wizard_main`; split **raw** ghost with `app/core_split.split_by_determiner`
- Brace JSON: Python tokenize only; keep empty `""` tokens
- Empty field draft → `index=-1` on persist (full overwrite)
- `needs_regex` fields → regex step; validate with `re.search`
- No trial-run gate; step 7 saves and exits
- Field agents: `Semaphore(2)` max concurrent
- Multi `input_area` list + multi `move_to` list supported in layout dialog

### 1.5 Python style

- Chinese docstrings on every function (模板见 `.cursor/rules/python-style.mdc`)
- `pathlib.Path` not `os`
- No blank lines inside function bodies
- No black/ruff format

---

## 2. Final file tree

```
llm_gemma4/workflow/
  __init__.py
  state.py           # WorkflowState, FieldState, InterruptPayload, ExecutorResult, Command
  graph.py           # WorkflowGraph, CompiledWorkflow, WorkflowInterrupt
  checkpoint.py      # MemoryCheckpoint
  router.py
  parallel.py        # map_send(fn, items, cap=2)

llm_gemma4/toml_config/
  __init__.py
  workflow_orchestrator.py
  decision.py
  parse_decision_json.py
  executor.py
  intake_plan.py
  design_doc.py
  field_agent.py       # copy from wizard/
  sample_preprocess.py
  prompts.py
  parse_field_json.py
  context.py
  template_labels.py
  toml_patcher.py

llm_gemma4/wizard/     # DELETE in Phase D after grep-clean
```

**NiceGUI touch points:**

| File | Change |
|------|--------|
| `nicegui_ui/components/toml_wizard.py` | `run_turn()` → `tick()` |
| `nicegui_ui/components/wizard_ui.py` | interrupt-driven dialogs |
| `nicegui_ui/pages/tab_input.py` | keep ghost guard |
| `nicegui_ui/pages/tab_toml.py` | start entry |
| `nicegui_ui/pages/main.py` | shell FAB, stop on template switch |

---

## 3. Data structures

### 3.1 FieldState (unchanged)

```python
@dataclass
class FieldState:
    input_label: str
    match_type: str = "unknown"   # exact | fuzzy | none
    index: int = -1
    column_name: str = ""
    needs_regex: bool = False
    regex: str = ""
    source_file: str = ""
    source_sheet: str = ""
    id: bool = False
    error: str = ""
    used_thinking: bool = False
```

### 3.2 WorkflowState (extend WizardState)

Keep all existing WizardState fields from `llm_gemma4/wizard/state.py` plus:

```python
design_doc: str = ""
user_inputs: dict[str, Any] = field(default_factory=dict)
computed_results: dict[str, Any] = field(default_factory=dict)
progress: dict[str, str] = field(default_factory=dict)  # pending|done|skip
history: list[dict[str, Any]] = field(default_factory=list)
route_key: str = ""
pending_interrupt: dict[str, Any] | None = None
finished: bool = False  # alias is_finished ok during migration
```

### 3.3 InterruptPayload

```python
@dataclass
class InterruptPayload:
    kind: str   # ask_sources | ask_layout | ask_sample | ask_db_id | show_progress
    expected_input: str
    auto_chain: bool = False
    meta: dict[str, Any] = field(default_factory=dict)
```

### 3.4 ExecutorResult

```python
@dataclass
class ExecutorResult:
    ok: bool
    messages: list[str]
    state_patch: dict[str, Any]
    interrupt: InterruptPayload | None = None
    route_key: str = ""
```

### 3.5 Decision JSON (Phase B)

```json
{
  "next_action": "ask_user | compute | validate | finalize | error",
  "action_id": "record_sources | capture_layout | capture_sample | preprocess_sample | plan_ghost_tasks | match_ghost_fields | match_sheet_columns | infer_regex | finalize_toml",
  "reason": "...",
  "expected_input": "...",
  "context_update": {},
  "route_key": ""
}
```

Parse failure on decision: **re-prompt same one-shot session** (thinking=False). Do NOT use thinking for decision retry.

---

## 4. Executor action catalog

| action_id | next_action | Preconditions | What it does |
|-----------|-------------|---------------|--------------|
| `record_sources` | ask/compute | template_id set | Store `data_sources`, `template_path`; `_persist_toml` |
| `capture_layout` | ask | sources done | Interrupt `ask_layout`; on resume set `input_area`, `move_to`, `offset`; rebuild fields; persist; switch tab 输入 |
| `capture_sample` | ask | layout done | Interrupt `ask_sample`; on resume: `read_ghost_sample()` + `read_field_drafts(labels)` → `ghost_text_sample`, `user_draft`; init `fields` per label |
| `preprocess_sample` | compute | ghost captured | `build_indexed_segments()`; determiner one-shot if plain text; set `indexed_segments`, `sample_kind`, `preprocess_done` |
| `plan_ghost_tasks` | compute | preprocess done | `wizard_main` plans labels; empty draft labels → skip, set `index=-1`, `match_type=none` |
| `match_ghost_fields` | compute | plan done | Parallel `run_field_agent("ghost")` cap 2; update `index`, `needs_regex` |
| `match_sheet_columns` | compute | ghost match done | Skip if no google source; else parallel sheet agents |
| `infer_regex` | compute | sheet done/skipped | Only `needs_regex` fields; haystack = single segment at `index` + draft value |
| `finalize_toml` | ask/finalize | all progress done | Interrupt `ask_db_id`; on confirm persist all indexes; `finished=True` |

**Lift implementation from:** `llm_gemma4/wizard/orchestrator.py` methods `_phase_preprocess`, `_phase_plan_ghost`, `_phase_match_ghost`, and `advance()` branches for steps 1–7.

**Phase A stub sequence (hard-coded decide_stub):**

```
record_sources → capture_layout → capture_sample → preprocess_sample →
plan_ghost_tasks → match_ghost_fields → match_sheet_columns → infer_regex → finalize_toml
```

Skip `match_sheet_columns` when no Google source (same logic as orchestrator step 5).

---

## 5. Main loop

```python
# llm_gemma4/toml_config/workflow_orchestrator.py

class WorkflowOrchestrator:
    def __init__(self, backend, on_progress, on_chat, on_match_notify):
        self._backend = backend
        self.state = WorkflowState()
        self._thread_id = "workflow_main"
        self._checkpointer = MemoryCheckpoint()
        self._ui_lock = threading.Lock()
        # callbacks...

    def tick(self, user_input: dict | None = None) -> WorkflowState:
        if self._checkpointer.is_interrupted(self._thread_id):
            self.state = self._checkpointer.resume(self._thread_id, user_input, self.state)
        intake = build_intake_plan(self.state)
        decision = decide(self.state, user_input, intake)  # stub in Phase A
        result = execute(decision, self.state, self._backend, callbacks...)
        self.state = apply_patch(self.state, result.state_patch)
        self.state.history.append({"decision": decision, "result": result})
        if result.interrupt:
            self._checkpointer.save_interrupt(self._thread_id, self.state, result.interrupt)
            return self.state
        if decision.next_action == "finalize" or self.state.finished:
            return self.state
        return self.state

    def close(self):
        # close wizard_main session if open
```

Controller (`toml_wizard.py`):

```python
async def run_turn(self, payload):
    self._busy = True
    try:
        state = await run.io_bound(self.orchestrator.tick, payload)
        if self.orchestrator.is_interrupted():
            workflow_ui.show_interrupt(self.orchestrator.pending_interrupt)
        elif state.finished:
            self.stop()
    finally:
        self._busy = False
```

---

## 6. Lite runtime API (implement in Phase A)

```python
# workflow/graph.py
class WorkflowInterrupt(Exception):
    def __init__(self, payload: InterruptPayload): ...

# workflow/checkpoint.py
class MemoryCheckpoint:
    def is_interrupted(self, thread_id: str) -> bool: ...
    def save_interrupt(self, thread_id, state, payload): ...
    def resume(self, thread_id, user_value, state) -> WorkflowState: ...

# workflow/parallel.py
def map_send(fn, items: list, cap: int = 2) -> list:
    # ThreadPoolExecutor + Semaphore(cap)
```

**Rule:** one `interrupt()` per node; validation retry via state flag, not nested interrupts.

---

## 7. IntakePlan (Phase B)

```python
# toml_config/intake_plan.py

INTAKE_KEYS = [
    "data_sources", "input_section", "ghost_sample", "field_drafts",
    "ghost_preprocess", "field_match", "sheet_match", "regex_infer", "db_id",
]

@dataclass
class IntakeItem:
    key: str
    status: str  # pending|done|skip
    interrupt_kind: str | None
    state_fields: list[str]  # fields that satisfy this key

def build_intake_plan(state: WorkflowState) -> list[IntakeItem]: ...
def already_captured(state, key) -> bool: ...
```

Initialize `state.progress` on workflow start from template labels:

```python
progress = {
    "input_section": "pending",
    "ghost_sample": "pending",
    "field_drafts": "pending",
    "db_id": "pending",
}
for label in template_labels:
    progress[f"field:{label}"] = "pending"
```

---

## 8. design_doc (Phase B)

```python
# toml_config/design_doc.py
def build_design_doc(template_id: str, template_path: Path, labels: list[str]) -> str:
    # 1. Read excerpt from docs/toml_config_design.md (determiner, index, input_section, db_id, id rules)
    # 2. Append template_labels list
    # 3. Append existing sidecar TOML snippet if present
    # Cap total ~8000 chars
```

---

## 9. UI interrupt mapping

| `InterruptPayload.kind` | Tab | Dialog / action |
|-------------------------|-----|-----------------|
| `ask_sources` | Google 连接 | data source collection |
| `ask_layout` | 输入配置 | multi `input_area` rows, multi-select `move_to`, `offset` — reuse wizard_ui layout dialog code |
| `ask_sample` | 输入 | user pastes Ghost; FAB confirms → `read_ghost_sample()` + `read_field_drafts()` |
| `ask_db_id` | 输入配置 | dropdown or None;「保存配置文件」in dialog |
| `show_progress` | — | log only; continue if `auto_chain` |

**Reuse from `wizard_ui.py`:** layout dialog (`_layout_area_inputs`, `_layout_move_checks`), step 7 db_id dialog, FAB `on_next_click` pattern refactored to `on_resume_interrupt(payload)`.

**Remove as driver:** `ui_step`, `_STEP_TABS` dict (Phase C — keep display-only).

---

## 10. Migration: copy from `llm_gemma4/wizard/`

| Source | Destination | Notes |
|--------|-------------|-------|
| `state.py` | `workflow/state.py` | extend |
| `orchestrator.py` | `executor.py` + `workflow_orchestrator.py` | split |
| `field_agent.py` | `toml_config/field_agent.py` | fix imports |
| `sample_preprocess.py` + `sample_analysis.py` | `toml_config/sample_preprocess.py` | merge |
| `toml_patcher.py` | `toml_config/toml_patcher.py` | import WorkflowState |
| `prompts.py` | `toml_config/prompts.py` | |
| `parse_field_json.py` | `toml_config/parse_field_json.py` | |
| `context.py` | `toml_config/context.py` | |
| `template_labels.py` | `toml_config/template_labels.py` | |
| `trial_run.py` | **drop** | |

**Import rewrite:** `llm_gemma4.wizard.*` → `llm_gemma4.toml_config.*` or `llm_gemma4.workflow.*`

---

## PHASE A — Runtime + executor parity (implement first)

### A1 Create `llm_gemma4/workflow/`

1. `state.py` — dataclasses above
2. `checkpoint.py` — MemoryCheckpoint per thread_id
3. `graph.py` — WorkflowInterrupt exception (minimal v1; full graph optional)
4. `parallel.py` — map_send with Semaphore(2)
5. Tests: interrupt save/resume merges user payload into state

### A2 Copy wizard modules → `toml_config/`

Copy files listed in §10; fix imports; `toml_patcher` uses `WorkflowState`.

### A3 `executor.py` + `workflow_orchestrator.py`

- `ACTION_HANDLERS: dict[str, Callable]` registry
- Lift orchestrator logic verbatim where possible
- `decide_stub(state, intake) -> Decision` returns next action in fixed order
- Callbacks: `_progress`, `_chat`, `_match_notify` with `_ui_lock` (copy from orchestrator)

### A4 NiceGUI

- `toml_wizard.py`: `WorkflowOrchestrator` instead of `WizardOrchestrator`; `run_turn()` not `run_step(n)`
- `wizard_ui.py`: on interrupt kind → open correct dialog; on confirm → `run_turn(resume_payload)`
- Keep `tab_input.py` ghost guard unchanged
- `run.io_bound` around sync `tick()`
- Yield between long phases: call `tick()` multiple times with `auto_chain=False` between preprocess/plan/match if needed

### A5 Phase A done when

Manual E2E passes items 1–9 in §14 checklist (except item 10 — wizard folder still exists).

---

## PHASE B — Decision layer + IntakePlan

### B1 `intake_plan.py`, `design_doc.py`

- Implement §7 and §8
- Wire into `tick()` before `decide()`
- Initialize `progress` on `start()`

### B2 `decision.py`, `parse_decision_json.py`

```python
def decide(state, user_input, intake, backend) -> Decision:
    if decide_stub_mode: ...  # remove after cutover
    doc = state.design_doc or build_design_doc(...)
    prompt = f"{ACTION_CATALOG}\n\nIntakePlan:\n{intake}\n\nState summary:\n{summary}\n..."
    sid = f"wizard_decision_{uuid4().hex[:8]}"
    # open_session(sid, thinking=False, max_tokens=512)
    # parse_decision_json(reply)
    # validate action_id in ALLOWED_ACTIONS
```

### B3 Executor guards

- Before returning `interrupt` for ask_user: assert `not already_captured(state, key)`
- Mark `progress[key] = "done"` after successful capture

### B4 Tests

- Mock `decide()` sequence: no duplicate interrupt kinds for same key
- Grep: only `field_agent` pass2 path sets `thinking=True`

### B5 Phase B done when

Full run driven by Gemma `decide()` (or mocked decide in tests); checklist items 1–9 pass.

---

## PHASE C — Dynamic UX

1. Remove `ui_step` / `_STEP_TABS` as workflow driver
2. Progress sidebar from `state.history` entries (not `[Step x/8]`)
3. `app.storage.user["workflow_active"]` with alias read for `wizard_active`
4. `route_key=skip_sheet` when no Google source (executor enforces regardless)

---

## PHASE D — Delete wizard/ + docs

1. `rg "llm_gemma4\.wizard" ` → **zero matches**
2. Delete directory `llm_gemma4/wizard/` (all 11 files)
3. Remove `WizardOrchestrator`, `advance(step, payload)` completely
4. `tab_input.py`: `from nicegui_ui.components.workflow_ui import is_workflow_active`
5. Write `docs/gemma4_dynamic_workflow.md`; delete `docs/gemma4_e4b_workflow.md`
6. Item 10 checklist: wizard folder must not exist

---

## 11. Key existing code to read (do not reinvent)

| Path | Why |
|------|-----|
| `llm_gemma4/wizard/orchestrator.py` | All step logic to lift |
| `llm_gemma4/wizard/field_agent.py` | pass1/pass2 sessions |
| `llm_gemma4/wizard/sample_preprocess.py` | indexed_segments |
| `llm_gemma4/wizard/toml_patcher.py` | persist_wizard_toml |
| `nicegui_ui/components/wizard_ui.py` | layout + db_id dialogs |
| `nicegui_ui/components/toml_wizard.py` | controller pattern |
| `nicegui_ui/pages/tab_input.py` | `read_ghost_sample`, `read_field_drafts`, ghost guard |
| `app/core_split.py` | split_by_determiner |
| `docs/embed_gemma4.md` | session/thinking rules |

---

## 12. preprocess_sample detail

**Brace JSON** (`{` and `}` in sample):

- Python only: tokenize → `dict[int,str]`; `determiner=""`; no LLM

**Plain text:**

1. `open_session("wizard_determiner_{uuid}", thinking=False, max_tokens=512)`
2. Parse determiner list from reply
3. `split_by_determiner(raw_sample, determiners)` → `parts_to_indexed_dict`
4. **Must split raw ghost**, not Gemma cleaned string
5. Close session; never use `wizard_main`

---

## 13. match_ghost_fields detail

For each planned label:

```python
run_field_agent(backend, "ghost", label,
    indexed_segments=state.indexed_segments,
    draft_value=state.user_draft.get(label),
    thinking_budget=budget, on_chat=...)
```

Priority: user draft value > label hint. Never select index merely because segment == label name.

Empty draft before plan: `match_type=none`, `index=-1`, no sub-agent call.

---

## 14. Verification checklist (manual)

1. Start from Input Config; FAB + sidebar chat appear
2. Layout: multi area + multi move_to; TOML persists; tab switches to 输入
3. Ghost paste does **not** auto-fill fields
4. One FAB captures ghost + field drafts together
5. Log shows indexed_segments preview before matching
6. ≥3 fields: progress shows (i/n), max 2 concurrent
7. Fuzzy → regex with pass2 thinking log line
8. Save db_id=None without opening dropdown
9. Close workflow → EndGemma; normal paste auto-split works
10. `llm_gemma4/wizard/` does not exist (Phase D only)

---

## 15. Implementation order

```
A1 workflow runtime
 → A2 copy toml_config modules
   → A3 executor + orchestrator + decide_stub
     → A4 NiceGUI interrupt wiring
       → B1 intake_plan + design_doc
         → B2 decision.py
           → B3 tests
             → C UX cleanup
               → D delete wizard/
```

**Do Phase A completely before Phase B.** Do not delete `wizard/` until Phase D grep-clean.
