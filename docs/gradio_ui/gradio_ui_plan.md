# Gradio UI 实施计划（基于 core*.py）

## 概述

全新 Gradio 界面，仅依赖 `core_*.py`。**界面文案纯中文**；英文（`data_input` / `toml_config` / `Input_label` 等）仅作代码标识，不出现在界面上。

不考虑既有 `gradio_*.py`、YAML 或历史路径。

**依赖模块**：

| 模块 | UI 用途 |
|------|---------|
| `core_registry.py` | 左侧模板列表 `SortTemplates` |
| `core_toml.py` | 输入配置（toml_config） |
| `core_store.py` | 存储配置（db_config）、输入页落库与读表 |
| `core_transform.py` | 输入页数据源拉取、写回、打印区域 |

**线框图（三张，旧版已废弃）**：

| 文件 | 对应页 |
|------|--------|
| [`gradio_ui_index.html`](gradio_ui_index.html) | 主界面 · 输入（含侧边栏 + 拖拽条） |
| [`gradio_ui_toml.html`](gradio_ui_toml.html) | 输入配置（仅顶部 Tab） |
| [`gradio_ui_db.html`](gradio_ui_db.html) | 存储配置（仅顶部 Tab） |

---

## 整体布局

```
┌─────────────────┬──┬──────────────────────────────────────────┐
│  模板侧边栏      │▐ │  [ 输入 ]  [ 输入配置 ]  [ 存储配置 ]        │
│  销售模板        │▐ │                                          │
│  订单模板        │▐ │           （当前 Tab 内容区）               │
│  …              │▐ │                                          │
└─────────────────┴──┴──────────────────────────────────────────┘
                  ↑
           拖拽条 / 折叠钮（平时隐藏，悬停显示）
```

侧边栏与拖拽条是**全局**组件，三个 Tab 共用。线框中 toml / db 两页省略侧边栏只为聚焦内容；实际应用里侧边栏始终在左。

### 左侧 — 模板侧边栏

| 行为 | 实现要点 |
|------|----------|
| 列出模板 | `SortTemplates.UpdateJson()` → 时间线 / `templates[]`，显示中文名 |
| 点击切换 | 重载 `template_id`、`cfg`、`db`、`ui`、`writer`、`t2db`；更新 `LastUseTemplate` |
| 高亮当前 | 与 `gr.State.template_id` 同步 |

### 拖拽条（侧边栏与主区之间）

| 行为 | 实现要点 |
|------|----------|
| 平时 | 几乎不可见（约 2–6px 命中区，透明） |
| 悬停 | 显示竖条，光标 `col-resize` |
| 拖拽 | 改侧边栏宽度，限 120–400px |
| 记忆宽度 | `localStorage`（如 `etv_sidebar_width`）持久化 |
| 单击 | 折叠 / 展开，状态同样持久化 |

Gradio 侧：`Blocks(css=..., js=...)` 注入；侧边栏与主区用并列 Column，JS 改宽度。

### 右侧 — 三个 Tab

| 代码名 | 界面标签 |
|--------|----------|
| `data_input` | 输入 |
| `toml_config` | 输入配置 |
| `db_config` | 存储配置 |

---

## 会话状态（`gr.State`）

