# v2 实施任务清单

勾选规则：完成且 `dialog demo --spec toml` 仍 exit 0 后再标 `[x]`。

---

## Phase 0 — 文档与计划（本交接）

- [x] 重写 `docs/gemma4_dynamic_workflow.md` v2.0
- [x] 删除旧 `plans/dynamic-wizard-runtime/phase-*.md` 等
- [x] 新建 `HANDOFF.md`、`file-map.md`、本 `tasks.md`

---

## Phase 1 — CLI 验收自动化（最高优先级）

- [x] 新建 `tests/test_cli_dialog_toml.py`
  - 子进程或 import 调用 `dialog demo --spec toml`
  - 断言 exit code 0
  - 断言 stdout 含 `[event] finished`、`field_match`
- [x] 在 `bootup/pyproject.toml` 或根 CI 脚本中注册 pytest 步骤（若项目有 CI）
- [x] `README.md` 增加 CLI 三节：安装、`dialog demo`、`dialog run --live`

---

## Phase 2 — CLI 增强（可选，不碰 NiceGUI）

- [x] 新建 `llm_gemma4/cli/queue.py`：`MainTurnQueue`（线程安全 FIFO）
- [x] `dialog repl --spec toml`：读 stdin 行入队，worker 消费 `dispatch(Resume)`
- [ ] 文档：在 `gemma4_dynamic_workflow.md` §3.3 补 repl 说明

---

## Phase 3 — 死代码与一致性

- [ ] `llm_gemma4/workflow/parallel.py`：删除 `map_send` 或模块顶注释 `# DEPRECATED: LiteRT serial only`
- [ ] `llm_gemma4/cli/mock_backend.py`：toml `wizard_main` 回复改为 TOML 域占位文案
- [ ] 全库 grep `map_send` / `max 2 concurrent` / `cap=2`，清理注释与文档残留
- [ ] `dialog demo --spec toml --write-toml` 用真实 `templates/{id}/` 样例测一次（文档记录限制）

---

## Phase 4 — 双编排器收敛（中风险，分步）

- [ ] 对照测试：同一 `TOML_DEMO_AUTO` payload，`WorkflowOrchestrator.dispatch` vs `DialogOrchestrator`+`TomlGuideSpec` 的 `progress` / `artifacts` 键集合一致
- [ ] 抽公共模块（建议名 `llm_gemma4/toml_config/runtime_facade.py`）或让 NiceGUI 改用 `DialogOrchestrator(TomlGuideSpec)`
- [ ] 删除重复路由逻辑前：CLI + NiceGUI 各跑完整 interrupt 路径

**不要在本阶段改：** interrupt 种类、intake 键顺序、`executor.ACTION_HANDLERS` 签名。

---

## Phase 5 — NiceGUI（仅 bugfix）

- [ ] FAB E2E 对照 `tasks.md` §13.2 in `gemma4_dynamic_workflow.md`
- [ ] 修复与 v2 不符的 UI 文案（若仍有「并行」「checklist」字样）

**明确不做：**

- [ ] ~~NiceGUI 主轮次排队~~
- [ ] ~~侧边栏可编辑聊天~~
- [ ] ~~恢复 `map_send` 并行 field match~~

---

## Phase 6 — Live 与发布

- [ ] Windows 机 `dialog run --spec toml --live --release` 全路径
- [ ] 更新 `docs/gemma4_dynamic_workflow.md` §13 勾选结果
- [ ] 考虑 tag `0.2.x` 与 merge `feature-gemma-toml-3` → main 的 PR 说明
