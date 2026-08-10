# Phase B — Decision Layer + IntakePlan

> **Repo:** `excel-template-viz`  
> **Prerequisite:** [phase-a.md](phase-a.md) complete — `WorkflowOrchestrator.tick()`, executor actions, interrupt UI all working with `decide_stub()`  
> **Next phase:** [phase-c.md](phase-c.md)  
> **Do NOT in this phase:** delete `llm_gemma4/wizard/`, remove `ui_step` driver (Phase C)

---

## 1. Mission

Replace hard-coded `decide_stub()` with Gemma-driven `decide()` that:

1. Reads `design_doc` + `IntakePlan` + state summary
2. Emits JSON: `next_action`, `action_id`, `reason`, `expected_input`, `context_update`, `route_key`
3. Never asks for data already captured (plan-before-ask)
4. Uses `thinking=False` on decision sessions only

Executor and UI from Phase A stay; only routing brain changes.

---

## 2. Prerequisites (must exist after Phase A)

```
llm_gemma4/workflow/state.py          # WorkflowState, InterruptPayload, Decision, ExecutorResult
llm_gemma4/workflow/checkpoint.py     # MemoryCheckpoint
llm_gemma4/toml_config/executor.py    # ACTION_HANDLERS (9 actions)
llm_gemma4/toml_config/workflow_orchestrator.py  # tick()
llm_gemma4/toml_config/field_agent.py # pass1/pass2
nicegui_ui/...                        # interrupt-driven FAB
```

---

## 3. Files to CREATE

### 3.1 `llm_gemma4/toml_config/intake_plan.py`

```python
INTAKE_KEYS = [
    "data_sources",
    "input_section",
    "ghost_sample",
    "field_drafts",
    "ghost_preprocess",
    "field_match",
    "sheet_match",
    "regex_infer",
    "db_id",
]

@dataclass
class IntakeItem:
    key: str
    status: str  # pending | done | skip
    interrupt_kind: str | None
    state_fields: list[str]

def build_intake_plan(state: WorkflowState) -> list[IntakeItem]:
    """
    函数名: build_intake_plan
    作用: 根据当前状态构建仍需采集/处理的数据项清单
    输入: state (WorkflowState)
    输出: list[IntakeItem]
    """

def already_captured(state: WorkflowState, key: str) -> bool:
    """Return True if state fields for this key are satisfied."""

def intake_key_for_action(action_id: str) -> str | None:
    """Map action_id to intake key for ask_user guards."""
```

**Satisfaction rules:**

| key | satisfied when |
|-----|----------------|
| `data_sources` | `state.data_sources` non-empty OR user skipped google |
| `input_section` | `state.offset >= 1` and `input_area` set |
| `ghost_sample` | `state.ghost_text_sample.strip()` non-empty |
| `field_drafts` | captured same interrupt as ghost (any non-empty draft OR explicit empty ok) |
| `ghost_preprocess` | `state.preprocess_done` |
| `field_match` | all `planned_labels` have `match_type != unknown` or error |
| `sheet_match` | no google source OR all sheet fields resolved |
| `regex_infer` | no `needs_regex` OR all regex filled/errored |
| `db_id` | `state.is_finished` or finalize interrupt completed |

**`sheet_match` / `regex_infer`:** mark `skip` when not applicable.

### 3.2 `llm_gemma4/toml_config/design_doc.py`

```python
def build_design_doc(
    template_id: str,
    template_path: Path | None,
    labels: list[str],
) -> str:
    """
    函数名: build_design_doc
    作用: 组合 toml_config_design 摘要 + 模板标签 + 已有 sidecar 片段
    输入: template_id, template_path, labels
    输出: str, max ~8000 chars
    """
```

**Include from `docs/toml_config_design.md`:**
- `determiner`, `index` semantics (base 0)
- `[[input_section]]` — multi `input_area`, multi `move_to`, `offset`
- `[[fields]]` required keys
- `db_id`, `id` rules
- `index = -1` meaning

Append: `Template labels: [...]`  
Append: first 2000 chars of existing sidecar TOML if file exists.

### 3.3 `llm_gemma4/toml_config/parse_decision_json.py`

Mirror `parse_field_json.py`:

```python
class ParseDecisionError(Exception): ...

def parse_decision_json(text: str) -> dict:
    """Extract single JSON object with required keys next_action, action_id."""
```

Required keys: `next_action`, `action_id`  
Optional: `reason`, `expected_input`, `context_update`, `route_key`

### 3.4 `llm_gemma4/toml_config/decision.py`

```python
ALLOWED_ACTION_IDS = frozenset({
    "record_sources", "capture_layout", "capture_sample",
    "preprocess_sample", "plan_ghost_tasks", "match_ghost_fields",
    "match_sheet_columns", "infer_regex", "finalize_toml",
})

ALLOWED_NEXT_ACTIONS = frozenset({
    "ask_user", "compute", "validate", "finalize", "error",
})

def decide(
    state: WorkflowState,
    user_input: dict | None,
    intake: list[IntakeItem],
    backend: LlmBackend,
) -> Decision:
    """
    函数名: decide
    作用: 调用 Gemma 一次性会话，返回下一步决策 JSON
    输入: state, user_input, intake, backend
    输出: Decision
    """
```

