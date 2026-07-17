# 数据流设计（core_store）

> 状态：plan（存图 API **尚未在 `core_store` 落地**）  
> 日期：2026-07-09  
> OCR 平台：[`embed_paddle_ocr.md`](embed_paddle_ocr.md)（推理；本文件只定落库与写回）  
> UI 菜单：[`nicegui_ui/nicegui_ui_plan.md`](nicegui_ui/nicegui_ui_plan.md) §3.1

## 1) 目标

`app/core_store.py` 负责存储层：接收来自 UI 或转换层的 `incoming` 数据，按 TOML 的 `Input_label` 规则稳定落库，并对上层提供一致的查询接口。

在现有文本字段持久化之外，本设计扩展“新图片保存功能”：支持原图持久化、图片元数据管理、与 `input_label` / 记录 / 模板三者建立稳定关联，并显式支持后续 Excel 落图数据契约。

**实施缺口（须先补齐再接 NiceGUI 拍照/OCR 写回）**：当前 `core_store` **尚不能**按 `input_label` 保存图片。须先按本文定稿并实现 `save_image` / `get_latest_image` / `list_images_by_label` / `update_image_ocr`，再与 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) 的阶段 E 对接。OCR 推理本身不依赖本模块，可并行开发。

## 2) 边界

### 模块负责
- SQLite 持久化（`records` 以及图片关联表）
- `insert_or_update` 的覆盖写语义（`data` 全量按 TOML 重建）
- 图片原图落盘路径管理与元数据入库
- 图片查询接口（最近一张、按 `input_label`、历史多图）
- 提供 Excel writer 可消费的图片渲染元数据（锚点/偏移/缩放/顺序）

### 模块不负责
- Excel 坐标读写与值格定位（`core_transform`）
- 外部数据源读取、`source_file/source_sheet` 解析（`Template2DB`）
- OCR 算法执行本身（可由上层或插件执行后回填结果）
- UI 组件状态管理（会话、按钮、交互节流）

### 2.1) 模板即库模式（非本模块）

当 UI 中 **取消勾选「使用独立数据库」**（`use_independent_db=false`）时，文本数据**不经过** `core_store`：

| 能力 | 独立数据库（默认） | 模板即库 |
|------|-------------------|----------|
| 文本持久化 | `insert_or_update` → 后缀 SQLite | `ExcelWriter.write_back` → 模板 xlsx（见 [`excel_transform.md`](excel_transform.md) §4.6） |
| 图片 | `save_image` / `get_latest_image` 等 | **不调用**；提交时丢弃 pending `field_images` |
| 输入页容量满 | `input_capacity` 达上限时禁用「下一行」 | **不适用**——无「容量已满」；录入行数由 xlsx instance 自然增长 |
| 写回定位键 | `records.id`（SQLite） | **`instance_k`**（immutable；列头排序后仍用 k 写回，见 [`excel_transform.md`](excel_transform.md) §4.6.5） |
| DB 页「全部数据」 | `ui_provider.get_data()` | `read_instances(template_path)` |

本文件 §4–§9 的 SQLite / `record_images` 契约仅在 **独立数据库** 模式下生效。模板即库的 UI 行为见 [`nicegui_ui/nicegui_ui_plan.md`](nicegui_ui/nicegui_ui_plan.md) §3.1、§3.4。

## 3) 输入输出

### 主要输入
- 文本记录输入：`incoming: dict[Input_label, value]`
- 图片输入：`image_bytes` 或临时文件路径 + 上下文字段（须支持手机常见 **JPEG / PNG / HEIC**；HEIC 解码策略与 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §3.2.1 一致，可复用同一解码路径或在 store 落盘前转成 JPEG/PNG）
- 上下文：`template_id`, `record_id`, `input_label`, 可选 `crop_box`
- 配置对象：`cfg`（含 `Input_label`、`db_id` 等规则）

### 主要输出
- 文本持久化结果：`records.id`, `data`
- 图片持久化结果：`image_id`, `image_path`, `mime`, `width/height` 等
- 查询结果：
  - 指定 `record_id + input_label` 最近一张图片
  - 指定 `record_id + input_label` 全历史
  - 指定 `template_id + input_label` 的跨记录检索（可选）
  - 指定 `record_id + input_label` 的 Excel 落图数据包（供 writer 读取）

## 4) 核心流程

