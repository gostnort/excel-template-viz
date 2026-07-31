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
ID#|ID#|Name|Recent Issue|Report Date|Discipline|Effective_Date|Name|Recent Issue|Report Date|Discipline|Effective_Date|Sign
:----|:----|:-----------|:--------------------------------|:-----|:-------------------------:|:---------|:-----------|:--------------------------------|:-----|:-------------------------:|:---------|:-----
8129|666|Clark Kent|recreate himself without changing his dob on reco|1978/02/29|10 Years of Community Service|2026-01-31|Lucifer|Smash my face|unknown|Smash by itself twice|forever|One
250||狗蛋|it must eat shit. Put here as a prediction|2026/01/31|Brush teeth daily|2026-01-31||||||One
* Input_sheet和Print_sheet放在template文件夹内。
* 本表示意：A/C–G/M 为 instance 0；B 与 H–L 为同行右侧下一组；第 3 行为向下下一组。对应下方 `input_area` 并集与 `move_to = ["right","down"]`。

Print_sheet*: 
Name|Clark Kent
:------|:--------------
Report Date|1978-03-01
Discipline|10 Years of Community Service
Effective Date|2026-01-01
Name|Lucifer
Report Date|unknown
Discipline|Smash by itself twice
Effective Date|forever
Name|狗蛋
Report Date|2030-01-01
Discipline|Brush teeth daily
Effective Date|2026-01-31
* 每 4 行为一个 print area；本例 3 人 → 3 个打印区（Clark Kent / Lucifer / 狗蛋），与 Input_sheet 上「同行右侧一组 + 下一行一组」的二维展开对应。

## toml设定

配置文件命名：`templates/{template_id}/{template_id}.toml`

采用 **TOML 1.0 严格范式**：`tomlkit` 读写。文件中**不使用** `null`（TOML 标准无此类型）。

### 作用域

- TOML **只处理**顶层 `work_sheet` 所指定的**那一张**工作表（如 `Input_sheet`）。
- **`print_sheet`** 仅用于 UI 打印区选择与 Windows 打印时激活的工作表；**不参与**定位、扫描、校验。
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
  - `input_area`：**第一组 instance 0 填写值**所在区域的登记（**不包含标签格**）；与标签如何被找到**无关联**。类型为**单个区域字符串**或**字符串列表**（多个区域取**并集**，可非连续，如 `["A2","C2:G2","M2"]`）
  - `move_to`：第 2、3… 组填写值相对 instance 0 的展开方向。类型为**单个方向字符串**或**方向字符串列表**（如 `["right","down"]` 表示二维展开：第一项为主轴，第二项为次轴）；合法值仍为 `up` / `down` / `left` / `right`
  - `offset`：每一轴上的平移步长（单元格数，正整数）；**不**平移标签格

`[[sources]]`：路径尚未配置时使用空字符串 `""` 填充；有路径后用 `tomlkit.string(..., literal=True)` 写单引号字面量。

顶层可选键 **`db_id`**：指定本地 `records` 表主键所对应的 **`Input_label`**（不是 `field` 列名）。未配置时由校验/入库逻辑按下列 id 规则自动推断或报错。

顶层可选键 **`use_independent_db`**（bool，默认 **`true`**）：控制 NiceGUI「存储配置」中「使用独立数据库」的默认与落盘状态。

| 值 | 含义 |
|----|------|
| `true`（默认） | 后缀 SQLite 库 + `core_store.save_image`；Input Tab「本次已录入」 |
| `false` | 模板 xlsx 即数据表（`ExcelWriter.write_back` / `read_instances`）；不存图 |

- 解析：`_config_from_dict` → `GetTomlValues.use_independent_db`（缺键视为 `true`）。
- 序列化：`_dict_to_toml` / `ToDict()` / `Save()` 均写出该键。
- UI 勾选变更：`tab_db.py` 更新 `cfg.use_independent_db` 后调用 `cfg.Save(template_id)`。
- **与** `db_id` **无关**：仅影响 UI 存储模式，不参与 `verify_toml` 坐标校验。

### `id` 与 `source_sheet`

`[[fields]].id = true` 表示该字段参与**外部数据源行查找**与**本地 records 主键**语义。规则如下：

