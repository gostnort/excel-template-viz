# NiceGUI 独立 UI 迁移计划

## 概述

本计划用于新建并替换为 NiceGUI UI。目标是在完全移除 Gradio 的前提下，重新实现模板录入、TOML 配置、数据库配置、Google 连接、导出和打印工作流。

`docs/nicegui_ui/nicegui_ui_plan.md` 是本计划的约束来源；本 Speckit 目录负责把该约束拆成可落地的工程计划、规格、任务和不可违反原则。

## 背景与问题

Gradio UI 已放弃，不再维护。原因包括：

- `gr.HTML` / `gr.Column` 等组件被 Gradio DOM wrapper 包裹，侧边栏、分隔条、主区域布局失真。
- 侧边栏拖拽依赖大量 CSS / JS hack，并与 Gradio 版本差异冲突。
- 表格交互依赖隐藏组件 JSON 桥接，链路脆弱。
- 产品形态是本地 Excel 工作台，不是 Gradio 擅长的 demo。

因此：**所有 Gradio 代码、文档、依赖、启动入口都必须删除**；NiceGUI 成为唯一 UI。

## NiceGUI 可行性与痛点攻克分析（针对多用户与布局）

鉴于您对 NiceGUI 多用户串车风险及配置复杂度的担忧，本计划特别确立以下攻克方案：

1. **彻底解决多用户状态串车（Session Bleeding）**：
   - NiceGUI 是基于 FastAPI 的异步服务器。默认情况下，模块级变量（如 `current_cfg = ...`）会在所有访问者间共享，导致串车。
   - **解决方案**：引入基于 `principal_id` 的字典 `SessionRegistry`。我们将结合 `app.storage.browser`（由 NiceGUI 自动颁发和校验的安全 cookie）作为唯一 Key，在内存中隔离每个用户的 `ExcelWriter` 和 `UiProvider` 实例。这比 Gradio 的状态管理更可控，且没有反序列化带来的性能负担。
2. **零门槛的极其复杂布局（HTML 草稿 1:1 还原）**：
   - 您担心 NiceGUI 无法实现草稿中的超紧凑布局。实际上，NiceGUI 底层是 Vue3 (Quasar) + TailwindCSS。
   - **解决方案**：使用 `ui.splitter(value=20).props('limits=[12, 40]')` 即可一行代码实现原生高性能侧边栏拖拽，无需任何 JS 注入。
   - 对于草稿中的“零间距”紧凑表单，我们将全程使用 Tailwind 原子类（如 `.classes('w-full gap-0 p-0 m-0')`）和 Quasar 原生属性（如 `.props('dense flat')`），完美抹平框架默认的内外边距，直接复现您的 HTML 设计。

## Gradio 残留清单（实施前必须清零）

以下路径在 Phase 0 清理阶段删除或改写，不得保留为运行依赖：

| 类别 | 路径 / 项 | 处理 |
|------|-----------|------|
| 运行代码 | `webui/` 整目录 | 删除；可复用逻辑先迁入 `nicegui_ui/` |
| 约束文档 | `docs/gradio_ui/` 整目录 | 删除；线框与计划已迁至 `docs/nicegui_ui/` |
| 依赖 | `requirements.txt` 中 `gradio>=4.0` | 删除；改为 `nicegui` |
| 启动 | `run.bat` 中 `python -m webui.app` | 改为 `python -m nicegui_ui.app` |
| Cursor 规则 | `.cursor/rules/gradio-usage.mdc` | 删除；改为 `nicegui-usage.mdc` |
| 生成脚本 | `create_webui.py`（若存在） | 删除 |

**可迁入 `nicegui_ui/` 后再删的纯 Python 逻辑（不含 Gradio 组件）：**

- 模板激活流程（原 `webui/utils/activation.py` 思路）
- handler 业务编排（原 `webui/handlers.py` 中与 core 交互部分）
- 侧边栏排序与 HTML 生成思路（原 `webui/utils/sidebar_html.py`，NiceGUI 中改为原生列表组件）

