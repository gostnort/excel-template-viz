# Gradio UI 实施约束（基于 core*.py）

## 目的

本文档是给实现者看的约束文档，用来限制 Gradio UI 的编码逻辑，避免把旧设计、历史组件或 UI 自行推导 Excel 坐标的逻辑带回来。

界面文案使用中文。英文名称仅用于代码级别标识，例如 `data_input`、`toml_config`、`db_config`、`Input_label`。

不考虑历史兼容，不沿用旧 `gradio_*.py` 组件。

## 依赖边界

| 模块 | UI 可做的事 | UI 不可做的事 |
|------|-------------|---------------|
| `core_registry.py` | 列出模板、切换模板、记录最近使用 | 自行扫描模板目录以外的位置 |
| `core_toml.py` | `ensure_exists()` / Load / Save / `verify_toml()`；展示校验报告 | 自行扫描 xlsx 标签、修正 TOML、猜坐标 |
| `core_store.py` | 当前库管理、落库、读 DB、文本拆分 | 合并旧 JSON、保留旧字段值 |
| `core_transform.py` | 本地 xlsx 数据源读取、`max_instance_count()` 取容量、`write_back()` 写回、打印区域读取 | 在 UI 层复制 Excel 坐标计算 |
| `core_connect.py` | OAuth 授权、`connect(cfg)` / `disconnect()`、ID 列表、`fetch_fields()` | 自行解析 Sheet URL、自行维护 sheet 缓存文件、改写 TOML 字段映射 |

核心原则：

- UI 负责交互、状态、提示。
- core 负责 TOML 解析、校验、定位、读写。
- UI 不计算标签坐标、不计算值格坐标、不推导 Excel 写入坐标。

## 四个 Tab

| 代码名 | 中文标签 | 职责 |
|--------|----------|------|
| `data_input` | 输入 | 粘贴 / 手动输入 / ID 拉源 / 本次录入列表 / 下一行 / 另存为 / 打印 |
| `toml_config` | 输入配置 | 编辑 TOML、保存、校验当前模板 |
| `db_config` | 存储配置 | 指定当前 DB、查看全部数据、选行覆盖录入 |
| `google_config` | Google 连接 | OAuth 授权、连接状态、主 ID 表单表多选预览、「导入选中行」入库 |

线框：`docs/gradio_ui/gradio_ui_connect.html`。实现契约：`docs/connect_google.md`。

左侧模板侧边栏与中间拖拽条是全局布局，不属于任一 Tab。

## 必须使用的新 TOML 模型

以 `docs/toml_config_design.md` 为准。

必须使用：

- 顶层 `worksheet`
- 单条 `[[input_section]]`
- `[[fields]].Input_label`
- `[[fields]].value_from_label`
- `[[fields]].value_offset`
- `[[fields]].index`
- `[[fields]].id`

禁止继续使用旧模型：

- `sections`
- `sections[0]`
- `detect_areas()` 作为主流程
- 表头行匹配 `Input_label` 作为主写回逻辑
- UI 维护完整 area 列表作为下一行依据

## 模板激活流程

切换模板或启动默认模板时，必须按顺序执行：

1. 根据模板路径得到 `template_id`。
2. `ensure_exists(template_id, template_path, worksheet_name=None)`。
3. `cfg = GetTomlValues().Load(template_id)`（等价于模块级 `load_toml(template_id)`）。
4. 调用 `verify_toml(template_path, cfg)`（等价于 `cfg.VerifyToml(template_path)`）。
5. 如果校验失败：展示问题，禁用输入、下一行、另存为、打印。
6. 如果校验成功：保存 `verify_report` 和 `verify_report["located"]` 到 `gr.State`。
7. 打开当前 DB：`default_db_path(template_id)` + `SecureSQLite`。
8. 构造 `UiProvider(cfg, db)`、`Template2DB(cfg)`、`ExcelWriter(cfg)`。
9. `input_capacity = writer.max_instance_count(template_path)`。
10. 清空 `draft`、`session_rows`，重置 `current_instance_index = 0`。
11. **Google 重连（每次切换模板必做）**：
    - 若上一模板曾连接：`connect_google.disconnect()` → `sheet_operation = None`，`google_connected = False`，清空 Google Tab 表格。
    - 加载**新模板** `cfg` 后，若同时满足：**已 OAuth 授权**、新 TOML 的 `[[sources]]` 中存在被 `fields` 引用的 Google Sheet URL、且 `verify_toml` 已成功 → `authorize()`（静默）→ `connect(cfg)` → `SheetOperation(connect_google)` → 渲染 Google Tab 主 ID 表。
    - 任一条件不满足（未授权、仅本地 xlsx、sources URL 为空、connect 失败）：保持未连接；Google Tab 显示原因，表格禁用。connect 失败时 `gr.Warning`，不阻塞模板其余功能。