| 键 | 类型 | 说明 |
|----|------|------|
| `template_id` | `str` | 当前模板 |
| `template_path` | `Path` | xlsx 路径 |
| `cfg` | `GetTomlValues` | 当前 TOML |
| `db_path` | `Path` | 当前库 `temp/{id}.A2026` |
| `db` | `SecureSQLite` | 连接 |
| `ui` | `UiProvider` | 表单列 + 落库 |
| `writer` | `ExcelWriter` | 写回 / 区域 / 打印区 |
| `t2db` | `Template2DB` | 按 ID 拉源 |
| `current_section_index` | `int` | 当前承接数据的区域序号（0-based，`detect_areas` 顺序） |
| `draft` | `dict` | 上方各 input 的 `Input_label → 值` |
| `session_rows` | `list[dict]` | 本次会话已录入的记录列表（驱动底部列表） |
| `session_table_event` | `dict` | HTML5 表格 JS 回传的动作：点击行、勾选、删除等 |
| `suppress_id_search` | `bool` | 由幽灵框拆分填充时置 True，防止误触发 ID 自动搜索 |
| `pending_id_value` | `Any` | ID 冲突询问弹窗暂存的待查 ID |
| `exported_files` | `list[Path]` | 本模板历次「另存为」产出的 xlsx 路径（供打印文件下拉） |
| `last_export_path` | `Path \| None` | 最近一次另存为路径；打印文件下拉默认选中 |
| `active_db_suffix` | `str` | 当前正在使用的库后缀（如 `A2026`），与下拉比对以控制「切换」按钮 |
| `sidebar_collapsed` / `sidebar_width_px` | — | 侧边栏 UI 状态 |

选模板后初始化：`EnsureExists` → `Load` → `default_db_path` → 构造 `UiProvider` / `ExcelWriter` / `Template2DB`。

---

## Tab「输入」（data_input）

### 布局（自上而下）

```
（幽灵输入框 — 几乎无边框）
ID#           [____]   ← 焦点切走时自动查数据源
姓名          [____]
…             （ui.get_labels() 动态生成）
─ 本次已录入列表（勾选 / 点击载入）───────
  ☑ 8129  Clark Kent  …
  ☐ 250   狗蛋        …
  [ 清空 ]                         [ 删除 ]
──────────── 分隔线 ────────────
[ 另存为 ]                         [ 下一行 ]
[ 打印文件 ▼ （空） ] [ 打印区域 ▼ Input_sheet, A1:D4 ] [ 打印 ]
```

### 1. 幽灵输入框（顶部）

| 项 | 说明 |
|----|------|
| 控件 | `gr.Textbox`，`show_label=False`，自定义 CSS 去边框、浅色 placeholder「粘贴整行数据…」 |
| 触发 | **`.blur()`（切换焦点）** → `ui.record_from_textbox(raw)` 拆分 |
| 结果 | 拆分值写入 `draft` 并填入下方各 input；**置 `suppress_id_search=True`** |
| 分隔符 | `cfg.determiner` |

### 2. 标签 + 输入列

| 项 | 说明 |
|----|------|
| 生成 | `labels = ui.get_labels()`，每项一行：中文标签 + `gr.Textbox` |
| 绑定 | 读写 `draft[Input_label]` |
| 主键列 | `id=true` 的 `Input_label`，标签旁标「★主键」 |

### 3. ID 自动搜索 与 幽灵拆分的**互不冲突**

两者都绑 `.blur()`，靠「真实焦点离开」区分，且加守卫标志：

- **幽灵框 blur** → 拆分填充（含 ID 框的值）。程序写值**不会**让 ID 框失焦，故不会触发 ID 搜索。同时置 `suppress_id_search=True`。
- **ID 框 blur**（用户手动编辑后离开）→ 若 `suppress_id_search` 为 True 则消费该标志并跳过本次；否则进入 **ID 解析流程**（见下）。
- ID 解析执行中 ID 框 `interactive=False`。

要点：**自动搜索只认焦点切换**，不依赖任何按钮；幽灵框整段填充不应被误判为用户在 ID 上的编辑。

#### ID 解析流程（含库内旧数据询问）

```
ID 框 blur（且未 suppress）
  → 规范化 id_value
  → row = db.query_by_id(id_value)
  → if row 存在:
        弹出询问（gr.Modal 或双按钮确认）:
          「从数据源重新读取」 | 「从数据库读取」
        暂存 pending_id_value = id_value
     else:
        直接 t2db.fetch_row_by_id(id_value) → merge draft
```

| 用户选择 | 行为 |
|----------|------|
| **从数据源重新读取** | `t2db.fetch_row_by_id(pending_id_value)` → merge 进 `draft`，刷新各 input |
| **从数据库读取** | `db.query_by_id(pending_id_value)` → 去掉顶层 `id` 键后载入 `draft`，刷新各 input |

