# Dynamic Wizard Runtime — v2 工程计划

> 替代 2026-08 之前的 Phase A–D 分阶段文档（已删除）。  
> **规格权威：** [`docs/gemma4_dynamic_workflow.md`](../../docs/gemma4_dynamic_workflow.md) v2.0

## 本目录文件

| 文件 | 用途 |
|------|------|
| [HANDOFF.md](./HANDOFF.md) | **交给下一个实施对话**：目的、文件清单、验收命令、Prompt 模板 |
| [tasks.md](./tasks.md) | 可勾选实施任务（按优先级） |
| [file-map.md](./file-map.md) | 运行时代码路径与职责 |

## 核心结论（一句话）

**CLI 跑通 TOML 向导 = 编排正确；NiceGUI 只是把 interrupt 换成表单。LiteRT 单线程，子 agent 串行。**

## 快速验证

```bash
uv run --project bootup python -m llm_gemma4.cli dialog demo --spec toml
```
