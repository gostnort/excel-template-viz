# 数据流设计（core_transform）

该文件为 core_transform 计划主文档。

## 1. 目标

`app/core_transform.py` 负责“转换层”能力：把模板配置、外部数据源、Excel 读写连接成可复用的数据转换流程。该模块输出标准化记录（`dict[Input_label, value]`）并基于坐标完成写回，不承担数据库持久化和 UI 状态管理。

## 2. 边界

### 模块负责
- 外部数据源读取（本地 xlsx / 上层注入后的来源）
- 按 TOML 字段规则做列映射与值转换（含 `regex`）
- 基于 `verify_toml` 定位结果进行坐标读写（label/value 坐标 + instance 平移）
- 导出文件写回、打印区域解析（`print_sheet`）
- 消费 store 提供的图片落图契约并执行图片写入

### 模块不负责
- SQLite 持久化、UPSERT、行主键分配
- textbox 拆分（`determiner` / `index` 的 UI 输入语义）
- 用户会话、草稿态、界面交互状态
- TOML 文件生成与最终校验策略实现（由 `core_toml` 提供）

## 3. 输入与输出

### 主要输入
- 配置对象 `cfg`（来自 `core_toml.GetTomlValues.Load`）
- `verify_toml(template_path, cfg)` 的 `located` 定位结果
- 外部来源标识（如 source id、sheet 名、path 映射）
- 写回目标：模板路径、导出路径、instance 序号、记录数据
- 图片渲染输入：来自 store 的图片元数据与 Excel 渲染字段

### 主要输出
- 标准记录 `incoming: dict[Input_label, value]`（允许缺键）
- Excel 文件更新结果（写入到导出文件）
- 读取实例列表（按 instance k 展开）
- 打印区域元数据（供上层渲染/选择）
- 图片落图结果（成功数量、跳过数量、失败原因摘要）

## 4. 关键流程

### 4.1 字段映射与外部数据读取（Template2DB）
1. 解析 `source_file` / `source_sheet`，定位数据源。
2. 汇总 `id=true` 字段形成 `id_lookup_keys`（`field` 优先，否则 `Input_label`）。
3. 按“全局 OR”查找目标行。
4. 对每条字段规则：
   - 用 `field` 或 `Input_label` 映射数据源列；
   - 应用 `regex`（配置时）抽取值；
   - 写入 `record[Input_label]`（不输出 `field` 名）。
5. 产出 `incoming`，交由上层传给 store 层持久化。

### 4.2 坐标定位与转换写回（ExcelWriter）
1. 使用 `located[Input_label]` 的 instance 0 值格坐标。
2. 对 instance k 按 `input_section.move_to` + `offset` 做平移，仅平移值格。
3. 读取或写入每个 `Input_label` 对应单元格。
4. 批量读取场景中，逐组读取直到整组为空则停止。
5. **模板即库**（`use_independent_db=false`）时，模板 xlsx 即持久化载体；读写契约见 §4.6。

### 4.4 图片落图流程（新增计划）
1. 先读取用户导出开关：
   - `export_attach_images`（`on/off`）
   - `export_attach_target_sheet_strategy`（`current_sheet` / `specified_sheet` / `default_sheet`）
   - `export_attach_multi_image_strategy`（`overlay` / `stack_vertical` / `stack_horizontal`）
2. 当 `export_attach_images=off` 时，直接跳过整段落图流程，不读取 storage 图片记录，保持纯文本导出路径不变。
3. 当 `export_attach_images=on` 时，从 store 拉取 `record_id + input_label` 对应图片列表（过滤 `is_deleted=0`）。
4. 按目标 sheet 策略解析落图 sheet（当前 sheet / 指定 sheet / 默认 sheet），并解析锚点（`excel_anchor` 或 `excel_target_cell`）。
5. 应用偏移、缩放、适配策略（`excel_offset_*`, `excel_scale_*`, `excel_fit_strategy`）。
6. 按稳定顺序（`excel_render_order ASC`，再 `created_at ASC`）执行单图或多图落图；多图策略由 `export_attach_multi_image_strategy` 或记录级 `excel_render_mode` 决定。
7. 记录跳过项（缺锚点、文件缺失、非法坐标、坏图解码失败）并输出导出摘要。

## 4.5 storage -> writer 最小契约（引用）

writer 侧按以下最小字段消费：
- `image_id`, `image_path`
- `template_id`, `record_id`, `input_label`
- `excel_sheet_name`（可缺省）
- `excel_anchor` 或 `excel_target_cell`（至少一项）

缺省策略：
- 缺 `excel_sheet_name`：使用当前写回 sheet。
- 缺锚点字段：跳过该图片并记录日志。
- 缺偏移/缩放：使用 `0,0` 与 `1.0,1.0`。
- 缺 `excel_render_mode`：默认 `overlay`。
- 缺 `excel_render_order`：按 `created_at` 升序。
- 导出开关为 `off`：writer 不访问图片存储接口，导出结果等同纯文本写回。

