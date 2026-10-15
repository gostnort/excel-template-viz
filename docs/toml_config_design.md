# TOML 配置文件设计规范 (TOML Configuration Design Specification)

本文档定义系统模板配置文件的核心数据契约、语法规范与定位校验机制。

> [!NOTE]
> 完整的配置实例如字段映射请参考专用样本文件：[sample_template.toml](sample/sample_template.toml)。
> 本文档聚焦于底层语法结构、几何平移模型与引擎校验规约，不堆砌特定业务数据。

---

## 1. 作用域与基础范式

- **存储规范**：配置文件存放在 `templates/{template_id}/{template_id}.toml`，采用 **TOML 1.0 严格范式**，由 `tomlkit` 负责读写。
- **作用域**：仅处理由 `work_sheet` 所指定的目标工作表。`print_sheet` 仅供打印区选择激活，不参与数据扫描与校验。
- **未映射与空值约定**：
  - TOML 标准无 `null` 类型，禁止使用 `null`。
  - 所有必填和可选键均需在配置中保留。未映射的可选字符串键统一写入空字符串 `""`（应用层解析为 Python `None`），整数键未映射时写 `-1`。

### 顶层控制键

| 键名 | 类型 | 默认值 | 作用与含义 |
| :--- | :--- | :--- | :--- |
| `determiner` | string \| list[string] | `"\t"` | 纯文本粘贴/导入时的列分隔符（支持单字符或转义字符列表如 `["\r\n", "\n", "\t"]`）。 |
| `work_sheet` | string | 必填 | 模板中进行数据定位、扫描与填充的目标工作表名称。 |
| `print_sheet` | string | `""` | 可选，Windows 打印时激活的工作表名称，不参与扫描定位。 |
| `use_independent_db` | boolean | `true` | `true` 表示使用后缀 SQLite 数据库做历史入库存储；`false` 表示模板 xlsx 自身即数据表。 |
| `db_id` | string | 可选 | 本地记录主键所对应的 `Input_label`（非外部源列名）。仅一条 `id = true` 时可缺省自动推断；多条 `id = true` 时必填。 |

---

## 2. 外部数据源表 `[sources]`

外部数据源统一收敛在 `[sources]` 字典表中管理，字段映射中仅需通过 `source = "source_key"` 关联。

针对本地与远程数据，设计为两套独立的物理结构：

### 结构 1：本地 Excel 数据源 (Local Excel Source)
- **语法规范**：采用 Excel 原生外部引用语法单字符串 `'<文件目录>\[<工作簿文件名>]<工作表名>'`。
- **示例**：
  ```toml
  [sources]
  source1 = 'E:\path\to\[执法堂业绩.xlsx]sheet1'
  ```
- **机制**：由 Excel 原生文件系统语法直接闭环目录、文件名与工作表名。

### 结构 2：远程 Google Sheet 数据源 (Remote Google Source)
- **核心原则**：**Google URL 必须 100% 真实原生**，严禁在 URL 字符串内部插入方括号或人为篡改拼接。
- **语法规范**：URL 本身由双引号 `""` 完整包裹，工作表名（sheet name）只能跟在 `""` URL 之后，统一采用**二元组数组**：
  `["<真实完整Google_URL>", "<工作表名>"]`。
- **示例**：
  ```toml
  [sources]
  source_remote = [
      "https://docs.google.com/spreadsheets/d/1XdaRK0cDnet54KzDUiSrpl_xcu4vOMSYacdipDXT14c/edit?gid=0#gid=0",
      "Containers"
  ]
  ```

### 解析器识别协议
- 值类型为 **单字符串 (string)** $\to$ 识别为本地 Excel 源，正则拆解文件路径与工作表；
- 值类型为 **二元数组 (list of string)** $\to$ 第 1 项为纯正 Google Sheet URL，第 2 项为目标工作表名。

---

## 3. 输入区段 `[[input_section]]` 几何模型

配置中**有且仅有一条** `[[input_section]]`，用于定义首组录入值（instance 0）的物理边界及后续录入组的展开轨迹。**只约束值格，不移动标签格**。

### 模式 A：扁平展开（单轴或二维网格）
适用于常规单行或连续块展开：
```toml
[[input_section]]
input_area = "A2:J2"          # 或非连续并集列表 ["A2", "C2:G2", "M2"]
move_to = "down"              # 单方向 "down" 或主次轴方向列表 ["right", "down"]
offset = 1                    # 正整数标量，各轴平移步长
```
- **坐标平移公式**：
  - 单轴：$v_{pos}(k) = v_{pos0} + \text{offset} \times k$
  - 二维主次轴：主轴步数 $i$、次轴步数 $j$ 分别按 $\text{offset} \times i$ 和 $\text{offset} \times j$ 沿对应方向平移。

