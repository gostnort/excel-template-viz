# YAML 配置指南

本文档详细说明如何为 Excel 模板创建 `.paste.yaml` 配置文件，以实现数据映射和多区域检测。

## 目录

1. [基础配置](#基础配置)
2. [字段映射](#字段映射)
3. [多区域配置（新功能）](#多区域配置)
4. [高级功能](#高级功能)
5. [完整示例](#完整示例)
6. [常见问题](#常见问题)

---

## 基础配置

### 文件命名

YAML 配置文件必须与 Excel 模板文件同名，扩展名为 `.paste.yaml`：

```
templates/
  ├── MyTemplate.xlsx
  └── MyTemplate.paste.yaml
```

### 基本结构

```yaml
determiner: tab          # 字段分隔符（tab/space/逗号等）
worksheet: "Sheet1"      # 默认工作表名称（可选）
order: []                # 字段显示顺序（可选）
sections: []             # 多区域配置（可选，新功能）

# 字段映射定义
FieldName1:
  - filed: "源字段名"
    index: 0
    regex: "正则表达式"  # 可选
    ID: false           # 是否为 ID 字段

FieldName2:
  - filed: "源字段名2"
    index: 1
```

---

## 字段映射

### 基本字段定义

每个字段映射包含以下属性：

| 属性 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `filed` | string | 是 | 源数据中的字段名称 |
| `index` | int | 是 | Excel 模板中的列索引（从 0 开始） |
| `regex` | string | 否 | 用于数据清洗的正则表达式 |
| `ID` | boolean | 否 | 标记为 ID 字段（用于查询和去重） |

### 示例

```yaml
Name:
  - filed: "姓名"
    index: 0

Employee_ID:
  - filed: "员工编号"
    index: 1
    ID: true          # 标记为 ID 字段

Phone:
  - filed: "电话"
    index: 2
    regex: "\\d+"     # 只保留数字

Email:
  - filed: "邮箱"
    index: 3
```

### ID 字段说明

- **唯一性标识**：`ID: true` 的字段用于唯一标识每条记录
- **自动查询**：在数据录入界面中，输入 ID 后自动从 Google Sheet 查询完整数据
- **批量导入去重**：批量导入时自动过滤已录入的 ID
- **每个模板至少需要一个 ID 字段**

---

## 多区域配置

### 什么是多区域？

多区域功能允许在同一个 Excel 工作表中定义多个相同结构的数据填充区域。

**使用场景：**
- 批量打印多个标签/证书
- 一页多个表单
- 重复的数据表格

### 配置结构

```yaml
sections:
  - input_area: "A1:M2"    # 第一个区域的范围
    move_to: "down"        # 移动方向
    offset: 3              # 偏移量（行数或列数）
```

### 参数说明

#### `input_area`（必需）
- **格式**：Excel 区域范围，如 `"A1:M2"`
- **说明**：定义第一个数据填充区域
- **示例**：
  - `"A1:M2"` - 从 A1 到 M2（2 行 13 列）
  - `"B5:F10"` - 从 B5 到 F10

#### `move_to`（必需）
- **格式**：字符串，只能是以下值之一
- **可选值**：
  - `"down"` - 向下移动（垂直排列）
  - `"up"` - 向上移动
  - `"right"` - 向右移动（水平排列）
  - `"left"` - 向左移动
- **大小写**：不敏感（`"Down"` 和 `"down"` 相同）

#### `offset`（必需）
- **格式**：正整数
- **说明**：移动的行数（down/up）或列数（right/left）
- **示例**：
  - `offset: 1` - 移动 1 行/列（紧邻）
  - `offset: 3` - 移动 3 行/列（中间留 2 行/列空白）

### 工作原理

1. **第一区域**：从 `input_area` 开始
2. **自动检测**：根据 `move_to` 和 `offset` 计算下一区域
3. **停止条件**：
   - 区域完全为空（不包含公式）
   - 区域格式与第一区域不一致
   - 超出工作表边界

### 完整示例

#### 场景 1：垂直标签打印

```yaml
sections:
  - input_area: "A1:E5"
    move_to: "down"
    offset: 6
```

**布局**：
```
┌─────────────┐  Row 1-5: 第一个标签
│  Label 1    │
│  A1:E5      │
└─────────────┘
                 Row 6: 空行
┌─────────────┐  Row 7-11: 第二个标签
│  Label 2    │
│  A7:E11     │
└─────────────┘
                 Row 12: 空行
┌─────────────┐  Row 13-17: 第三个标签
│  Label 3    │
│  A13:E17    │
└─────────────┘
```

#### 场景 2：水平证书打印

```yaml
sections:
  - input_area: "A1:F20"
    move_to: "right"
    offset: 8
```

**布局**：
```
┌──────┐ ┌──────┐ ┌──────┐
│Cert 1│ │Cert 2│ │Cert 3│
│A1:F20│ │I1:N20│ │Q1:V20│
└──────┘ └──────┘ └──────┘
 (A-F)   (2列空白) (I-N)   (2列空白) (Q-V)
```

---

## 高级功能

### 字段顺序（order）

控制数据录入界面中字段的显示顺序：

```yaml
order:
  - Employee_ID
  - Name
  - Department
  - Phone
  - Email
```

### 正则表达式清洗

使用 `regex` 属性清洗数据：

```yaml
Phone:
  - filed: "联系电话"
    index: 5
    regex: "\\d{11}"      # 只保留 11 位数字

Salary:
  - filed: "工资"
    index: 6
    regex: "\\d+\\.?\\d*"  # 只保留数字和小数点
```

### 工作表指定

指定默认工作表（如果模板有多个 sheet）：

```yaml
worksheet: "员工信息"

Name:
  - filed: "姓名"
    index: 0
```

---

## 完整示例

### 示例 1：简单员工信息表

**文件**：`Employee.paste.yaml`

```yaml
determiner: tab
worksheet: "员工表"

# ID 字段（用于查询和去重）
Employee_ID:
  - filed: "工号"
    index: 0
    ID: true

# 基本信息
Name:
  - filed: "姓名"
    index: 1

Department:
  - filed: "部门"
    index: 2

Position:
  - filed: "职位"
    index: 3

# 联系信息
Phone:
  - filed: "手机"
    index: 4
    regex: "\\d{11}"

Email:
  - filed: "邮箱"
    index: 5

# 字段显示顺序
order:
  - Employee_ID
  - Name
  - Department
  - Position
  - Phone
  - Email
```

### 示例 2：多区域证书模板

**文件**：`Certificate.paste.yaml`

```yaml
determiner: tab
worksheet: "证书"

# 多区域配置（一页 3 个证书，垂直排列）
sections:
  - input_area: "A1:M15"    # 第一个证书区域
    move_to: "down"         # 向下移动
    offset: 16              # 每个证书 15 行 + 1 行空白

# 字段映射
Student_ID:
  - filed: "学号"
    index: 0
    ID: true

Student_Name:
  - filed: "学生姓名"
    index: 1

Course_Name:
  - filed: "课程名称"
    index: 2

Grade:
  - filed: "成绩"
    index: 3

Issue_Date:
  - filed: "颁发日期"
    index: 4

# 显示顺序
order:
  - Student_ID
  - Student_Name
  - Course_Name
  - Grade
  - Issue_Date
```

### 示例 3：批量标签打印

**文件**：`Labels.paste.yaml`

```yaml
determiner: tab

# 多区域配置（一页 4 列 × 6 行 = 24 个标签）
sections:
  - input_area: "A1:C4"     # 每个标签 3 列 × 4 行
    move_to: "down"         # 先向下排列
    offset: 5               # 每个标签 4 行 + 1 行空白

# 注意：如果需要先横向再纵向，需要分别配置每列
# 这里假设标签按列排列（A列一组，D列一组，G列一组，J列一组）

# 字段映射
Product_ID:
  - filed: "产品编号"
    index: 0
    ID: true

Product_Name:
  - filed: "产品名称"
    index: 1

Price:
  - filed: "价格"
    index: 2
    regex: "\\d+\\.\\d{2}"  # 保留两位小数
```

---

## 常见问题

### Q1: 如何确定字段的 index？

**A**: 在 Excel 模板中，从左到右数列的索引：
- 第一列（A 列）= `index: 0`
- 第二列（B 列）= `index: 1`
- 第 N 列 = `index: N-1`

### Q2: sections 配置中的 offset 如何计算？

**A**: 
- **向下/向上移动**：offset = 区域高度 + 空白行数
  - 例如：区域高度 5 行，留 1 行空白，则 `offset: 6`
- **向右/向左移动**：offset = 区域宽度 + 空白列数
  - 例如：区域宽度 10 列，留 2 列空白，则 `offset: 12`

### Q3: 为什么区域检测停止了？

**A**: 区域检测会在以下情况停止：
1. **完全为空**：下一区域没有任何内容（不包含公式）
2. **格式不一致**：下一区域的单元格内容格式与第一区域不同
3. **超出边界**：计算出的下一区域超出工作表范围

### Q4: 可以有多个 ID 字段吗？

**A**: 建议只有一个 ID 字段。如果需要复合主键，可以创建一个组合字段作为 ID。

### Q5: 如何调试 YAML 配置？

**A**: 
1. 使用 Gradio UI 的"数据源"标签页测试查询
2. 检查应用日志中的错误信息
3. 验证 YAML 语法（使用在线 YAML 验证器）
4. 确认 `input_area` 范围与 Excel 模板一致

### Q6: 正则表达式不生效？

**A**: 
1. 确保使用双反斜杠转义（`\\d` 而不是 `\d`）
2. 使用 Python 正则表达式语法
3. 测试正则表达式：https://regex101.com/

### Q7: 如何处理空值？

**A**: 
- 字段映射会自动处理空值
- 如果 Google Sheet 中某字段为空，该字段在 Excel 中也会留空
- 使用 `regex` 可以设置默认值或清洗规则

---

## 最佳实践

1. **先设计后配置**：在编写 YAML 前，先在 Excel 中设计好模板布局
2. **使用有意义的字段名**：字段名要清晰易懂
3. **测试验证**：配置完成后先用少量数据测试
4. **版本控制**：将 YAML 文件纳入版本控制
5. **文档注释**：在 YAML 中添加注释说明特殊配置
6. **备份模板**：修改前备份原始 Excel 模板

---

## 技术支持

如遇问题，请检查：
1. YAML 语法是否正确
2. 文件名是否匹配（大小写敏感）
3. 字段 index 是否正确
4. sections 配置的 move_to 和 offset 是否合理
5. 应用日志中的详细错误信息

更多帮助请参考项目 README 或提交 Issue。
