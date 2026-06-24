# 数据表格转换核心（Data Sheet Core）实施计划

## 概述

**本计划交付两个 Python 模块**（各一个 `.py` 文件），按职责分层：Excel 转换与持久化/UI 供给分离。四个类、无编排类；调用方（Gradio 或命令行）串联两模块完成流程。

**设计依据**：
- 架构蓝图：`docs/data_sheet_core_design.md`
- **字段语义与场景**：`docs/toml_config_design.md`（determiner / index / source_* / Input_label 分工；**落库 JSON 键仅为 `Input_label`，`field` 不落库**）
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

## 落库策略：`insert_or_update` 以 TOML 覆盖 JSON

**核心**：每次写入时，`SecureSQLite` **不读取、不合并**库内已有 `data`。以**当前 TOML** 的全体 `[[fields]].Input_label` 为**唯一列定义**，生成本次完整 JSON 后**整份覆盖** `data` 列。

与路径 A/B/Excel **无关**——路径只决定调用方传入的 `incoming` 里有哪些值；**store 只认 `cfg` + `incoming`**。

```
insert_or_update(incoming, cfg):
  1. payload = {}
  2. 对 cfg.field_rules 中每一个 Input_label：
       若 incoming 含该键且值有效 → payload[Input_label] = 值
       否则 → payload[Input_label] = ""（或 null，实现统一一种）
  3. records.id ← id=true 的 Input_label 在 incoming 中的有效值；无则自动生成
  4. INSERT 或 UPDATE：data = json.dumps(payload)   # 不读旧 data
```

| 项 | 说明 |
|----|------|
| JSON 键集合 | **始终等于当前 TOML 的全部 `Input_label`**（含 `index=-1`） |
| 键的值 | **仅来自本次 `incoming`**；TOML 有而 incoming 无 → 空 |
| 旧 `data` | **不参与**；禁止 merge / `dict.update(旧 JSON)` |
| TOML 增删列 | 下次写入 JSON **随最新 TOML 变**；旧 TOML 多出的键自然消失 |
| `field` 名 | **永不进入** `payload` |

读取：`query_by_id` / `get_data()` 返回 **最后一次 TOML 覆盖写入** 的 `payload`（外加 SQLite 列 `records.id`）。

## TOML 字段语义（核心契约）

依据 `docs/toml_config_design.md`，两类入参路径：

### 路径 A：UI textbox → DB（`core_store` 主责）

Gradio 提供一个 **textbox**，用户输入**一整段纯字符串**，原样或解析后写入 DB。

| 键 | 作用 |
|----|------|
| `determiner` | 拆分上述纯字符串的分隔符（如 `"\t"` tab） |
| `index` | 该 `[[fields]]` 对应字段在拆分结果中的**顺序位置**（0-based） |
| `Input_label` | Excel 模板列标题 / Gradio 表单列名；**写入 `data` JSON 的键名**（`get_labels()` 用） |
| `field` | **仅路径 B**：在外部数据源表中匹配列名；**不写入** `data` JSON |
| `id` | `true` 时：该 `Input_label` 的值用于设定 `records.id`（有有效值时）；**同时**作为 `Input_label` 写入 JSON |

- `index = -1`：该列**不参与** textbox 拆分；落库时仍出现在 JSON 中（TOML 骨架），值来自本次 `incoming` 或为空
- 示例：`determiner = "\t"`，用户输入 `"8129\tClark Kent\t..."`，`index = 0` → `ID#`，`index = 1` → `Name`

`core_store` 须提供：
- 接收 UI 纯字符串直接持久化
- 按 `determiner` + 各 rule 的 `index` 拆分为 `{Input_label: segment}`（不写 `field` 名）

### 路径 B：外部数据源表 → 标准记录（`Template2DB` 主责）

从 `[[sources]]` 配置的文件 / Google Sheet 读取标准数据库结构工作表。

