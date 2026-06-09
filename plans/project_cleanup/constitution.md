# 项目清理宪章（constitution.md）

## 1. 核心原则

本计划基于只读审计任务 a7d71f75，目标是在不破坏 Streamlit 应用主流程的前提下，删除冗余文件、死代码与已弃用测试体系。

* **单一安装源**：`requirements.txt` 为运行时依赖的唯一权威来源；删除 pytest 后不再维护双源依赖清单。
* **应用优先**：凡被 `streamlit_app.py` → `app/` 生产链路引用的符号，除非经决策明确废弃，否则不得删除。
* **历史计划只读**：已完成 Speckit 计划（`excel_template_viz`、`template_auto_discovery`、`data_source_in_form_tab`）正文作为档案保留，不在本计划中大规模改写；仅通过 README 与 `CODEGRAPH_OVERVIEW.md` 反映当前真相。
* **删除前决策**：存在产品含义的代码（如 `list_template_data_sources`、legacy 粘贴解析）须先裁决再删，避免误删未来可能接入 UI 的能力。

## 2. 技术约束

* **路径**：Python 代码继续使用 `pathlib.Path`。
* **不引入新工具链**：本计划不引入 ruff、vulture、CI；清理以人工审计与 grep 追踪为准。
* **不提交缓存**：`__pycache__/`、`.pytest_cache/` 等仅清理工作区，不纳入版本库。

## 3. 明确禁止

* 删除 `templates/*.xlsx` 旁路配置、`templates/*.paste.yaml` 等**运行时**模板资产。
* 删除 `scripts/debug_vision_paste.py`（开发调试入口，审计判定保留）。
* 删除 `app/components/paste_image_button_frontend/`（Streamlit 自定义组件必需文件）。
* 在未裁决的情况下删除 `source_parser.py` 中 Google Sheet 查表仍使用的 `sheet_row_to_form_fields`、`merge_parsed_into_headers` 等符号。

## 4. 用户明确要求

* **pytest 彻底移除**：依赖、配置、`tests/` 目录、文档与脚本中的 pytest 引用一并删除；不以「保留测试」为理由保留仅被测试调用的生产代码。
