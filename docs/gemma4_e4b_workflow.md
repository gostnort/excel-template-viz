# Gemma 4 E4B · TOML 配置向导（应用层规格 v5）

> 状态：v5.0（彻底移除 Playwright 依赖，全面适配 NiceGUI 进程内无缝交互）
> 日期：2026-07-22
> 平台依赖：[`embed_gemma4.md`](embed_gemma4.md)（本地 LiteRT 引擎调用）
> 业务依赖：[`toml_config_design.md`](toml_config_design.md)、[`connect_google.md`](connect_google.md)、`app/core_toml.py`

---

## 1. 核心设计演进 (v4 -> v5)

### 1.1 移除独立自动化与浏览器监测
废弃原有的 Playwright/BrowserSession 强依赖。向导的宿主（NiceGUI 组件）与向导的“大脑”（Gemma 4 Orchestrator）现在运行在同一进程内。向导可以直接在内存中读取用户的行为和状态（如直接获取 `tab_input` 中的 `顶部粘贴` 内容）。

### 1.2 全局悬浮与跨页面保持
对话框虽然从“输入配置”(`tab_toml.py`) 调用，但必须是一个**可拖拽移动 (Movable)、跨页面持久存在 (Persistent)** 的全局悬浮窗口。用户在向导步骤进行时，能够自由切换到“输入”或“Google连接”页面进行相应的操作，向导本身绝不会因为 Tab 切换而被销毁或遮挡。

### 1.3 LLM 容错解析
不对粘贴的原始文本进行强约定（不论是带了 `\r` `\n` 的混杂文本，还是 PaddleOCR 返回的 JSON），由 Gemma 4 本地模型通过其强大的推理能力，直接从脏数据中提取映射和规则。

---

## 2. 用户旅程 (7 步向导逻辑)

宿主 UI 的 Stepper 需要完全遵循以下 7 个阶段：

### 1. 填写数据源
- **行为**：收集此模板关联的数据源基本信息（本地来源或 Google Sheet 来源等）。

### 2. 用户输入样本数据
- **行为**：提示用户直接在“输入” Tab 的 `顶部粘贴`（Ghost textbox）中输入数据，或通过右键菜单调用 OCR 获取样本。向导后台通过状态侦听捕获这些样本数据。

### 3. 推测 Ghost Textbox 的相关 Fields
- **行为**：将捕获到的 `顶部粘贴` 内容（纯文本或 JSON）发给 Gemma 4。
- **目标**：模型解析文本，找出直接包含在表单中的各个字段，并推理初步的字段映射。

### 4. 推测 Google Sheet 的相关 Fields
- **行为**：如果前置配置了 Google Sheet，则拉取远程表头和数据样例交给模型。
- **目标**：推测哪些字段对应到远程数据表，完成本地与远端的字段拼图。

### 5. 渠道选定与 Regex 推理 (容错处理)
- **行为**：当上两步“没有严格匹配数据”或产生歧义时，向导为每一个游离的 Field 选定其可能的数据渠道（来源）。
- **目标**：为这些非标准匹配的字段，交给 Gemma 4 针对性地推理 Regex 提取规则。

### 6. 要求用户指定 ID
- **行为**：当所有字段基本对齐后，界面向用户展示列表，强制要求用户指定哪一列作为主键 `db_id`。

### 7. 测试并反馈不匹配
- **行为**：对生成的配置进行验证（试跑）。
- **目标**：利用提取规则切分已有的样本数据，向用户高亮展示解析失败或不匹配的地方，以便微调；如果全部通过，则直接生成 TOML 结束。

---

## 3. UI 交互层 (`nicegui_ui/components/toml_wizard.py`)

实现一个支持拖拽（可以结合 Quasar 的相关指令或定制化 CSS/JS 赋予对话框移动属性）的非模态（non-modal）或可穿透遮罩的浮窗。
窗口内部包含上述 7 个步骤的 Stepper。在执行 AI 任务时展示 Loading，不阻塞主线程（使用异步任务调度 `run.io_bound` 给 `llm_gemma4`）。

## 4. 智能引擎层 (`llm_gemma4/wizard/`)

向导大脑必须由纯 Python 代码实现，不直接绑定 UI。提供如下接口：
1. `orchestrator.py`: 维护 7 步状态机的运转，暴露 `next_step(state_payload)` 供前端推动。
2. `prompts.py`: 存放步骤 3、4、5 用到的 System Prompt。
3. `toml_patcher.py`: 最终在步骤 7 完成验证后生成持久化配置。