| 规则 | 约定 |
|------|------|
| 每外部表至多一个 id | 对每个 `(source_file, source_sheet)`，**至多一条** `id = true`；同一表出现多条 → `verify_toml` 报告 `duplicate_id_sheets`（如 `source1/sheet1`） |
| 外部行查找键 | 对所有 `id = true` 字段，查行用 **`field`（已映射时）否则 `Input_label`**；汇总为 `id_lookup_keys`；**全局 OR**：任意一个键匹配即视为命中该行 |
| 单 id | 仅一条 `id = true` 时，生效的 `db_id` 自动为该条的 **`Input_label`**；若写了 `db_id` 且与唯一 id 的 `Input_label` 不一致 → `invalid_db_id` |
| 多 id | 两条及以上 `id = true` 时，**必须**在顶层写 `db_id = "<某个 id 字段的 Input_label>"`；未写 → `db_id_required`；写了但不在 `id_labels` 列表中 → `invalid_db_id` |
| 无 id | 无 `id = true` 时，`db_id` 为 `null`（报告字段）；入库时由数据库自动分配主键 |

**`db_id` 始终引用 `Input_label`**，例如 `db_id = "ID#"` 表示本地主键取自模板工作表上标签为 `ID#` 的那一列对应的填写值，而非数据源列名 `ID`。

### 定位模型

每次 **UI 加载 template 并激活校验** 时，须对当前 xlsx + 当前 TOML **重新扫描、重新印证**（防止 template 被改过）。`core_toml` **提供函数供 UI 调用**，不在模块内部写死「只校验一次」。

**标签与 `input_area` 无关联**：`Input_label` 靠全表扫描定位；`input_area` 只约束**找到标签之后**推算出的 instance 0 **填写值格**必须落在该区域**并集**内。

#### 两层职责

| 层级 | 键 | 作用对象 | 是否随第 k 组录入而变 |
|------|-----|----------|----------------------|
| 字段级 | `Input_label`、`value_from_label`、`value_offset` | 在 `work_sheet` 上扫描得**标签格** → 推算 instance 0 **值格** | 否（单次校验内坐标固定） |
| `[[input_section]]` | `input_area` | 第一组 instance 0 **填写值**区域并集（校验值格是否落入任一子区域） | 否 |
| `[[input_section]]` | `move_to`、`offset` | 第 k≥1 组**填写值**相对 instance 0 的平移（单方向或主轴+次轴二维） | 是（仅值格） |

#### 标准数据库范式（默认唯一自动处理布局）

默认生成与自动校验**仅**支持标准范式（指 `work_sheet` 上的输入表，**不是** sheet1/sheet2 数据源）：

| 行 | 含义 |
|----|------|
| 第 1 行 | 字段名 / 标签文本（标准下即各 `Input_label` 所在行） |
| 第 2 行及以后 | 填写值（多行表示多条录入；instance 0 对应第一行值） |

- 非标准布局（标签不在第 1 行、值不在 `input_area` 等）**不**由默认逻辑处理，须**用户手工改 TOML** 后由 UI 再次调用校验。

#### 何时扫描、何时只生成

| 条件 | 行为 |
|------|------|
| template 已选，**TOML 不存在** | `TomlGenerator` 生成**默认 TOML**（不逐格扫描）；按标准范式：第 1 行写出 `[[fields]].Input_label` 骨架，`input_area` 登记第 2 行**连续**填写值区域字符串，`move_to = "down"` |
| template 已选，**TOML 已存在**，UI **激活校验** | 对 `work_sheet` **逐字段**全表扫描各 `Input_label`，确定标签格与 instance 0 值格，并做相互印证 |

#### 标签格如何确定（斜向波面扫描）

在 **`work_sheet` 指定表**上（仅此表），在 **100 行 × 100 列**内，按**左上 → 右下**的斜向波面顺序扫描（非行优先逐行扫描）。

扫描顺序：令 `s = row + col`（1-based），`s` 从小到大；同一 `s` 内 `row` 从小到大。即越靠近 `(1,1)` 的格越早被访问——例如 `(2,2)` 早于 `(1,100)`。

实现建议：

1. 用 `iter_rows` 一次性读取 100×100 区域到内存快照（避免逐格随机读）。
2. 在快照上按上述斜向顺序遍历；非空单元格文本（trim 后）作为候选标签。
3. 建立「标签文本 → 出现坐标列表」（保留全部出现，不只首见）；是否构成 `duplicate_labels` 留到与 `input_area` 并集交叉后再判定。

