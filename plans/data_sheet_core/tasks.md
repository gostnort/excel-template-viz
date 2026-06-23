# 数据表格转换核心 — 任务分解

**唯一权威蓝本（不得改写）**：[`docs/data_flow_design.md`](../../docs/data_flow_design.md)  
任务对应蓝本 Phase 1–6，不在此重复蓝本正文。

## Phase 1：模块骨架

- [ ] 创建 `app/services/core_store.py`
- [ ] 创建 `app/services/core_transform.py`
- [ ] 定义 `SecureSQLite`、`UiProvider`、`Template2DB`、`ExcelWriter` 类壳与构造函数
- [ ] 实现 `default_db_path`、`CORE_DB_SUFFIX`
- [ ] 确认 `core_transform` 不 import `core_store`

## Phase 2：`core_store` — textbox 与 SQLite

- [ ] `UiProvider.split_by_determiner(raw, determiner) -> list[str]`
- [ ] `UiProvider.record_from_textbox(raw) -> dict`（`index >= 0` 取段，`field` 映射，`id` 主键）
- [ ] `SecureSQLite.ensure_table`
- [ ] `SecureSQLite.insert_or_update`（JSON `data` 列）
- [ ] `SecureSQLite.query_by_id` / `query_all` / `close`
- [ ] 路径后缀校验（拒绝 `.db` / `.sqlite` / `.sql`）
- [ ] ID 规范化（str / float → int）

**验收**：tab 分隔样例串拆分正确；单条记录可存取。

## Phase 3：`core_transform` — Template2DB

- [ ] `resolve_source_path(sources, source_file_key)`
- [ ] 本地 xlsx 按 `source_sheet` 打开
- [ ] 按 `id=true` rule 列定位行
- [ ] 按 `Input_label` 取列值
- [ ] `apply_regex`
- [ ] 多 rule 合并为一条 `record`（含 sheet1 + sheet2 场景）
- [ ] `generate_auto_id`（无 `id=true` 时）

**验收**：与 `toml_config_design.md` 场景1 期望记录一致。

## Phase 4：`core_transform` — ExcelWriter

- [ ] `_parse_area_range`
- [ ] `_calculate_next_area`（四方向）
- [ ] `detect_areas`（停止条件：模式不一致 / 全空 / 越界）
- [ ] `read_area_rows`（`Input_label` 对表头）
- [ ] `write_back`（按 `Input_label` 列写纯值，不覆盖未映射列）
- [ ] `get_print_areas`（`ws.print_area`）

**验收**：垂直多区域模板可检测、读、写；打印区域可读。

## Phase 5：`core_store` — UiProvider

- [ ] `get_labels()` 顺序与 TOML `field_rules` 一致
- [ ] `get_data()` 仅 `query_all` + JSON 解析
- [ ] 确认不直读 Excel / 不 import `core_transform`

**验收**：`get_data()` 与 DB 内容一致。

## Phase 6：命令行验证

- [ ] `core_transform.py` 添加 `argparse` 入口
- [ ] import `core_store` 串联全流程
- [ ] 打印 `=== 1. 从 Excel / 数据源读取的数据 ===`
- [ ] 打印 `=== 2. 写入 DB 后的数据 ===`
- [ ] 打印 `=== 3. Gradio 可获得的数据 ===`（labels + data）
- [ ] 路径 A 样例：textbox 纯字符串 + determiner
- [ ] 路径 B 样例：`fetch_row_by_id` + 场景1 数据

**验收**：`python app/services/core_transform.py ...` 三段输出一致；不创建 `tests/` 目录。