库内无该 ID 时**不弹窗**，直接走数据源拉取；数据源未配置或查无结果 → `gr.Warning`，其余字段不动。

### 4. 本次输入列表（最后一个 input 下、分隔线之上）

| 项 | 说明 |
|----|------|
| 控件 | **HTML5 自定义表格**（`gr.HTML` 渲染），不使用 `gr.Dataframe` |
| 数据 | `session_rows`：每成功录入一条 → 追加一行 |
| 列 | 勾选 + 关键列（`id` + 部分 `Input_label`） |
| 点击行 | 该行数据载入上方各 input（`draft` 覆盖），便于编辑 |
| 左按钮 | **清空**：清空整个列表（仅会话列表层；不删库） |
| 右按钮 | **删除**：删除勾选行 |

列表让用户随时看到「本次录入了多少 / 哪些」。

实现方式：

- 后端根据 `session_rows` 生成 `<table>` HTML：每行带 `data-row-index` / `data-record-id`，checkbox 带稳定标识。
- JS 监听表格行点击、checkbox change、清空、删除按钮。
- JS 将动作写入一个隐藏组件（如隐藏 `gr.Textbox` / `gr.JSON`），内容为 JSON：`{"action": "load_row", "row_index": 1}`。
- 隐藏组件 `.change()` 触发 Python handler，更新 `draft`、`session_rows` 和 HTML 表格。
- 行高亮、勾选状态、删除预览都由 HTML5 + JS 控制；Python 只保留权威状态。

不用 `gr.Dataframe` 的原因：它不提供稳定的「点击某行」事件，也不适合做行高亮、checkbox 勾选、删除勾选行这类交互。

外观要求：HTML5 表格仍按线框中的表格样式呈现，视觉上不需要像浏览器默认表格；用 CSS 统一边框、表头底色、行 hover、高亮行、checkbox 列宽。换成 HTML5 的目的只是获得交互能力，不是改变用户看到的表格风格。

### 5. 分隔线下的操作区

#### 另存为（左） / 下一行（右）

| 按钮 | 行为 |
|------|------|
| **另存为** | 见下文「另存为 xlsx 命名规则」；**不弹保存对话框**，按规则直接写出文件 |
| **下一行** | ① `ui.persist_fields(draft)` 保存当前行并追加到 `session_rows`；② 按 TOML `sections.move_to` / `offset` 方向 `current_section_index += 1`（对应 `detect_areas` 的下一区域）；③ 清空上方 input，等待下一条录入 |

「下一行」= **保存 + 按 TOML 方向切到下一个承接数据的区域**（不是切 DB 记录）。

#### 区域顺序与越界检查

「下一行」不能只做 `current_section_index += 1`，必须依赖一个已验证的区域序列：

1. 读取当前 TOML 的 `sections[0]`。
2. 根据 `input_area` / `move_to` / `offset` 生成候选区域序列。
3. 用模板实际内容检测候选区域是否仍属于同一组承接区域。
4. 得到有序 `areas` 后，`current_section_index + 1 < len(areas)` 才允许切下一行。
5. 若区域不足，提示「已到最后一个区域」，不清空当前输入。

建议在 `core_transform.ExcelWriter` 增加一个公开方法，而不是让 Gradio 层自己计算：

```python
def detect_section_areas(self, excel_path: Path, section_index: int = 0) -> list[dict[str, Any]]:
    ...
```

返回结构沿用并扩展现有 `detect_areas` 风格：

```python
[
    {
        "index": 1,
        "area": "A2:G2",
        "start_row": 2,
        "start_col": 1,
        "end_row": 2,
        "end_col": 7,
    },
    ...
]
```

为什么不只返回 `"A2:G100"`：这个范围丢失了每一条记录对应哪个承接区，`write_back` 时仍要重新拆分，容易错位。  
为什么不只返回坐标：UI / 日志 / `write_back` 都需要 A1 字符串。  
因此推荐同时返回 `area` 字符串和数值坐标；`area` 给 UI 与写回，坐标给越界检查和调试。

