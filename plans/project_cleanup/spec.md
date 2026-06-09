# 项目清理规格说明（spec.md）

## 1. 背景

审计日期：2026-06-09。应用已迁移至模板自动发现（`registry.py` 扫描 `templates/*.xlsx`）、YAML 驱动粘贴解析（`paste_parse_config`）与 Phi-3.5 Vision 填映射。仓库中仍残留注册表时代文件、双语弃用文档、仅测试覆盖的死代码，以及用户明确要求废弃的 pytest 体系。

## 2. 删除范围（按类别）

### 2.1 pytest 全量移除（P0，用户强制）

| 目标 | 原因 |
|------|------|
| 整个 `tests/` 目录（含 `fixtures/`、`test_image.png` 等） | 用户要求「pytest 毫无用处，彻底删除」 |
| `requirements.txt` 中 `pytest>=8.0` | 运行时不需要 |
| `pyproject.toml` 全文 | 删除 pytest 后，文件仅剩过时 `[project].dependencies` 与无人使用的元数据；**推荐整文件删除**（见 §4.3） |
| `README.md`「测试 / Tests」整节 | 仅写 `pytest`，无其他测试入口 |
| `.gitignore` 中 pytest 相关块（`.pytest_cache/`、`htmlcov/`、`.coverage`） | 无测试体系后可选删除该注释块 |
| 工作区 `.pytest_cache/`、`tests/**/__pycache__/` | 构建缓存噪音 |

**不在本计划内修改**（历史档案，提及 pytest 可接受）：`plans/excel_template_viz/`、`plans/template_auto_discovery/` 已完成任务描述中的 pytest 字样。

**需更新引用**：`plans/CODEGRAPH_OVERVIEW.md`、`plans/data_source_in_form_tab/implementation_context.md`（若保留该文件，删去对 `tests/` 的路径依赖说明）。

### 2.2 配置文件与依赖（P1）

| 目标 | 原因 |
|------|------|
| `config/templates.json` | `app/` 零引用；内容仍指向旧 `gin_lot` / `gin_lot_template.xlsx`；`template_auto_discovery` 已验收不依赖注册表 |
| `requirements.txt` 中 `torchvision>=0.27.0` | 全仓库无 `import torch` / `import torchvision`；与 OpenVINO/Phi-3.5 路径无关 |
| `config/` 目录（若删除 `templates.json` 后为空） | 避免空目录悬挂 |

### 2.3 弃用文档（P2）

| 目标 | 原因 |
|------|------|
| `plans/excel_template_viz/plan_zh.md` | README 声明双语 Speckit 已弃用 |
| `plans/excel_template_viz/spec_zh.md` | 同上 |
| `plans/excel_template_viz/tasks_zh.md` | 同上 |
| `plans/excel_template_viz/constitution_zh.md` | 同上 |
| `plans/template_auto_discovery/plan_zh.md` | 同上 |
| `plans/template_auto_discovery/spec_zh.md` | 同上 |

共 6 个 `*_zh.md`。英文版 Speckit 保留作历史档案。

### 2.4 重复与 handoff 产物（P2）

| 目标 | 原因 |
|------|------|
| `plans/data_source_in_form_tab/fixtures/Ginger_Lots.paste.yaml` | 与 `templates/Ginger_Lots.paste.yaml` 内容重复；测试与运行时代码均读 `templates/` |

| 目标 | 处理方式（需决策） |
|------|-------------------|
| `plans/data_source_in_form_tab/implementation_context.md` | 任务已全部 `[x]`；`spec.md` 仍引用。可选：**合并关键表格进 `spec.md` 后删除**，或**保留**作 handoff 档案 |

### 2.5 应用内死代码（P2–P3，删除前见 §3）

| 位置 | 符号 | 置信度 |
|------|------|--------|
| `paste_parse_config.py` | `read_paste_mapping_yaml_text()` | 高：`_prepare_yaml_draft` 直接 `read_text()` |
| `phi35_vision_model.py` | `reset_phi35_vision_cache()` | 高：无调用方 |
| `shutdown.py` | `get_pid_file_path()` | 高：模块使用常量 `PID_FILE` |
| `template_form.py` | `import math` | 高：未使用 |
| `data_source.py` | `list_template_data_sources()`、`TemplateDataSourceEntry` | 中：仅测试调用，UI 未接入 |
| `data_source.py` | `tab_mappings()` | 中：仅测试；生产用 `sheet_mappings()` |
| `source_parser.py` | `parse_source_text()`、`parse_source_line()`、`parse_source_text_with_mappings()`、`map_tab_line_with_mappings()` | 中：粘贴已改 `paste_parse_config`；**Sheet 路径仍活跃** |

**保留（非死代码）**：

