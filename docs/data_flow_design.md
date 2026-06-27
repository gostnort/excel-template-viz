# 数据表格转换核心（Data Sheet Core）实施计划

## 概述

**本计划交付两个 Python 模块**（各一个 `.py` 文件），按职责分层：Excel 转换与持久化/UI 供给分离。四个类、无编排类；调用方（Gradio 或命令行）串联两模块完成流程。

**设计依据**：
- 架构蓝图：`docs/data_sheet_core_design.md`
- **字段语义、标签/值格定位、`input_area` 印证**：`docs/toml_config_design.md`（**权威**；含 `value_from_label` / `value_offset` / `[[input_section]]` / `verify_toml`）
- TOML 解析与校验：`app/services/core_toml.py`（`GetTomlValues`、`TomlGenerator`、`verify_toml`）
- 模板路径约定：`app/services/core_registry.py`（`TEMPLATES_DIR`）
- **落库 JSON 键仅为 `Input_label`**；`field` 不落库（见下文落库策略）

**为何拆成两模块**：

| 分层 | 模块 | 关注点 |
|------|------|--------|
| 存储 + UI 供给 | `core_store.py` | UI 纯字符串入 DB；`determiner` 拆分；Gradio 读 DB |
| Excel 转换 | `core_transform.py` | 外部数据源读取；`worksheet` 上按定位写回值格 |
| TOML 与坐标校验 | `core_toml.py`（非本计划交付范围，但为上下游契约） | Load/Save；`verify_toml`；`offset_cell` |

- **UI 只依赖 store 层**：textbox 纯字符串直接落库；`UiProvider` 从 DB 供给 labels + data。
- **转换层不依赖 store 层**：`Template2DB` 按 `source_file` / `source_sheet` / `Input_label` 读外部表；产出标准 `dict` 由调用方写入 DB。
- **依赖方向单一**：`core_transform` 不 import `core_store`。

**关键原则**：
- 本计划**交付** `core_store.py` 与 `core_transform.py`；不另建 `tests/`
- 仅 `import` 其他 `core_*.py` 及标准库；`core_transform` 另用 `openpyxl`
- 不引用 `section_detector`、`excel_parser`、`excel_print`、`paste_parse_config` 等既有服务
- 字段语义与 **worksheet 上标签→值格→`input_area`** 印证，严格遵循 `toml_config_design.md`
- **`index`**：仅用于 UI textbox 按 `determiner` 拆分后的段序；**不是** Excel 列号，**不参与** `input_section` 的 k 组平移
- 四个类之外不新增类；不设编排类
- TOML **只处理**顶层 `worksheet` 指定的那一张表；**与 Print_sheet 及其他工作表无关**（打印区域读取若存在，不纳入 TOML 定位模型）

## 落库策略：`insert_or_update` 以 TOML 覆盖 JSON

**核心**：每次写入时，`SecureSQLite` **不读取、不合并**库内已有 `data`。以**当前 TOML** 的全体 `[[fields]].Input_label` 为**唯一列定义**，生成本次完整 JSON 后**整份覆盖** `data` 列。

与路径 A/B/Excel **无关**——路径只决定调用方传入的 `incoming` 里有哪些值；**store 只认 `cfg` + `incoming`**。

