# 发布记录

## 0.1 — `split-logic-core`

**Git 标签**：`v0.1`  
**分支**：`split-logic-core`

**范围**：

- Gradio 已移除；唯一 UI 为 **NiceGUI**（`nicegui_ui/`）
- 业务核心：`app/`（TOML、SQLite、`core_transform` 写回 xlsx）
- 功能：模板侧边栏、输入 / TOML / 存储 / Google 连接、导出与打印
- **不含**：`paddle_ocr/`、`llm_gemma4/`

根目录 `VERSION` 文件与 `v0.1` 标签在该分支上维护。

## 当前主线 — `main` / `add-paddle-ocr`

**分支**：`main` 与 `add-paddle-ocr` 同步（同一提交 `cc2473d` 起）。

**范围**（相对 0.1 的增量）：

- `paddle_ocr/`、`llm_gemma4/`
- NiceGUI OCR 菜单、安装与文档更新

日常开发在 `add-paddle-ocr`；合并到 `main` 后 `main` 与之间保持一致。