12. 同一 `ConnectGoogle` 实例可复用（`gr.State`）；每次 `connect(cfg)` 前必须先 `disconnect()`，避免旧 spreadsheet 内存残留。

`verify_toml()` 的报告是 UI 是否允许录入和写回的前置条件。

## 会话状态

| State | 含义 |
|-------|------|
| `template_id` | 当前模板 ID |
| `template_path` | 当前模板 xlsx |
| `cfg` | 当前 TOML 配置 |
| `verify_report` | `verify_toml()` 返回报告 |
| `located` | `verify_report["located"]`，供 core 写回使用 |
| `db_path` | 当前 DB 路径 |
| `db` | 当前 `SecureSQLite` |
| `ui` | 当前 `UiProvider` |
| `t2db` | 当前 `Template2DB` |
| `writer` | 当前 `ExcelWriter` |
| `input_capacity` | 当前 input_section 最多可承接的数据条数 |
| `current_instance_index` | 当前第几条录入，0-based |
| `draft` | 当前 inputs 中的 `Input_label -> value` |
| `session_rows` | 本次已录入记录，顺序即 instance 顺序 |
| `session_table_event` | HTML5 表格 JS 回传事件 |
| `suppress_id_search` | 防止程序填值误触发 ID 搜索 |
| `pending_id_value` | ID 冲突弹窗暂存 ID |
| `exported_files` | 本模板已导出的 xlsx 列表 |
| `last_export_path` | 最近一次导出的 xlsx |
| `active_db_suffix` | 当前 DB 后缀 |
| `sidebar_width_px` | 侧边栏宽度 |
| `sidebar_collapsed` | 侧边栏是否折叠 |
| `connect_google` | 当前 `ConnectGoogle` 实例（`gr.State`） |
| `sheet_operation` | 连接成功后的 `SheetOperation` 实例；`disconnect()` 后置 `None` |
| `google_connected` | 是否已执行 `connect(cfg)`（模板激活自动或手动重连） |
| `google_sheet_rows` | 主 ID 表浅拷贝（`FetchFieldsResult.sheet_rows` 或 connect 后直接取自 `_tables`） |
| `google_table_event` | 主 ID 表 JS 回传事件（勾选 / 全选 / 取消） |

不要把这些用户会话状态放到模块级全局变量。

## 输入页

### 幽灵输入框

顶部保留一个近似隐藏的输入框，用于粘贴整行文本。

行为：

1. 用户粘贴文本。
2. 输入框 `.blur()`。
3. 调用 `ui.record_from_textbox(raw)`。
4. 将返回值写入 `draft` 和下方 inputs。
5. 设置 `suppress_id_search = True`。

注意：

- 这个输入框只负责拆分，不直接落库。
- 拆分依据是 `cfg.determiner` 和 `[[fields]].index`。
- `value_from_label` / `value_offset` 与文本拆分无关。

### 动态 inputs

根据 `ui.get_labels()` 生成输入项。

主键字段：

- 来自 `id=true` 的 `Input_label`。
- 用户手动修改并切换焦点后，触发 ID 解析流程。

### ID 解析流程

ID 输入框 `.blur()` 时：

1. 第一行检查 `suppress_id_search`。
2. 如果为 True：置回 False，直接返回。
3. 如果为 False：规范化 ID。
4. `db.query_by_id(id_value)`。
5. 如果 DB 已有旧数据：询问用户「从数据源重新读取」还是「从数据库读取」。
6. 如果 DB 无旧数据：直接 `t2db.fetch_row_by_id(id_value)`。