**Session rules:**
- `session_id = f"wizard_decision_{uuid4().hex[:8]}"`
- `SessionOptions(thinking=False, max_tokens=512)`
- Close session after each call
- **Never** use `wizard_main` for routing
- **Never** `thinking=True` on decision session
- JSON parse fail → one re-prompt same session (still thinking=False); then return `next_action=error`

**Prompt must include:**
1. `ACTION_CATALOG` — table of action_id + preconditions (from phase-a executor table)
2. `design_doc` — `state.design_doc` or `build_design_doc(...)`
3. `IntakePlan` — formatted list with pending/done/skip
4. `already_captured` — keys where `already_captured(state, k)` is True
5. State summary via `context.build_main_turn_prefix(state)` — **not** full indexed_segments
6. Last `user_input` if any

**System prompt instructs:**
- Output **only** JSON
- `ask_user` only for keys still `pending` in IntakePlan
- Do not request ghost_sample if already captured
- `action_id` must match `next_action` (ask_user → capture_* / finalize_toml; compute → preprocess/match/regex)
- Emit `route_key=skip_sheet` when no Google source (executor also enforces)

---

## 4. Files to MODIFY

### `workflow_orchestrator.py`

```python
# On start():
self.state.design_doc = build_design_doc(...)
self.state.progress = _init_progress(self.state.template_labels)

# In tick():
intake = build_intake_plan(self.state)
decision = decide(self.state, user_input, intake, self._backend)  # NOT decide_stub
self.state.history.append({"decision": asdict(decision), ...})
```

Remove or gate `decide_stub` behind `WORKFLOW_DECIDE_STUB=1` env for debugging only.

### `executor.py`

Before returning `interrupt` on ask actions:

```python
key = intake_key_for_action(action_id)
if key and already_captured(state, key):
    return ExecutorResult(ok=True, messages=[f"skip ask {key}, already captured"], route_key="already_have")
```

After successful capture:

```python
state_patch["progress"] = {**state.progress, key: "done"}
```

**`capture_sample`:** single interrupt collects both `ghost_sample` and `field_drafts` keys → mark both `done`.

### `decide_stub.py`

Keep file but unused in production path; or delete if tests don't need it.

---

## 5. `progress` initialization

```python
def _init_progress(labels: list[str]) -> dict[str, str]:
    p = {
        "data_sources": "pending",
        "input_section": "pending",
        "ghost_sample": "pending",
        "field_drafts": "pending",
        "ghost_preprocess": "pending",
        "field_match": "pending",
        "sheet_match": "pending",
        "regex_infer": "pending",
        "db_id": "pending",
    }
    for label in labels:
        p[f"field:{label}"] = "pending"
    return p
```

Executor marks `field:{label}` done after each field match completes.

---

## 6. Decision JSON example

```json
{
  "next_action": "ask_user",
  "action_id": "capture_sample",
  "reason": "ghost_sample pending; layout already done",
  "expected_input": "Paste one representative sample in Ghost textbox on Input tab, fill field drafts, then click FAB",
  "context_update": {},
  "route_key": ""
}
```

```json
{
  "next_action": "compute",
  "action_id": "preprocess_sample",
  "reason": "sample captured, build indexed_segments",
  "expected_input": "",
  "context_update": {},
  "route_key": ""
}
```

---

## 7. Hard constraints (enforce in code + prompt)

### No duplicate input
- `decide()` prompt lists `already_captured`
- `executor` skips interrupt if key done
- Unit test: mock decide sequence; assert at most one interrupt per IntakePlan key per run

### Thinking only pass2
- Grep audit: `thinking=True` appears only in `toml_config/field_agent.py` pass2 path
- Decision parse retry: **no** thinking

### Session isolation
- determiner → `wizard_determiner_*` (unchanged from Phase A)
- planner → `wizard_main` thinking=False
- router → `wizard_decision_*` thinking=False

---

## 8. Tests to add

```
test/test_workflow_intake_plan.py
  - already_captured after capture_sample
  - sheet_match skip when no google source

test/test_workflow_decision.py
  - parse_decision_json valid/invalid
  - decide rejects unknown action_id (mock backend)

test/test_workflow_no_duplicate_ask.py
  - full mocked run: interrupt kinds unique per key
```

Tests live in `test/` per project rules; import from `llm_gemma4.toml_config`.

---

## 9. Phase B acceptance

1. All Phase A acceptance items 1–9 still pass
2. Workflow routing uses `decide()` not `decide_stub()` (verify via log: decision reason from Gemma)
3. No second `ask_layout` after layout saved
4. No second `ask_sample` after ghost captured
5. `design_doc` populated on start
6. `state.history` contains decision records
7. `thinking=True` only in field_agent pass2 (grep)

---

## 10. Reference

| Path | Purpose |
|------|---------|
| `llm_gemma4/toml_config/executor.py` | add guards |
| `llm_gemma4/toml_config/workflow_orchestrator.py` | wire decide |
| `llm_gemma4/toml_config/context.py` | state summary prefix |
| `llm_gemma4/toml_config/parse_field_json.py` | JSON extract pattern |
| `docs/toml_config_design.md` | design_doc source |
| `plans/toml-guide-2.md` | next_action JSON shape |
