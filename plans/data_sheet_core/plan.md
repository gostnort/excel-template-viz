# 数据表格转换核心 — Speckit 索引

**唯一权威蓝本（不得改写）**：[`docs/data_flow_design.md`](../../docs/data_flow_design.md)

本目录文档仅作 Speckit 配套索引与技术展开；**分阶段实施、验收标准、风险约束均以蓝本为准**，不在此重复或替代蓝本正文。

| 文件 | 用途 |
|------|------|
| [`spec.md`](spec.md) | API 与数据结构展开（须与蓝本一致，冲突时以蓝本为准） |
| [`tasks.md`](tasks.md) | 可勾选任务（对应蓝本 Phase 1–6） |
| [`constitution.md`](constitution.md) | 约束摘要（对应蓝本「关键原则」与「风险」） |

实施代码：

- `app/services/core_store.py` — `SecureSQLite`、`UiProvider`
- `app/services/core_transform.py` — `Template2DB`、`ExcelWriter`（含 `__main__` 验证）