**不得迁入：**

- 任何 `import gradio`；
- `gr.State` / `gr.HTML` / hidden textbox 桥接；
- `webui/style.css` 中针对 Gradio DOM 的 override（可另写 NiceGUI 样式）。

## 目标

1. 新建独立运行的 NiceGUI UI，不引用 Gradio 组件。
2. 保留当前 core 服务边界：模板发现、TOML 校验、数据库读写、Excel 坐标与写回全部由 `app/services/core_*.py` 负责。
3. 运行时只从 `templates/*.xlsx` 加载模板，不使用 wireframe 或文档样例作为数据。
4. 使用 NiceGUI 原生布局和事件能力实现：
   - 左侧模板列表；
   - 可拖拽 / 可折叠分隔布局；
   - 四个主 tab；
   - 动态输入字段；
   - 表格点击、勾选、删除和高亮；
   - 弹窗、通知、导出、下载和打印。
5. 建立按 `principal_id` 隔离的会话状态；当前可无登录用户名，但未来加入用户名时不得大改架构。

## 非目标

- 不保留 Gradio `webui/` 作为并行入口。
- 不改动 `app/services/*`，除非迁移时发现已记录的缺失 core API。
- 不重新设计 TOML 模型。
- 不实现 UI 侧 Excel 坐标计算。
- 不引入文档样例或 fallback 模板。
- 不把 Google 连接作为第一阶段阻塞项。

## 目标目录

建议新增：

```text
nicegui_ui/
  app.py                 # 唯一根模块：ui.run()、注册路由
  pages/
    main.py              # splitter 骨架，组装 sidebar + tabs
    sidebar.py
    tab_input.py
    tab_google.py
    tab_toml.py
    tab_db.py
  components/
    auth.py              # admin 默认账户、principal、pref_key
    session.py           # SessionState、SessionRegistry
    activation.py        # 模板激活（Phase 2）
    style.css
```

这是唯一 UI 包。入口：`python -m nicegui_ui.app`（`run.bat` 同步修改）。

## 核心架构

```text
NiceGUI 页面层
  ├─ shell: splitter + sidebar + tabs
  ├─ tab_input: 粘贴 / 动态字段 / 本次录入 / 导出 / 打印
  ├─ tab_toml: TOML 编辑 / 保存 / 校验
  ├─ tab_db: DB 切换 / 新建 / 全部数据 / 覆盖录入
  └─ tab_google: 授权 / 连接状态 / 多选导入

Principal + SessionRegistry
  ├─ principal_id（默认 user:admin；多用户时 user:{name}）
  └─ SessionState（每个 principal 一份）

SessionState
  ├─ 当前模板、TOML、校验报告
  ├─ DB、UiProvider、Template2DB、ExcelWriter
  ├─ draft、session_rows、current_instance_index
  ├─ exported_files、last_export_path
  └─ Google 连接状态

core 服务层
  ├─ core_registry.py
  ├─ core_toml.py
  ├─ core_store.py
  └─ core_transform.py
```

## 关键技术选择

| 需求 | NiceGUI 方案 |
|------|--------------|
| 主布局 | `ui.splitter` |
| 模板侧边栏 | `ui.column` / `ui.list` / `ui.button` |
| Tab | `ui.tabs` + `ui.tab_panels` |
| 动态字段 | `@ui.refreshable` |
| blur 事件 | `ui.input.on('blur', handler)` |
| ID 冲突选择 | `ui.dialog` |
| 录入 / DB / Google 表格 | `ui.table`，必要时用 refreshable 自定义行 |
| 提示 | `ui.notify` |
| 文件下载 | `ui.download.file` |
| 本地桌面模式 | 后期评估 `ui.run(native=True)` |
| 侧边栏宽度记忆 | `app.storage.user`，需要 `storage_secret` |

## 分阶段实施

### Phase 0：清理 Gradio 并确认 NiceGUI 环境