| 键 | 作用 |
|----|------|
| `source_file` | 指向 `[[sources]]` 中的键名（如 `source1`），解析为实际路径或 Sheet URL |
| `source_sheet` | 数据源工作表名（如 `sheet1`） |
| `Input_label` | 在**数据源表**中定位列（列标题匹配）；模板列名；**写入 `data` JSON 的键名** |
| `field` | **仅读外部源表**时匹配列（如 `ID`、`name`、`issues`）；**不写入** `data` JSON |
| `regex` | 对读到的单元格值再做提取（如 `Report Date` 从 `issues` 列用 `'\d+/\d+/\d+'` 抽日期）；结果写入对应 `Input_label` |
| `id` | `true` 表示该 `Input_label` 为业务 ID：用于按 ID 查行，并在有有效值时设定 `records.id`；**同时**写入 JSON |

- `source_file` / `source_sheet` 为 `""` 时：不走数据源，仅 UI 或 Input_sheet 路径
- 同一 `field` + 同一 `index` 可对应不同 `Input_label`（如 `Recent Issue` 与 `Report Date` 均 `field = "issues"`，`index = 2`，后者加 `regex`）；落库时各写各自 `Input_label` 键，**不在 JSON 中出现 `issues` 键**

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
| `SecureSQLite` | `insert_or_update(incoming, cfg)`：TOML 覆盖 JSON；`query_by_id` / `query_all` |
| `UiProvider` | `get_labels()` ← `Input_label` 列表；`get_data()` ← DB |

模块级：`default_db_path(template_id)`

**UI → DB**：
1. 用户 textbox 提交纯字符串
2. `split_by_determiner(raw, cfg.determiner)` → `list[str]`
3. `record_from_textbox` → `incoming`：仅含 `index >= 0` 的 `Input_label` 键值（局部 dict）
4. `insert_or_update(incoming, cfg)`：按**当前 TOML 全部 `Input_label`** 生成完整 `payload` 并覆盖 `data`（见上文落库策略）

**DB → UI**：`get_data()` 返回 `records.id` 与解析后的 `data` JSON（键集合 = 当前 TOML 的 `Input_label`）；Gradio 按 `get_labels()` 展示。

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
| `Template2DB` | 按 `source_file` + `source_sheet` 读外部表行；`field` 仅用于读源列；产出 `dict[Input_label]` |
| `ExcelWriter` | Input_sheet 写回（按 `Input_label` 对表头列）；另存；打印区域；区域检测 |

不 import `core_store`。

**数据源读取**（`Template2DB`）：
1. `resolve_source_path(cfg.sources, rule.source_file)` → 文件路径或 Sheet 句柄（本模块仅本地 xlsx；远程 URL 由上层注入路径后调用）
2. 打开 `rule.source_sheet`，按 `id=true` 的 rule 所对应源表列定位行
3. 读外部表时用 `field` / `Input_label` 匹配列 → `apply_regex` → 写入 `record[rule.Input_label]`（不写 `field` 名）

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

# 路径 A 或 B 仅产生 incoming（可为局部 Input_label 子集）
incoming = ui.record_from_textbox(user_raw_string)
# incoming = Template2DB(cfg).fetch_row_by_id(source_id)

db.insert_or_update(incoming, cfg)  # TOML 骨架 + incoming 填值 → 覆盖 data

writer = ExcelWriter(cfg)
writer.write_back(template_path, output_path, db.query_by_id(...))

labels = ui.get_labels()
rows = ui.get_data()
```
## 标准记录与存储

物理表：

```sql
records (id INTEGER PRIMARY KEY, data TEXT NOT NULL)
```

- 文件路径：`temp/{template_id}.{Letter}{Year}`（见上文 db 命名规则）
- 禁止后缀：`.db`、`.sqlite`、`.sql`

### `records.id`（行主键）

- **查询与 UPSERT 以 SQLite 列 `records.id` 为准**（不依赖解析 `data` 内的键）。
- 若当前 TOML 中存在 `id=true` 的 `[[fields]]`，且本次写入中该 **`Input_label` 有有效值**，则 `records.id` 取该值（规范化后）。
- 若**没有任何** `Input_label` 被标记为 `id=true`，或本次未提供有效业务 ID，则 `records.id` 由数据库**自动生成**（如 `uuid.uuid4().int >> 64`）。
- 标记为 `id=true` 的 `Input_label`（如 `ID#`）**同样写入** `data` JSON，与 `records.id` 在有业务 ID 时数值一致。

