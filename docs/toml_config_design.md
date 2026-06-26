# 场景1：

## 标准数据库结构工作表：
sheet1：
ID|name|gender|dob|
:----|:-----|:----|:-------
666|Lucifer|unknown|Null
250|狗蛋|f|2026-01-31
8129|Clark Kent|m|1938-06-01
1111|One|unknown|Null

sheet2：
ID|Report_date|issues
:----|:-----|:----------
666|Null|It created a "Creator" branching storyline, but I lack the ability to complete it.
8129|1978-03-01|recreate himself without changing his dob on records on 1978/02/29
250|2030-01-01|it must eat shit when it was born on 2026/01/31. Put here as a prediction

---

Input_sheet*:
ID#|Name|Recent Issue|Report Date|Discipline|Effective_Date|Sign
:----|:-----------|:--------------------------------|:-----|:-------------------------:|:---------|:-----
8129|Clark Kent|recreate himself without changing his dob on reco|1978/02/29|10 Years of Community Service|2026-01-31|One
250|狗蛋|it must eat shit. Put here as a prediction|2026/01/31|Brush teeth daily|2026-01-31|One
* Input_sheet和Print_sheet放在template文件夹内。

Print_sheet*: 
Name|Clark Kent
:------|:--------------
Report Date||1978-03-01
Discipline|10 Years of Community Service
Effective Date|2026-01-01
Name|狗蛋
Report Date|2030-01-01
Discipline|Brush teeth daily
Effective Date|2026-01-31
* 4 lines are a print area

## toml设定

配置文件命名：`templates/{template_id}/{template_id}.toml`

采用 **TOML 1.0 严格范式**：`tomlkit` 读写。文件中**不使用** `null`（TOML 标准无此类型）。

### 作用域

- TOML **只处理**顶层 `worksheet` 所指定的**那一张**工作表（如 `Input_sheet`）。
- **与 Print_sheet、其他工作表无关**；定位、扫描、校验均不在 `worksheet` 之外进行。
- **切换 template** 会换用另一套 xlsx + 另一份 TOML，属于 UI 层行为；本文档与 `core_toml` **只负责解析/校验当前 template 下的 TOML**，不描述切换流程。

### 未映射语义

| 层级 | 约定 |
|------|------|
| 内存 / API | Python `None` |
| 磁盘文件 | 所有键均需保留，未映射的可选键写入空字符串 `""`，不写 `null`，不省略键 |

`[[fields]]` 每一行：

- **必有键**：`Input_label`、`value_from_label`、`value_offset`、`index`、`id`
- **可选键**：`field`、`source_file`、`source_sheet`、`regex`
- 可选键的值为 `""` → 应用层视为 `None`
- `index = -1` 表示无文本框列索引（整数键保留）

`[[input_section]]`（**有且仅有一条**）：

- **必有键**：`input_area`、`move_to`、`offset`
- **语义**：
  - `input_area`：**第一组 instance 0 填写值**所在区域的登记（**不包含标签格**）；与标签如何被找到**无关联**
  - `move_to` / `offset`：第 2、3… 组填写值相对 instance 0 的整体平移；**不**平移标签格

`[[sources]]`：路径尚未配置时使用空字符串 `""` 填充；有路径后用 `tomlkit.string(..., literal=True)` 写单引号字面量。

### 定位模型

每次 **UI 加载 template 并激活校验** 时，须对当前 xlsx + 当前 TOML **重新扫描、重新印证**（防止 template 被改过）。`core_toml` **提供函数供 UI 调用**，不在模块内部写死「只校验一次」。

**标签与 `input_area` 无关联**：`Input_label` 靠全表扫描定位；`input_area` 只约束**找到标签之后**推算出的 instance 0 **填写值格**必须落在该区域内。

#### 两层职责

| 层级 | 键 | 作用对象 | 是否随第 k 组录入而变 |
|------|-----|----------|----------------------|
| 字段级 | `Input_label`、`value_from_label`、`value_offset` | 在 `worksheet` 上扫描得**标签格** → 推算 instance 0 **值格** | 否（单次校验内坐标固定） |
| `[[input_section]]` | `input_area` | 第一组 instance 0 **填写值**区域（校验值格是否落入） | 否 |
| `[[input_section]]` | `move_to`、`offset` | 第 k≥1 组**填写值**相对 instance 0 的整体平移 | 是（仅值格） |

#### 标准数据库范式（默认唯一自动处理布局）

默认生成与自动校验**仅**支持标准范式（指 `worksheet` 上的输入表，**不是** sheet1/sheet2 数据源）：