* `source_parser.merge_parsed_into_headers`、`sheet_row_to_form_fields`、`map_sheet_row_with_mappings` 等 — `template_form.py` 与 Google Sheet 查表仍使用。
* `registry.get_template()` — 内部封装，合理。
* `infer_paste_mapping_from_image_debug()` — `scripts/debug_vision_paste.py` 使用。

### 2.6 文档与仓库卫生（P3）

| 目标 | 处理方式 |
|------|----------|
| `plans/CODEGRAPH_OVERVIEW.md` | **刷新**（推荐）：更新模块列表、数据流（YAML 粘贴非 `parse_source_text`）、删除 tests/pyproject 描述；或**删除**若团队不再维护 CodeGraph |
| `.gitignore` 第 20 行 `tamplates/*.json` | 修正为 `templates/*.json`（拼写错误，规则从未生效） |
| 工作区未跟踪的 `__pycache__`、`.pytest_cache` | 本地删除，不提交 |

## 3. 删除前必须裁决的项

### 3.1 `list_template_data_sources()` 与 `TemplateDataSourceEntry`

| 选项 | 说明 |
|------|------|
| **A. 删除**（推荐，与 pytest 移除一致） | 函数仅被 `tests/test_data_source.py` 使用；当前 `data_source_settings` 未展示全模板汇总表；删除后更新 CODEGRAPH 中「数据源 Tab 汇总全部模板」的错误描述 |
| **B. 接入 UI** | 在数据源 Tab 恢复汇总表；工作量大，超出「清理」范围，应单独立项 |

**本计划默认：选 A**，除非实施前用户明确要求 B。

### 3.2 legacy `source_parser` 粘贴路径

粘贴生产路径：`paste_parse_config.parse_text_with_config()`（`template_form._apply_source_parse`）。

| 选项 | 说明 |
|------|------|
| **A. 删除 legacy 粘贴函数**（推荐） | 删除 `parse_source_text`、`parse_source_line`、`parse_source_text_with_mappings`、`map_tab_line_with_mappings` 及仅服务粘贴的硬编码索引常量（`IDX_*` 等），**保留** Sheet 映射与 `parse_md_date` |
| **B. 保留整文件** | 增加维护负担；无测试后无回归保障，不建议 |

**本计划默认：选 A**。

### 3.3 `tab_mappings()`

仅测试使用；生产使用 `sheet_mappings()`。**默认删除** `tab_mappings()`。

### 3.4 `implementation_context.md`

**默认**：将 §4 验收表格与 TSV fixture 行合并进 `spec.md`（若尚未完整），然后删除 `implementation_context.md` 并更新 `spec.md` 内链。

### 3.5 `pyproject.toml` 命运

审计曾建议「保留作 pytest 配置」。用户已否决 pytest。

| 选项 | 说明 |
|------|------|
| **A. 删除整个 `pyproject.toml`**（推荐） | 无 `[build-system]`、无 `pip install .` 流程；`install.bat` / README 仅用 `requirements.txt` |
| **B. 保留极简元数据** | 仅 `[project] name/version/description`，无 dependencies、无 tool 段；价值有限 |

**本计划默认：选 A**。

### 3.6 `CODEGRAPH_OVERVIEW.md`

| 选项 | 说明 |
|------|------|
| **A. 刷新**（推荐） | 与当前 17+ 模块、vision/paste、无 tests 一致 |
| **B. 删除** | README 去掉 CodeGraph 链接 |

**本计划默认：选 A**。

## 4. pytest 移除影响说明

* **无自动化回归**：删除后依赖手动 Streamlit 冒烟（粘贴、Sheet 查表、导出、Vision 下载）。
* **解锁死代码删除**：`list_template_data_sources`、`tab_mappings`、legacy `source_parser` 粘贴函数、仅测试引用的 debug 路径可安全按 §3 删除。
* **`scripts/debug_vision_paste.py` 保留**：非 pytest，独立调试入口。
* **历史计划中的 pytest 验收句**：只读档案，可不改；新真相由 CODEGRAPH 与 README 体现。

## 5. 验收标准

1. 仓库中不存在 `tests/`、`pyproject.toml`（若采用 §3.5-A）、`config/templates.json`。
2. `requirements.txt` 无 `pytest`、`torchvision`。
3. `grep -r pytest` 在 `app/`、`README.md`、`requirements.txt`、根配置中无命中（`plans/` 历史文档除外）。
4. `app/` 中 §2.5 高置信度死符号已移除；§3 默认裁决项已执行或已记录偏离。
5. README 文档节指向本清理计划；无「运行 pytest」说明。
6. `CODEGRAPH_OVERVIEW.md` 已刷新或已删除且 README 已同步。