用户选择：

| 选择 | 行为 |
|------|------|
| 从数据源重新读取 | `t2db.fetch_row_by_id(pending_id_value)`，merge 到 `draft` |
| 从数据库读取 | `db.query_by_id(pending_id_value)`，载入 `draft` |

禁止用按钮触发 ID 搜索。ID 搜索只由焦点切换触发。

### 本次录入列表

必须使用 HTML5 自定义表格，不使用 `gr.Dataframe`。

来源：

- 用户在「输入」页手动录入 / 下一行追加。
- 用户在「Google 连接」页勾选行并点击「导入选中行」：`fetch_fields` → `ui.persist_fields` 落库 → 同时追加到 `session_rows`（与手动录入共用同一列表）。

原因：

- 需要点击行载入。
- 需要 checkbox 勾选。
- 需要删除勾选行。
- 需要当前行高亮。
- `gr.Dataframe` 对这些交互支持不稳定。

实现方式：

- 后端根据 `session_rows` 渲染 `<table>`。
- 每行带 `data-row-index`。
- JS 监听点击、勾选、删除、清空。
- JS 将事件写入隐藏组件，例如隐藏 `gr.Textbox` / `gr.JSON`。
- 隐藏组件 `.change()` 触发 Python handler。
- Python 更新 `draft` / `session_rows` 后重新渲染 HTML。

表格外观继续使用线框中的样式：边框、表头底色、hover、高亮行、checkbox 列宽。

### 下一行

“下一行”只处理 UI instance 序号，不计算 Excel 坐标。

点击后：

1. 校验 `verify_report.ok`。
2. 校验 `current_instance_index < input_capacity`。
3. `ui.persist_fields(draft)`。
4. 将当前 `draft` 追加或覆盖到 `session_rows[current_instance_index]`。
5. 如果 `current_instance_index + 1 >= input_capacity`：提示已到最后可承接位置，不清空 input。
6. 否则 `current_instance_index += 1`。
7. 清空 inputs，等待下一条。

UI 只保存：

- `current_instance_index`
- `input_capacity`
- `session_rows`

UI 不保存完整 area 列表。

写回时由 `core_transform` 根据：

- `located`
- `input_section.move_to`
- `input_section.offset`
- `instance_k`

计算真实值格坐标。

### input capacity

UI 需要知道最多可录入多少条，但不需要知道每条对应的 Excel area。

core 已提供真实 API（不是概念 API）：

```python
ExcelWriter.max_instance_count(excel_path: Path) -> int
```

语义：

- 以 `input_section.input_area` 为第一块，按 `move_to` / `offset` 逐块平移。
- 统计与第一块 `cell.value` 完全一致的最大块数，含 instance 0。
- 公式格（`=` 开头）不参与比较。
- 行/列上界 16384；越界或遇到与第一块不一致的块即停止。

UI 用法：

```python
input_capacity = writer.max_instance_count(template_path)
max_instance_index = input_capacity - 1
```

UI 主流程只使用 `input_capacity` / `max_instance_index`。

不要在 UI 中用 `input_area`、`move_to`、`offset` 自行推导坐标。

注意（实现者需知道的边界）：

- `max_instance_count` 只比较 `input_area` 内的 `cell.value`，不看边框、合并单元格、单元格样式，也不看 `input_area` 以外的内容。
- 若 `input_area` 是空白且每块均匀（标准库范式常见），所有平移块都为全空、彼此一致，返回值会一路逼近 16384，相当于“几乎不限量”。此时 UI 不应把 `input_capacity` 当作可见证书槽位数，仅作为“能否继续 +1”的上界。
- 因此“最后一块”的判定要么来自该上界，要么来自 `input_area` 内出现与第一块不同的值；其余结构性边界（边框/版式）core 当前不识别。

### 另存为

“另存为”不询问路径，直接输出 xlsx。

命名规则：

```text
exports/{template_id}/{template_id}_{db_suffix}_{YYYYMMDD}_{HHMMSS}.xlsx
```

行为：

