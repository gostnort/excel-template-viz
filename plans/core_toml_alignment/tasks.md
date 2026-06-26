# core_toml TOML 配置对齐 — 任务分解

## Phase 1：结构替换

- [ ] 移除旧 `sections` / `filed` 读写逻辑
- [ ] 定义 `input_section` 内存结构与解析函数
- [ ] 为 `TomlDefault` 增加 `value_from_label`、`value_offset`
- [ ] 确保 `ToDict` / TOML 序列化写出新结构

## Phase 2：默认 TOML 生成

- [ ] `CreateDefaultFromTemplate` 读取指定 `worksheet` 或 active sheet
- [ ] 第 1 行非空单元格生成 `[[fields]]`
- [ ] 第 2 行对应范围生成单条 `[[input_section]]`
- [ ] 默认字段定位为 `value_from_label = "down"`、`value_offset = 1`
- [ ] 不逐格扫描、不从 `input_area` 反推标签

## Phase 3：校验 API

- [ ] 实现 `offset_cell(row, col, direction, offset)`
- [ ] 实现 100×100 标签扫描
- [ ] 实现 `input_area` 矩形解析与包含判断
- [ ] 实现 `verify_toml(template_path, cfg)` 报告
- [ ] 缺 label 进入 `missing_labels`
- [ ] 值格越界进入 `out_of_area_labels`
- [ ] 成功项进入 `located`

## Phase 4：读写与保存

- [ ] `Load` 只解析 TOML 文本，不打开 xlsx
- [ ] `Save` 保存当前实例或解析后的 TOML 文本
- [ ] 未映射可选字符串写 `""`
- [ ] `sources` 路径和 `regex` 保留字面量字符串写法

## Phase 5：验证

- [ ] 对 `app/services/core_toml.py` 读取 linter 诊断
- [ ] 如可行，运行最小 Python 导入检查
- [ ] 不修改 UI、`core_transform.py`、样例 TOML 或 README