```
insert_or_update(incoming, cfg):
  1. payload = {}
  2. 对 cfg.field_rules 中每一个 Input_label：
       若 incoming 含该键且值有效 → payload[Input_label] = 值
       否则 → payload[Input_label] = ""（或 null，实现统一一种）
  3. records.id ← resolve_db_id(cfg) 所指 Input_label 在 incoming 中的有效值；无则自动生成
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

依据 `docs/toml_config_design.md`。下列键分工与「路径 A/B」**独立**——路径只产生 `incoming` 或读写 xlsx；**标签如何落在表上**由 `[[fields]]` + `[[input_section]]` + `verify_toml` 定义。

### `[[fields]]` 共有键（每条必有）

| 键 | 作用 |
|----|------|
| `Input_label` | 在 `worksheet` 上**全表扫描**（每字段从 (1,1) 重扫）找标签格；**落库 JSON 键名**；`get_labels()` 用 |
| `value_from_label` | `up` / `down` / `left` / `right`：从标签格推算 **instance 0 填写值格**的方向 |
| `value_offset` | 与 `value_from_label` 配合的步长（格数） |
| `index` | **仅路径 A**：`determiner` 拆分后的段序（0-based）；`-1` 表示不参与 textbox 拆分 |
| `id` | `true` 时：参与**外部数据源**行查找（汇总为 `id_lookup_keys`）；**本地** `records.id` 由顶层 **`db_id`** 指定，见下文 |

可选键：`field`、`source_file`、`source_sheet`、`regex`（空串 `""` 视为未配置）。`field` **仅读外部数据源列**，**不写入** `data` JSON。

### 标签格与值格（及与 `input_area` 的相互印证）

**标签与 `input_area` 无关联**：找标签**只认** `Input_label` 文本；`input_area` **不参与**找标签。

1. 在 `worksheet` 指定表上，对每个 `Input_label` 扫描得标签格 `(label_row, label_col)`（trim 后完全相等；0 个或多个匹配 → `verify_toml` 失败）。
2. 值格：`(value_row, value_col) = offset_cell(label_row, label_col, value_from_label, value_offset)`。
3. **instance 0** 的值格**必须**落在 `[[input_section]].input_area` 矩形内，否则记入 `out_of_area_labels`。
4. **标签格坐标固定**；`move_to` / `offset` **只平移**第 k≥1 组的**填写值格**，不平移标签。

第 k 组值格（k≥0）：在记住的 instance 0 值格上，对 k≥1 重复应用 `input_section.move_to` / `offset`。

UI 加载 template 并激活校验时调用 **`core_toml.verify_toml(template_path, cfg)`**（唯一校验入口），返回至少：

- `ok`、`missing_labels`、`out_of_area_labels`、`duplicate_id_sheets`、`db_id` / `db_id_required` / `invalid_db_id`
- `located`：`{ Input_label: {label_row, label_col, value_row, value_col}, ... }`（内存用，不写回 TOML）

`ExcelWriter` 读/写 **填写值格**时应与 `located` + k 平移一致（实现逐步对齐；**不再**以「`input_area` 首行作表头匹配列」为主模型）。

### `[[input_section]]`（有且仅一条）

| 键 | 作用 |
|----|------|
| `input_area` | **instance 0 填写值**所在区域（**不含标签格**） |
| `move_to` | 第 2、3… 组填写值相对 instance 0 的平移方向 |
| `offset` | 平移步长 |

### 路径 A：UI textbox → DB（`core_store` 主责）

Gradio 提供一个 **textbox**，用户输入**一整段纯字符串**，原样或解析后写入 DB。

| 键 | 路径 A 中的用途 |
|----|----------------|
| `determiner` | 拆分 textbox 纯字符串 |
| `index` | 拆分结果中的段序；`-1` 不参与拆分 |
| `Input_label` | 段映射目标键名；落库 JSON 键 |
| `id` | 见 `[[fields]]` 共有键 |

- 示例：`determiner = "\t"`，`"8129\tClark Kent\t..."` → `index=0` → `ID#`，`index=1` → `Name`
- `value_from_label` / `value_offset`：**不参与** textbox 拆分与 DB JSON；仅用于 xlsx 值格定位

`core_store`：`split_by_determiner` → `record_from_textbox` → `incoming`（局部 `dict[Input_label]`）→ `insert_or_update(incoming, cfg)`

### 路径 B：外部数据源表 → 标准记录（`Template2DB` 主责）

从 `[[sources]]` 配置的文件 / Google Sheet 读取标准数据库结构工作表。

| 键 | 路径 B 中的用途 |
|----|----------------|
| `source_file` / `source_sheet` | 解析并打开外部数据源表 |
| `field` | 在**数据源表**中匹配列（如 `ID`、`name`）；不落库 |
| `Input_label` | 产出 `incoming` 的键名（与模板列同名） |
| `regex` | 读源后的提取；结果写入对应 `Input_label` |
| `id` | 见 `[[fields]]` 共有键；外部查行用 `id_lookup_keys`（全局 OR） |

- `source_*` 为空：该字段不走数据源，仅 UI / xlsx 填写 / 落库
- 同 `field` + 同 `index` 可对应不同 `Input_label`（如 `Recent Issue` 与 `Report Date`）；落库为两个 `Input_label` 键
- 查行键：对所有 `id=true` 字段，用 **`field`（已映射时）否则 `Input_label`**，汇总为 `id_lookup_keys`；**任意一个键匹配即命中该行**（与 `toml_config_design.md` 一致）