1. 汇总 `session_rows`；若为空，则先保存当前 `draft` 作为一条记录。
2. 调用 `ExcelWriter.write_back(...)`。
3. 写回顺序为 `session_rows[0] -> instance 0`，`session_rows[1] -> instance 1`，依此类推。
4. 成功后更新 `exported_files` 和 `last_export_path`。
5. 打印文件 Dropdown 默认选中新文件。

UI 不向 `ExcelWriter` 传旧 `areas`。

### 打印

打印基于已导出的 xlsx 文件。

控件顺序：

```text
[打印文件 Dropdown] [打印区域 Dropdown] [打印]
```

规则：

- 打印文件 Dropdown 平时可为空。
- 另存为成功后默认选中新文件。
- 打印区域来自 `writer.get_print_areas(所选 xlsx)`。
- 打印区域只用于打印，不参与 TOML 定位。
- Windows 本地可调用系统打印。
- 非 Windows 或云端环境提供下载文件作为降级。

## 输入配置页

### 字段表

字段表必须包含新 TOML 必有键。

| 中文列 | TOML 键 |
|--------|---------|
| 标签 | `Input_label` |
| 值相对标签方向 | `value_from_label` |
| 值偏移 | `value_offset` |
| 数据源列 | `field` |
| 数据源 | `source_file` |
| 数据源工作表 | `source_sheet` |
| 文本序号 | `index` |
| 正则 | `regex` |
| 主键 | `id` |

### 输入区域

只编辑单条 `[[input_section]]`。

| 中文列 | TOML 键 |
|--------|---------|
| 输入值区域 | `input_area` |
| 下一组方向 | `move_to` |
| 下一组偏移 | `offset` |

不要再出现 `sections` 或多条 section 表。

### 数据源 sources

在「输入配置」Tab **唯一**维护 `[[sources]]`：

| 中文列 | 说明 |
|--------|------|
| 数据源键 | 如 `source1`、`source2` |
| 路径 / Google Sheet URL | 本地 xlsx 路径或完整 Google Sheet URL |
| 操作 | 浏览（本地）或粘贴（URL） |

保存后 `connect(cfg)` 从此处读取；「Google 连接」Tab 不重复编辑 sources。

### 校验配置

配置页需要有“校验配置”动作。

行为：

1. 保存或暂存 TOML。
2. 调用 `verify_toml(template_path, cfg)`。
3. 展示：
   - 找不到的标签
   - 重复标签
   - 值格不在输入值区域内的标签
4. 通过后刷新 `verify_report`、`located`、`input_capacity`。

### TOML 保存后的刷新

保存 TOML 后必须：

1. `cfg = GetTomlValues().Load(template_id)`。
2. `verify_report = verify_toml(template_path, cfg)`。
3. 若失败：禁用输入页写入动作，展示错误。
4. 若成功：更新 `located`，并重算 `input_capacity = writer.max_instance_count(template_path)`。
5. 重建 `UiProvider(cfg, db)`。
6. 重建 `Template2DB(cfg)`。
7. 重建 `ExcelWriter(cfg)`。
8. 重新生成输入页动态字段。
9. 清空 `draft`。
10. 清空 `session_rows`。
11. 重置 `current_instance_index = 0`。
12. 清空 `suppress_id_search` 和 `pending_id_value`。

## 存储配置页

职责：

- 指定当前模板使用哪个 DB。
- 新建 DB。
- 查看全部数据。
- 选中某行后粘贴文本，覆盖性保存。

DB 切换按钮：

- 初始不可用。
- Dropdown 变更且不同于 `active_db_suffix` 时可用。
- 切换成功后重新不可用。

全部数据表也使用 HTML5 自定义表格，不使用 `gr.Dataframe`。

覆盖录入：

1. 用户在 HTML5 表格中选中一行。
2. 粘贴整段文本。
3. `record_from_textbox` 得到 `incoming`。
4. 使用选中行 ID 覆盖保存。

## Google 连接页

实现契约见 `docs/connect_google.md`。UI 只调用 `ConnectGoogle` 与 `SheetOperation`，不 import 旧 `google_sheets` / `data_source` 模块。

**不在本 Tab 编辑 `[[sources]]`** — 数据源 URL / 本地路径仅在「输入配置」Tab 的 sources 表维护。

