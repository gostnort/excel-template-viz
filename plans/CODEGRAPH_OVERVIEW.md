# Excel Template Viz — 项目概览（CodeGraph 风格快照）

> 快照日期：**2026-06-10** · 工作区：`e:\my_github\excel-template-viz`

本文档按 CodeGraph 约定整理。当前工作区未启用 CodeGraph MCP，本次为基于代码库的手工刷新。

---

## 项目定位

Streamlit 应用：将 Excel 模板（如 Ginger Lots）可视化为 Web 表单，支持 YAML 驱动制表符粘贴批量填表、YAML 驱动 Google Sheet 按 ID 查询填表、Phi-3.5 Vision 生成粘贴映射，并导出/打印 xlsx。每个模板通过 `templates/` 自动发现，配置保存在同名 sidecar JSON 与 `.paste.yaml`。

---

## 目录与模块

| 路径 | 职责 |
|------|------|
| `streamlit_app.py` | **应用入口**（须在项目根目录 `streamlit run`） |
| `app/main.py` | 侧边栏模板导航、关闭应用；路由至 `render_template_page` |
| `app/components/template_form.py` | 单模板页：`数据录入` / `粘贴映射` / `数据源` 三 Tab；PO 自动查询、源数据粘贴、Save As、打印预览 |
| `app/components/data_source_settings.py` | 「数据源」Tab：Google 认证、连接测试、YAML 表头在线校验、工作表/ID 列；无 YAML 时显示列映射编辑器 |
| `app/components/paste_parse_settings.py` | 「粘贴映射」Tab：Phi-3.5 Vision 推理、YAML 编辑与保存 |
| `app/components/paste_image_button.py` | 粘贴截图自定义 Streamlit 组件（Python 桥接） |
| `app/components/paste_image_button_frontend/` | 上述组件前端（HTML/JS/CSS） |
| `app/services/registry.py` | 扫描 `templates/*.xlsx`，读写 sidecar `.config.json` |
| `app/services/data_source.py` | 读写 sidecar 内 `data_source` 字段 |
| `app/services/paste_parse_config.py` | `.paste.yaml` 加载/保存/校验；TSV 解析；Sheet 行映射（`map_sheet_row_from_paste_config`）；表头对齐校验 |
| `app/services/phi35_vision_model.py` | Phi-3.5 OpenVINO 模型下载与加载 |
| `app/services/phi35_vision_paste_infer.py` | 截图 → §4 粘贴映射 YAML 推理 |
| `app/services/paste_mapping_infer.py` | **未引用（死代码）**：旧 HTML/MD 行推断，已被 §4 YAML 取代 |
| `app/services/excel_parser.py` | xlsx 读写、Spreadsheet ID 解析 |
| `app/services/excel_print.py` | 打印区域检测、导出持久化、PIL 预览图、Windows 打印对话框 |
| `app/services/export_naming.py` | 导出文件名 `template-IDs-data-time.xlsx` |
| `app/services/source_parser.py` | Sheet 行 → 表单字段（**无 YAML 时回退**）；`merge_parsed_into_headers` |
| `app/services/google_sheets.py` | gspread 连接、预览、按 ID 查行 |
| `app/services/shutdown.py` | 后台 PID、优雅关闭 |
| `templates/` | 本地 xlsx + sidecar + `*.paste.yaml` |
| `credentials/` | OAuth 客户端 JSON（不入库） |
| `exports/` | Save As / 打印用导出 xlsx（不入库） |
| `plans/` | Speckit 规划文档 |
| `.cursor/rules/streamlit-ui.mdc` | Streamlit 布局与样式约定（列布局用 Python，CSS 按页合并） |

**已移除（2026-06-09 清理）：** `tests/`、`pyproject.toml`、`config/templates.json`、弃用 `*_zh.md`、侧边栏「添加数据源」入口。

---

## 入口点

| 类型 | 位置 | 说明 |
|------|------|------|
| Streamlit main | `streamlit_app.py` → `app.main.main` | `run.bat` 与手动启动均使用此路径 |
| 调试脚本 | `scripts/debug_vision_paste.py` | Phi-3.5 粘贴映射离线调试 |

**导入要点：** 不可执行 `streamlit run app/app.py`。须在项目根目录运行 `streamlit run streamlit_app.py`。

**依赖：** 仅以 `requirements.txt` + `pip install -r requirements.txt` 安装；无 pytest、无 `pyproject.toml`。

---

## 模板页 Tab 结构

| Tab | 组件 | 主要能力 |
|-----|------|----------|
| 数据录入 | `template_form._render_form_entry_tab` | 工作表选择、TSV 粘贴解析、多行编辑、ID 自动 Sheet 查询、Save As、打印预览 |
| 粘贴映射 | `paste_parse_settings.render_paste_mapping_tab` | Phi-3.5 Vision 截图推理、YAML 草稿编辑、保存至 `.paste.yaml` |
| 数据源 | `data_source_settings.render_data_sources_tab` | Google 认证、Sheet 测试、YAML↔Sheet 表头对齐表、工作表/ID 列持久化 |

---

## 数据流

