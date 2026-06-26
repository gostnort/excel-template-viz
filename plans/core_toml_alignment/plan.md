# core_toml TOML 配置对齐 — Speckit 索引

**唯一权威蓝本**：[`docs/toml_config_design.md`](../../docs/toml_config_design.md)

本计划只服务于 `app/services/core_toml.py` 按当前 TOML 设计稿重写，不处理 UI、`core_transform.py`、历史 TOML、旧 `sections` 兼容或模板切换流程。

| 文件 | 用途 |
|------|------|
| [`spec.md`](spec.md) | `core_toml.py` 的数据结构、读写、默认生成、校验 API 规格 |
| [`tasks.md`](tasks.md) | 可执行任务列表 |
| [`constitution.md`](constitution.md) | 实现边界与不可妥协约束 |

实施代码：

- `app/services/core_toml.py` — TOML 读写、默认生成、`verify_toml()` 校验报告
