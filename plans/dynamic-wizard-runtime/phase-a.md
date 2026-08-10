# Phase A — Runtime + Executor Parity

> **Repo:** `excel-template-viz`  
> **Prerequisite:** none (start here)  
> **Next phase:** [phase-b.md](phase-b.md)  
> **Do NOT in this phase:** Gemma routing (`decide()`), delete `llm_gemma4/wizard/`, rename `wizard_active`

---

## 1. Mission

Replace `WizardOrchestrator.advance(step, payload)` with `WorkflowOrchestrator.tick(user_input)` using:

- New packages `llm_gemma4/workflow/` and `llm_gemma4/toml_config/`
- **Hard-coded** `decide_stub()` — fixed action sequence, no Gemma workflow routing yet
- Interrupt/resume for human steps (layout, sample, db_id)
- **Same end-user behavior** as v8.3 fixed wizard (layout → sample → match → save)

`llm_gemma4/wizard/` **stays** during Phase A (reference + fallback imports OK until UI switched).

---

## 2. Global rules (apply in all phases)

| Rule | Detail |
|------|--------|
| No new deps | Do not add `langgraph` or `langchain` |
| Thinking | Only `field_{label}_pass2` may use `thinking=True` (in copied `field_agent.py`) |
| Input tab | While wizard active, Ghost blur must NOT call `record_from_textbox` — see `tab_input.py` L726–728 |
| TOML matching | `dict[int,str]` indexed_segments; determiner one-shot; empty draft → `index=-1` |
| Style | Chinese docstrings; `pathlib`; no blank lines inside functions; no auto-formatters |
| LLM thread | NiceGUI: `await run.io_bound(sync_tick, payload)` |

---

## 3. Files to CREATE

### 3.1 `llm_gemma4/workflow/`

**`state.py`**

```python
@dataclass
class FieldState:
    input_label: str
    match_type: str = "unknown"
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
class WorkflowState:
    # --- copy all fields from llm_gemma4/wizard/state.py WizardState ---
    current_step: int = 1
    template_id: str = ""
    template_path: Path | None = None
    data_sources: list[dict[str, str]] = field(default_factory=list)
    ghost_text_sample: str = ""
    sample_kind: str = ""
    determiner: str | list[str] = ""
    indexed_segments: dict[int, str] = field(default_factory=dict)
    preprocess_done: bool = False
    field_tasks_planned: bool = False
    planned_labels: list[str] = field(default_factory=list)
    user_draft: dict[str, str] = field(default_factory=dict)
    google_sheet_headers: list[str] = field(default_factory=list)
    google_sheet_sample: list[list[Any]] = field(default_factory=list)
    template_labels: list[str] = field(default_factory=list)
    fields: dict[str, FieldState] = field(default_factory=dict)
    input_area: str | list[str] = ""
    move_to: str | list[str] = ""
    offset: int = 0
    db_id: str = ""
    is_finished: bool = False
    written_toml_path: str = ""
    # --- new workflow fields (used fully in Phase B) ---
    design_doc: str = ""
    user_inputs: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    route_key: str = ""
    pending_interrupt: dict[str, Any] | None = None

@dataclass
class InterruptPayload:
    kind: str  # ask_sources | ask_layout | ask_sample | ask_db_id
    expected_input: str
    auto_chain: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

@dataclass
class ExecutorResult:
    ok: bool
    messages: list[str]
    state_patch: dict[str, Any]
    interrupt: InterruptPayload | None = None
    route_key: str = ""

@dataclass
class Decision:
    next_action: str
    action_id: str
    reason: str = ""
    expected_input: str = ""
    context_update: dict[str, Any] = field(default_factory=dict)
    route_key: str = ""
```

**`checkpoint.py`**

```python
class MemoryCheckpoint:
    def is_interrupted(self, thread_id: str) -> bool: ...
    def get_interrupt(self, thread_id: str) -> InterruptPayload | None: ...
    def save_interrupt(self, thread_id: str, state: WorkflowState, payload: InterruptPayload) -> None: ...
    def resume(self, thread_id: str, user_value: dict | None, state: WorkflowState) -> WorkflowState: ...
    def clear(self, thread_id: str) -> None: ...
```

On `save_interrupt`: store state snapshot + payload; set `state.pending_interrupt = payload`.  
On `resume`: merge `user_value` into state via executor-specific logic; clear interrupt flag.

**`graph.py`**

```python
class WorkflowInterrupt(Exception):
    def __init__(self, payload: InterruptPayload): ...
```