目标：移除全部 Gradio 残留，并确认 NiceGUI 可独立启动。

任务：

1. 将 `webui/` 中可复用的纯 Python 逻辑迁入 `nicegui_ui/`（见上文清单）。
2. 删除 `webui/`、`docs/gradio_ui/`、`.cursor/rules/gradio-usage.mdc`。
3. `requirements.txt`：移除 `gradio`，加入 `nicegui`。
4. `run.bat` 改为启动 `nicegui_ui.app`。
5. 确认 `ui.run(storage_secret=...)` 与 `app.storage.user` 可用。
6. 确认 `ui.splitter`、`ui.table`、`ui.dialog`、`ui.download.file` 在当前版本可用。

成功标准：

- 仓库中无 `import gradio`、无 `webui/`、无 `docs/gradio_ui/`。
- `python -m nicegui_ui.app` 能启动空壳页面。
- 页面能显示 `ui.splitter` 与四个 tab。

### Phase 1：Shell Spike

目标：验证 NiceGUI 是否真正承载本项目布局。

任务：

1. 实现 `nicegui_ui/app.py` 和 `pages/main.py`。
2. 用 `ui.splitter` 实现左侧模板栏与右侧 tab 区。
3. 用 `app.storage.user` 保存 sidebar 宽度和折叠状态。
4. 从 `core_registry.SortTemplates` 读取 `templates/*.xlsx`。
5. 模板为空时显示空状态。

成功标准：

- 左侧栏不使用 dropdown。
- 分隔布局可拖拽。
- 刷新页面后宽度 / 折叠状态可恢复。
- 无 `templates/*.xlsx` 时不出现 demo 模板。

### Phase 2：Principal、SessionRegistry 与模板激活

目标：建立多访问者安全的状态模型，并完成模板激活。

任务：

1. 实现 `components/auth.py` 与 `components/session.py`：
   - 默认 `user:admin`，无额外用户时不显示登录；
   - 多用户时 `login_required()` 为真，未登录为 `user:unauthenticated`。
2. 实现 `SessionRegistry.for_current()`（位于 `components/session.py`）。
3. 创建 `SessionState` dataclass。
4. 实现 `activate_template(template_id)`：
   - `ensure_exists`
   - `load_toml`
   - `verify_toml`
   - `default_db_path`
   - `SecureSQLite`
   - `UiProvider`
   - `Template2DB`
   - `ExcelWriter(cfg, located)`
   - `writer.max_instance_count(template_path)`
3. 校验失败时禁用输入、下一行、另存为、打印。
4. 模板切换后自动回到 `输入` tab。

成功标准：

- 两个浏览器会话互不覆盖 `draft` / `session_rows`。
- 激活真实模板后能显示校验状态。
- 校验失败不会进入可写入状态。
- `input_capacity` 来自 core，不由 UI 推导。
- 未来只需改 `resolve_principal()`，不必重写各 Tab handler。

### Phase 3：输入页

目标：完成核心录入闭环。

任务：

1. 实现 ghost input blur 拆分。
2. 根据 `ui.get_labels()` 动态生成字段。
3. 主键字段根据 `id=true` 标记，并绑定 blur 查找。
4. DB 已存在记录时用 `ui.dialog` 询问数据源 / 数据库。
5. 实现 `session_rows` 表格：
   - 点击载入；
   - 勾选；
   - 删除；
   - 高亮；
   - 清空。
6. 实现 `下一行`：
   - 落库；
   - 写入 / 覆盖 `session_rows[current_instance_index]`；
   - 容量检查；
   - 清空 draft。
7. 实现 `另存为`：
   - 固定路径导出；
   - 更新打印文件列表。
8. 初步实现打印：
   - Windows 使用 `os.startfile(path, 'print')`；
   - 非 Windows 使用 `ui.download.file`。

成功标准：