| 行 | 含义 |
|----|------|
| 第 1 行 | 字段名 / 标签文本（标准下即各 `Input_label` 所在行） |
| 第 2 行及以后 | 填写值（多行表示多条录入；instance 0 对应第一行值） |

- 非标准布局（标签不在第 1 行、值不在 `input_area` 等）**不**由默认逻辑处理，须**用户手工改 TOML** 后由 UI 再次调用校验。

#### 何时扫描、何时只生成

| 条件 | 行为 |
|------|------|
| template 已选，**TOML 不存在** | `TomlGenerator` 生成**默认 TOML**（不逐格扫描）；按标准范式：第 1 行写出 `[[fields]].Input_label` 骨架，`input_area` 登记第 2 行填写值区域 |
| template 已选，**TOML 已存在**，UI **激活校验** | 对 `worksheet` **逐字段**全表扫描各 `Input_label`，确定标签格与 instance 0 值格，并做相互印证 |

#### 标签格如何确定（斜向波面扫描）

在 **`worksheet` 指定表**上（仅此表），在 **100 行 × 100 列**内，按**左上 → 右下**的斜向波面顺序扫描（非行优先逐行扫描）。

扫描顺序：令 `s = row + col`（1-based），`s` 从小到大；同一 `s` 内 `row` 从小到大。即越靠近 `(1,1)` 的格越早被访问——例如 `(2,2)` 早于 `(1,100)`。

实现建议：

1. 用 `iter_rows` 一次性读取 100×100 区域到内存快照（避免逐格随机读）。
2. 在快照上按上述斜向顺序遍历；非空单元格文本（trim 后）作为候选标签。
3. 某文本**首次**出现的位置记为该标签的**标签格**；若后续斜向位置再次出现相同文本，记为**重复标签**。

对每一个 `[[fields]]` 的 `Input_label`（在校验阶段查索引，不再逐字段重扫）：

1. 在索引中查 `Input_label`：0 个 → `missing_labels`；≥2 个（重复）→ `duplicate_labels`；1 个 → 记为 `(label_row, label_col)`。
2. **标签格是否在 `input_area` 内不作要求**；`input_area` 不参与找标签。

#### 值格如何确定与 `input_area` 约束

在标签格 `(label_row, label_col)` 上：

```
(value_row, value_col) = offset_cell(label_row, label_col, value_from_label, value_offset)
```

`offset_cell` 含义：

| value_from_label | 效果 |
|------------------|------|
| `down` | `row += value_offset` |
| `up` | `row -= value_offset` |
| `right` | `col += value_offset` |
| `left` | `col -= value_offset` |

得到 **instance 0** 的填写值格后，**必须**满足：

```
(value_row, value_col) 落在 [[input_section]].input_area 所围矩形内
```

否则校验失败。即：**先找标签，再按 offset 找值；值必须在 `input_area` 内**。

#### `input_section` 只移动填写值、不移动标签

同一页有多份证书/多条录入时，`[[input_section]]` 只描述**填写值区域**的重复平移；**标签格坐标始终不变**。

设 instance 序号为 `k`（`k = 0` 为第一次填写）。在已记住的 instance 0 值格 `(v_row, v_col)` 上：

```
k = 0  →  使用记住的 instance 0 值格坐标
k ≥ 1  →  在 instance 0 值格上，应用 k 次 move_to/offset 平移：
           (v_row, v_col) = offset_cell(v_row, v_col, move_to, offset)  # 重复 k 次
```

**标签格**对任意 `k` 均为记住的 `(label_row, label_col)`，不参与 `move_to` / `offset`。

#### 演算示例

标准范式：`input_area = "A3:G3"`（第一组**填写值**行）；标签在上一行。

```toml
[[input_section]]
input_area = "A3:B3"
move_to = "right"
offset = 2

[[fields]]
Input_label = "Label1"
value_from_label = "down"
value_offset = 1

[[fields]]
Input_label = "Label2"
value_from_label = "down"
value_offset = 1
```

全表扫描后记住（1-based）：

| 对象 | 绝对坐标 | 说明 |
|------|----------|------|
| label1 | A2 | 扫描得 Label1 |
| label2 | B2 | 从头扫描得 Label2 |
| value1（k=0） | A3 | A2 向下 1 格 |
| value2（k=0） | B3 | B2 向下 1 格 |

`input_area = A3:B3` 与 instance 0 值格粗略一致。

**k = 1**（`move_to = "right"`, `offset = 2`）：