### 4.1 文本落库（既有语义）
1. 基于 TOML 收集全部 `Input_label` 作为 JSON 键集合。
2. `incoming` 命中键写值，缺失键统一补空值。
3. `resolve_db_id(cfg)` 决定 `records.id` 来源（业务 id 或自动 id）。
4. UPSERT 到 `records`，`data` 全量覆盖，禁止 merge 旧 JSON。

### 4.2 图片保存（新增语义）
1. 接收图片输入（bytes/路径）并完成基础校验（非空、mime 可识别）。
2. 生成 `image_id`，按模板与记录组织目录后落盘原图。
3. 解析图片元数据（mime、width、height、hash、size）。
4. 写入图片元数据表，并关联 `template_id + record_id + input_label`。
5. OCR 执行结果写回 `ocr_text/ocr_status` 字段，不影响图片保存主流程。

### 4.3 关联规则
- 一条记录（`record_id`）下，同一 `input_label` 允许多张图片（历史保留）。
- “最近一张”由 `created_at`（或自增 `image_id`）定义。
- `template_id` 作为隔离维度，避免同名 `input_label` 跨模板污染。

## 5) 数据模型建议（图片）

推荐新增 `record_images`（或 `images`）表，字段建议如下：

- `image_id`: INTEGER PRIMARY KEY AUTOINCREMENT  
  图片主键，供稳定引用。
- `template_id`: TEXT NOT NULL  
  绑定模板命名空间。
- `record_id`: INTEGER NOT NULL  
  对应 `records.id`。
- `input_label`: TEXT NOT NULL  
  业务字段关联键，必须与 TOML 语义一致。
- `image_path`: TEXT NOT NULL  
  原图存储路径（建议相对模板目录的相对路径，便于迁移）。
- `mime`: TEXT NOT NULL  
  如 `image/png`, `image/jpeg`。
- `width`: INTEGER  
  图像宽度（像素）。
- `height`: INTEGER  
  图像高度（像素）。
- `file_size`: INTEGER  
  原图字节数。
- `content_hash`: TEXT  
  用于去重或一致性检查（如 sha256）。
- `crop_box`: TEXT  
  JSON 字符串 `{x,y,w,h}`：与**裁剪库**坐标系一致（本期 OpenCV ROI，相对原图左上），与 `paddle_ocr.recognize(crop_box=(x,y,w,h))` 同形；用于局部截图追溯。PaddleOCR 本身不消费该字段。
- `ocr_text`: TEXT  
  OCR **原文**（可空），直接来自 `paddle_ocr` 的 `OcrResult.text`，本层不做清洗；与保存解耦。
- `ocr_engine`: TEXT  
  OCR 引擎标识（可空），如 `paddleocr`。
- `ocr_version`: TEXT  
  OCR 版本（可空）。
- `ocr_status`: TEXT  
  OCR 状态（如 `pending/success/failed/empty`），用于排障与重试；对 UI 展示须映射为中文说明（见 §7）。
- `excel_sheet_name`: TEXT  
  目标工作表名；为空时由 writer 按默认策略推断。
- `excel_anchor`: TEXT  
  落图锚点单元格（如 `B12`）。
- `excel_target_cell`: TEXT  
  等效锚点字段；与 `excel_anchor` 二选一至少一项可解析。
- `excel_offset_x`: INTEGER  
  水平像素偏移，默认 `0`。
- `excel_offset_y`: INTEGER  
  垂直像素偏移，默认 `0`。
- `excel_scale_x`: REAL  
  X 方向缩放，默认 `1.0`。
- `excel_scale_y`: REAL  
  Y 方向缩放，默认 `1.0`。
- `excel_fit_strategy`: TEXT  
  适配策略（建议：`none`/`fit_cell`/`fit_range`）。
- `excel_render_order`: INTEGER  
  同一锚点多图时的渲染顺序，数值越小越先绘制。
- `excel_render_mode`: TEXT  
  同位输出策略（建议：`overlay`/`stack_vertical`/`stack_horizontal`）。
- `created_at`: TEXT NOT NULL  
  UTC 时间戳，ISO8601。
- `updated_at`: TEXT  
  更新元数据时写入。
- `is_deleted`: INTEGER NOT NULL DEFAULT 0  
  软删除标记（0/1）。