现有 `detect_areas` 已接近这个目标；若保留原名，也应明确它返回的顺序就是 `sections.move_to` / `offset` 推导出的承接顺序，并在越界时停止。

#### 另存为 xlsx 命名规则

**不询问用户路径**；点击「另存为」后按下列规则生成文件并 `write_back`：

| 项 | 规则 |
|----|------|
| 目录 | `exports/{template_id}/`（不存在则创建） |
| 文件名 | `{template_id}_{db_suffix}_{YYYYMMDD}_{HHMMSS}.xlsx` |
| `db_suffix` | 当前库后缀，如 `A2026`（来自 `db_path`） |
| 写入内容 | `session_rows` 中全部记录（若无则仅当前 `draft` 落库后那一行） |
| 区域 | `writer.detect_areas(template_path)` 得到的 areas，与记录条数 zip |

示例：`exports/sample_template/sample_template_A2026_20260625_143052.xlsx`

成功后：

1. 路径追加到 `exported_files`（去重，新文件排最前）
2. `last_export_path` 更新为该路径
3. **打印文件** Dropdown 刷新并**默认选中**此文件
4. `gr.Info` 提示完整路径（仅通知，非对话框）

#### 打印文件 + 打印区域 + 打印（同一行紧挨）

| 控件 | 说明 |
|------|------|
| **打印文件** Dropdown | 选项来自 `exported_files`（本模板历次另存为产出）；**平时可为空**（placeholder「选择文件…」）；另存为成功后默认选中新文件；用户可改选其他已导出文件 |
| **打印区域** Dropdown | 对**所选 xlsx** 调用 `writer.get_print_areas(所选路径)`；每项 `{sheet_name}, {print_area}` |
| **打印** | 紧挨打印区域右侧；对所选文件打开 Windows 系统打印对话框（`os.startfile(path, "print")` 等）；未选文件时 `gr.Warning`；非 Windows 降级为下载提示 |

打印**不再**临时 `write_back`；以用户选定的已导出 xlsx 为准。

### 6. 按钮统一尺寸

清空 / 删除 / 另存为 / 下一行 / 打印 等所有按钮**等宽等高**（如 110×36），通过统一 CSS 类设定。

---

## Tab「输入配置」（toml_config）

TOML 编辑，影响输入页列定义与拉源行为；保存后刷新输入页动态表单。

| 区块 | 内容 | core API |
|------|------|----------|
| 基础 | 分隔符、工作表 | `GetTomlValues` + `Save` |
| 数据源 | `[[sources]]` 表格 | `Save` |
| 区域 | `[[sections]]` 输入区域 / 方向 / 偏移 | `Save`；「检测区域」只读 `writer.detect_areas` |
| 字段 | `[[fields]]` 全列 | `Save` + `Validate` |
| 高级 | TOML 全文 | `Save(toml_text=...)` |
| 操作 | 生成骨架 / 重置 | `TomlGenerator` |

仅落盘 TOML，不写 DB。

### TOML 保存后的 UI 刷新

保存 TOML 后必须整套重建依赖当前配置的对象，禁止沿用旧实例：

1. `cfg = GetTomlValues.Load(template_id)`
2. `ui = UiProvider(cfg, db)`
3. `t2db = Template2DB(cfg)`
4. `writer = ExcelWriter(cfg)`
5. 重新生成输入页动态字段
6. 重新检测 `areas = writer.detect_areas(template_path)`
7. 清空 `draft`
8. 清空 `session_rows`
9. 重置 `current_section_index = 0`
10. 清空 `suppress_id_search` / `pending_id_value`

这样可以避免「字段已删但 input 还在」「旧数据源路径仍被使用」「下一行还指向旧 sections」这类残留状态。

---

## Tab「存储配置」（db_config）

当前模板的 SQLite 库（`temp/{template_id}.{Letter}{Year}`）管理与全量数据查看。

