# 数据表格转换核心（Data Sheet Core）实施计划

## 概述

**本计划交付两个 Python 模块**（各一个 `.py` 文件），按职责分层：Excel 转换与持久化/UI 供给分离。四个类、无编排类；调用方（Gradio 或命令行）串联两模块完成流程。

**设计依据**：
- 架构蓝图：`docs/data_sheet_core_design.md`
- **字段语义与场景**：`docs/toml_config_design.md`（determiner / index / source_* / Input_label 分工）
- TOML 配置契约：`app/services/core_toml.py`
- 模板路径约定：`app/services/core_registry.py`（`TEMPLATES_DIR`）

**为何拆成两模块**：

| 分层 | 模块 | 关注点 |
|------|------|--------|
| 存储 + UI 供给 | `core_store.py` | UI 纯字符串入 DB；`determiner` 拆分；Gradio 读 DB |
| Excel 转换 | `core_transform.py` | 外部数据源表读取；Input_sheet 写回；区域检测 |

- **UI 只依赖 store 层**：textbox 纯字符串直接落库；`UiProvider` 从 DB 供给 labels + data。
- **转换层不依赖 store 层**：`Template2DB` 按 `source_file` / `source_sheet` / `Input_label` 读外部表；产出标准 `dict` 由调用方写入 DB。
- **依赖方向单一**：`core_transform` 不 import `core_store`。

**关键原则**：
- 仅交付 `core_store.py` 与 `core_transform.py`；不另建 `tests/`
- 仅 `import` 其他 `core_*.py` 及标准库；`core_transform` 另用 `openpyxl`
- 不引用 `section_detector`、`excel_parser`、`excel_print`、`paste_parse_config` 等既有服务
- 字段语义严格遵循 `toml_config_design.md`，**index 不是 Excel 列号**
- 四个类之外不新增类；不设编排类

## TOML 字段语义（核心契约）

依据 `docs/toml_config_design.md`，两类入参路径：

### 路径 A：UI textbox → DB（`core_store` 主责）

Gradio 提供一个 **textbox**，用户输入**一整段纯字符串**，原样或解析后写入 DB。

| 键 | 作用 |
|----|------|
| `determiner` | 拆分上述纯字符串的分隔符（如 `"\t"` tab） |
| `index` | 该 `[[fields]]` 对应字段在拆分结果中的**顺序位置**（0-based） |
| `Input_label` | Excel 模板列标题 / Gradio 表单列名（`get_labels()` 用） |
| `field` | 写入标准 DB 记录时的键名；`""` 表示不入标准库结构 |
| `id` | `true` 时该段值为记录主键 |

- `index = -1`：该列**不参与** textbox 字符串拆分（仅 Input_sheet 展示或仅走数据源路径）
- 示例：`determiner = "\t"`，用户输入 `"8129\tClark Kent\t..."`，`index = 0` → `ID#`，`index = 1` → `Name`

`core_store` 须提供：
- 接收 UI 纯字符串直接持久化
- 按 `determiner` + 各 rule 的 `index` 拆分为 `{Input_label: segment}` 或标准 `{field: value}`

### 路径 B：外部数据源表 → 标准记录（`Template2DB` 主责）

从 `[[sources]]` 配置的文件 / Google Sheet 读取标准数据库结构工作表。

| 键 | 作用 |
|----|------|
| `source_file` | 指向 `[[sources]]` 中的键名（如 `source1`），解析为实际路径或 Sheet URL |
| `source_sheet` | 数据源工作表名（如 `sheet1`） |
| `Input_label` | 在**数据源表**中定位列（列标题匹配）；同时是模板上的显示名 |
| `field` | 标准 DB 列名（如 `ID`、`name`、`issues`） |
| `regex` | 对读到的单元格值再做提取（如 `Report Date` 从 `issues` 列用 `'\d+/\d+/\d+'` 抽日期） |
| `id` | `true` 表示该列为 ID，用于按 ID 查行 |