- 输入字段完全来自 TOML。
- 不使用 Gradio hidden bridge。
- 本次录入表格可编辑回填。
- 导出的 xlsx 路径符合约定。

### Phase 4：TOML 配置页

目标：用 NiceGUI 实现配置查看、编辑、保存和校验。

任务：

1. 实现基础配置：`determiner`、`worksheet`。
2. 实现数据源表：`[[sources]]`。
3. 实现单条 `input_section` 编辑。
4. 实现字段映射表：`[[fields]]`。
5. 实现 TOML 全文编辑。
6. 保存后重新加载 cfg、重新校验、重建对象、清空输入会话状态。

成功标准：

- 不出现旧 `sections` 模型。
- 校验报告显示缺失、重复、越界和结构错误。
- TOML 保存后不会沿用旧 `UiProvider` / `Template2DB` / `ExcelWriter`。

### Phase 5：DB 配置页

目标：完成本地数据库管理。

任务：

1. 列出 `list_db_paths(template_id)`。
2. 仅在选择项不同于 `active_db_suffix` 时启用“切换”。
3. 实现新建 DB。
4. 实现全部数据表。
5. 实现选中记录后的覆盖录入。

成功标准：

- DB 切换状态与 UI 按钮一致。
- 全部数据表反映当前 SQLite 内容。
- 覆盖录入使用 TOML determiner 和主键规则。

### Phase 6：Google 连接页

目标：迁移 Google 连接能力。

任务：

1. 上传 `oauth_client.json`。
2. 授权 Google 账号。
3. 模板激活后根据 TOML sources 自动连接。
4. 渲染主 ID 表。
5. 多选导入到 DB 和输入页 `session_rows`。

成功标准：

- 未授权时表格不可用。
- 导入后输入页立即显示新增记录。
- 数据源 URL 仍只在 TOML 配置页维护。

### Phase 7：收尾

目标：NiceGUI 成为仓库唯一 UI。

任务：

1. 确认 Gradio 残留清单已全部清零。
2. 增加关键手动验收用例（含双浏览器会话隔离）。
3. 评估 `ui.run(native=True)` 在 Windows 本地使用的体验。

成功标准：

- 用户能用 NiceGUI UI 完成一轮模板选择、录入、导出、打印或下载。
- 仓库内搜索 `gradio` / `webui` 无运行时代码命中。

## 风险与应对

| 风险 | 应对 |
|------|------|
| `ui.splitter` 无法按像素满足设计 | 先用比例实现；必要时只在 splitter 层补少量 JS |
| `ui.table` 行选择能力不足 | 改用 refreshable 自定义行，但仍保持 Python 事件，不用隐藏 JSON 桥 |
| `app.storage.user` 序列化复杂对象失败 | 只存轻量字段；引擎对象保存在页面闭包或 SessionState 内存 |
| Google 连接阻塞主流程 | 将 Google 页放在 Phase 6，不阻塞输入 / TOML / DB |
| 本地打印跨平台不一致 | Windows 打印，其他平台下载 |
| 删除 Gradio 后旧启动脚本失效 | Phase 0 同步改 `run.bat` 与依赖 |
| 多用户并发覆盖彼此状态 | `SessionRegistry` 按 `principal_id` 隔离 |
| 未来加用户名需大改 | 仅扩展 `resolve_principal()` 与持久化 key 前缀 |

## 验收标准

1. 新 UI 不导入 Gradio。
2. 新 UI 从 `templates/*.xlsx` 读取模板。
3. 模板激活必跑 `verify_toml`。
4. 校验失败禁用写入、导出和打印。
5. 输入字段完全来自 `ui.get_labels()`。
6. 表格支持选择、高亮、删除和回填。
7. 下一行只基于 `input_capacity` 判断。
8. 写回只调用 core，不在 UI 计算 Excel 坐标。
9. TOML 保存后重建 core 对象。
10. 仓库无 Gradio 运行代码与依赖。
11. 多浏览器会话状态互不污染；未来用户名仅改 principal 解析层。

