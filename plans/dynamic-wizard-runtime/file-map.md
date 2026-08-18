# 代码文件职责图（v2）

与 [`docs/gemma4_dynamic_workflow.md`](../../docs/gemma4_dynamic_workflow.md) 配套。实施改动前先查本表，避免改错层。

---

## 入口层

| 文件 | 职责 | v2 备注 |
|------|------|---------|
| `llm_gemma4/cli/main.py` | argparse：`gemma` / `dialog` 子命令 | 验收主线 |
| `llm_gemma4/cli/dialog_cmds.py` | `catalog` / `run` / `demo`；`_run_loop` | 对应 NiceGUI 的 resume 循环 |
| `llm_gemma4/cli/gemma_cmds.py` | `ask` / `health` / `StartGemma` 等底座命令 | 与 wizard 正交 |
| `llm_gemma4/cli/mock_backend.py` | `--mock` 脚本后端 | 勿与 briefing 文案混用 |
| `llm_gemma4/cli/briefing.py` | `BriefingSpec` 演示域 | 非 TOML |
| `nicegui_ui/components/workflow_ui.py` | FAB、interrupt 对话框、`_collect_resume_payload` | **表单 I/O**，非聊天 |
| `nicegui_ui/components/toml_wizard.py` | `TomlWizardController`、`await_gemma_thread(dispatch)` | `_busy` 挡并发 |
| `nicegui_ui/pages/tab_toml.py` | 「启动配置向导」按钮 | |
| `nicegui_ui/pages/tab_input.py` | Ghost、字段草稿；`is_workflow_active` 守卫 | |

---

## 编排层（双 facade — 收敛目标）

| 文件 | 职责 | 使用者 |
|------|------|--------|
| `llm_gemma4/toml_config/workflow_orchestrator.py` | `WorkflowOrchestrator`、Graph dispatch | **NiceGUI** |
| `llm_gemma4/dialog/orchestrator.py` | `DialogOrchestrator`、通用 Graph | **CLI** briefing |
| `llm_gemma4/toml_config/spec.py` | `TomlGuideSpec`（九动作 weights） | **CLI** toml |
| `llm_gemma4/workflow/graph.py` | `CompiledWorkflow.dispatch`、Continue cap 24 | 共用 |
| `llm_gemma4/workflow/events.py` | `EVENT_START/RESUME/STOP/...` | 共用 |
| `llm_gemma4/workflow/checkpoint.py` | `MemoryCheckpoint`（进程内） | 共用 |
| `llm_gemma4/workflow/state.py` | `WorkflowState`、`Decision`、`InterruptPayload` | TOML |
| `llm_gemma4/dialog/state.py` | `DialogState`、`IntakeNeed` | CLI briefing |
| `llm_gemma4/dialog/actions.py` | briefing 五动作 + `map_run_sequential` 子代理 | CLI briefing |

---

## 领域层（TOML 九动作）

| 文件 | 职责 |
|------|------|
| `llm_gemma4/toml_config/decision.py` | `decide()` JSON 路由 + fallback |
| `llm_gemma4/toml_config/decide_stub.py` | `WORKFLOW_DECIDE_STUB=1` |
| `llm_gemma4/toml_config/executor.py` | `ACTION_HANDLERS`（九动作）、interrupt 发出 |
| `llm_gemma4/toml_config/intake_plan.py` | `INTAKE_KEYS`、`already_captured` |
| `llm_gemma4/toml_config/intake_seed.py` | sidecar `[[sources]]` 预填 |
| `llm_gemma4/toml_config/field_agent.py` | `run_field_agent` pass1/pass2 |
| `llm_gemma4/toml_config/toml_patcher.py` | `persist_wizard_toml` |
| `llm_gemma4/toml_config/payload.py` | resume 合并 |
| `llm_gemma4/toml_config/workflow_orchestrator.py` | `_main_turn`、`wizard_main` |

---

## 推理底座

| 文件 | 职责 |
|------|------|
| `llm_gemma4/runtime/gemma_worker.py` | **单线程队列**；所有 dispatch 必经 |
| `llm_gemma4/__main__.py` | `StartGemma` / `EndGemma` / `_get_backend` |
| `llm_gemma4/backends/litert/backend.py` | 单 `Engine`、多 `open_session` |
| `llm_gemma4/backends/litert/session.py` | 持久 `Conversation` |
| `llm_gemma4/dialog/subagent.py` | 一次性子 session + thinking retry |

---

## 并行相关（勿在生产启用）

| 文件 | 状态 |
|------|------|
| `llm_gemma4/workflow/parallel.py` | `map_run_sequential` = 生产；`map_send` = 死代码 |

---

## 业务 / 落盘

| 文件 | 职责 |
|------|------|
| `app/core_toml.py` | TOML 加载、`verify_toml` |
| `app/core_split.py` | `indexed_segments` 预处理 |
| `templates/{id}/{id}.toml` | sidecar（CLI demo 默认无真实模板） |

---

## 测试（待建）

| 文件 | 职责 |
|------|------|
| `tests/test_cli_dialog_toml.py` | **Phase 1 新建** |

---

## 数据流（对照用）

```
CLI stdin / TOML_DEMO_AUTO
NiceGUI _collect_resume_payload()
        → WorkflowEvent(Resume, payload)
        → await_gemma_thread(WorkflowOrchestrator.dispatch)
        → decide → executor → [interrupt | continue | finished]
```

Interrupt kinds：`ask_sources` | `ask_layout` | `ask_sample` | `ask_db_id`