### `data` JSON（业务列）

落库后的 `data` **永远包含当前 TOML 的全部 `Input_label` 键**；值来自**该次** `insert_or_update` 的 `incoming`，未提供的键为空。

示例（`records.id = 250`，TOML 含下列七列）：

```json
{
  "ID#": 250,
  "Name": "狗蛋",
  "Recent Issue": "it must eat shit when it was born on 2026/01/31. Put here as a prediction",
  "Report Date": "2026/01/31",
  "Discipline": "Brush teeth daily",
  "Effective_Date": "2026-01-31",
  "Sign": "One"
}
```

若本次 `incoming` 仅含路径 A 拆出的三列，则落库结果为同结构七键，其余四键为 `""`（**不会**保留该行上一次写入的非空值）。

| 规则 | 说明 |
|------|------|
| 键集合 | **当前 TOML** 的每一个 `Input_label`；不含 `field` 名 |
| 写入方式 | **TOML 覆盖**：按 TOML 生成完整 `payload` 后替换 `data`；**禁止**与旧 JSON merge |
| `incoming` | 调用方传入的局部 `dict[Input_label]`；store 不负责区分来自路径 A 或 B |
| TOML 变动 | 列定义以**最新 TOML** 为准；`records.id` 为行稳定标识 |

`Template2DB` / `record_from_textbox` 产出 **`incoming`（可缺键）**；持久化后的 `data` JSON **键全、值按 incoming 填或空**。`write_back` 使用已落库的完整行或同等结构的 dict。

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
2. `record_from_textbox(raw) -> incoming`：局部 `dict[Input_label]`
3. `insert_or_update(incoming, cfg)`：TOML 骨架覆盖 `data`；禁止读/合并旧 JSON

**验收**：`"\t"` 拆分键名为 `Input_label`；`insert_or_update` 后 `data` 键集合等于 TOML 全部 `Input_label`；incoming 未带的键为空。

### Phase 3：`core_transform` — Template2DB 数据源路径

1. `resolve_source_path(sources, source_file_key)`
2. `fetch_row_by_id(id_value)`：读 `source_sheet`，按 `Input_label` 取列，`regex` 处理
3. 产出 `incoming`：`dict[Input_label]`（不含 `field` 名；可缺键）

**验收**：与 `toml_config_design.md` 场景1 一致；经 `insert_or_update` 后 `Recent Issue` 与 `Report Date` 同在 TOML 骨架 JSON 中。

### Phase 4：`core_transform` — ExcelWriter

区域检测、按 `Input_label` 写回 Input_sheet、`get_print_areas`。

### Phase 5：`core_store` — UiProvider

`get_labels()` → 全部 `Input_label`；`get_data()` → `records.id` + 解析 `data`（各 `Input_label` 值）。

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
- `data` JSON 键 = 当前 TOML 全部 `Input_label`（不含 `field` 名）
- `records.id` 与 `id=true` 的 `Input_label` 在有业务 ID 时一致
- 同 `records.id` 再次 `insert_or_update` 且 incoming 缺键时，缺键在 `data` 中为**空**（非旧值残留）

## 风险与注意事项

1. **index 语义**：禁止当作 Excel 列索引；写回靠 `Input_label` 对表头
2. **index = -1**：不参与 textbox 拆分；落库仍在 TOML 骨架中，值仅来自本次 incoming
3. **同 index 多 rule**：读源时靠 `regex` 区分；落库 JSON 中仍为两个 `Input_label` 键
4. **sources 空路径**：`source_file` 已填但路径为 `""` 时，数据源读取应明确失败或跳过
5. **模块边界**：`core_store` 不 import `core_transform`
6. **区域检测**：内建于 `ExcelWriter`，不引用 `section_detector`
7. **TOML 覆盖**：`insert_or_update` 不得读旧 `data` 做 merge；键集合以**当前 TOML** 为准，与 incoming 来自哪条路径无关
