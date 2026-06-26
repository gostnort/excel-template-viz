# core_toml TOML 配置对齐 — 技术规格

> **唯一权威蓝本**：[`docs/toml_config_design.md`](../../docs/toml_config_design.md)  
> 本文件仅展开 `app/services/core_toml.py` 的实现细节；冲突时以蓝本为准。

## 1. 交付范围

仅修改 `app/services/core_toml.py`，实现当前 TOML 结构：

- 顶层：`determiner`、`worksheet`、`[[sources]]`、`[[input_section]]`、`[[fields]]`
- `[[input_section]]`：有且仅有一条，含 `input_area`、`move_to`、`offset`
- `[[fields]]`：必有 `Input_label`、`value_from_label`、`value_offset`、`index`、`id`
- `field`、`source_file`、`source_sheet`、`regex` 未映射时内存为 `None`，磁盘写 `""`

不实现旧格式兼容：

- 不读取或写出 `[[sections]]`
- 不读取或写出 `filed`
- 不把 `print_sheet` 或其他工作表纳入 TOML 作用域

## 2. 数据模型

`TomlDefault` 表示一条 `[[fields]]`：

| 属性 | 类型 | 说明 |
|------|------|------|
| `Input_label` | `str` | 工作表内要扫描的标签文本 |
| `value_from_label` | `str` | `up` / `down` / `left` / `right` |
| `value_offset` | `int` | 从标签格到 instance 0 值格的步长 |
| `field` | `str | None` | 标准字段名 |
| `source_file` | `str | None` | `[[sources]]` 别名 |
| `source_sheet` | `str | None` | 外部数据源工作表 |
| `index` | `int` | 粘贴文本拆分索引，base 0；`-1` 表示不用 |
| `regex` | `str | None` | 可选提取规则 |
| `id` | `bool` | 是否作为 ID 字段 |

`GetTomlValues` 表示已加载配置：

- `determiner`
- `sources`
- `field_rules`
- `worksheet`
- `input_section`

## 3. 默认生成

`TomlGenerator.CreateDefaultFromTemplate(template_path, worksheet_name=None)`：

1. 选择 `worksheet_name`；若未传，则使用 xlsx active sheet 名写入 `worksheet`。
2. 只按标准数据库范式生成：
   - 第 1 行非空单元格作为 `Input_label`
   - 第 2 行同列范围作为 `input_area`
   - 每个字段默认 `value_from_label = "down"`、`value_offset = 1`
3. 不逐格扫描标签；不分析非标准布局。
4. 若第 1 行无字段，则生成空 `fields` 骨架并保留 `input_section`。

## 4. `verify_toml()` 校验

UI 只调用 `verify_toml()`。

入参：

- `template_path`
- 已加载的 `GetTomlValues`

返回报告：

```python
{
    "ok": bool,
    "missing_labels": [Input_label, ...],
    "out_of_area_labels": [Input_label, ...],
    "located": {
        Input_label: {
            "label_row": int,
            "label_col": int,
            "value_row": int,
            "value_col": int,
        },
        ...
    },
}
```

校验规则：

1. 只打开 `worksheet` 指定工作表。
2. 每个字段从 `(1, 1)` 重新扫描，范围为 100 行 × 100 列。
3. 找不到 `Input_label` → 计入 `missing_labels`。
4. 找到标签后按 `value_from_label` / `value_offset` 推算 instance 0 值格。
5. 值格不在 `input_area` 内 → 计入 `out_of_area_labels`。
6. 两个列表均为空时 `ok = True`。

`verify_toml()` 只报告问题，不改 TOML、不改 xlsx、不写回坐标。

## 5. 持久化

- 使用 `tomlkit` 读写严格 TOML 1.0。
- 磁盘不写 `null`。
- 可选字符串未映射时写 `""`。
- Windows 路径与 regex 需要时写 TOML 字面量字符串。
