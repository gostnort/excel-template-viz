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

## 7. 后续扩展

- 增加更多数据源适配器（CSV、API、Google Sheet 直接连接层）。
- 提供批量 instance 写回策略（并行/分块）和性能指标。
- 增加字段级 transform pipeline（标准化、类型转换、单位换算）。
- 为 `located` 缓存与失效机制提供统一策略，减少重复校验成本。
