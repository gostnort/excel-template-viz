# Dynamic Wizard Runtime — Phase Index

> **Implementation status (2026-08-16):** [STATUS.md](STATUS.md) — reconciles this folder with `feature-gemma-toml-3` on disk.  
> **Task checkboxes:** [tasks.md](tasks.md)  
> **Runtime authority:** [`docs/gemma4_dynamic_workflow.md`](../../docs/gemma4_dynamic_workflow.md)

Send **one file per phase** to the coding LLM. Each file is self-contained for a brand-new context.

| Phase | File | Plan intent | Actual (see STATUS) |
|-------|------|-------------|---------------------|
| **A** | [phase-a.md](phase-a.md) | Runtime + executor + interrupt UI | **Done** (E2E partial) |
| **B** | [phase-b.md](phase-b.md) | IntakePlan + Gemma `decide()` | **Mostly done** (pytest B3 open) |
| **C** | [phase-c.md](phase-c.md) | Remove step driver; dynamic UX | **Mostly done** (FAB left, no checklist) |
| **D** | [phase-d.md](phase-d.md) | Delete `llm_gemma4/wizard/` | **Done** |

**Order:** A → B → C → D (historical). **Remaining:** B3 tests, E2E regression, doc cleanup — not a new phase.

Other docs: [specify.md](specify.md) (requirements), [plan.md](plan.md) (overview).

Legacy combined handoff: [coding-handoff.md](coding-handoff.md) (superseded by STATUS + phase-a..d).