| 对象 | 绝对坐标 | 说明 |
|------|----------|------|
| label1、label2 | **仍为** A2、B2 | 标签不动 |
| value1 | C3 | instance 0 的 A3 向右 +2 列 |
| value2 | D3 | instance 0 的 B3 向右 +2 列 |

若 `move_to = "down"`、`offset = 1`，则 k=1 时值格行号 +1、列号不变。

#### 校验入口：`verify_toml()`

UI **只**调用一个函数 `verify_toml()`，由 `core_toml` 完成「打开 xlsx → 搜每个 `Input_label` → 算 instance 0 值格 → 判断是否在 `input_area` 内」，并把**有问题的标签**回报给 UI。UI 不关心扫描细节。

**入参（概念）**

| 参数 | 说明 |
|------|------|
| `template_path` | 当前 template 的 `.xlsx` 路径 |
| 已加载的 `GetTomlValues`（或 `template_id`） | 提供 `worksheet` / `input_section` / `fields`，二选一，以实现为准 |

**返回（概念）**

返回一份**报告**，至少能让 UI 知道：

- 整体是否通过（无任何问题即通过）。
- **哪些 `Input_label` 在 `worksheet` 上找不到**（label 不存在）。
- **哪些 `Input_label` 在工作表上出现多处**（duplicate_labels）。
- **哪些 `Input_label` 的 instance 0 值格不在 `input_area` 内**（input 越界）。

建议形如：

```
{
  "ok": bool,
  "missing_labels": [Input_label, ...],          # 在 worksheet 上搜不到的标签
  "duplicate_labels": [Input_label, ...],        # 工作表上多处匹配的标签
  "out_of_area_labels": [Input_label, ...],       # 值格不在 input_area 内的标签
  "located": { Input_label: {label_row, label_col, value_row, value_col}, ... }  # 通过项的坐标，可选
}
```

`located` 仅内存返回，供 UI 初始化输入框与后续填表使用；**不写回 TOML**。k≥1 的值格由填表逻辑在 instance 0 坐标上再应用 `move_to`/`offset`，不在本次校验逐 instance 扫描。

**执行步骤（仅 `worksheet` 指定表）**

1. 打开 `worksheet` 指定的工作表；不存在 → 整体失败。
2. 把 `[[input_section]].input_area` 解析为矩形 `(min_row, min_col, max_row, max_col)`。
3. 对 100×100 区域做**一次**斜向波面扫描，建立标签文本 → 首见坐标索引，并收集重复文本。
4. 对每一条 `[[fields]]` 查索引：
   - 找不到 `Input_label` → 计入 `missing_labels`。
   - `Input_label` 在表中出现多处 → 计入 `duplicate_labels`。
   - 找到唯一标签格后，`offset_cell(...)` 得 instance 0 值格；若不在 `input_area` 矩形内 → 计入 `out_of_area_labels`。
5. `missing_labels`、`duplicate_labels`、`out_of_area_labels` 均为空 → `ok = True`。

**不检查**：标签格是否在 `input_area` 内；`field` / `source_*` / `regex` 是否已映射；Print_sheet 及其他工作表。`verify_toml()` **只报告**问题，**不**静默改 TOML、不改 xlsx、不自动修正坐标。

> 文本层面的 TOML 语法/字段骨架解析由 Load 解析阶段负责（不打开 xlsx）；`verify_toml()` 专注 xlsx 与坐标印证。

### 配置示例

