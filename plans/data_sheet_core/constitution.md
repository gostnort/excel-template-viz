# 数据表格转换核心 — 设计原则与约束

> **唯一权威蓝本（不得改写）**：[`docs/data_flow_design.md`](../../docs/data_flow_design.md)  
> 本文件仅为蓝本「关键原则」「风险与注意事项」的摘要；冲突时以蓝本为准。

## 1. 交付边界

### 1.1 两个模块、四个类

| 文件 | 类 | 禁止新增 |
|------|-----|----------|
| `core_store.py` | `SecureSQLite`, `UiProvider` | 编排类、门面类 |
| `core_transform.py` | `Template2DB`, `ExcelWriter` | 编排类、门面类 |

### 1.2 依赖规则

- **仅**可 import：`core_toml.py`、`core_registry.py`、Python 标准库
- `core_transform` 额外允许 `openpyxl`
- **禁止** import：`section_detector`、`excel_parser`、`excel_print`、`paste_parse_config` 及一切非 `core_*` 业务模块
- `core_transform` **不得** import `core_store`
- `core_store` **不得** import `core_transform`

### 1.3 验证方式

- 不创建 `tests/` 或 pytest 套件
- 在 `core_transform.py` 的 `__main__` 中命令行打印三段结果

## 2. 数据语义

### 2.1 路径 A — UI textbox

- Gradio textbox 提交**一整段纯字符串**
- `determiner` 负责拆分
- `index` 是拆分后的**段序**（0-based），**不是** Excel 列号
- `index = -1`：不参与 textbox 拆分

### 2.2 路径 B — 外部数据源

- `source_file` → `[[sources]]` 别名
- `source_sheet` → 数据源工作表名
- `Input_label` → 数据源表列标题
- `field` → 标准 DB 键名
- `regex` → 可选二次提取

### 2.3 UI 与 DB

- **Gradio 展示数据必须来自 DB**（`UiProvider.get_data()`）
- textbox 字符串经拆分后 `insert_or_update`，不得绕过 DB 直显

### 2.4 Excel 写回

- 列定位：`sections` 区域内表头匹配 `Input_label`
- 只写单元格**纯值**，不写公式
- 区域检测内建于 `ExcelWriter`，不外包

## 3. 存储

- 后缀：`.mydatax`（禁止 `.db` / `.sqlite` / `.sql`）
- 路径：`TEMPLATES_DIR / template_id / data_store.mydatax`
- `data` 列：`json.dumps`，禁止 `str(dict)`
- ID 入库前规范化

## 4. 代码风格

遵循项目 `.cursor/rules/python-style.mdc`：

- 路径使用 `pathlib.Path`
- 模块顶栏 import（非循环依赖时）
- 不用自动化 formatter 批量改格式

## 5. Gradio 集成约束（上层，本计划不实现）

- 会话状态用 `gr.State()`，禁止全局变量存用户数据
- 数据录入 Tab 依赖 `UiProvider` 供给 labels / data
- 长操作设 `interactive=False` 并用 `gr.Info()` / `gr.Warning()` 反馈

## 6. 禁止事项

1. 新增第五类或 `DataTransformCore` 等编排类
2. 将 `index` 当作 Excel 列索引
3. `core_store` 与 `core_transform` 相互 import
4. 引用非 `core_*` 既有服务实现本功能
5. 引入 pandas（本计划 Excel 仅 openpyxl）
6. 调用 `excel_print` 做打印预览（`get_print_areas` 只读元数据即可）
7. 另建 pytest / `tests/test_core_*.py`

## 7. 成功不可妥协项

1. 两模块、四类与蓝本一致
2. 路径 A / B 语义正确
3. `__main__` 三段命令行输出可复现
4. UI 数据路径经 DB，不直读 Excel