- `source_file` / `source_sheet` 为 `""` 时：不走数据源，仅 UI 或 Input_sheet 路径
- 同一 `field` + 同一 `index` 可对应不同 `Input_label`（如 `Recent Issue` 与 `Report Date` 均 `field = "issues"`，`index = 2`，后者加 `regex`）

### 其他顶层键

| 键 | 使用方 | 作用 |
|----|--------|------|
| `worksheet` | `core_transform` | Input_sheet 工作表名 |
| `sections` | `ExcelWriter` | 多区域 `input_area` / `move_to` / `offset` |
| `sources` | `Template2DB` | 解析 `source_file` 别名 → 真实路径 |

**index 不再表示 Excel 列号。** Input_sheet 写回时按 `sections` 区域内**表头行匹配 `Input_label`** 定位列，或由 `input_area` 首行 headers 顺序推导。

## 模块结构

### `app/services/core_store.py` — UI 字符串与 DB

| 类 | 职责 |
|----|------|
| `SecureSQLite` | 持久化；`insert_or_update` / `query_by_id` / `query_all` |
| `UiProvider` | `get_labels()` ← `Input_label` 列表；`get_data()` ← DB |

模块级：`default_db_path(template_id)`

**UI → DB**：
1. 用户 textbox 提交纯字符串
2. `split_by_determiner(raw, cfg.determiner)` → `list[str]`
3. 对每个 `index >= 0` 的 rule，取 `parts[rule.index]` 填入记录（`field` 或 `Input_label` 键，实现时统一）
4. `SecureSQLite.insert_or_update(record)`

**DB → UI**：`get_data()` 返回库内 JSON 记录；Gradio 按 `get_labels()` 列名展示。

### db命名规则
1. 每一个数据库对应的是template的名字。
2. 不固定扩展名，但是有命名规则。
  - 使用字符顺序作为顺序。
  - 使用当前年份作为扩展名的一部分
例如：模板名字是"sample_template.xlsx"，今年是2026年。所以默认的数据库名字就是`sample_template.A2026`。如果用户手工继续创建，但是在同一年，那就是`sample_template.B2026`;如果用户在2027年手工通过UI想创建新的数据库，那就是`sample_template.A2027`.

数据库放置在`temp`文件夹中。最新的数据总是写入创建的扩展名数据库中。

### `app/services/core_transform.py` — 数据源读取与 Excel

| 类 | 职责 |
|----|------|
| `Template2DB` | 按 `source_file` + `source_sheet` + `Input_label` 读外部表行；`field` 映射 + `regex` + `id`；自动 ID |
| `ExcelWriter` | Input_sheet 写回（按 `Input_label` 对表头列）；另存；打印区域；区域检测 |

不 import `core_store`。

**数据源读取**（`Template2DB`）：
1. `resolve_source_path(cfg.sources, rule.source_file)` → 文件路径或 Sheet 句柄（本模块仅本地 xlsx；远程 URL 由上层注入路径后调用）
2. 打开 `rule.source_sheet`，按 ID 列（`id=true` 的 rule）定位行
3. 取 `Input_label` 对应列值 → `apply_regex` → 写入 `record[rule.field]`

### 数据流

```
                    ┌── UI textbox 纯字符串 ──► core_store
                    │      determiner 拆分 + index 取段
GetTomlValues ──────┤                              ▼
                    │                        SecureSQLite
                    │                              ▲
                    └── source_file/sheet ──► Template2DB ── record dict
                              Input_label            │
                                                     │
                    ExcelWriter.write_back ◄─────────┘（写 Input_sheet）
                    UiProvider.get_* ◄── DB
```

典型调用（伪代码）：