```# toml
determiner = "\t"           # 纯文本粘贴的分隔符；支持 \t(tab) 等转义字符和其他单字符分隔符
worksheet = "Input_sheet"   # 模板中需要输入数据的表格

# 外部数据源；路径可为本地文件、网页链接或 Google Sheet
# 首次生成时写入空值 ""，真实路径由专用配置页写入后再落盘
[[sources]]
source1 = ""
source2 = ""

# input_section：仅登记第一组填写值区域及后续组的平移；不包含标签。
[[input_section]]
input_area = "A2:G2"        # 第一组填写值所在行（粗略登记，不含标签）
move_to = "down"              # 第 2、3… 组填写值平移方向：up / down / left / right
offset = 1                    # 平移步长。本例 k=1 时填写值行由第 2 行移至第 3 行；标签行不动

# 字段映射：每个输入项一个 [[fields]] 表项
[[fields]]
Input_label = "ID#"         # 全表从头扫描，首个完全匹配格为标签格（记住坐标）
value_from_label = "down"   # 支持up/down/left/right。这里的down表示标签在上，数值在“下边”
value_offset = 1            # 说明找到标签之后，往下“1”格就是填写内容的地方。
field = "ID"                # 数据源的所在列
source_file = "source1"     # 数据源的引用
source_sheet = "sheet1"     # 打开数据源之后，寻找指定的这个表格
index = 0                   # 作为纯文本粘贴被分隔符拆分后的索引值；index base 0
regex = ""                  # 获得该项目后，获取数据的正则表达式。一般用于截取某一段内容。
id = true                   # 如果为真，这个内容将从数据源（符合数据库范式）所属的数据，也同时是本地数据的索引id。


[[fields]]
Input_label = "Name"
value_from_label = "down"  
value_offset = 1  
field = "name"
source_file = "source1"
source_sheet = "sheet1"
index = 1
regex = ""
id = false

[[fields]]
Input_label = "Recent Issue"
value_from_label = "down"  
value_offset = 1   
field = "issues"
source_file = "source2"
source_sheet = "sheet2"
index = 2
regex = ""
id = false

[[fields]]
Input_label = "Report Date"
value_from_label = "down"  
value_offset = 1    
field = "issues"
source_file = "source2"
source_sheet = "sheet2"
index = 2
regex = '\d+/\d+/\d+'
id = false

[[fields]]
Input_label = "Discipline"
value_from_label = "down"  
value_offset = 1      
field = ""
source_file = ""
source_sheet = ""
index = -1            # 无文本框列索引；无 field / source_* / regex
regex = ""
id = false

[[fields]]
Input_label = "Effective_Date"
value_from_label = "down"  
value_offset = 1      
field = ""
source_file = ""
source_sheet = ""
index = -1
regex = ""
id = false

[[fields]]
Input_label = "Sign"
value_from_label = "down"  
value_offset = 1 
field = ""
source_file = ""
source_sheet = ""
index = -1
regex = ""
id = false
```

### 格式说明

1. **字段名含空格或 `#`**：列名放在 `[[fields]].Input_label`。
2. **Windows 路径**：单引号字面量，反斜杠原样保留，例如 `'c:\temp\cache\执法堂业绩.xlsx'`。
3. **正则表达式**：含反斜杠时用字面量，例如 `'\d+/\d+/\d+'`。
4. **已映射但无 regex**：写入空字符串 `regex = ""`。
5. **默认配置**：包含 `determiner`、`worksheet`（若有）、`[[input_section]]`（**一条**）、`[[sources]]` 与 `[[fields]]` 骨架；可选字符串键以 `""` 占位。
6. **`index`**：纯文本粘贴时按 `determiner` 拆分后的列索引（base 0）；与 Excel 列号、与 `input_section` 平移无关。
7. **`input_area`**：只框 instance 0 **填写值**；**不**用于找标签。找标签后推算出的值格**必须**落在此区域内。
8. **标签与 `input_area`**：二者独立——扫描只认 `Input_label`；`input_area` 只校验值格是否入框。

### 实现依赖

```
tomlkit>=0.13
```

`tomlkit` 用于读写 TOML。



### `core_toml` 与 UI 的分工

| 职责 | 模块 | 说明 |
|------|------|------|
| 生成默认 TOML | `TomlGenerator` | TOML 不存在时；标准范式；**不**做全表扫描 |
| 读写 TOML 文本 | `GetTomlValues` | Load / Save / ToDict |
| **激活校验**（UI 调用） | `verify_toml()` | UI 只调这一个；斜向扫描 worksheet，报告找不到 / 重复 / 值格越界的 `Input_label` |
| 坐标解析 | `offset_cell`、`_scan_worksheet_labels_diagonal` 等 | 校验与填表共用；扫描上限 **100×100** |

**不在 `core_toml` 内写死**「仅首次 Load 校验」；是否校验、何时校验由 **UI 在加载 template 时决定**。

### 职责划分

- **生成器（`TomlGenerator`）**：TOML 不存在时，按标准范式生成骨架（第 1 行 → `[[fields]].Input_label`，`input_area` → 第 2 行值区）；默认 `value_from_label = "down"`、`value_offset = 1`；**不**扫描全表。
- **持久化层（`GetTomlValues`）**：Load / Save / ToDict；**`verify_toml()`**——回报 `missing_labels`、`duplicate_labels`、`out_of_area_labels`。
- **定位**：仅在 `worksheet` 上斜向波面扫描标签；值格由 offset 推算且**必须**在 `input_area` 内；`move_to`/`offset` 处理 k≥1 值格平移。
- **数据源路径**：由专用 UI 写入，不由生成器提供。
