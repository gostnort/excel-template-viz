# feature-gemma-toml-1 · 综合实施设计

> **DEPRECATED** — superseded by [plans/dynamic-wizard-runtime/](../dynamic-wizard-runtime/) and [docs/gemma4_dynamic_workflow.md](../docs/gemma4_dynamic_workflow.md). Fixed 8-step `WizardOrchestrator` removed.

> 契约：[docs/embed_gemma4.md](../docs/embed_gemma4.md) v7.0、[docs/gemma4_e4b_workflow.md](../docs/gemma4_e4b_workflow.md) v7.0  
> 分支：`feature-gemma-toml-1`  
> 日期：2026-07-27

## 1. 目标

实现 TOML 智能向导：**进程内向导模式**（非独立 Tab）。从「输入配置」启动，自动切换真实业务 Tab、步骤说明对话框、Shell 级 danger「下一步配置」FAB。单 Engine、主对话 `wizard_main`、字段子 agent（`Semaphore(2)`）、pass1 普通 → pass2 thinking 重试、步骤 7 完整试跑写盘。

Paddle-OCR 已有 API（`run_judgment`、`ConversationOnce`、`Pic2Str`、`StartGemma`）**冻结不改**。

## 2. 架构

```
「输入配置」Tab 点「启动 AI 智能配置向导」
    → TomlWizardController.start() 加载 Gemma
    → wizard_ui.enter_step(n)：切 Tab + 步骤对话框
    → Shell FAB「下一步配置」→ run_step(n) → WizardOrchestrator.advance
        → wizard_main + FieldAgentPool (Semaphore(2))
    → SessionRegistry: last_ghost_paste, connect_google, template_path
llm_gemma4: SessionOptions, LiteRtBackend.open_session
```

## 3. 模块清单

| 文件 | 职责 |
|------|------|
| `llm_gemma4/backends/base.py` | `SessionOptions` |
| `llm_gemma4/backends/litert/backend.py` | `open_session(..., options=)` |
| `llm_gemma4/config.py` | `load_thinking_budget()` |
| `llm_gemma4/wizard/*` | 7 步状态机、子 agent、试跑、TOML 生成 |
| `nicegui_ui/components/toml_wizard.py` | `TomlWizardController`（无 UI） |
| `nicegui_ui/components/wizard_ui.py` | Tab 导航、步骤对话框、FAB |
| `nicegui_ui/pages/main.py` | `render_wizard_chrome` + `register_shell` |
| `nicegui_ui/components/general.py` | `last_ghost_paste` |

**已删除**：`nicegui_ui/pages/tab_toml_wizard.py`（独立「AI 向导」Tab）。

## 4. advance(step) 状态机

| step | 输入 payload | 动作 | 完成后 current_step |
|------|--------------|------|---------------------|
| 1 | `data_sources` | 主对话记录数据源 | 2 |
| 2 | `ghost_text_sample`, `template_path` | 扫 labels；主对话理解样本 | 3 |
| 3 | — | 子 agent ghost 匹配 | 4 |
| 4 | `google_headers`, `google_rows`（可空跳过） | 子 agent sheet 匹配 | 5 |
| 5 | — | 子 agent regex | 6 |
| 6 | `db_id` | 设 id 字段 | 7 |
| 7 | `template_id`, `template_path` | trial_run；写 TOML | 7 + `is_finished` |

**禁止**单步内跨多步。

## 5. 子 agent pass1/pass2

- pass1: `thinking=False`, `max_tokens=256`
- pass2: `thinking=True`, `max_tokens=load_thinking_budget()`
- 新 `session_id` per pass；用完 `close()`
- step5 regex: `re.search` 失败 → pass2

## 6. SessionRegistry 约定

- `last_ghost_paste`: `tab_input` ghost blur 时写入；步骤 2 从该字段读取，**无重复 textarea**
- Google 步骤 1/4：`connect_google.prepare_id_sheet_table()` 的 columns + rows[:5]
- `app.storage.user["wizard_active"]`：向导模式标志，控制 FAB 显示

## 7. 步骤 7 试跑

1. `generate_toml(state)` → `tomlkit.loads` → `_config_from_dict`
2. `verify_toml(template_path, cfg)`
3. `UiProvider` 试跑拆分比对
4. `ok` 时写 sidecar TOML → `trigger_toml_save`

## 8. OCR 回归

- `paddle_ocr/gate/semantic_gate.py` 仍 `run_judgment(_get_backend(), spec)`
- `open_session` 新增可选参数，默认 `None`，不影响 `generate`

## 9. 验收

见 [gemma4_e4b_workflow.md](../docs/gemma4_e4b_workflow.md) §7（UI 路径改为进程内 Tab + FAB）。

## 10. UI 步骤表（进程内模式）

| Step | 激活 Tab | 对话框说明 | FAB「下一步配置」 |
|------|----------|------------|-------------------|
| 1 | Google 连接 | 配置 OAuth / Sheet（可跳过） | `build_data_sources()` → `advance(1)` |
| 2 | 输入 | Ghost 粘贴或 OCR | 无 ghost 且无 Google → **结束**；否则 `advance(2)` |
| 3 | 输入配置 | Ghost 字段匹配进度 log | `advance(3)` |
| 4 | Google 连接（有 Sheet）或自动跳 5 | Sheet 列匹配 | `advance(4)` 或跳过 |
| 5 | 输入配置 | Regex 推理进度 | `advance(5)` |
| 6 | 输入配置 | 对话框内选 `db_id` | `advance(6)` |
| 7 | 输入配置 | 试跑结果 + TOML 预览 | `advance(7)`；通过则写盘并结束向导 |

Shell FAB：`AppBtn("下一步配置", variant="danger")` + `退出向导`；仅 `wizard_active` 时显示；`.wizard-fab-anchor` 固定右下角。