| 区块 | 内容 | core API |
|------|------|----------|
| 当前数据库 | 显示并指定本模板**当前使用**的库；下拉同年全部库 | `default_db_path` / `list_db_paths` |
| **切换** | 仅当 Dropdown 选项 ≠ `active_db_suffix` 时可点；确认后切库、重建连接、刷新数据表 | `SecureSQLite` + `UiProvider` |
| **新建库** | 始终可用；同年下一字母并设为 active | `allocate_next_db_path` |

**「切换」按钮交互**：

- 初始与每次切库成功后：`interactive=False`（灰显不可用）
- Dropdown `.change()`：若选中值 ≠ `active_db_suffix` → `interactive=True`；若改回当前库 → 再置 `False`
- 点击「切换」：执行切库 → 更新 `active_db_suffix` → 按钮恢复不可用
| 全部数据 | HTML5 只读表：`id` + 全部 `Input_label`，带勾选 | `ui.get_data()` |
| 覆盖录入 | **选中某行**后，在粘贴框输入整段数据 → 按分隔符覆盖该记录并保存 | `record_from_textbox` → `persist_fields`（同 `records.id` 覆盖） |

「数据库直接输入文字」的入口放在此页：选行 → 粘贴 → 覆盖保存。Excel 写回 / 打印只在「输入」页。

---

## 事件流（输入页核心）

```
幽灵框 blur
  → record_from_textbox → 填 draft + 各 Textbox → suppress_id_search=True

ID 框 blur
  → if suppress_id_search: 消费标志, 跳过
    else if db.query_by_id 有记录: 弹窗询问数据源 / 数据库
    else: fetch_row_by_id → merge draft → 刷新其余 Textbox

下一行 click
  → persist_fields(draft) → session_rows.append
  → current_section_index++（按 move_to/offset）
  → 清空 inputs

另存为 click
  → 汇总 session_rows（或当前 draft）
  → 按命名规则 write_back → exported_files / last_export_path 更新
  → 打印文件 Dropdown 默认选新文件 → gr.Info

HTML5 表格 click
  → JS 写隐藏事件组件
  → Python 按 row_index 载入该行到 inputs（draft 覆盖）

清空 click → 清空 session_rows
删除 click → 移除勾选行

打印 click
  → 校验已选打印文件 → 系统打印对话框（所选 xlsx）

TOML 保存 click
  → Save
  → Load 新 cfg
  → 重建 UiProvider / Template2DB / ExcelWriter
  → 清空 draft / session_rows / current_section_index
  → 重新渲染输入页字段和区域状态
```

防双提交：触达 DB / 文件 / 数据源的按钮与拉源过程 `interactive=False`，完毕恢复。

---

## 文件布局建议

```
app/components/
  gradio_app.py              # Blocks：侧边栏 + 拖拽条 + 三 Tab
  gradio_layout_sidebar.py   # 模板列表 + 折叠/宽度 JS
  gradio_tab_data_input.py   # 输入
  gradio_tab_toml_config.py  # 输入配置
  gradio_tab_db_config.py    # 存储配置
  gradio_session.py          # State 初始化、切模板
app/services/
  print_windows.py           # 可选：Windows 打印封装
```

---

## 与 core API 对照

| 用户动作 | 调用 |
|----------|------|
| 点侧边栏模板 | `SortTemplates` + 会话初始化 |
| 幽灵框拆分 | `UiProvider.record_from_textbox` |
| ID 焦点切走（库无记录） | `Template2DB.fetch_row_by_id` |
| ID 焦点切走（库有记录） | 询问后：`fetch_row_by_id` 或 `db.query_by_id` |
| 下一行 | `persist_fields` + 按 `sections` 切区域 |
| 另存为 | `ExcelWriter.write_back` → `exports/{id}/{id}_{suffix}_{时间}.xlsx` |
| 打印文件列表 | `exported_files`（会话 + 扫描 `exports/{template_id}/`） |
| 打印区域列表 | `ExcelWriter.get_print_areas(所选xlsx)` |
| 改 TOML | `GetTomlValues.Save` |
| 指定 / 新建库 | `default_db_path` / `list_db_paths` / `allocate_next_db_path` |
| 覆盖录入 | `record_from_textbox` → `persist_fields` |