### 分区

| 分区 | 控件 | 行为 |
|------|------|------|
| OAuth 授权 | 上传 oauth_client.json、授权状态、「授权 Google 账号」 | `ConnectGoogle.authorize()`；执行中禁用按钮 |
| 连接状态 | 只读状态、主 ID 表摘要 | 模板激活时若已授权则自动 `connect(cfg)`；本 Tab 无「连接」按钮 |
| 主 ID 工作表 | **单张** HTML5 表：checkbox + 主表全部列（浅拷贝） | 勾选行高亮；数据来自 connect 后的主 ID 表 |
| 导入 | 「全选」「取消全选」「导入选中行」 | 见下方导入流程 |

### 自动连接（模板切换时断开并重连）

数据源随模板变化，**每次切换模板**必须：

```text
disconnect(旧)  →  connect(新 cfg)  （若可用）
```

| 步骤 | 行为 |
|------|------|
| 1 | `connect_google.disconnect()`：清 `_tables` / `_spreadsheets`；`sheet_operation = None` |
| 2 | 判断新模板是否「可连 Google」：已授权 + `fields` 引用的 source 在 `[[sources]]` 中有非空 Google URL |
| 3 | 可连 → `connect(cfg)`（新 TOML 的 sources / sheets）→ `SheetOperation` → 渲染主 ID 表 |
| 4 | 不可连 → 保持断开；表格区禁用并提示（未授权 / 无 Google 源 / connect 失败） |

注意：

- **不**保留上一模板的 sheet 内存；切换即断开。
- OAuth token **不**随 `disconnect()` 清除；跨模板复用授权。
- 用户在本 Tab  newly 授权后：应触发与「切换模板」相同的重连序列（或提示用户切换一次模板）。

### 主 ID 表（单表：多选 + 预览）

- **一张表**同时承担：浅拷贝预览 + checkbox 多选。
- 勾选行加 `selected` 样式高亮（与输入页本次录入列表一致）。
- 不单独展示「字段摘要」表或第二张预览表。
- JS + 隐藏组件回传勾选行 index / id_value。

### 导入选中行

用户勾选一行或多行 → 点击「导入选中行」：

1. 收集勾选行的 `id_value`。
2. `result = sheet_operation.fetch_fields(id_values)`。
3. 对每条 `record`（`found=True`）：
   - `ui.persist_fields(record.data)` → 写入当前 DB（`core_store`）。
   - 将 `record.data` 追加到 `session_rows`（与输入页共用 State）。
4. `gr.Info` 反馈导入条数。
5. 刷新「输入」Tab 的「本次已录入」HTML5 表格（同 `session_rows` 数据源）。

`found=False` 的 ID 跳过并 Warning，不中断其余行。

### ID 与跨表规则（UI 只展示，不在 UI 推导）

- 每个 `(source_file, source_sheet)` 至多一个 `id=true`。
- 无自身 `id=true` 的 sheet 继承已声明 ID 列；多列 OR 匹配由 core 完成。
- 主 ID 表为 TOML 顺序中第一个 `id=true` 的 sheet；表格展示其浅拷贝列。
- `fetch_fields` 仍按 TOML 跨 sheet 取全部 `Input_label` 字段用于入库。

### 与输入页的关系

- **共用 `session_rows`**：Google 导入与手动「下一行」写入同一列表；输入 Tab 立即可见。
- 输入页 ID blur：DB 有记录优先；无记录且 `google_connected` 时可 `fetch_fields([id])` 单条拉源（与批量导入同一套 core API）。

### 禁止事项（本 Tab）

- 禁止重复编辑 `[[sources]]`（属输入配置 Tab）。
- 禁止 UI 自行请求 gspread / 解析 spreadsheet id。
- 禁止在本 Tab 编辑 `fields` 映射。
- 禁止绕过 `core_store` / `ui.persist_fields` 写 DB。
- 禁止模块级变量保存 OAuth 凭据或 `_tables`。

## 事件流

只保留对实现有帮助的事件流。