对每一个 `[[fields]]` 的 `Input_label`（在校验阶段查索引，不再逐字段重扫）：

1. 在索引中查 `Input_label` 的全部出现位置。0 个 → `missing_labels`。
2. 对每一处标签格推算值格；**值格落入 `input_area` 并集**的记为候选：
   - 候选 ≥2 → `duplicate_labels`
   - 候选 =1 → 记为 `(label_row, label_col)` 与对应值格
   - 候选 =0（表上有同文标签，但全部值格在并集外）→ `out_of_area_labels`
3. 值格落在并集外的同文标签视为**其它 instance 槽位的表头装饰**（如场景1 中 B 列第二个 `ID#`、H 列起第二组 `Name`…），只要并集内仍恰有一个候选，**不**报 `duplicate_labels`。
4. **标签格是否在 `input_area` 内不作要求**；`input_area` 不参与找标签。

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
(value_row, value_col) 落在 [[input_section]].input_area 并集内的任一子矩形中
```

否则校验失败。即：**先找标签，再按 offset 找值；值必须在 `input_area` 并集内**。

#### `input_section` 只移动填写值、不移动标签

同一页有多份证书/多条录入时，`[[input_section]]` 只描述**填写值区域**的重复平移；**标签格坐标始终不变**（含其它槽位上重复画出的表头文字，亦不随 k 移动）。

设 instance 序号为 `k`（`k = 0` 为第一次填写）。在已记住的 instance 0 值格 `(v_row, v_col)` 上：

```
k = 0  →  使用记住的 instance 0 值格坐标
k ≥ 1  →  按 move_to / offset 相对 instance 0 平移（见下）
```

**`move_to` 为单个方向字符串**时：

```
(v_row, v_col) = offset_cell(v_row0, v_col0, move_to, offset * k)
```

**`move_to` 为方向列表**时（本例 `["right","down"]`）：

- 一项：与单字符串相同。
- 两项：视为**二维网格**——列表第一项为**主轴**（同带上的相邻组），第二项为**次轴**（换带/换行）。`k` → `(主轴步数 i, 次轴步数 j)` 由容量与填表实现约定（建议行优先：先沿主轴铺满再沿次轴）。每一步仍用同一 `offset`（单元格数）：
  ```
  (v_row, v_col) = offset_cell(v_row0, v_col0, move_to[0], offset * i)
  (v_row, v_col) = offset_cell(v_row,  v_col,  move_to[1], offset * j)
  ```
- 超过两项：本设计不要求；实现可拒绝或只取前两项。

**标签格**对任意 `k` 均为记住的 `(label_row, label_col)`，不参与 `move_to` / `offset`。

二维版式下，各字段块的列距必须与统一的 `offset` **相容**（每个值格经同一套 `(i,j)` 步长后落到目标槽）。若列距不一致（例如 ID 列距 1、Name 块列距 5），属非标准版式，须改表或改 `offset`/区域划分，不能指望引擎为每块使用不同步长。

#### 演算示例

对照场景1：`input_area` 只登记 instance 0 的填写值并集（故意不含 B2、H2:L2——那些是主轴 `right` 下一组占用的格）；标签在第 1 行。

```toml
[[input_section]]
input_area = ["A2", "C2:G2", "M2"]
move_to = ["right", "down"]
offset = 1

[[fields]]
Input_label = "ID#"
value_from_label = "down"
value_offset = 1

[[fields]]
Input_label = "Name"
value_from_label = "down"
value_offset = 1

