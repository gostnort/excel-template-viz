# 数据录入 Tab 控件说明

本文档描述 Gradio 应用「数据录入」Tab 中各控件的设计目的与运行行为，依据 `app/components/gradio_template_form.py`（`build_form_tab` 及关联处理函数）与 `app/gradio_main.py`（Tab 挂载、模板切换）的当前实现编写。

---

## 1. Tab 定位与整体流程

数据录入 Tab 是用户将外部数据（Google Sheet、粘贴文本或手工输入）填入 Excel 模板并导出的主工作区。典型流程为：

1. 在左侧边栏选择模板（触发本 Tab 表单刷新）。
2. 选择工作表与录入方式。
3. 通过 ID 自动查询、粘贴或手工编辑填充各「区域」字段。
4. 可选：从 Google Sheet 批量勾选未处理行并导入。
5. 导出 Excel 或打开打印预览。

Tab 内所有会话数据（表单行、导入选择、脏标记等）均通过 `gr.State` 持有，不使用全局 Python 变量。

---

## 2. 表单数据区

### 2.1 录入方式（`entry_mode`）

**控件类型**：单选（Radio）  
**选项**：`ID Auto`（默认）、`Manual`

**设计目的**：在同一套模板字段上切换两种数据入口策略，避免为「查表填表」与「纯手工/粘贴」维护两套 UI。

| 模式 | 行为 |
|------|------|
| **ID Auto** | 显示「区域选择」下拉框；隐藏「粘贴数据」文本框。用户在 ID 字段失焦后自动从 Google Sheet 拉取并映射字段（见 §6）。 |
| **Manual** | 隐藏「区域选择」；显示「粘贴数据」文本框。用户可粘贴 Tab 分隔行，按 YAML 的 `index` 规则解析并写入当前区域（见 §2.4）。 |

切换模式时同步更新 `entry_mode_state`，并刷新区域选择与粘贴框的可见性（`on_entry_mode_change`）。

---

### 2.2 选择工作表（`sheet_selector`）

**控件类型**：下拉框（Dropdown）  
**标签**：选择工作表

**设计目的**：同一 xlsx 模板可能含多个工作表；字段表头与输入区域均按「当前工作表 + YAML/模板配置」解析。工作表列表来自模板文件（`list_sheet_names`），默认选中顺序为：YAML 中 `worksheet` → 模板元数据 `sheet_name` → 工作簿第一个 sheet（`resolve_default_sheet_name`）。

**行为要点**：

- 用户**主动点选**工作表时走 `sheet_selector.select` → `try_sheet_select`，而非 `.change`，以避免模板刷新时用 stale 状态误触发刷新。
- 切换工作表会调用 `refresh_data_entry_form`：重新读取表头、检测多区域、初始化或保留内存中的 `form_data`。
- 若当前会话存在未保存编辑（`form_session_state.dirty == True`）且目标工作表与已确认工作表不同，则**拦截切换**并弹出未保存确认对话框（见 §2.6）；数据保留在内存中，不会静默丢失。

---

### 2.3 区域选择（`row_selector`）

**控件类型**：下拉框  
**标签**：区域选择（原「选择行」）  
**可见性**：仅在 **ID Auto** 模式且模板已成功解析表头时显示。

**设计目的**：支持**一页多区域**（证书、标签、名片等重复块）。每个选项对应一个可编辑的输入区域（一行表单数据），而非 Excel 物理行号的概念。

**选项标签格式**（`format_row_choice_label`）：

```
{区域范围} — {摘要}
```

- **区域范围**：多区域检测到的 Excel 区域地址（如 `B5:H5`），或单区域时的 `Row N`。
- **摘要**：当前区域中与模板静态默认值**不同**的非空字段值，用 ` | ` 连接（`build_row_brief`），便于快速识别已填内容。

**多区域检测逻辑**（`refresh_data_entry_form` → `_detect_form_areas`）：

1. 从 YAML 第一个 `sections` 条目读取 `input_area`、`move_to`（down/up/left/right）、`offset`。
2. 在工作表上扫描相同结构的重复块（`detect_multi_areas`）。
3. 若无重复块，则退化为 YAML/模板配置的单一 `input_area`。

**交互**：

- 切换选项 → `sync_form_fields_to_row`：将对应行的字段值加载到下方文本框。
- 批量导入预览激活时，区域选择会切换为「当前勾选导入 ID 列表中的第 N 条」，并与 Sheet 行缓存联动（§5.3）。

---

