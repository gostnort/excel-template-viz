# 交接说明 — Gemma4 Dynamic TOML Workflow v2 工程落地

> **给下一个实施对话（大模型 / 开发者）**  
> 分支：`feature-gemma-toml-3`  
> 规格权威：`docs/gemma4_dynamic_workflow.md`（v2.0，2026-08-18）  
> 本文件夹：旧 Phase A–D 计划已删除，由本文 + `tasks.md` + `file-map.md` 替代

---

## 1. 改动总目的（Why）

| # | 目的 | 背景 |
|---|------|------|
| P1 | **CLI 作为唯一验收主线** | 手动点 NiceGUI 测 TOML 向导成本过高；`python -m llm_gemma4.cli dialog demo --spec toml` 应在每次提交前跑通 |
| P2 | **文档与实现一致：LiteRT 单车道、无并行** | 旧计划写 `map_send(cap=2)`、UI 轮询 `tick`；实测 LiteRT 跨线程挂死，已改为 `gemma_worker` + `map_run_sequential` |
| P3 | **明确 NiceGUI = CLI 的表单 I/O 变种** | 侧边栏是只读日志；真人输入仅在 4 类 interrupt；compute 段为 Gemma「自说自话」 |
| P4 | **收敛双编排器技术债** | NiceGUI 用 `WorkflowOrchestrator`；CLI TOML 用 `DialogOrchestrator` + `TomlGuideSpec` — 行为须一致，长期应合并 |
| P5 | **可自动化回归** | 无 pytest；需基于 `--mock --stub` 的 smoke，再逐步 `--live` |
| P6 | **清理过时计划与死代码** | 删除本目录旧 phase 文档；处理 `map_send` 等误导性代码 |

**不在本期范围（除非 tasks 明确打开）：**

- NiceGUI 主对话排队（用户已确认 NiceGUI 可不改）
- LiteRT 真并行子 agent（硬件/运行时不可行）
- 大规模重写状态机为线性 FSM（成本高，CLI 已证明现架构可测）

---

## 2. 已完成的准备工作（本对话）

| 项 | 位置 |
|----|------|
| v2 规格重写 | `docs/gemma4_dynamic_workflow.md` |
| CLI 运行时 | `llm_gemma4/cli/`、`llm_gemma4/dialog/`、`llm_gemma4/toml_config/spec.py` |
| 旧 plans 删除 | `plans/dynamic-wizard-runtime/phase-*.md` 等（见 §4） |
| 新 plans 骨架 | 本目录 `README.md`、`tasks.md`、`file-map.md` |

---

## 3. 实施方应遵循的原则

1. **先 CLI 后 NiceGUI**：任何 workflow 行为变更必须先 `dialog demo --spec toml`（mock+stub），再 FAB E2E。
2. **不恢复并行 field match**：禁止在生产路径启用 `map_send`。
3. **interrupt 四件套不可删**：`ask_sources`、`ask_layout`、`ask_sample`、`ask_db_id` — 与 `toml_config_design.md` 强制项一致。
4. **NiceGUI 侧边栏保持只读**：不要把 sidebar 改成聊天输入。
5. **最小 diff**：合并 orchestrator 可分阶段；不要顺带重构 unrelated 模块。

---

## 4. 文件变更清单

### 4.1 已删除（旧计划，勿恢复）

```
plans/dynamic-wizard-runtime/coding-handoff.md
plans/dynamic-wizard-runtime/phase-a.md
plans/dynamic-wizard-runtime/phase-b.md
plans/dynamic-wizard-runtime/phase-c.md
plans/dynamic-wizard-runtime/phase-d.md
plans/dynamic-wizard-runtime/plan.md
plans/dynamic-wizard-runtime/specify.md
plans/dynamic-wizard-runtime/tasks.md
plans/dynamic-wizard-runtime/README.md   # 旧版；已由新 README 替代
```

### 4.2 新建 / 重写（本交接包）

```
plans/dynamic-wizard-runtime/HANDOFF.md      # 本文件
plans/dynamic-wizard-runtime/README.md       # 目录索引
plans/dynamic-wizard-runtime/tasks.md        # 可勾选任务列表
plans/dynamic-wizard-runtime/file-map.md     # 代码文件职责表
```

### 4.3 规格（只读参考，改动需同步 tasks）

```
docs/gemma4_dynamic_workflow.md              # v2.0 权威
docs/embed_gemma4.md                         # LiteRT 底座
docs/toml_config_design.md                   # 落盘 TOML 语义
```

### 4.4 实施时可能修改的代码（按 tasks 优先级）

| 优先级 | 文件 | 改动目的 |
|--------|------|----------|
| 高 | `tests/test_cli_dialog_toml.py`（新建） | mock+stub 冒烟 pytest |
| 高 | `llm_gemma4/cli/dialog_cmds.py` | 可选 `repl` 子命令、输入队列 |
| 高 | `llm_gemma4/cli/queue.py`（新建） | CLI 主轮次 FIFO（仅 CLI） |
| 中 | `llm_gemma4/workflow/parallel.py` | 删除或明确废弃 `map_send` |
| 中 | `llm_gemma4/toml_config/workflow_orchestrator.py` | 与 `TomlGuideSpec` 行为对齐 |
| 中 | `llm_gemma4/dialog/orchestrator.py` + `toml_config/spec.py` | 双 facade 收敛（阶段 2） |
| 中 | `llm_gemma4/cli/mock_backend.py` | toml 域 `_main_reply` 勿用 briefing 文案 |
| 低 | `README.md` | 增加 CLI 快速入门 |
| 低 | `nicegui_ui/components/workflow_ui.py` | 仅 bugfix；**不做**排队/聊天改造 |
| 低 | `nicegui_ui/components/toml_wizard.py` | 仅与 orchestrator API 对齐 |

完整路径见 `file-map.md`。

---

## 5. 验收命令（实施方必须能跑通）

```bash
# 环境（Linux 示例）
cd bootup && uv sync
cd ..
uv run --project bootup python -m llm_gemma4.cli dialog catalog --spec toml
uv run --project bootup python -m llm_gemma4.cli dialog demo --spec toml
# 实施后增加：
uv run --project bootup pytest tests/test_cli_dialog_toml.py -q
```

Windows 开发机：激活 `bootup\.venv` 后同等命令。

---

## 6. 给下一个对话的 Prompt 模板（可直接复制）

```
你在仓库 excel-template-viz 分支 feature-gemma-toml-3 上工作。

请先阅读：
1. docs/gemma4_dynamic_workflow.md（v2.0）
2. plans/dynamic-wizard-runtime/HANDOFF.md
3. plans/dynamic-wizard-runtime/tasks.md

按 tasks.md 优先级实施。原则：CLI 先验收，不恢复 LiteRT 并行，NiceGUI 不做排队。
每完成一项任务：跑 dialog demo --spec toml，更新 tasks.md 勾选。
```

---

## 7. 风险提醒

| 风险 | 缓解 |
|------|------|
| 改 `WorkflowOrchestrator` 导致 NiceGUI 回归 | CLI demo + 手动 FAB 各测一次 |
| 合并双 orchestrator 范围膨胀 | 先做共享 integration test，再抽公共模块 |
| `--live` 仅能在有 GPU/权重的 Windows 机验证 | CI 只用 `--mock --stub` |