推荐索引：
- `(template_id, record_id, input_label, created_at DESC)`：支撑“最近一张”和历史查询。
- `(template_id, input_label, created_at DESC)`：支撑按字段跨记录检索。
- `(template_id, record_id, input_label, excel_render_order, created_at)`：支撑导出排序。
- `(content_hash)`：可选去重辅助索引。

## 5.1 storage -> Excel writer 数据契约（最小集合）

最小必要字段（writer 读取时至少应有）：
- `image_id`, `image_path`
- `template_id`, `record_id`, `input_label`
- `excel_sheet_name`（可缺失）
- `excel_anchor` 或 `excel_target_cell`（至少一项可解析）

用户可控导出开关（计划）：
- `export_attach_images`：是否附图总开关（`on/off`）。
- `export_attach_target_sheet_strategy`：附图目标 sheet 策略（`current_sheet` / `specified_sheet` / `default_sheet`）。
- `export_attach_multi_image_strategy`：单图/多图附着策略（`overlay` / `stack_vertical` / `stack_horizontal`）。
- 当 `export_attach_target_sheet_strategy=specified_sheet` 时，允许上层传入 `export_attach_specified_sheet_name` 作为目标 sheet。

可选增强字段：
- `excel_offset_x`, `excel_offset_y`
- `excel_scale_x`, `excel_scale_y`
- `excel_fit_strategy`
- `excel_render_order`, `excel_render_mode`

缺失字段处理与默认策略（计划）：
- 缺 `excel_sheet_name`：使用当前导出上下文的默认 sheet。
- `excel_anchor` 与 `excel_target_cell` 同时缺失：该图片跳过导出并记录告警。
- 偏移缺失：按 `0,0` 处理。
- 缩放缺失：按 `1.0,1.0` 处理。
- `excel_fit_strategy` 缺失：按 `none` 处理。
- `excel_render_order` 缺失：按 `created_at ASC` 补序。
- `excel_render_mode` 缺失：按 `overlay` 处理。
- 导出开关为 `off`：writer 不读取图片记录，直接走纯文本导出路径。

## 6) 写入/查询/更新语义

### 6.1 写入（save_image）
- 输入：`template_id, record_id, input_label, image payload, optional crop_box`。
- **`input_label` 必填**，且须属于当前模板 TOML 的 `Input_label` 集合；非法标签返回失败（中文 `message`），不写文件。
- 行为：
  - 先持久化原图文件，再写元数据。
  - 若元数据入库失败，尝试回滚文件（或标记待清理）。
  - 成功后返回完整图片元数据对象（含 `image_id`、`ok`、中文 `message`）。
- **不**在本方法内调用 `paddle_ocr`；拍照与 OCR 分离。

### 6.2 查询最近一张（get_latest_image）
- 维度：`template_id + record_id + input_label`。
- 规则：`is_deleted=0` 且按 `created_at DESC LIMIT 1`。
- 为空时返回 `None`，不抛异常。

### 6.3 按 input_label 查询历史（list_images_by_label）
- 维度：`template_id + record_id + input_label`。
- 返回：按时间倒序的图片列表，可带分页参数（`limit/offset`）。

### 6.4 多图历史与更新
- 默认追加写入，不覆盖历史。
- 元数据更新仅允许补充字段（如 `ocr_text`, `crop_box`），不改 `image_id` 和归属键。
- 删除推荐软删除：置 `is_deleted=1`，保留审计能力。

### 6.4.1 OCR 写回（update_image_ocr）
- 输入：`image_id` + 来自 `paddle_ocr.OcrResult` 的字段（`text` → `ocr_text`，`engine`，`version`，以及由 UI 判定的 `ocr_status`）。
- 可选写入本次识别用的 `crop_box`（与裁剪库 / 门面 `(x,y,w,h)` 同形；本期 = OpenCV ROI）。
- `ocr_text` 存引擎原文，store **不**再加工。
- 仅当存在已存 `image_id` 时调用；纯 OCR 未拍照可不写库。
- 返回：`ok` + 中文 `message`（成功/找不到图/写库失败等）。

### 6.5 同记录/同 input_label 的多图输出规则（Excel）
- 排序：先按 `excel_render_order ASC`，再按 `created_at ASC`。
- 覆盖：当 `excel_render_mode=overlay` 时，后绘制图片可覆盖先绘制图片。
- 并列：当 `excel_render_mode=stack_vertical` 或 `stack_horizontal` 时，writer 基于锚点与偏移顺次排布。
- 未显式指定 `excel_render_mode` 时，默认 `overlay`；未显式指定顺序时按创建时间稳定输出。
- 单图场景：按单条记录锚点直接落图，不触发并列排布逻辑。

