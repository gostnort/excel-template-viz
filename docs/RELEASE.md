# 发布记录

## 0.1 — `split-logic-core`

**分支**：`split-logic-core`（本仓库的 **0.1 基线**）

**范围**：

- Gradio 已移除；唯一 UI 为 **NiceGUI**（`nicegui_ui/`）
- 业务核心：`app/`（TOML、SQLite、`core_transform` 写回 xlsx）
- 功能：模板侧边栏、输入 / TOML / 存储 / Google 连接、导出与打印
- **不含**：`paddle_ocr/`、`llm_gemma4/`（在后续分支开发）

**启动**：

```bat
install.bat
run.bat
```

浏览器：`http://127.0.0.1:8738`

**规格**：`docs/nicegui_ui/nicegui_ui_plan.md`、`plans/nicegui_ui_migration/`