[[fields]]
Input_label = "Sign"
value_from_label = "down"
value_offset = 1
```

全表扫描后记住（1-based；重复表头若值格在并集外则忽略）：

| 对象 | 绝对坐标 | 说明 |
|------|----------|------|
| label ID# | A1 | 首见；B1 同文但值格 B2 ∉ 并集 → 不报重复 |
| label Name | C1 | 首见；H1 同文但值格 H2 ∉ 并集 → 不报重复 |
| label Sign | M1 | 唯一 |
| value ID#（k=0） | A2 | A1 向下 1 格 ∈ 并集 |
| value Name（k=0） | C2 | C1 向下 1 格 ∈ 并集 |
| value Sign（k=0） | M2 | M1 向下 1 格 ∈ 并集 |

`input_area` 并集与 instance 0 值格粗略一致。

**单方向对照**：若 `move_to = "down"`、`offset = 1`，则 k=1 时各值格行号 +1、列号不变（A3 / C3 / M3，对应狗蛋所在行）。

**二维对照**（`move_to = ["right","down"]`，假设主轴方向列距恰为 `offset`）：k 对应网格 `(i,j)` 时，先右移 `offset*i` 再下移 `offset*j`。场景1 示意三人时，Print_sheet 三个 print area 分别对应 (0,0) Clark Kent、(主轴下一步) Lucifer、(次轴下一步) 狗蛋；若实际 Name 块列距 ≠ `offset`，须先改版式再依赖自动平移。

#### 校验入口：`verify_toml()`

UI **只**调用一个函数 `verify_toml()`，由 `core_toml` 完成「打开 xlsx → 搜每个 `Input_label` → 算 instance 0 值格 → 判断是否在 `input_area` 并集内」，并把**有问题的标签**回报给 UI。UI 不关心扫描细节。

**入参（概念）**

| 参数 | 说明 |
|------|------|
| `template_path` | 当前 template 的 `.xlsx` 路径 |
| 已加载的 `GetTomlValues`（或 `template_id`） | 提供 `work_sheet` / `print_sheet` / `input_section` / `fields`，二选一，以实现为准 |

**返回（概念）**

返回一份**报告**，至少能让 UI 知道：

- 整体是否通过（无任何问题即通过）。
- **哪些 `Input_label` 在 `work_sheet` 上找不到**（label 不存在）。
- **哪些 `Input_label` 在并集内对应多个标签格**（duplicate_labels；并集外的同文表头不计）。
- **哪些 `Input_label` 的 instance 0 值格不在 `input_area` 并集内**（input 越界）。

建议形如：

```
{
  "ok": bool,
  "missing_labels": [Input_label, ...],
  "duplicate_labels": [Input_label, ...],
  "out_of_area_labels": [Input_label, ...],
  "located": { Input_label: {label_row, label_col, value_row, value_col}, ... },
  "errors": [str, ...],
  "duplicate_id_sheets": ["source_file/source_sheet", ...],
  "db_id_required": bool,
  "invalid_db_id": str | null,
  "db_id": str | null,
  "id_labels": [Input_label, ...],
  "id_lookup_keys": [str, ...]
}
```

`ok` 为真当且仅当：坐标三项列表与 `errors` 均为空，且 `duplicate_id_sheets` 为空、`db_id_required` 为假、`invalid_db_id` 为 `null`。

`located` 仅内存返回，供 UI 初始化输入框与后续填表使用；**不写回 TOML**。k≥1 的值格由填表逻辑在 instance 0 坐标上再应用 `move_to`/`offset`（含二维列表），不在本次校验逐 instance 扫描。

**执行步骤（仅 `work_sheet` 指定表 + TOML 层 id / regex 规则）**

1. **TOML 层**（不打开 xlsx）：统计各 `(source_file, source_sheet)` 的 `id=true` 数量；汇总 `id_labels`、`id_lookup_keys`；解析或校验 `db_id`；对每条非空 `[[fields]].regex` 做 `re.compile`（失败 → `errors`，形如 `{Input_label}: 正则表达式无效 (...)`）。
2. 打开 `work_sheet` 指定的工作表；不存在 → 整体失败。
3. 把 `[[input_section]].input_area` 解析为**一个或多个**矩形，组成并集（单项字符串或字符串列表均可）；无法解析 → `errors`。
4. 对 100×100 区域做**一次**斜向波面扫描，建立标签文本 → 出现坐标列表（含重复）。
5. 对每一条 `[[fields]]` 查索引：
   - 表上 0 处 `Input_label` → `missing_labels`。
   - 对每处出现推算值格，筛「值格 ∈ 并集」的候选：候选 ≥2 → `duplicate_labels`；候选 =1 → 写入 `located`；候选 =0（仅有并集外同文）→ `out_of_area_labels`。
6. 坐标与 id / regex 规则均通过 → `ok = True`。

**不检查**：标签格是否在 `input_area` 内；`field` / `source_*` / `regex` **是否已映射**（空串仍合法）；`print_sheet` 是否存在或其 `print_area`。**会检查**：非空 `regex` 是否能被 Python `re` 编译。`verify_toml()` **只报告**问题，**不**静默改 TOML、不改 xlsx、不自动修正坐标。

> 文本层面的 TOML **语法**解析由 Load 阶段负责（不打开 xlsx）。若 `regex` 误用双引号写出 `\d` 等非法转义，**整文件解析失败**，`load_toml` 返回 `None`，校验入口根本拿不到配置——这不是 `re.compile` 报错，而是 TOML 层拒收（见下方「正则表达式写法」）。`verify_toml()` 在配置已成功加载后，再做坐标印证、**id/db_id** 与 **regex 可编译性**。

### 配置示例

```# toml
determiner = "\t"           # 纯文本粘贴的分隔符；支持单字符串（如 "\t"）或多个分隔符组成的列表（如 ["\r\n", "\n", "\t"]）
work_sheet = "Input_sheet"   # 模板中需要输入数据的表格（TOML 定位 / 读写）
print_sheet = "Print_sheet"  # UI 打印区选择与 Windows 打印时激活的工作表（可选）
use_independent_db = true    # 是否使用独立后缀数据库（false = 模板 xlsx 即数据表）
db_id = "ID#"               # 本地 records 主键对应的 Input_label；仅一条 id=true 时可省略；多条 id=true 时必填