Minimal v1 — exception + checkpoint is enough for Phase A.

**`parallel.py`**

```python
def map_send(fn: Callable[[str], T], items: list[str], cap: int = 2) -> list[T]:
    # threading.Semaphore(cap) + ThreadPoolExecutor
```

**`router.py`** — stub `pass` or empty module OK for Phase A.

**`__init__.py`** — export public types.

### 3.2 `llm_gemma4/toml_config/` — COPY from `wizard/`

| Copy from | To | Change imports |
|-----------|-----|----------------|
| `wizard/field_agent.py` | `toml_config/field_agent.py` | `llm_gemma4.toml_config.*` |
| `wizard/sample_preprocess.py` + `sample_analysis.py` | `toml_config/sample_preprocess.py` | merge analysis helpers |
| `wizard/toml_patcher.py` | `toml_config/toml_patcher.py` | `WorkflowState` from `workflow.state` |
| `wizard/prompts.py` | `toml_config/prompts.py` | |
| `wizard/parse_field_json.py` | `toml_config/parse_field_json.py` | |
| `wizard/context.py` | `toml_config/context.py` | `WorkflowState` |
| `wizard/template_labels.py` | `toml_config/template_labels.py` | |

Do **not** copy `trial_run.py`.

**`executor.py`** — NEW; lift from `wizard/orchestrator.py`:

```python
ACTION_HANDLERS: dict[str, Callable] = {
    "record_sources": _action_record_sources,
    "capture_layout": _action_capture_layout,
    "capture_sample": _action_capture_sample,
    "preprocess_sample": _action_preprocess_sample,
    "plan_ghost_tasks": _action_plan_ghost_tasks,
    "match_ghost_fields": _action_match_ghost_fields,
    "match_sheet_columns": _action_match_sheet_columns,
    "infer_regex": _action_infer_regex,
    "finalize_toml": _action_finalize_toml,
}

def execute(decision: Decision, state: WorkflowState, backend, *, on_progress, on_chat, on_match_notify) -> ExecutorResult: ...
```

**Per-action behavior** (lift verbatim logic from orchestrator):

| action_id | Source in orchestrator.py | Returns interrupt? |
|-----------|---------------------------|-------------------|
| `record_sources` | `advance` step 1 | No |
| `capture_layout` | step 2 | Yes `ask_layout` if no payload; else apply + persist |
| `capture_sample` | step 3 | Yes `ask_sample` if no payload |
| `preprocess_sample` | `_phase_preprocess` | No |
| `plan_ghost_tasks` | `_phase_plan_ghost` | No |
| `match_ghost_fields` | `_phase_match_ghost` | No |
| `match_sheet_columns` | step 5 | No; skip if no google source |
| `infer_regex` | step 6 | No |
| `finalize_toml` | step 7 | Yes `ask_db_id` if no payload |

**`decide_stub.py`** (or inside orchestrator file):

```python
_STUB_SEQUENCE = [
    "record_sources", "capture_layout", "capture_sample",
    "preprocess_sample", "plan_ghost_tasks", "match_ghost_fields",
    "match_sheet_columns", "infer_regex", "finalize_toml",
]

def decide_stub(state: WorkflowState, user_input: dict | None) -> Decision:
    # Track index in state.computed_results["_stub_idx"] or similar
    # Skip match_sheet_columns when no google source in data_sources
    # If interrupted, return same action_id until resume completes
```

**`workflow_orchestrator.py`** — NEW:

```python
class WorkflowOrchestrator:
    def __init__(self, backend, on_progress=None, on_chat=None, on_match_notify=None):
        self._backend = backend
        self.state = WorkflowState()
        self._checkpoint = MemoryCheckpoint()
        self._thread_id = "workflow_0"
        self._main_session_id = "wizard_main"
        self._main_opened = False
        self._ui_lock = threading.Lock()
        # copy _progress, _chat, _match_notify, _thinking_budget, _persist_toml from orchestrator

    def is_interrupted(self) -> bool:
        return self._checkpoint.is_interrupted(self._thread_id)

    @property
    def pending_interrupt(self) -> InterruptPayload | None:
        return self.state.pending_interrupt

    def tick(self, user_input: dict | None = None) -> WorkflowState:
        if self.is_interrupted():
            self.state = self._checkpoint.resume(self._thread_id, user_input, self.state)
            self._checkpoint.clear(self._thread_id)
            self.state.pending_interrupt = None
        decision = decide_stub(self.state, user_input)
        result = execute(decision, self.state, self._backend, ...)
        self.state = _merge_state(self.state, result.state_patch)
        for msg in result.messages:
            self._progress(msg)
        if result.interrupt:
            self._checkpoint.save_interrupt(self._thread_id, self.state, result.interrupt)
            self.state.pending_interrupt = result.interrupt
            return self.state
        if self.state.is_finished:
            return self.state
        return self.state

    def close(self): ...
```

