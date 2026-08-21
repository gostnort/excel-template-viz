# 代码文件职责图（LM Studio）

## 入口

| 文件 | 职责 |
|------|------|
| `llm_lmstudio/__main__.py` | `models` / `load` / `unload` / `health` / `ask` / `vision` |
| `llm_toml_wizard/cli/main.py` | `dialog catalog/run/demo/repl` |
| `llm_toml_wizard/cli/dialog_cmds.py` | resume 循环 |
| `nicegui_ui/components/model_runtime.py` | 可编辑模型名 + load/unload 开关 |
| `nicegui_ui/components/toml_wizard.py` | `TomlWizardController` |
| `nicegui_ui/components/workflow_ui.py` | FAB / interrupt 表单 |

## 编排

| 文件 | 使用者 |
|------|------|
| `llm_toml_wizard/toml_config/workflow_orchestrator.py` | NiceGUI |
| `llm_toml_wizard/dialog/orchestrator.py` | CLI briefing |
| `llm_toml_wizard/toml_config/spec.py` | CLI toml |
| `llm_toml_wizard/workflow/graph.py` | 共用 |

## 推理

| 文件 | 职责 |
|------|------|
| `llm_lmstudio/client.py` | urllib REST |
| `llm_lmstudio/models.py` | list/get/load/unload/vision |
| `llm_lmstudio/chat.py` | `/api/v1/chat` |
| `llm_lmstudio/backend.py` | `LmStudioBackend` |