```mermaid
flowchart LR
    subgraph UI
        A[streamlit_app / main]
        B[template_form]
        P[paste_parse_settings]
        C[data_source_settings]
    end
    subgraph Sidecar
        T["templates/*.xlsx"]
        J["*.config.json"]
        Y["*.paste.yaml"]
    end
    subgraph Services
        R[registry]
        DS[data_source]
        PPC[paste_parse_config]
        SP[source_parser]
        GS[google_sheets]
        EP[excel_parser]
        EX[excel_print]
        VI[phi35_vision_paste_infer]
    end
    A --> B
    B --> P
    B --> C
    B --> R
    B --> DS
    B --> PPC
    B --> SP
    B --> GS
    B --> EP
    B --> EX
    P --> VI
    P --> PPC
    VI --> PPC
    C --> DS
    C --> PPC
    C --> GS
    R --> T
    R --> J
    PPC --> Y
    DS --> J
```

1. **模板发现：** `registry.load_templates()` 扫描 `templates/*.xlsx` → 侧边栏列出模板。
2. **制表符粘贴：** 用户粘贴 TSV → `parse_text_with_config`（读 `.paste.yaml` §4 schema）→ `merge_parsed_into_headers` → 表单；解析失败不覆盖已有单元格。
3. **PO 自动查询（YAML 主路径）：** ID 字段由 `.paste.yaml` 中 `ID: true` 决定 → `id_column_from_config` 得 Sheet 检索列 → `fetch_row_by_id`（worksheet 优先 YAML `worksheet`，否则 sidecar）→ `map_sheet_row_from_paste_config` → `merge_parsed_into_headers`（保留已有手动输入）。**无 YAML 时回退** `sheet_row_to_form_fields` + sidecar `column_mappings`。
4. **数据源表头校验：** 「测试连接」成功后 → `validate_yaml_against_sheet_headers` → 展示 YAML `filed` 与 Sheet 列对齐表；ID 列下拉默认选中 YAML 中的 `filed`。
5. **粘贴映射：** 截图 → Phi-3.5 Vision → 校验 §4 YAML → 保存 `.paste.yaml`。
6. **导出 / 打印：** Save As → `exports/` + 打印区域预览图；打印按钮 → Windows 打印对话框。

---

## `.paste.yaml` 关键 API（`paste_parse_config.py`）

| 函数 | 用途 |
|------|------|
| `parse_text_with_config` | TSV 粘贴 → 表单行 |
| `id_column_from_config` | 从 `ID: true` 规则提取 Sheet 检索列名 |
| `id_target_field_from_config` | 提取触发表单字段名 |
| `map_sheet_row_from_paste_config` | Sheet 行 dict → 表单字段（`filed` + 可选 `regex`） |
| `validate_yaml_against_sheet_headers` | 在线表头对齐诊断 |
| `resolve_sheet_header` | 精确/松散匹配 Sheet 列名 |

可选顶层键：`determiner`、`order`、`worksheet`（Sheet 工作表名，查表时优先于 sidecar）。

---

## Sidecar 配置结构

每个 `templates/<name>.xlsx` 对应 `<name>.config.json`（或 `<name>.json`）：

```json
{
  "display_name": "Ginger Lots",
  "description": "",
  "sheet_name": "",
  "header_row": 0,
  "data_start_row": 1,
  "data_source": {
    "sheet_url": "https://docs.google.com/spreadsheets/d/...",
    "spreadsheet_id": "...",
    "worksheet_name": "Sheet1",
    "id_column": "PO",
    "column_mappings": [
      { "source": "PO", "target": "P.O. No.", "kind": "sheet" }
    ]
  }
}
```

`column_mappings` 仅在**无** `.paste.yaml` 时作为 Sheet 查表回退路径。

粘贴映射示例（§4 schema，见 `plans/data_source_in_form_tab/spec.md` §4 与 `plans/yaml_driven_sheet_lookup/spec.md`）：

```yaml
determiner: "tab"
worksheet: "Sheet1"
P.O. No.:
  - ID: true
    filed: "PO"
    index: 0
Receiving Date:
  - filed: "recv. date"
    index: 12
    regex: '(\d{1,2}\/\d{1,2})'
```

---

## 全局统计

| 指标 | 数值 |
|------|------|
| Python 源文件 | 18（`app/` 17 + `streamlit_app.py`） |
| 活跃 Speckit 计划 | `yaml_driven_sheet_lookup`（英文）、`data_source_in_form_tab`、`project_cleanup` 等 |
| 外部依赖 | streamlit, pandas, openpyxl, gspread, google-auth, PyYAML, Pillow, transformers, openvino, optimum-intel, huggingface-hub |

---

## 维护建议

1. **新模板：** 将 xlsx 复制到 `templates/`，无需注册表。
2. **数据源：** 在「数据源」Tab 完成认证、测试与保存；有 `.paste.yaml` 时以 YAML 为映射权威，无需维护 `column_mappings`。
3. **粘贴：** 在「粘贴映射」Tab 配置 YAML，在「数据录入」Tab 粘贴并「解析并填入」。
4. **Streamlit UI：** 同行控件用 `st.columns`（列数可变）；样式 CSS 按页合并注入，见 `.cursor/rules/streamlit-ui.mdc`。
5. **死代码清理：** 可删除未引用的 `paste_mapping_infer.py`。
6. **刷新本文档：** 大改架构后手工更新本文件，或启用 CodeGraph MCP 后自动再生。