## 7) 错误处理与降级

对 UI 可见的 store 结果须带中文 `message`（与 `paddle_ocr` 同一约定：不暴露 HTTP 码或英文异常类名）。

| 场景 | 建议中文 `message`（示例） |
|------|---------------------------|
| 存图成功 | 图片已保存。 |
| `input_label` 非法或不属于当前模板 | 字段标签无效，无法保存图片。 |
| 路径不可写 / 存储不可用 | 存储不可用，图片未能保存。 |
| 图片为空或无法识别格式 | 无法读取图片，请重新拍照或选择文件。 |
| 元数据入库失败（已尝试回滚文件） | 图片保存失败，请稍后重试。 |
| 查询无图 | （返回 `None`；若需 notify）当前字段暂无已存图片。 |
| 元数据在但文件缺失 | 图片文件缺失，请重新拍照。 |
| `update_image_ocr` 成功 | 识别结果已保存。 |
| `update_image_ocr` 找不到 `image_id` | 未找到对应图片，无法保存识别结果。 |
| `update_image_ocr` 写库失败 | 识别结果保存失败，请稍后重试。 |

其它规则：

- 文件写入成功但 DB 失败：记录待清理项，避免孤儿文件长期堆积。
- 元数据不一致（如 `mime` 与后缀冲突、width/height 不匹配）：以实际解码结果为准并记录告警。
- OCR 推理异常：图片保存继续成功；`ocr_status=failed`，允许后续重试；**不**回滚已存图片。
- OCR 空结果写回：可标 `ocr_status=empty`，`ocr_text` 为空串。
- `install.bat` 与 OCR：默认安装 OCR；允许 `--skip-ocr`。跳过或安装失败时，运行期由 `paddle_ocr.health_check` / `recognize` 返回中文未就绪说明；**存图仍可用**（与 OCR 解耦）。详见 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §6。
- Excel 导出单图失败（缺图/坏图/解码失败/坐标非法）：仅跳过当前图片并记录告警，不阻断整份导出。

## 8) 清理与生命周期

- 保留策略：
  - 默认保留全历史；
  - 可配置每 `record_id + input_label` 仅保留最近 N 张。
- 删除策略：
  - 首选软删除（`is_deleted=1`）；
  - 周期性任务执行物理删除（DB + 文件双删）。
- GC 建议：
  - 扫描“DB 无记录但文件存在”的孤儿文件；
  - 扫描“DB 有记录但文件缺失”的坏引用并输出修复报告。
- 模板级清理：
  - 删除模板时，按 `template_id` 批量清理图片记录与目录文件。

## 9) 测试要点

- 文本覆盖语义：`data` 始终等于当前 TOML `Input_label` 集合。
- 图片写入成功路径：落盘 + 元数据入库 + 可查询。
- 最近一张语义：多图写入后返回时间最新记录。
- 历史查询：同 `input_label` 多图顺序、分页正确。
- OCR 状态流：`pending/success/failed` 状态转换与重试写回正确。
- 异常回滚：路径不可写、DB 失败、文件缺失场景有可预期状态。
- 生命周期：软删除后默认查询不可见，GC 可清理对应文件。
- Excel 契约读取：保存后 writer 能稳定读取最小字段并完成落图。
- Excel 定位一致性：锚点、偏移、缩放、适配策略缺省时均按默认策略可重复导出。
- 多图规则验证：同 `record_id + input_label` 在 overlay/并列模式下顺序与结果稳定。
- 导出开关验证：`export_attach_images=off` 时无图片输出，且纯文本导出结果与历史一致。
- 缺图/坏图容错：存在异常图片时导出流程不中断，告警信息可追踪到 `image_id`。
- **模板即库**：确认 `use_independent_db=false` 时无 `insert_or_update` / `save_image` 调用路径。

## 10) 后续扩展

- 图片去重（按 `content_hash` 复用底层文件）
- 缩略图与预览缓存（独立于原图）
- OCR 异步队列化（重试、优先级、批处理）
- 结构化视觉特征存储（如表格检测框、关键点）
