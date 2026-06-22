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
ID#|Name|Recent Issue|Report Date|Discipline|date|Sign
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

### 未映射语义

| 层级 | 约定 |
|------|------|
| 内存 / API | Python `None` |
| 磁盘文件 | 所有键均需保留，未映射的可选键写入空字符串 `""`，不写 `null`，不省略键 |

`[[fields]]` 每一行：

- **必有键**：`Input_label`、`index`、`id`
- **可选键**：`field`、`source_file`、`source_sheet`、`regex`
- 可选键的值为 `""` → 应用层视为 `None`
- `index = -1` 表示无文本框列索引（整数键保留）

`[[sources]]`：路径尚未配置时使用空字符串 `""` 填充；有路径后用 `tomlkit.string(..., literal=True)` 写单引号字面量。

### 配置示例

```toml
# 支持 \t(tab) 等转义字符和其他单字符分隔符
determiner = "\t"       
worksheet = "Input_sheet"

# 外部数据源；路径可为本地文件、网页链接或 Google Sheet
# 首次生成时写入空值 ""，真实路径由专用配置页写入后再落盘
[[sources]]
source1 = ""
source2 = ""

# 多区域配置（一页 3 个证书，垂直排列）
[[sections]]
input_area = "A2:G2"
move_to = "down"      # 向下移动；支持 up, down, left, right
offset = 1            # 向下移动一行；up/down 移动行，left/right 移动列

# 字段映射：每个模板列一个 [[fields]] 表项
[[fields]]
Input_label = "ID#"
field = "ID"
source_file = "source1"
source_sheet = "sheet1"
index = 0             # index base 0
regex = ""
id = true

[[fields]]
Input_label = "Name"
field = "name"
source_file = "source1"
source_sheet = "sheet1"
index = 1
regex = ""
id = false

[[fields]]
Input_label = "Recent Issue"
field = "issues"
source_file = "source2"
source_sheet = "sheet2"
index = 2
regex = ""
id = false

[[fields]]
Input_label = "Report Date"
field = "issues"
source_file = "source2"
source_sheet = "sheet2"
index = 2
regex = '\d+/\d+/\d+'
id = false

[[fields]]
Input_label = "Discipline"
field = ""
source_file = ""
source_sheet = ""
index = -1            # 无文本框列索引；无 field / source_* / regex
regex = ""
id = false

[[fields]]
Input_label = "date"
field = ""
source_file = ""
source_sheet = ""
index = -1
regex = ""
id = false

[[fields]]
Input_label = "Sign"
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
5. **默认配置**：包含 `determiner`、`worksheet`（若有）、`sections`（若有）、`[[sources]]` 与 `[[fields]]` 骨架，其中的可选值使用 `""` 占位填充。

### 实现依赖

```
tomlkit>=0.13
```

`tomlkit` 用于读写 TOML。

### 与 YAML 版的结构对应

| 概念 | YAML | TOML |
|------|------|------|
| 顶层分隔符 | `determiner: tab` | `determiner = "\t"` 等转义字符 |
| 工作表 | `worksheet: "Input_sheet"` | `worksheet = "Input_sheet"` |
| 数据源列表 | `sources:` 下 `- source1: ...` | `[[sources]]` 表数组 |
| 多区域 | `sections:` 列表 | `[[sections]]` 表数组 |
| 字段映射 | 以列名为顶层键 | `[[fields]]` + `Input_label` |
| 是否 ID 列 | `ID: true` | `id = true`（小写） |
| 空 / 未映射 | `null` | **空字符串 `""`**（内存仍为 `None`） |

### 职责划分

- 生成器（`TomlGenerator`）：根据 template + input_area 生成空映射骨架并序列化
- 持久化层（`GetTomlValues`）：load / save / validate / ToDict
- 模块级 `_dict_to_toml`、`_config_from_dict`：两类的读写管道
- 数据源真实路径：由专用 UI 模块写入，不由模板生成器提供