```python
cfg = GetTomlValues.Load(template_id)
db = SecureSQLite(default_db_path(template_id))
ui = UiProvider(cfg, db)

# 路径 A：UI 纯字符串入 DB
record = ui.record_from_textbox(user_raw_string)  # determiner + index
db.insert_or_update(record)

# 路径 B：外部数据源填充（可与 A 合并为一条标准记录）
t2db = Template2DB(cfg)
record = t2db.fetch_row_by_id(source_id_value)
db.insert_or_update(record)

writer = ExcelWriter(cfg)
writer.write_back(template_path, output_path, record)

labels = ui.get_labels()
rows = ui.get_data()
```

## 标准记录与存储

```python
{"id": 8129, "ID": 8129, "name": "Clark Kent", "issues": "..."}
```

- 主键：`id=true` 字段的值，或 `uuid.uuid4().int >> 64`
- `data` 列：JSON；含 `field` 映射后的标准库键
- 路径：`/temp`
- 禁止后缀：`.db`、`.sqlite`、`.sql`

## Excel 读写（`core_transform.py`，仅 openpyxl）

| 操作 | 要点 |
|------|------|
| 读 Input_sheet | `sections` 首行作表头，列名匹配 `Input_label` |
| 写回 | 按 `Input_label` 找列号赋值（**不用 index 当列号**） |
| 打印区域 | `ws.print_area` |

`ExcelWriter` 内建：`_parse_area_range`、`_calculate_next_area`、`detect_areas`、`read_area_rows`、`write_back`、`get_print_areas`。

## 分阶段实施

### Phase 1：两模块骨架

创建 `core_store.py`、`core_transform.py`；四类空壳；`core_transform` 不 import `core_store`。

### Phase 2：`core_store` — determiner 与 textbox

1. `split_by_determiner(raw, determiner) -> list[str]`
2. `record_from_textbox(raw) -> dict`：遍历 `index >= 0` 的 rules 取段
3. `SecureSQLite` 基础 CRUD

**验收**：给定 `"\t"` 分隔样例串，拆分结果与 `index` 映射一致。

### Phase 3：`core_transform` — Template2DB 数据源路径

1. `resolve_source_path(sources, source_file_key)`
2. `fetch_row_by_id(id_value)`：读 `source_sheet`，按 `Input_label` 取列，`regex` 处理
3. `transform` 合并为 standard `dict`

**验收**：与 `toml_config_design.md` 场景1（sheet1/sheet2）一致。

### Phase 4：`core_transform` — ExcelWriter

区域检测、按 `Input_label` 写回 Input_sheet、`get_print_areas`。

### Phase 5：`core_store` — UiProvider

`get_labels()`、`get_data()`；数据仅来自 DB。

### Phase 6：命令行验证（`core_transform.py` 的 `__main__`）

打印三段：

```
=== 1. 从 Excel / 数据源读取的数据 ===
=== 2. 写入 DB 后的数据 ===
=== 3. Gradio 可获得的数据 ===
labels: [...]
data: [...]
```

含 textbox 拆分样例与 `Template2DB` 数据源读取各一例。

## 成功标准

### 功能
- `determiner` 仅用于 UI 纯字符串拆分；`index` 为拆分后的段序
- `source_file` / `source_sheet` / `Input_label` 仅用于外部数据源表读列
- 两模块职责与上表一致；无第五类

### 验证
- `__main__` 打印三段数据且前后一致
- `data` 列统一 JSON

## 风险与注意事项

1. **index 语义**：禁止当作 Excel 列索引；写回靠 `Input_label` 对表头
2. **index = -1**：不参与 textbox 拆分；可仅 Input_sheet 展示或仅数据源
3. **同 index 多 rule**：如 `Report Date` 与 `Recent Issue` 共享 `index=2`、`field=issues`，靠 `regex` 区分
4. **sources 空路径**：`source_file` 已填但路径为 `""` 时，数据源读取应明确失败或跳过
5. **模块边界**：`core_store` 不 import `core_transform`
6. **区域检测**：内建于 `ExcelWriter`，不引用 `section_detector`
