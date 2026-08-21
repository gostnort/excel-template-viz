# TOML 配置向导（动态 agents CLI）

> 状态：feature-llm-toml-4  
> 包：[`llm_toml_wizard/`](../llm_toml_wizard/)  
> 推理底座：[`llm_lmstudio.md`](llm_lmstudio.md)

保留后期动态 agents 的 CLI 设计：`dispatch(Start|Resume|Stop)`、四类 interrupt、`map_run_sequential` 子代理、`--mock --stub` 冒烟。NiceGUI 是同一条链的表单 I/O，侧边栏只读日志。

## CLI 优先

```bat
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog demo --spec toml
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog catalog --spec toml
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog run --spec toml --live --release
```

| 标志 | 含义 |
|------|------|
| `--mock` | `ScriptedBackend`，不连 LM Studio |
| `--stub` | 固定 `decide` 顺序 |
| `--demo` | 预填 `TOML_DEMO_AUTO` |
| `--live` | 真实 LM Studio |
| `--release` | 结束后 unload 当前模型 |

真人输入仅在 interrupt：`ask_sources` / `ask_layout` / `ask_sample` / `ask_db_id`。compute 段自动 Continue（cap 24），字段匹配串行。

## 包布局

| 路径 | 职责 |
|------|------|
| `llm_toml_wizard/cli/` | `dialog catalog/run/demo/repl` |
| `llm_toml_wizard/dialog/` | 通用 `DialogOrchestrator`、briefing spec |
| `llm_toml_wizard/toml_config/` | 九动作、提示词、`WorkflowOrchestrator`、field agent |
| `llm_toml_wizard/workflow/` | Graph 事件、`map_run_sequential` |
| `nicegui_ui/components/workflow_ui.py` | interrupt 对话框、FAB、只读日志 |
| `nicegui_ui/components/toml_wizard.py` | `TomlWizardController`；dispatch 走 `run.io_bound` |

## 九动作

`capture_sources` → `capture_layout` → `capture_sample` → `preprocess_sample` → `plan_ghost_tasks` → `match_ghost_fields`（串行）→ `match_sheet_columns` → `infer_regex` → `finalize_toml`

提示词在 `llm_toml_wizard/toml_config/prompts.py`。落盘语义仍以 [`toml_config_design.md`](toml_config_design.md) 为准。