### 4.6 模板即库（Excel 作数据库）

> UI 编排见 [`nicegui_ui/nicegui_ui_plan.md`](nicegui_ui/nicegui_ui_plan.md) §3.1、§3.4；store 边界见 [`db_store.md`](db_store.md) §2.1。

当用户取消「使用独立数据库」时，**不再经 SQLite 落库**，文本记录的权威来源为模板 xlsx 上的 instance 值格。`core_transform` 提供读写原子能力；会话态（`session_rows`、`draft`）由 UI 维护。

#### 4.6.1 读取：显示值与公式标记

同一组 instance 需区分两类信息：

| 用途 | 打开方式 | 规则 |
|------|----------|------|
| **显示值**（填入 `input_label`） | `data_only=True` | 与 Excel 中用户看到的计算结果一致 |
| **是否公式**（决定是否可编辑） | `data_only=False` | 单元格 `str(value).startswith("=")` → 该 `Input_label` 为公式格 |

建议 API 形态（实现时二选一，文档以语义为准）：

- `read_instances(..., with_formula_mask=True)` 返回 `list[dict[str, Any]]` 值，并附带同结构的 `list[dict[str, bool]]` 公式掩码；或
- 每条记录为 `dict[Input_label, {"value": ..., "formula": bool}]`。

单实例预填（`read_values` / 等价方法）同样返回 value + formula 掩码，供 UI 载入「下一行」编辑区。

`read_instances` 仍按 instance 0 起逐组读取，遇**整组值格皆空**停止（与 §4.2 一致）。`max_instance_count` 已用 `data_only=False` 排除公式格参与块比较（与容量统计一致）。

#### 4.6.2 写回：保护公式格

`write_back` 写入前，对目标模板 xlsx 用 `data_only=False` 检测各 instance 值格：

- 模板中已是公式（`=` 开头）的格：**永不覆盖**，即使 `record[Input_label]` 非空。
- 非公式格：沿用现有语义（空值不覆盖模板既有内容；非空写入）。

独立数据库模式下的「另存为」导出仍走 `write_back` 到 `exports/`，同样跳过公式格。

#### 4.6.3 容量语义（与独立库模式区分）

| 模式 | `max_instance_count` / `input_capacity` 用途 | 「容量已满」 |
|------|---------------------------------------------|--------------|
| **独立数据库**（`use_independent_db=true`） | 限制**内存会话** `session_rows` 行数及「装载文件」载入上限；与模板几何块数对齐 | **有**：`current_instance_index >= input_capacity` 时禁用「下一行」，`ui.notify` 提示 |
| **模板即库**（`use_independent_db=false`） | 仅作参考（如展示已占用 instance 数）；**不**作为「下一行」的前置阻断条件 | **无**：「下一行」在 `verify_report.ok` 时始终可用；新行写入下一空闲 instance，已有行可点击表内行就地编辑 |

模板即库模式下，物理上仍受 Excel 行列与 `input_section` 平移边界约束（`offset_cell` 越界、`16384` 上界）；此类错误在 `write_back` 时失败并返回上下文，**不**预先用「容量 N」拦截录入。

#### 4.6.4 流程编排（模板即库）

- **O(log N) 快速定位与懒加载**：对于万行级超大文件，系统不会直接扫描所有行，而是利用二分查找快速计算 `total_instance_count`。数据装载时，默认只读取最后（最底部）的 50 条记录。
- **UI 倒序排列与插入**：为了确保“最新数据在最上面”，读取出来的最新数据会直接展现在表格顶部。每次新增“下一行”，新记录会被写回 Excel 的最新 `instance_k`，并在 UI 表格的 **第 0 行（最上方）** 插入，且不改变物理文件内的顺序。
- 激活 / 切换为模板即库：`get_total_instance_count()` → 计算总量；`read_instances(..., limit=50, reverse=True)` → UI `session_rows`（**每条附带 `instance_k`**）；`current_instance_index = total_count`；`draft` ← 下一 instance 的 `read_values`。
- 下一行 / 覆盖保存：`write_back` 时**按 `instance_k` 定位**（见 §4.6.5），不得按 UI 表格显示顺序；写完后在内存 `session_rows` 最顶部插入新数据。
- **不**调用 `store.insert_or_update`（见 `db_store.md` §2.1）。

#### 4.6.5 稳定 instance 键与表行 ↔ Sheet 几何

UI 底部表：**一行 = 一条逻辑记录 = 一个 instance `k`**；**一列 = 一个 `Input_label`**。写回、载入 draft、删除、勾选批量操作**必须**使用行上的 **`instance_k`（0-based，与 `read_instances` / `write_back` 一致）**，**禁止**使用排序后的视觉行号或 `tbody` 下标。