```text
模板切换
  -> disconnect() 清旧 Google 内存（必做，不论新模板是否用 Google）
  -> ensure_exists
  -> Load TOML（新 cfg）
  -> verify_toml
  -> 成功: 构造 ui/t2db/writer, input_capacity = writer.max_instance_count(path)
  -> 若已授权且新 cfg 含可用 Google sources: connect(cfg), SheetOperation, 渲染 Google Tab 主 ID 表
  -> 否则: google_connected=False, Google Tab 表格禁用
  -> 失败: 展示校验问题, 禁用输入写回动作

幽灵框 blur
  -> record_from_textbox
  -> draft / inputs
  -> suppress_id_search = True

ID blur
  -> if suppress_id_search: consume and return
  -> db.query_by_id
  -> if exists: ask source/db
  -> else: fetch_row_by_id

HTML5 表格事件
  -> JS 写隐藏组件
  -> Python 更新 draft/session_rows
  -> 重新渲染表格 HTML

下一行
  -> persist_fields
  -> session_rows[current_instance_index] = draft
  -> 检查 input_capacity
  -> current_instance_index += 1
  -> 清空 inputs

另存为
  -> write_back(session_rows, located, instance order)
  -> 更新 exported_files / last_export_path

TOML 保存
  -> Load
  -> verify_toml
  -> 重建 ui/t2db/writer
  -> 清空输入会话状态

Google 导入选中行
  -> 勾选主 ID 表行（同表预览+多选，高亮）
  -> fetch_fields(selected_ids)
  -> ui.persist_fields(record.data) 写入 DB
  -> 追加 session_rows
  -> 刷新输入 Tab 本次已录入表格

OAuth 授权（Google Tab）
  -> authorize()
  -> 用户可切换模板触发自动 connect，或点可选「重新连接」
```

## 禁止事项

- 禁止 UI 自行扫描 Excel 标签。
- 禁止 UI 自行计算值格坐标。
- 禁止 UI 保存完整 area 列表作为主流程状态。
- 禁止继续使用旧 `sections` 模型。
- 禁止把 `index` 当 Excel 列号。
- 禁止用 `gr.Dataframe` 实现需要点击行、勾选、删除、高亮的交互表格。
- 禁止 TOML 保存后沿用旧 `UiProvider` / `Template2DB` / `ExcelWriter`。
- 禁止打印逻辑参与 TOML 定位。
- 禁止模块级全局变量保存用户会话数据。

## 风险与降级

| 风险 | 处理 |
|------|------|
| `.blur()` 版本差异 | 程序填值前设 `suppress_id_search=True`；ID blur 第一行检查并消费 |
| HTML5 表格事件 | 使用 JS + 隐藏组件桥接到 Python |
| 侧边栏拖拽 | CSS/JS 注入；宽度和折叠状态写 localStorage |
| 打印 | Windows 本地调用系统打印；其他环境降级下载 |
| TOML 校验失败 | 禁用输入写回动作，只允许修配置 |
| input capacity 不足 | 提示已满，不清空当前输入 |
| Google 未授权 | 跳过自动 connect；Google Tab 表格禁用 |
| Google 导入部分失败 | 跳过 `found=False` 的 ID，其余照常入库 |

## 验收标准

1. 模板切换后必定执行 `verify_toml()`。
2. 校验失败时不能录入、下一行、另存为或打印。
3. 输入配置页字段表包含 `value_from_label` 和 `value_offset`。
4. 输入配置页使用单条 `input_section`，不出现旧 `sections`。
5. 输入页使用 `current_instance_index`，不使用 `current_section_index`。
6. 下一行只基于 `input_capacity` 判断能否继续。
7. xlsx 写回由 core 根据 `located + input_section + instance_k` 完成。
8. HTML5 表格支持点击载入、勾选、删除、高亮。
9. TOML 保存后重建 UI 相关对象并清空会话输入状态。
10. 另存为输出固定命名 xlsx，并更新打印文件 Dropdown。
11. 模板切换：`disconnect(旧)` 后按新 TOML 重连 Google（已授权且 sources 可用时）；不可用时保持断开。
12. Google 相关逻辑仅通过 `core_connect.py`；`[[sources]]` 仅在输入配置 Tab 编辑。