# 外部数据源；路径可为本地文件、网页链接或 Google Sheet
# 首次生成时写入空值 ""，真实路径由专用配置页写入后再落盘
[[sources]]
source1 = ""
source2 = ""

# input_section：仅登记第一组填写值区域及后续组的平移；不包含标签。
[[input_section]]
input_area = ["A2","C2:G2","M2"]        # instance 0 填写值并集（可非连续；本例不含 B2、H2:L2）
move_to = ["right","down"]              # 单字符串或列表；列表两项 = 主轴 + 次轴（up/down/left/right）
offset = 1                    # 每一轴上的平移步长（单元格数）；标签行不动

# 字段映射：每个输入项一个 [[fields]] 表项
[[fields]]
Input_label = "ID#"         # 扫描全部同文；值格落入 input_area 并集的那一处为标签格（本例 A1，非 B1）
value_from_label = "down"   # 支持up/down/left/right。这里的down表示标签在上，数值在“下边”
value_offset = 1            # 说明找到标签之后，往下“1”格就是填写内容的地方。
field = "ID"                # 数据源的所在列
source_file = "source1"     # 数据源的引用
source_sheet = "sheet1"     # 打开数据源之后，寻找指定的这个表格
index = 0                   # 作为纯文本粘贴被分隔符拆分后的索引值；index base 0
regex = ""                  # 无截取时写空串；有 \d 等反斜杠时必须用单引号字面量，见「格式说明」§正则
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
regex = '\d+/\d+/\d+'       # 正确：单引号字面量；勿写成 regex = "\d+/\d+/\d+"（TOML 双引号解析失败）
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
3. **正则表达式（`[[fields]].regex`）——易踩坑**：
   - **语义**：Python `re` 模式；应用层用 `re.search`；有捕获组时取 `group(1)`（见 `core_connect._apply_regex`）。空串 `""` = 未映射，不做截取。
   - **落盘必须用 TOML 单引号字面量**（`literal=True`），让 `\d` `\w` `\s` `\b` `\(` 等**原样**进入内存。正确示例：
     - `regex = '\d+/\d+/\d+'`
     - `regex = '(\d+)/'`
     - `regex = '\d+/(\d+)'`
   - **禁止**对含反斜杠的模式使用双引号基本字符串。TOML 1.0 基本字符串只认有限转义（`\\` `\"` `\n` `\t` `\uXXXX` 等），**不认** `\d` `\w` `\s`。因此：
     - `regex = "\d+"` → **整份 TOML 解析失败**（`InvalidCharInStringError`），不是「正则不合法」。
     - `regex = "\\d+"` → 能解析，内存得到 `\d+`（正确但易手滑少写一层 `\`）。
   - **模式本身含单引号 `'`** 时无法用字面量：改用双引号，并把每个反斜杠写成 `\\`，例如内存模式 `don't\d+` → `regex = "don't\\d+"`。引擎序列化（`_toml_string`）对 `regex` 默认写字面量；仅当值含 `'` 时退回双引号并正确转义。
   - **校验**：`verify_toml` 对非空 `regex` 调用 `re.compile`；编译失败写入报告 `errors`（带 `Input_label`）。解析阶段失败则根本进不了 `verify_toml`。