### 2.4 粘贴数据（`paste_input`）

**控件类型**：多行文本框  
**可见性**：仅在 **Manual** 模式且存在已配置字段时显示。

**设计目的**：允许用户从 Excel 复制 Tab 分隔的一行（或多行），按模板 `.paste.yaml` 中的字段 `index` 映射直接灌入表单，无需连接 Google Sheet。

**行为**：

- 提交（Enter）或内容变化且含 Tab/换行时触发解析（`apply_pasted_form_data`）。
- 解析目标区域由「区域选择」当前索引决定；Manual 模式下区域选择隐藏，默认写入第 1 个区域，多行粘贴依次写入后续区域。
- 解析前临时 `interactive=False`，防止重复提交。
- 成功填充后标记会话为 dirty，并清空粘贴框。

---

### 2.5 表单字段网格（`form_field_boxes`）

**控件类型**：最多 40 个动态文本框（`MAX_FORM_FIELDS`），按每行 7 列（`DEFAULT_FIELDS_PER_ROW`，可由 YAML `fields_per_row` 覆盖）排布。

**设计目的**：UI 在构建时固定槽位数量，实际显示哪些字段由模板**输入区域上方表头**决定（`get_form_field_headers` → `read_input_area_headers`），从而支持不同模板字段数量而无需重建页面。

**行为**：

- 刷新时：有表头的槽位显示为对应列名标签并填入值；多余槽位隐藏。
- 任一字段修改 → `form_session_state` 标记 `dirty=True`。
- 导出/打印前，当前文本框内容会通过 `_merge_field_boxes_into_form_data` 合并回 `form_data_state` 中「区域选择」指向的那一行（其余行保留内存中已有值）。

**表头来源优先级**：YAML `sections[0].input_area` → 模板默认输入区域；表头行由模板 `header_row` 指定。

---

### 2.6 下一个（`next_area_btn`）

**设计目的**：在填写完当前区域后，**保存当前文本框到内存**并切换到下一个区域，减少手动在下拉框中查找下一项的操作。适用于多区域批量打印场景。

**行为**（`advance_to_next_area`）：

1. 点击时先禁用按钮，完成后恢复（防连点）。
2. **普通模式**：合并当前字段 → 区域索引 +1；若已是最后一区域则提示「已是最后一个区域」并保持当前项。
3. **批量导入预览激活且存在勾选 ID 列表**：在导入 ID 序列中前进（「已是最后一个选中行」），并通过 Sheet 行缓存重新映射表单字段，区域选择标签同步更新。

每次成功前进会标记表单 dirty。

---

### 2.7 未保存切换确认（`unsaved_switch_group` / `unsaved_save_group`）

**设计目的**：切换**工作表**或**侧边栏模板**时，若用户已编辑但未导出，给出明确选择：继续切换（数据仍保留在内存）或先导出再切换。避免误以为切换会清空数据，也避免无意覆盖未导出成果。

**触发条件**：`form_session_state.dirty == True`，且目标与 `committed_sheet_state` / `committed_template_name_state` 不同。

**对话框步骤**：

| 步骤 | 文案 | 按钮 | 行为 |
|------|------|------|------|
| 1 | 有未保存的更改，是否继续切换？当前数据将保留。 | **是** / **否**（默认） | 是 → 进入步骤 2；否 → 取消切换，保持当前模板/工作表与全部表单数据 |
| 2 | 是否先保存？保存将导出 Excel；返回将留在当前页面。 | **保存并切换** / **返回当前**（默认） | 保存并切换 → 执行与「导出 Excel」相同的写入，再完成挂起的切换；返回 → 关闭对话框，不切换 |

**实现细节**：

- 挂起的目标保存在 `form_session_state.pending`（`type`: `sheet` 或 `template`，`target`: 名称）。
- 拦截切换时 UI 不刷新表单（`_hold_form_refresh_outputs`），避免对话框打开期间字段被重置。
- 用户确认「是」但不保存而完成切换时，仍 **preserve_form_data=True** 刷新布局，内存中的 `form_data` 保留；切换成功后更新 snapshot，清除 dirty（若走了导出路径则 `clear_dirty`）。

侧边栏模板 Radio 通过 `apply_template_and_refresh_form` → `try_template_select` 接入同一套守卫逻辑。

---

## 3. 导出与打印

### 3.1 导出 Excel（`export_btn` + `export_download`）

**设计目的**：将内存中所有区域的表单数据写回模板副本，供用户下载存档或后续在 Excel 中编辑/打印。

