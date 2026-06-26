# core_toml TOML 配置对齐 — 约束

## 1. 权威来源

`docs/toml_config_design.md` 是唯一设计来源。实现若与本文冲突，以设计稿为准。

## 2. 修改边界

- 允许修改：`app/services/core_toml.py`
- 允许新增：本 Speckit 计划目录
- 不修改：UI、`core_transform.py`、`section_detector.py`、样例 TOML、README、测试目录

## 3. 不兼容旧格式

- 不保留 `[[sections]]`
- 不保留 `filed`
- 不保留旧 label-in-input-area 语义
- 不为历史 TOML 做迁移或 shim

## 4. 作用域

- TOML 只处理顶层 `worksheet` 指定工作表
- 不处理 Print_sheet
- 不处理模板切换流程
- 不自动修正用户 TOML

## 5. Python 风格

- 路径使用 `pathlib.Path`
- 非条件 import 放在模块顶部
- 不运行自动 formatter
- 保持修改聚焦，不做无关重构