### 其他顶层键

| 键 | 使用方 | 作用 |
|----|--------|------|
| `worksheet` | `core_toml` / `core_transform` | **唯一**参与扫描与读写的模板表名 |
| `input_section` | `core_toml` / `core_transform` | 单条；instance 0 值区 + 多组值格平移 |
| `sources` | `Template2DB` | `source_file` 别名 → 路径 |
| `determiner` | `core_store` | textbox 拆分 |
| `db_id` | `core_toml` / `core_store` | 本地 `records.id` 所对应的 **`Input_label`**（不是 `field` 列名）；解析见 `resolve_db_id(cfg)` |

#### `db_id` 与 `id`（本地主键 vs 外部查行）

依据 `docs/toml_config_design.md`：

| 情况 | `db_id`（生效值） |
|------|-------------------|
| 无 `id=true` | `null`；`records.id` 由数据库自动生成 |
| 仅一条 `id=true` | 自动为该条的 `Input_label`；若 TOML 写了 `db_id` 且不一致 → `verify_toml` 报 `invalid_db_id` |
| 两条及以上 `id=true` | **必须**写顶层 `db_id = "<某个 id 字段的 Input_label>"`；未写 → `db_id_required` |

- **`core_store`**：`insert_or_update` 通过 `resolve_db_id(cfg)` 取主键列名，从 `incoming[db_id]` 推导 `records.id`。
- **`core_toml`**：`verify_toml` 回报 `db_id` / `db_id_required` / `invalid_db_id` / `id_labels` / `id_lookup_keys` 等；`id` 规则不通过时 `ok=False`。

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
| `Template2DB` | 外部数据源 → `incoming`（`dict[Input_label]`，可缺键） |
| `ExcelWriter` | 按 `verify_toml` 的 `located` + k 组平移读写 **值格**；另存；`get_print_areas`（Print_sheet，非 TOML 定位范围） |

不 import `core_store`。

**数据源读取**（`Template2DB`）：
1. `resolve_source_path(cfg.sources, rule.source_file)` → 文件路径或 Sheet 句柄（本模块仅本地 xlsx；远程 URL 由上层注入路径后调用）
2. 打开 `rule.source_sheet`，按 `id_lookup_keys`（`id=true` 字段的 field/Input_label，全局 OR）定位行
3. 读外部表时用 `field` / `Input_label` 匹配列 → `apply_regex` → 写入 `record[rule.Input_label]`（不写 `field` 名）

### 数据流

```
GetTomlValues.Load ──► verify_toml(xlsx, cfg) ──► located / 问题列表
        │                                              │
        ├── UI textbox ──► core_store ──► SecureSQLite ◄── Template2DB ── sources
        │         determiner+index              ▲              incoming
        │                                       │
        └──────── ExcelWriter.write_back ◄──────┘（值格坐标 + k）
                    UiProvider.get_* ◄── DB
```

典型调用（伪代码）：

```python
cfg = GetTomlValues.Load(template_id)
report = verify_toml(template_path, cfg)  # UI 激活校验；ok 后再填表/写库
located = report.get("located", {})

db = SecureSQLite(default_db_path(template_id))
ui = UiProvider(cfg, db)

incoming = ui.record_from_textbox(user_raw_string)
# incoming = Template2DB(cfg).fetch_row_by_id(source_id)

db.insert_or_update(incoming, cfg)

writer = ExcelWriter(cfg, located=located)  # 目标 API：按值格写回；k 由 input_section 推导
writer.write_back(template_path, output_path, db.query_by_id(...), instance_k=0)

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
- 生效的 **`db_id`**（`Input_label`）由 `core_toml.resolve_db_id(cfg)` 解析：单条 `id=true` 时自动推断；多条 `id=true` 时取顶层 `db_id`；无 `id=true` 时为 `null`。
- 若 `resolve_db_id(cfg)` 非空，且本次 `incoming` 中该 **`Input_label` 有有效值**，则 `records.id` 取该值（规范化后）。
- 若 `resolve_db_id(cfg)` 为 `null`，或本次未提供有效业务 ID，则 `records.id` 由数据库**自动生成**（如 `uuid.uuid4().int >> 64`）。
- `db_id` 所指的 `Input_label`（如 `ID#`）**同样写入** `data` JSON，与 `records.id` 在有业务 ID 时数值一致。

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