**Important:** For compute actions that previously ran inside one `advance(4)` with phases, either:
- call `tick()` multiple times from UI with `auto_chain` between preprocess/plan/match, OR
- let `decide_stub` advance through compute actions in one `tick()` until next interrupt

Prefer **UI yields** between preprocess / plan / match (log lines visible) — match e4b feedback rule.

---

## 4. Files to MODIFY (NiceGUI)

### `nicegui_ui/components/toml_wizard.py`

- Replace `from llm_gemma4.wizard.orchestrator import WizardOrchestrator`  
  → `from llm_gemma4.toml_config.workflow_orchestrator import WorkflowOrchestrator`
- Replace `run_step(step, payload)` with `run_turn(payload: dict)`
- `run_turn`: `await run.io_bound(self.orchestrator.tick, payload)`
- If `orchestrator.is_interrupted()`: do not auto-chain; wait for UI
- If not interrupted and not finished: call `run_turn({})` again to advance stub (or loop in controller with care for busy flag)

### `nicegui_ui/components/wizard_ui.py`

Refactor `on_next_click()`:

**Old:** `ui_step` 1–8 → build payload → `run_step(n, payload)`

**New:**

```python
def on_next_click():
    ctrl = get_toml_wizard()
    if ctrl.orchestrator.is_interrupted():
        payload = _build_resume_payload_from_dialog()  # layout / sample / db_id
        await ctrl.run_turn(payload)
    else:
        await ctrl.run_turn({})  # advance compute step
    if ctrl.orchestrator.is_interrupted():
        kind = ctrl.orchestrator.pending_interrupt.kind
        if kind == "ask_layout":
            _open_layout_dialog()
        elif kind == "ask_sample":
            _switch_tab("输入")
        elif kind == "ask_db_id":
            _open_db_id_dialog()
        elif kind == "ask_sources":
            _switch_tab("Google 连接")
```

Reuse existing layout dialog code (`_layout_area_inputs`, multi `move_to` checkboxes, step 7 db_id).

**Keep** `_STEP_TABS` and `ui_step` for now (removed in Phase C) — can map interrupt kind to tab switch.

### `nicegui_ui/pages/tab_input.py`

**Do not change** ghost guard in Phase A except if import path breaks:

```python
if is_wizard_active():
    return
```

### Entry points

- `tab_toml.py` — still calls `start_wizard()` 
- `main.py` — shell FAB unchanged

---

## 5. preprocess / match details (when lifting code)

**preprocess_sample:**
- Brace JSON (`{` and `}`): Python tokenize only via `build_indexed_segments`
- Plain text: `wizard_determiner_{uuid}` session, `thinking=False`; split **raw** ghost with `app/core_split.split_by_determiner`
- Never call determiner via `wizard_main`

**plan_ghost_tasks:**
- Empty `user_draft[label]` → not in planned_labels; set `FieldState.match_type=none`, `index=-1`

**match_ghost_fields:**
- `run_field_agent(backend, "ghost", label, ...)` with `Semaphore(2)`
- Primary signal: `user_draft[label]`, not label string in segments

**infer_regex:**
- Haystack = single segment at `fs.index`, not full dict

---

## 6. Phase A acceptance (manual)

1. Start wizard from Input Config; FAB + sidebar work
2. Layout dialog: multi `input_area`, multi-select `move_to`; TOML writes; tab → 输入
3. Ghost paste does **not** auto-fill fields (`record_from_textbox` skipped)
4. FAB captures ghost + `read_field_drafts()` together
5. Log shows indexed_segments preview before field matching
6. ≥3 fields: `(i/n)` progress, max 2 concurrent agents
7. Fuzzy field → regex with pass2 thinking log
8. Save with `db_id=None` without opening dropdown
9. Close wizard → `EndGemma()`; normal paste auto-split works again
10. `llm_gemma4/wizard/` still exists (not deleted yet)

---

## 7. Phase A deliverables checklist