| 字段 | 规则 |
|------|------|
| `instance_k` | 载入时由 `read_instances` 顺序赋值（第 0 条 → `k=0`，…）；追加新行时分配下一空闲 `k`；**排序、筛选不改变此值** |
| `session_rows` 内存顺序 | 建议始终保持 `instance_k` 升序；若 UI 做列头排序，仅影响**展示层**（`ui.table` 客户端排序或渲染用排序副本），**不重排**用于 `write_back` 的 canonical 列表 |
| `write_back` | 第 `i` 条记录写入 instance `record.instance_k`（若 API 仍用 list 下标，则 list 必须按 `instance_k` 排序且与 `k` 一一对应）；**不得**假设「列表第 i 项 = instance i」在用户排序后仍成立 |

**`move_to` 与 Sheet 上 instance 的物理方向**（见 [`toml_config_design.md`](toml_config_design.md) §值格平移）：

| `input_section.move_to` | Sheet 上 instance 0,1,2… 沿…扩展 | UI 表行与 Sheet 关系 |
|-------------------------|----------------------------------|----------------------|
| `down` / `up` | **行**（纵向叠放） | 表**行** ≈ Sheet **行**方向的各组填写值 |
| `left` / `right` | **列**（横向叠放） | 表**行** ≈ Sheet **列**方向的各组填写值（标签仍在固定格，仅值格横移） |

`value_from_label` 为 `left` / `right` 只描述**单条 instance 内**标签与值格的左右关系，**不**改变「一表行 = 一 instance」的语义。

**列头排序（仅视图）**：

- 可对 `Input_label` 列排序以便浏览；排序**不改变** `(instance_k, Input_label) → 值格坐标` 的映射。
- 勾选列、`instance_k` 列（若展示）不可排序。
- 行点击载入 `draft`、删除选中、`write_back`、模板即库覆盖保存：用行的 **`instance_k`** 解析数据，不用当前可见行序号。

**独立数据库模式**：`session_rows` 在 **另存为** / 导出写回时同样按 `instance_k`（或追加时分配的序号）映射到 instance 0…n；列头排序后也不得用视觉行号写 Excel。

### 4.3 流程编排位置
- `core_transform` 提供转换原子能力，不做全局编排。
- 编排由上层（UI/CLI）完成：`verify_toml -> fetch/compose incoming -> store insert_or_update -> write_back`。

## 5. 错误处理

- 数据源路径缺失或 `source_sheet` 不存在：返回明确异常或可识别失败状态。
- 查行未命中：返回空记录或约定错误码，不直接写库。
- `located` 缺键或坐标非法：拒绝读写并报告具体 `Input_label`。
- `regex` 处理失败：保持原值或空值（以实现约定为准），记录可追踪信息。
- 写回路径不可写、工作表缺失：立即失败并返回文件上下文。
- 图片契约缺失关键字段：按“单图失败、整体不中断”策略处理并汇总告警。
- 单张图片文件缺失或损坏：仅跳过当前图片，继续导出并输出告警列表。

## 6. 测试要点

- 字段映射：`field` 与 `Input_label` 混合配置时，映射正确且不污染键名。
- `id_lookup_keys`：多 `id` 字段时 OR 语义生效。
- `regex`：提取成功、空匹配、非法表达式三类路径。
- 坐标平移：k=0 与 k>0 的值格一致性，标签坐标不变。
- 读写闭环：`write_back` 后再读同一 instance，值一致。
- 打印区域：多区域、重复内容去重、空区域容错。
- 图片落图契约：最小字段齐备时可稳定落图，缺省策略生效。
- 多图同位策略：overlay/并列模式输出顺序与视觉结果稳定。
- 开关关闭验证：`export_attach_images=off` 时导出文件不包含新增图片对象。
- 锚点附着验证：开关开启后，图片按锚点与目标 sheet 策略正确落位。
- 多图顺序验证：同锚点多图在多次导出中顺序稳定。
- 缺图/坏图容错验证：单图失败不阻断整份导出，告警可追踪。
- **模板即库**：`read_instances` + 公式掩码与 `data_only=True` 显示值一致；公式格 `write_back` 不被覆盖。
- **instance_k**：排序/筛选后 `write_back`、载入 draft、删除仍按 `instance_k` 写对 instance；`move_to=left/right` 时表行对应 sheet 列向 instance。
- **容量**：独立库模式「下一行」在 `input_capacity` 处阻断；模板即库模式无此阻断，仅写回越界时失败。
- 模板即库闭环：激活加载全表 → 编辑 → `write_back` → 再读一致。

## 7. 后续扩展

- 增加更多数据源适配器（CSV、API、Google Sheet 直接连接层）。
- 提供批量 instance 写回策略（并行/分块）和性能指标。
- 增加字段级 transform pipeline（标准化、类型转换、单位换算）。
- 为 `located` 缓存与失效机制提供统一策略，减少重复校验成本。