**行为**（`handle_export`）：

1. 合并当前文本框到 `form_data`。
2. `build_export_workbook_bytes`：复制模板 xlsx，按检测到的各输入区域写入对应行（跳过公式单元格）。
3. 文件保存至 `exports/` 目录，并通过隐藏的 `gr.File` 触发浏览器下载。
4. 文件名由 `build_export_filename` 根据模板与内容生成。

未选择模板或工作表、无数据时给出 Warning。

---

### 3.2 打印预览（`print_btn`）

**设计目的**：在 Windows 上生成与导出相同的已填充工作簿，并调用系统打印预览对话框（`show_print_dialog`），面向「填完即打」场景。

**行为**（`handle_print_preview`）：

- 数据准备路径与导出一致。
- 读取模板定义的打印区域（`primary_print_area`）；未定义则 Warning。
- 仅 Windows 环境有效（依赖 `excel_print` 模块）。

---

## 4. 批量导入区

批量导入依赖「数据源」Tab 中配置的 Google Sheet 与 OAuth 凭证；历史状态持久化在 `templates/<id>/<id>.history.json`（`import_history` 服务）。

### 4.1 导入统计（`import_stats`）

**控件类型**：Markdown 动态文本

**设计目的**：一眼展示当前模板的导入进度，避免重复处理同一 ID。

**显示内容**（`update_import_stats`）：已处理数量、垃圾数据数量、最后导入时间。模板切换时自动刷新；刷新 Sheet 时显示「正在从 Google Sheet 加载数据...」。

---

### 4.2 刷新未处理数据（`refresh_btn`）

**设计目的**：从 Google Sheet 拉取**尚未**记入「已处理」或「垃圾」的 ID 行，供用户勾选后批量导入表单。

**行为**（`handle_refresh_unrecorded`）：

1. 点击后按钮暂时禁用，统计区显示加载中。
2. `force_refresh=True` 拉取 Sheet（Polars DataFrame），构建 ID → 行字典缓存（`import_sheet_cache_state`）。
3. 预览表列：**选择**（bool）、**ID**、**状态**（「新数据」）、**数据预览**（除 ID 外最多 3 列样本，`|` 分隔）。
4. 最多显示 1000 行（`MAX_IMPORT_PREVIEW_ROWS`），超出时 Warning。
5. 有数据时显示预览表及「导入选中行」「标记为垃圾」「清空历史」；隐藏「恢复为未处理」。
6. 设置 `import_preview_active_state = True`，后续区域选择与「下一个」进入导入联动模式。

---

### 4.3 查看已处理 / 查看垃圾数据

| 按钮 | 目的 | 预览状态列 | 可用操作 |
|------|------|------------|----------|
| **查看已处理** | 审计已导入 ID | 已处理 | 恢复为未处理、清空历史 |
| **查看垃圾数据** | 审计被排除 ID | 垃圾 | 恢复为未处理、清空历史 |

两者均不显示「导入选中行」「标记为垃圾」。仍填充 Sheet 缓存，便于勾选后预览字段映射。

---

### 4.4 导入预览表（`import_preview`）

**控件类型**：可编辑 Dataframe（首列为 checkbox）

**设计目的**：

- **选择**：勾选待导入（或未处理视图中待标记）的行。
- **轻量预览**：勾选变化时**不重新请求 Sheet**，而是用缓存行映射到当前表单字段（`handle_import_preview_selection_change`），让用户在导入前确认映射效果。
- 勾选集合变化时，区域选择切换为导入 ID 列表视图，索引重置为 0。

取消全部勾选时，恢复为普通区域选择行为。

---

### 4.5 导入选中行（`import_btn`）

**设计目的**：将勾选的 Sheet 行正式写入表单内存，并标记为已处理，形成可导出的多行/多区域数据。

**行为**（`handle_import_selected`）：

1. 对每条选中 ID 从缓存或 Sheet 取行。
2. 优先使用 Phi-4 字段匹配器（`create_field_matcher`）将 Sheet 列映射到 YAML 字段；模型不可用时回退规则映射（`map_sheet_row_from_paste_config`）。
3. 每条成功映射追加到 `form_data_state`。
4. ID 写入 `mark_as_processed` 历史。
5. 隐藏预览表，清空导入选择状态，`import_preview_active_state = False`，刷新统计与表单首区域显示。

---

### 4.6 标记为垃圾（`mark_trash_btn`）

**设计目的**：将无需导入的 Sheet 行 ID 记入垃圾列表，后续「刷新未处理数据」会自动排除，避免反复出现在待办列表。