- [x] `llm_gemma4/workflow/` (state, checkpoint, graph, parallel, router stub)
- [~] `llm_gemma4/toml_config/` (executor + modules; orchestrator **draft broken**)
- [ ] `toml_wizard.py` uses `WorkflowOrchestrator.tick`
- [ ] `wizard_ui.py` interrupt-driven FAB/dialog
- [ ] Full template config E2E passes acceptance 1–9

---

## 9. Audit (2026-08-05) — claim vs code

Third-party summary partially correct. Verified against repo:

| Claim | Verdict | Evidence |
|-------|---------|----------|
| Bug 3 `capture_layout` interrupt | **Done** | `executor.py` returns `InterruptPayload(kind="ask_layout")` when `parts` empty |
| Bug 4 `toml_patcher` import | **Done** | `from llm_gemma4.toml_config.toml_patcher import persist_wizard_toml` |
| Bug 5 `self.state` | **Done** | `plan_ghost_tasks` uses `state.planned_labels` |
| Bug 6 preprocess `one_shot` | **Partial** | `_determiner_one_shot_stub` returns `"\t"` only — **not** real Gemma session; parse falls back to default delimiters. Acceptable Phase A only if plain-text E2E still passes; for parity lift `orchestrator._determiner_one_shot` |
| Bug 7 match concurrency | **Not done** | Still `with threading.Semaphore(2):` **inside** `_guarded()` — new semaphore per worker |
| Bug 8 persistent `wizard_main` | **Not done** | Still `wizard_main_{uuid}` + `session.close()` each `_main_turn` |
| `workflow_orchestrator.py` | **Draft broken** | `tick()` calls `execute()` but **no import**; `decide_stub()` skips `capture_layout` unless `input_area` already set; no `MemoryCheckpoint`; `tick` requires `user_input` always |
| UI wired | **Not done** | `toml_wizard.py` still `WizardOrchestrator` + `run_step` |
| `capture_sample` interrupt | **Not done** | Always `interrupt=None` even when ghost empty |
| `finalize_toml` interrupt | **Not done** | No `ask_db_id` before write |
| Duplicate `WorkflowState` | **Not done** | `toml_config/state.py` still duplicates `workflow/state.py` |

Delete scratch files before merge: `workflow_orchestrator_backup.py`, `workflow_orchestrator_full.py` (or finish one canonical orchestrator).

---

## 10. Remaining fixes — implementation playbook

Execute in order. Each step is independently testable.

### Step 1 — Fix `executor.py` (30 min)

**1a. Match concurrency** — copy pattern from `wizard/orchestrator.py`:

```python
# module top
_match_sem = threading.Semaphore(2)

def _guarded(label: str) -> None:
    with _match_sem:
        _ghost_worker(label)
```

**1b. Determiner one-shot (real Gemma for plain text)** — lift from `orchestrator._determiner_one_shot`:

```python
def _determiner_one_shot(backend, sample: str, on_chat) -> str:
    sid = f"wizard_determiner_{uuid.uuid4().hex[:8]}"
    opts = SessionOptions(system_message=DETERMINER_PROMPT, thinking=False, max_tokens=512)
    # open_session → send_turn → close; return result.text
```

Pass to `build_indexed_segments(raw, one_shot=lambda s: _determiner_one_shot(...))`.

**1c. Persistent `wizard_main` for plan** — module-level on orchestrator (not on state dataclass):

```python
# workflow_orchestrator holds _main_opened, _main_session_id = "wizard_main"
# executor receives optional callbacks or MainSession helper from orchestrator
```

Lift `_ensure_main_session` / `_main_turn` from `wizard/orchestrator.py`; **do not** append uuid per turn.

**1d. Missing interrupts**

| Action | When | Interrupt |
|--------|------|-----------|
| `capture_sample` | `not ghost_text_sample.strip()` | `ask_sample` |
| `finalize_toml` | `not state.user_inputs.get("db_id_confirmed")` and first call | `ask_db_id` |
| `record_sources` | optional Phase A | auto-fill from `SessionRegistry` or `ask_sources` |

On resume, merge payload into `state` (`input_area`, `ghost_text_sample`, `user_draft`, `db_id`) **before** re-running action.

**1e. `load_thinking_budget`** — match orchestrator: read profile in `match_ghost_fields` / `infer_regex`, not hardcoded `512`.

### Step 2 — Rewrite `workflow_orchestrator.py` (60 min)

Replace draft with spec from §5 of this doc. Minimum correct behavior:

