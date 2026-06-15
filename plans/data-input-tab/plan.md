# 数据录入 Tab 文档计划

## 概述

本计划为 excel-template-viz Gradio 界面「数据录入」Tab 提供面向实现的中文控件说明，供开发与测试对照代码行为。

## 文档

- **控件与行为说明**：[`spec.md`](spec.md)（唯一正文，基于 `app/components/gradio_template_form.py` 与 `app/gradio_main.py` 当前实现）

## 范围

- 数据录入 Tab 内全部可见控件及关联对话框
- 侧边栏模板切换对 Tab 的守卫逻辑（切换确认、导出后再切换）
- 不包含「数据源」「参数配置」等其他 Tab 的详细说明

## 实现入口

| 模块 | 职责 |
|------|------|
| `app/components/gradio_template_form.py` | Tab UI、`build_form_tab`、表单刷新、导入/导出、ID 查询 |
| `app/gradio_main.py` | Tab 挂载、`apply_template_and_refresh_form`、模板列表 |