4. **已映射但无 regex**：写入空字符串 `regex = ""`。
5. **默认配置**：包含 `determiner`、`work_sheet`（若有）、`print_sheet`（可选）、`use_independent_db`（默认 `true`）、`[[input_section]]`（**一条**）、`[[sources]]` 与 `[[fields]]` 骨架；可选字符串键以 `""` 占位。生成器默认仍写**单个**连续 `input_area` 字符串与**单个** `move_to` 方向；列表形式由用户手工（或向导）填写非连续/二维版式时使用。
6. **`index`**：纯文本粘贴时按 `determiner` 拆分后的列索引（base 0）；与 Excel 列号、与 `input_section` 平移无关。
7. **`input_area`**：只框 instance 0 **填写值**（字符串或字符串列表并集）；**不**用于找标签。找标签后推算出的值格**必须**落在此并集内。
8. **标签与 `input_area`**：二者独立——扫描认 `Input_label`；重复同文标签仅当其值格落入并集时参与 `duplicate_labels` 判定；`input_area` 只校验 instance 0 值格是否入框。
9. **`move_to`**：字符串 = 单轴；长度为 2 的列表 = 主轴+次轴二维展开；与 `offset` 共同决定 k≥1 值格坐标。

### 实现依赖

```
tomlkit>=0.13
```

`tomlkit` 用于读写 TOML。



### `core_toml` 与 UI 的分工

| 职责 | 模块 | 说明 |
|------|------|------|
| 生成默认 TOML | `TomlGenerator` | TOML 不存在时；标准范式；**不**做全表扫描；默认单个连续 `input_area` + 单个 `move_to` |
| 读写 TOML 文本 | `GetTomlValues` | Load / Save / ToDict（含 `db_id`、`use_independent_db`；`input_area`/`move_to` 可为字符串或列表） |
| **激活校验**（UI 调用） | `verify_toml()` | UI 只调这一个；斜向扫描 work_sheet，报告找不到 / 并集内重复 / 值格越界的 `Input_label`，以及 `duplicate_id_sheets` / `db_id` / **非空 regex 的 `re.compile` 失败** |
| 解析本地主键 | `resolve_db_id()` | 由已加载配置推断生效的 `db_id`（`Input_label`）；无 id 字段时返回 `None` |
| 坐标解析 | `offset_cell`、`_scan_worksheet_labels_diagonal` 等 | 校验与填表共用；扫描上限 **100×100**；`input_area` 按并集判定 |
| regex 落盘 | `_toml_string` / `_needs_literal_string` | `regex` 默认单引号字面量；值含 `'` 时改双引号并转义反斜杠 |

**不在 `core_toml` 内写死**「仅首次 Load 校验」；是否校验、何时校验由 **UI 在加载 template 时决定**。

### 职责划分

- **生成器（`TomlGenerator`）**：TOML 不存在时，按标准范式生成骨架（第 1 行 → `[[fields]].Input_label`，`input_area` → 第 2 行连续值区字符串）；默认 `value_from_label = "down"`、`value_offset = 1`、`move_to = "down"`；**不**扫描全表；非连续/二维列表由后续手工或向导写入。
- **持久化层（`GetTomlValues`）**：Load / Save / ToDict（含可选 `db_id`、`use_independent_db`）；**`verify_toml()`**——回报坐标问题、id 规则与非空 `regex` 的 `re.compile` 结果。
- **定位**：仅在 `work_sheet` 上斜向波面扫描标签；值格由 offset 推算且**必须**在 `input_area` 并集内；同文重复标签仅统计值格入并集者；`move_to`/`offset` 处理 k≥1 值格平移（单轴或主轴+次轴）。
- **regex 写法**：含 `\d` 等反斜杠时磁盘上用单引号字面量；双引号 `"\d"` 会导致整文件 TOML 解析失败（见格式说明 §3）。
- **打印**：`print_sheet` 由 `ExcelWriter.get_print_areas()` 与 UI 打印行使用；不参与 `verify_toml` 坐标印证。场景1 约定每 4 行为一个 print area。
- **数据源路径**：由专用 UI 写入，不由生成器提供。