### 模式 B：两段嵌套展开（行级共享主区 + 行内次区槽位）
适用于同一行内既有行级共享主区，又有多槽次区展开且列距不同的版式：
```toml
[[input_section]]
# [0] 为 major 行级共享段；[1] 为 minor 次区各槽模板（仅登记第 0 槽）
input_area = [["D2:J2", "AF2:AH2"], ["A2", "K2:Q2"]]
move_to = ["down", "right"]
# 与 input_area 同形：offset[s][k] 分别对应各子块在各轴上的展开步长
offset = [[1, 1], [1, 7]]
```
- **解析契约**：
  - `move_to[0]` 为主轴（major 平移方向），`move_to[1]` 为次轴（minor 槽位平移方向）。
  - 次区在沿次轴展开的同时，继承主轴的行级下移。
  - `offset` 矩阵与 `input_area` 嵌套结构必须同形，否则校验报错。

---

## 4. 字段映射表 `[[fields]]`

每个输入字段对应一个 `[[fields]]` 项。

### 键结构规范

| 键名 | 类型 | 必填 | 说明 |
| :--- | :--- | :---: | :--- |
| `Input_label` | string | 是 | 模板表格上的标签文本（扫描匹配锚点）。 |
| `value_from_label` | string | 是 | 相对标签格的偏移方向：`"up"` / `"down"` / `"left"` / `"right"`。 |
| `value_offset` | integer | 是 | 相对标签格的偏移格数（正整数）。 |
| `cell_role` | string | 是 | 单元格角色契约：`"data"` / `"regex"` / `"formula"` / `"input"`。 |
| `source` | string | 否 | 关联的外部数据源标识，对应 `[sources]` 中的键。 |
| `field` | string | 否 | 外部数据源的目标列名。 |
| `regex` | string | 否 | 正则截取表达式（**必须用 TOML 单引号字面量**）。 |
| `formula` | string | 否 | 公式模板（仅外部公式需要提供）。 |
| `index` | integer | 是 | 纯文本粘贴导入时的列索引（0-based，无映射时写 `-1`）。 |
| `id` | boolean | 是 | 是否为主键/行查找标识。 |

### `cell_role` 四态数据契约

1. **`"data"`（直接复制）**：
   直接从 `source` 指定的外部表读取 `field` 列的数据填入。
2. **`"regex"`（正则提取）**：
   从 `source` 外部表读取 `field` 列后，通过 Python 正则表达式抽取（有捕获组优先取 `group(1)`）。
   - **字面量规则**：磁盘落盘必须使用单引号字面量（如 `regex = '\d+/\d+/\d+'`），严禁使用双引号导致反斜杠转义崩溃。
3. **`"formula"`（公式格）**：
   - **外部派生公式**：需要外部源时，由 `source` 与 `formula` 模板展开为标准 Excel 外链公式（如 `formula = "='{source1}'!$C$4 & '{source1}'!$B$4"`）。
   - **模板内部公式**：若为模板内已有的计算闭环公式，无需指定外部 `source`，**系统写回时自动跳过**，保留 Excel 自算。
4. **`"input"`（人工手填）**：
   纯手工录入字段，无外部源依赖，`source` 与 `field` 留空。

### `id` 语义与主键规则
- 对每个外部数据源（`source`），**至多配置一个** `id = true` 字段。
- 外部源查找时，使用 `id = true` 字段的 `field`（或 `Input_label`）作为 lookup key，多源之间按**全局 OR** 命中行。
- 仅有 1 个 `id = true` 时，顶层 `db_id` 自动推断为该字段的 `Input_label`；存在多个 `id = true` 时，顶层必须显式声明 `db_id`。

---

## 5. 定位与校验引擎 (`verify_toml`)

UI 加载模板或激活校验时，调用 `verify_toml()` 对模板工作表与配置进行双向几何印证。

### 1. 斜向波面扫描定位
- 在 `work_sheet` 工作表的前 **100 行 × 100 列** 区域内，按曼哈顿距离 $s = \text{row} + \text{col}$ 从小到大、同 $s$ 内 row 从小到大的斜向顺序扫描。
- 记录所有单元格文本与坐标，建立候选索引。

### 2. 标签与填写值格判定
- 依据 `value_from_label` 与 `value_offset` 计算候选标签对应的值格坐标。
- **并集约束**：计算出的 instance 0 填写值格**必须落在 `input_area` 并集范围内**。
- 同文标签（如多槽位重复表头）若其推算值格落在 `input_area` 之外，视作其他槽位的装饰文本，不触发 `duplicate_labels`。

### 3. 返回报告契约
`verify_toml()` 仅执行校验并返回内存报告，不静默改写磁盘文件：
```python
{
    "ok": bool,                       # 整体校验是否通过
    "missing_labels": list[str],      # 未在表中找到的标签
    "duplicate_labels": list[str],    # 并集内命中多处值格的冲突标签
    "out_of_area_labels": list[str],  # 找到标签但其值格越出 input_area 并集
    "located": dict,                  # 成功定位的标签与值格坐标字典
    "errors": list[str],              # 语法/正则编译/同形校验等错误信息
    "formula_cells": dict,            # 公式格记录
    "db_id": str | None               # 当前生效的本地记录主键标签
}
```
