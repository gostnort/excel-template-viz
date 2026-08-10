# Dynamic Wizard Runtime — Phase Index

Send **one file per phase** to the coding LLM. Each file is self-contained for a brand-new context.

| Phase | File | When |
|-------|------|------|
| **A** | [phase-a.md](phase-a.md) | Runtime + executor + interrupt UI; `decide_stub`; **keep** `wizard/` |
| **B** | [phase-b.md](phase-b.md) | IntakePlan + Gemma `decide()`; no duplicate input |
| **C** | [phase-c.md](phase-c.md) | Remove step driver; progress UX; `workflow_active` |
| **D** | [phase-d.md](phase-d.md) | Delete `llm_gemma4/wizard/` + docs cutover |

**Order:** A → B → C → D (do not skip).

Other docs: [specify.md](specify.md) (requirements), [plan.md](plan.md) (overview), [tasks.md](tasks.md) (checklist).

Legacy combined handoff: [coding-handoff.md](coding-handoff.md) (superseded by phase-a..d).