`Template2DB` / `record_from_textbox` 产出 **`incoming`（可缺键）**；持久化后的 `data` JSON **键全、值按 incoming 填或空**。`write_back` 向 **`located` 值格（及 k 平移）** 写入 `incoming` 或 `query_by_id` 中的各 `Input_label` 值。

## Excel 读写（`core_transform.py`，仅 openpyxl）

| 操作 | 要点 |
|------|------|
| 定位前提 | 调用方已 `verify_toml` 通过；使用 `located[Input_label]` 的 instance 0 值格坐标 |
| 读填写值 | 对 instance k，在 instance 0 值格上应用 k 次 `input_section.move_to`/`offset` 后读单元格 |
| 写回 | 向同上坐标写入；**不用 `index` 当列号**；**不用**「区域内表头行匹配 `Input_label`」作主路径 |
| 打印区域 | `ws.print_area`（多在 Print_sheet；**不在** TOML `worksheet` 定位模型内） |

`ExcelWriter` 应对齐：`offset_cell` 语义与 `core_toml` 共用；k 组值格平移与 `input_section` 一致。过渡实现若仍含 `detect_areas` / `read_area_rows`（旧 `sections` 表头模型），视为**待废弃**，以本文与 `toml_config_design.md` 为准。

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

1. 消费 `verify_toml` 的 `located`（或由调用方传入等价坐标表）
2. 按 `input_section` 计算 instance k 值格并读/写
3. `write_back` / `get_print_areas`（后者仅读元数据，不参与定位）

**验收**：标准范式下 instance 0 值格落在 `input_area` 内；k=1 值格仅平移、标签坐标不变；与 `toml_config_design.md` 演算示例一致。

### Phase 4b：`core_toml` — 与 UI 的校验契约（已实现，本计划依赖）

1. `verify_toml(template_path, cfg)` → `missing_labels` / `out_of_area_labels` / `located`
2. TOML 不存在时 `TomlGenerator` 生成标准范式骨架（不全表扫描）

**验收**：故意错 `input_area` 或删标签时 `ok=False` 且问题列表非空。

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

含 textbox 拆分、`Template2DB` 数据源读取、`verify_toml` 报告摘要各一例。

## 成功标准

### 功能
- `determiner` / `index`：仅 UI textbox 拆分；与 Excel 列、k 平移无关
- `value_from_label` / `value_offset`：仅标签→值格定位；不落库
- `input_section`：单条；只约束/平移**填写值**，不找标签
- `source_file` / `source_sheet` / `field`：仅外部数据源读列
- `verify_toml`：坐标通过且 **id/db_id 规则**通过（无 `duplicate_id_sheets`、`db_id_required`、`invalid_db_id`），方可进入填表/写库主流程
- 两模块（store/transform）职责与上表一致；校验在 `core_toml`

### 验证
- `__main__` 打印三段数据且前后一致
- `data` JSON 键 = 当前 TOML 全部 `Input_label`（不含 `field` 名）
- `records.id` 与 `resolve_db_id(cfg)` 所指 `Input_label` 在有业务 ID 时一致
- 同 `records.id` 再次 `insert_or_update` 且 incoming 缺键时，缺键在 `data` 中为**空**
- `verify_toml` 对样本 template 通过，`located` 含全部 `Input_label`

## 风险与注意事项

1. **index**：禁止当作 Excel 列索引；禁止用于 k 组平移；写回靠 **值格坐标**，不靠 index
2. **index = -1**：不参与 textbox；落库仍在 TOML 骨架中，值仅来自本次 incoming
3. **标签 vs input_area**：二者独立——先扫标签，再验值格是否入框；勿用 `input_area` 当表头行
4. **同 index 多 rule**（textbox）：靠多段或同一 `incoming` 键区分；读源时靠 `regex` 区分 `Input_label`
5. **sources 空路径**：`source_file` 已填但路径为 `""` 时，数据源读取应明确失败或跳过
6. **模块边界**：`core_store` 不 import `core_transform`；`core_transform` 不 import `core_store`
7. **TOML 覆盖**：`insert_or_update` 不得读旧 `data` 做 merge
8. **实现落差**：当前 `ExcelWriter` 可能仍使用旧 `cfg.sections` / 表头模型；对齐 `input_section` + `located` 为后续改造项，以本文为准
