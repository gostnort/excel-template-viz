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

## 开发中（未发版）

| 分支 | 相对 0.1 的增量 |
|------|-----------------|
| `add-paddle-ocr` | `paddle_ocr/`、`llm_gemma4/`、OCR 菜单、安装与文档更新 |

合并回 `split-logic-core` 或发 **0.2** 前，以上分支不视为稳定发布。
