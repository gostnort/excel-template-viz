# YAML 配置示例

本目录包含各种场景的 YAML 配置示例，帮助您快速上手。

## 示例列表

### 1. `employee_simple.paste.yaml`
**场景**：简单员工信息表  
**特点**：
- 单区域填充
- 基本字段映射
- 包含 ID 字段和数据清洗（regex）
- 适合初学者学习基础配置

**使用方法**：
1. 创建同名 Excel 模板：`employee_simple.xlsx`
2. 在 `Sheet1`（或配置中的 `worksheet`）中设计表格
3. 字段从 A 列（index: 0）开始依次排列

---

### 2. `certificate_vertical.paste.yaml`
**场景**：批量证书打印（垂直排列）  
**特点**：
- 多区域配置（sections）
- 向下移动（`move_to: down`）
- 一页 3 个证书
- 15 行高度 + 1 行空白

**布局示意**：
```
┌────────────────┐  Row 1-15: 证书 1
│  Certificate   │
│  A1:M15        │
└────────────────┘
                   Row 16: 空行
┌────────────────┐  Row 17-31: 证书 2
│  Certificate   │
│  A17:M31       │
└────────────────┘
                   Row 32: 空行
┌────────────────┐  Row 33-47: 证书 3
│  Certificate   │
│  A33:M47       │
└────────────────┘
```

---

### 3. `product_labels.paste.yaml`
**场景**：商品价格标签批量打印  
**特点**：
- 多区域配置
- 向下移动（先填充一列）
- 每个标签 3 列 × 4 行
- 4 行高度 + 1 行空白
- 价格字段使用 regex 保留两位小数

**布局示意**：
```
┌─────┐         Col A-C: 标签 1
│Label│  Row 1-4
└─────┘
        Row 5: 空行
┌─────┐         Col A-C: 标签 2
│Label│  Row 6-9
└─────┘
```

---

### 4. `business_card.paste.yaml`
**场景**：员工名片批量打印（水平排列）  
**特点**：
- 多区域配置
- 向右移动（`move_to: right`）
- 每张名片 6 列 × 10 行
- 6 列宽度 + 2 列空白

**布局示意**：
```
┌────────┐  ┌────────┐  ┌────────┐
│ Card 1 │  │ Card 2 │  │ Card 3 │
│ A1:F10 │  │ I1:N10 │  │ Q1:V10 │
└────────┘  └────────┘  └────────┘
  (A-F)      (2列空白)     (I-N)
```

---

## 如何使用这些示例

### 步骤 1：选择合适的示例

根据您的需求选择最接近的示例：
- **单区域**：`employee_simple.paste.yaml`
- **垂直多区域**：`certificate_vertical.paste.yaml`
- **水平多区域**：`business_card.paste.yaml`
- **小标签**：`product_labels.paste.yaml`

### 步骤 2：复制并重命名

```bash
cp templates/examples/employee_simple.paste.yaml templates/MyTemplate.paste.yaml
```

### 步骤 3：修改配置

1. 根据您的 Excel 模板调整 `input_area`
2. 修改 `move_to` 和 `offset` 以匹配布局
3. 更新字段映射（`filed` 和 `index`）
4. 设置 ID 字段

### 步骤 4：测试验证

1. 在 Gradio UI 中选择模板
2. 使用"数据源"标签页测试查询
3. 验证多区域检测是否正确
4. 尝试导入少量数据

---

## 配置要点

### 单区域 vs 多区域

| 特性 | 单区域 | 多区域 |
|------|--------|--------|
| 配置 | 无需 `sections` | 必需 `sections` |
| 用途 | 单个表单/记录 | 批量打印/多记录 |
| 复杂度 | 简单 | 中等 |
| 示例 | 员工信息表 | 证书、标签、名片 |

### move_to 方向选择

| 方向 | 适用场景 | offset 含义 |
|------|----------|------------|
| `down` | 纵向排列 | 行数 |
| `up` | 逆向填充 | 行数 |
| `right` | 横向排列 | 列数 |
| `left` | 逆向填充 | 列数 |

### offset 计算公式

```
offset = 区域大小 + 空白间隔

例如：
- 证书高度 15 行，留 1 行空白 → offset: 16
- 名片宽度 6 列，留 2 列空白 → offset: 8
```

---

## 常见配置错误

### ❌ 错误 1：index 从 1 开始

```yaml
Name:
  - filed: "姓名"
    index: 1  # ❌ 错误：Excel A 列应该是 index: 0
```

**正确写法**：
```yaml
Name:
  - filed: "姓名"
    index: 0  # ✅ 正确：A 列 = 0，B 列 = 1，以此类推
```

### ❌ 错误 2：offset 等于区域大小

```yaml
sections:
  - input_area: "A1:M15"    # 15 行高度
    move_to: "down"
    offset: 15  # ❌ 错误：没有空白行，区域会紧贴
```

**正确写法**：
```yaml
sections:
  - input_area: "A1:M15"    # 15 行高度
    move_to: "down"
    offset: 16  # ✅ 正确：15 行 + 1 行空白
```

### ❌ 错误 3：忘记 ID 字段

```yaml
Name:
  - filed: "姓名"
    index: 0
    # ❌ 错误：没有任何字段标记为 ID

Phone:
  - filed: "电话"
    index: 1
```

**正确写法**：
```yaml
Employee_ID:
  - filed: "工号"
    index: 0
    ID: true  # ✅ 正确：至少一个字段需要 ID: true

Name:
  - filed: "姓名"
    index: 1
```

### ❌ 错误 4：无效的 move_to 方向

```yaml
sections:
  - input_area: "A1:M2"
    move_to: "diagonal"  # ❌ 错误：只能是 down/up/right/left
    offset: 1
```

**正确写法**：
```yaml
sections:
  - input_area: "A1:M2"
    move_to: "down"  # ✅ 正确：使用有效方向
    offset: 3
```

---

## 进阶技巧

### 1. 复杂布局：先纵向再横向

如果需要先填充一列，再移动到下一列：

```yaml
sections:
  - input_area: "A1:C4"
    move_to: "down"     # 先向下填充第一列
    offset: 5

# Excel 模板应该包含第一列的所有位置
# 程序会自动检测并停止在第一列的末尾
```

### 2. 使用 regex 进行数据验证

```yaml
Phone:
  - filed: "电话"
    index: 4
    regex: "^1[3-9]\\d{9}$"  # 验证手机号格式

Email:
  - filed: "邮箱"
    index: 5
    regex: "^[\\w.-]+@[\\w.-]+\\.\\w+$"  # 验证邮箱格式
```

### 3. 字段顺序优化

将最重要的字段放在前面：

```yaml
order:
  - ID_Field          # ID 字段最先
  - Name              # 姓名其次
  - Primary_Info      # 主要信息
  - Secondary_Info    # 次要信息
  - Optional_Fields   # 可选字段最后
```

---

## 更多帮助

- **完整文档**：[YAML 配置指南](../../docs/yaml_config_guide.md)
- **视频教程**：查看 README 中的链接
- **技术支持**：提交 Issue 或查看 FAQ

---

## 贡献示例

如果您有好的配置示例，欢迎提交 PR：

1. 创建新的 `.paste.yaml` 文件
2. 添加详细注释
3. 在本 README 中添加说明
4. 提供布局示意图（可选）