仅在「未处理」预览视图显示。勾选后从预览表移除对应行并更新统计。

---

### 4.7 恢复为未处理（`restore_btn`）

**设计目的**：纠正误标记——将「已处理」或「垃圾」中的 ID 恢复为未处理状态（`unmark_ids`），使其再次出现在刷新列表中。

---

### 4.8 清空历史（`clear_history_btn`）

**设计目的**：重置当前模板的全部导入历史（已处理 + 垃圾），用于测试或模板复用。操作后仅更新统计 Markdown，不自动刷新预览表。

---

## 5. ID 自动查询（ID Auto 模式）

**触发方式**：ID 字段对应文本框 **失焦（blur）** 时，非点击按钮。

**设计目的**：用户只需输入业务主键（YAML 中 `ID: true` 的字段），系统自动从已配置 Google Sheet 拉取整行并按 paste 配置映射到当前区域，减少逐字段复制。

**流程**（`handle_id_field_lookup`）：

1. 仅当录入方式为 ID Auto、非导入预览激活、当前 blur 的字段索引与 YAML ID 字段一致、且值非空时执行。
2. blur 瞬间 ID 框 `interactive=False`，查询结束恢复。
3. 校验 OAuth 凭证与模板数据源配置。
4. `lookup_row_by_id` 查 Sheet → `map_sheet_row_from_paste_config` 映射。
5. 映射结果**合并**进当前区域行（已有手工修改的非空值不被空值覆盖，`_merge_mapped_into_row`）。
6. 成功则 Info 提示并标记 dirty；未找到 ID 或网络错误则 Warning。

批量导入预览激活期间 ID 查询 deliberately  no-op，避免与导入选择逻辑冲突。

---

## 6. 与侧边栏模板选择的关系

模板 Radio 位于主界面左侧边栏（`gradio_main.py`），不在 Tab 内部，但驱动本 Tab 的初始与切换刷新：

- 选择模板 → `apply_template_and_refresh_form` → `try_template_select`。
- 加载 sheet 列表、默认 sheet、刷新表单、更新导入统计。
- 与切换工作表共用 §2.7 未保存守卫。

用户在同一 Tab 内完成「选模板 → 选 sheet → 填表 → 导出」闭环；数据源 OAuth 在另一 Tab 配置，本 Tab 只消费凭证与模板侧 data source 配置。

---

## 7. 关键状态变量（供调试）

| State | 含义 |
|-------|------|
| `form_data_state` | 各区域字段值列表 `list[dict[str, str]]` |
| `detected_areas_state` | 多区域检测结果 |
| `entry_mode_state` | ID Auto / Manual |
| `form_session_state` | dirty、snapshot、pending 切换、dialog_step |
| `committed_sheet_state` | 已确认的工作表（守卫对比用） |
| `committed_template_name_state` | 已确认的模板显示名 |
| `import_selection_state` | `{ids: [...], index: n}` 导入预览勾选序列 |
| `import_preview_active_state` | 是否处于导入预览联动模式 |
| `import_sheet_cache_state` | ID → Sheet 行字典 |
| `import_view_state` | `unprocessed` / `processed` / `trash` |

---

## 8. 配置与外部依赖

| 依赖 | 影响控件 |
|------|----------|
| 模板 xlsx + 输入区域 | 字段网格列名、区域检测、导出写入位置 |
| `.paste.yaml` | 字段 index、ID 字段、sections 多区域、worksheet 默认 |
| 模板 data source JSON | ID 查询、批量导入的 Sheet URL / 工作表 / ID 列 |
| Google OAuth（数据源 Tab） | 刷新、ID 查询、导入 |
| `.history.json` | 导入统计、未处理过滤 |
| Phi-4 模型（可选） | 批量导入时的语义字段匹配 |

更详细的 YAML 字段说明见项目根目录 `docs/yaml_config_guide.md`。

---

## 9. 已知 UI 约束

- 表单字段槽位上限 40；超出 YAML/表头定义的字段无法在 UI 编辑（需调整模板或配置）。
- 导入预览单次最多 1000 行，防止 Gradio 前端与内存压力过大。
- 打印预览依赖 Windows 与模板打印区域定义。
- Manual 模式下无区域选择 UI，粘贴与字段编辑默认针对第 1 区域索引，多行粘贴可顺序填充后续区域。

---

*文档版本：与 `gradio_template_form.build_form_tab` 实现同步。实现变更时请优先更新本文档。*