```python
_STUB_ORDER = [
    "record_sources", "capture_layout", "capture_sample",
    "preprocess_sample", "plan_ghost_tasks", "match_ghost_fields",
    "match_sheet_columns", "infer_regex", "finalize_toml",
]

class WorkflowOrchestrator:
    def __init__(...):
        self._checkpoint = MemoryCheckpoint()
        self._thread_id = "workflow_0"
        self._stub_index = 0
        ...

    def is_interrupted(self) -> bool:
        return self._checkpoint.is_interrupted(self._thread_id)

    def tick(self, payload: dict | None = None) -> WorkflowState:
        if self.is_interrupted():
            self._apply_resume_payload(payload)
            self._checkpoint.clear(self._thread_id)
            self.state.pending_interrupt = None
        decision = self._next_stub_decision()  # linear index; skip sheet if no google
        result = execute(decision, self.state, self._backend,
                         on_progress=self._progress, on_chat=self._chat, ...)
        self._merge_patch(result.state_patch)
        if result.interrupt:
            self._checkpoint.save_interrupt(...)
            self.state.pending_interrupt = asdict(result.interrupt)
            return self.state
        if result.ok and not result.interrupt:
            self._stub_index += 1
        return self.state
```

Fixes vs current draft:

- Import `execute` from `toml_config.executor`
- **Always** emit `capture_layout` / `capture_sample` in order; let executor interrupt if data missing
- `payload` optional for compute-only ticks
- Merge `state_patch` into `self.state` (dataclass fields, not dict-only checkpoint)
- Wire `MemoryCheckpoint` from `llm_gemma4/workflow/checkpoint.py`
- `close()` closes `wizard_main` session

Remove `workflow_orchestrator_backup.py` / `_full.py` after canonical file works.

### Step 3 — Wire NiceGUI (45 min)

**`toml_wizard.py`**

```python
from llm_gemma4.toml_config.workflow_orchestrator import WorkflowOrchestrator

async def run_turn(self, payload: dict | None = None):
    self._busy = True
    try:
        await run.io_bound(self.orchestrator.tick, payload)
        if self.orchestrator.is_interrupted():
            return  # wizard_ui opens dialog
        if self.orchestrator.state.is_finished:
            self.stop()
    finally:
        self._busy = False
```

**`wizard_ui.py` — `on_next_click`**

```
if ctrl.orchestrator.is_interrupted():
    payload = _collect_resume_payload()  # layout / sample / db_id from dialogs + read_field_drafts
    await ctrl.run_turn(payload)
else:
    await ctrl.run_turn({})
    # optional: while not interrupted and not finished and not busy: await ctrl.run_turn({})
```

Map `pending_interrupt.kind` → existing layout dialog / Input tab / db_id dialog (reuse current step 2/7 UI code).

### Step 4 — Dedupe state (15 min)

- `toml_config/state.py`: keep only `WizardState` for backward compat OR delete file
- All code imports `FieldState`, `WorkflowState` from `llm_gemma4.workflow.state`
- `capture_sample` must not import `FieldState` from `toml_config.state`

### Step 5 — Manual E2E

Run §6 acceptance items 1–9 with **new** orchestrator path (not old `WizardOrchestrator`).

### Step 6 — Optional unit test

`test/test_workflow_checkpoint.py`: save_interrupt → resume merges `input_area` into state.

---

## 11. Phase A exit criteria (revised)

Phase A is **done** only when ALL true:

1. §10 Steps 1–5 complete
2. §6 acceptance 1–9 pass on `WorkflowOrchestrator` path
3. No runtime import of `llm_gemma4.wizard` from `toml_config/` or `toml_wizard.py` (wizard/ folder may still exist for reference until Phase D)
4. `decide_stub` is linear sequence; Gemma used inside executor actions (determiner, plan, field agents) same as old orchestrator

**Then** start [phase-b.md](phase-b.md).

---

## 8. Reference files (read before coding)

| Path | Purpose |
|------|---------|
| `llm_gemma4/wizard/orchestrator.py` | All logic to lift |
| `llm_gemma4/wizard/field_agent.py` | pass1/pass2 |
| `nicegui_ui/components/wizard_ui.py` | dialogs, FAB |
| `nicegui_ui/components/toml_wizard.py` | controller |
| `nicegui_ui/pages/tab_input.py` | `read_ghost_sample`, `read_field_drafts`, ghost guard |
| `docs/gemma4_e4b_workflow.md` | business rules v8.3 |
| `docs/embed_gemma4.md` | session/thinking rules |
| `app/core_split.py` | split_by_determiner |
