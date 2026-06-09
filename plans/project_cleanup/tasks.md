# 项目清理任务清单（tasks.md）

优先级：P0 最高。每项完成后将 `[ ]` 改为 `[x]`。

**实施日期：2026-06-09** — 已按 `spec.md` §3 默认裁决执行。

---

## Phase 0：删除前裁决（实施前与用户确认）

### [x] Task 0.1 — 确认默认裁决
* 确认采用 `spec.md` §3 默认项：`list_template_data_sources` 删除、legacy 粘贴 parser 删除、`pyproject.toml` 整删、CODEGRAPH 刷新、`implementation_context.md` 合并后删除。

---

## Phase 1：pytest 彻底移除（P0）

### [x] Task 1.1 — 删除测试目录
* 删除整个 `tests/`（含 `fixtures/`、`test_image.png` 及全部 `test_*.py`）。

### [x] Task 1.2 — 删除 pytest 依赖
* 从 `requirements.txt` 移除 `pytest>=8.0` 行。

### [x] Task 1.3 — 删除 pytest 配置
* 删除根目录 `pyproject.toml`。

### [x] Task 1.4 — 更新用户文档
* `README.md`：无「测试 / Tests」节；文档索引含 `plans/project_cleanup/`。

### [x] Task 1.5 — 清理 pytest 缓存规则
* `.gitignore`：删除 pytest 注释块。
* 本地删除工作区 `.pytest_cache/`。

---

## Phase 2：配置与依赖清理（P1）

### [x] Task 2.1 — 删除废弃注册表
* 删除 `config/templates.json` 与空 `config/` 目录。

### [x] Task 2.2 — 移除 torchvision
* 从 `requirements.txt` 删除 `torchvision>=0.27.0`。

---

## Phase 3：文档与重复资产（P2）

### [x] Task 3.1 — 删除弃用双语 Speckit（6 个文件）
* 6 个 `*_zh.md` 已删除。

### [x] Task 3.2 — 删除重复 fixture
* 删除 `plans/data_source_in_form_tab/fixtures/Ginger_Lots.paste.yaml` 与空 `fixtures/`。

### [x] Task 3.3 — 处理 implementation_context.md
* 验收表格并入 `plans/data_source_in_form_tab/spec.md` §1。
* 删除 `implementation_context.md`。

### [x] Task 3.4 — 更新 data_source_in_form_tab 计划内测试引用
* `plan.md`、`tasks.md` 中 pytest/测试路径改为手动验收。

---

## Phase 4：应用内死代码删除（P2–P3）

### [x] Task 4.1 — 高置信度小清理
* 已删除 `read_paste_mapping_yaml_text`、`reset_phi35_vision_cache`、`get_pid_file_path`、未使用的 `import math`。

### [x] Task 4.2 — data_source 仅测试符号
* 已删除 `list_template_data_sources()`、`TemplateDataSourceEntry`、`tab_mappings()`。

### [x] Task 4.3 — source_parser legacy 粘贴路径
* 已删除 legacy 粘贴函数与 `IDX_*` 常量；保留 Sheet 路径与 `merge_parsed_into_headers`。

---

## Phase 5：文档与仓库卫生（P3）

### [x] Task 5.1 — 刷新 CODEGRAPH
* 已更新 `plans/CODEGRAPH_OVERVIEW.md`。

### [x] Task 5.2 — 修正 .gitignore
* `tamplates/*.json` → `templates/*.json`。

### [x] Task 5.3 — 更新 README 文档索引
* 已含 `plans/project_cleanup/`；弃用说明已更新。

### [x] Task 5.4 — 工作区缓存清理
* 已删除 `__pycache__/`。

---

## Phase 6：验收（P0）

### [x] Task 6.1 — 静态扫描
* `tests/`、`pyproject.toml`、`config/templates.json` 已不存在；`requirements.txt` 无 pytest/torchvision。

### [ ] Task 6.2 — 手动冒烟
* 按 `plan.md` §6 执行 Streamlit 六项检查（需用户本地验证）。

---

## 任务依赖简图

```
Phase 0 → Phase 1 → Phase 4 → Phase 6
              ↓
         Phase 2, 3, 5（可与 Phase 4 部分并行，但 CODEGRAPH 宜在 Phase 4 后）
```