---

## 分阶段实施

### Phase 1 — 壳 + 侧边栏 + 输入页骨架

- 三栏布局、拖拽条 CSS/JS、宽度记忆与折叠
- 侧边栏模板列表、切模板、State 初始化
- 输入页：幽灵框 + 动态字段 + 占位按钮

### Phase 2 — 输入页业务

- 幽灵框 blur 拆分；ID blur 拉源；`suppress_id_search` 互斥
- HTML5 本次输入列表（追加 / 勾选 / 清空 / 删除 / 点击载入）
- 下一行（落库 + 使用已验证 `areas` 顺序切区域，处理区域不足）

### Phase 3 — 另存为与打印

- `write_back` 另存
- `get_print_areas` Dropdown + 紧邻打印钮 + Windows 打印对话框

### Phase 4 — 输入配置 + 存储配置

- toml_config 完整编辑与保存后刷新输入页
- db_config 指定/新建库、全部数据、选行覆盖录入

---

## 验收标准

1. 侧边栏列出模板；拖拽改宽刷新后仍记住；单击折叠再展开。
2. 三个 Tab，标签为「输入 / 输入配置 / 存储配置」，界面纯中文。
3. 幽灵框粘贴并切换焦点后，下方字段自动拆分填充，且**不触发** ID 搜索。
4. 手动改 ID# 并切换焦点：库无记录时自动从数据源回填；库有记录时弹窗询问数据源 / 数据库。
5. 每次录入在底部列表新增一行；勾选后「删除」移除，「清空」清空全部；点击行载回 input 编辑。
6. 「下一行」保存当前并按 TOML 方向切到下一区域；区域不足时提示且不清空 input。
7. 「另存为」按 `{template_id}_{db_suffix}_{日期}_{时间}.xlsx` 直接写出，不弹保存框。
8. 打印文件 Dropdown 平时可空；另存为后默认选新文件；打印区域对所选文件显示 `{sheet_name}, {print_area}`；打印钮紧邻其右。
9. 存储配置「切换」平时不可用，仅 Dropdown 变更后才可用。
10. 所有按钮等宽等高。
11. 存储配置页可指定当前库、查看全部数据、选行粘贴覆盖保存。
12. 会话数据均在 `gr.State`，无模块级用户变量。

---

## 风险

| 项 | 说明 |
|----|------|
| `.blur()` 版本差异 | Gradio 不同版本中 blur / change / 程序写值的触发顺序可能不同。所有程序填值前必须设置 `suppress_id_search=True`；ID blur handler 第一行必须检查并消费该标志。 |
| HTML5 表格事件 | `gr.Dataframe` 不承担点击行、勾选、删除、高亮。本次输入列表与存储配置数据表用 `gr.HTML` + JS + 隐藏组件回传事件实现。 |
| 打印 | core 仅提供 `get_print_areas`。Windows 本地可用系统打印；macOS / Linux / 云端环境降级为下载文件。 |
| 侧边栏拖拽 | Gradio 原生不提供拖拽调宽、折叠、悬停、localStorage 记忆；必须用 `Blocks(css=..., js=...)` 或独立 JS 文件注入。 |
| 区域移动 | `sections.move_to` / `offset` 必须由 core 统一计算并返回有序区域列表；UI 只消费列表，不自行推导，避免越界和错位。 |
| TOML 刷新 | 保存后必须重建 `UiProvider` / `Template2DB` / `ExcelWriter` 并清空会话输入状态，避免旧字段和旧区域残留。 |
| 删除记录 | 列表「删除」目前为会话层；同步删库需后续扩展 `SecureSQLite` |
| Google Sheet | 远程源需先下载到本地再写入 `sources` |
