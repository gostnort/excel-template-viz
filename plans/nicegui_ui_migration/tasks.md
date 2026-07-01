# NiceGUI 独立 UI 迁移任务清单

## Phase 0：清理 Gradio 并确认 NiceGUI 环境

**目标**：移除全部 Gradio 残留，确认 NiceGUI 可独立启动。

### Task 0.0：Gradio 残留清理

- [ ] 确认 `webui/` 已删除
- [ ] 确认 `docs/gradio_ui/` 已删除
- [ ] 从 `requirements.txt` 移除 `gradio`，加入 `nicegui`
- [ ] `run.bat` 改为 `python -m nicegui_ui.app`
- [ ] 删除 `.cursor/rules/gradio-usage.mdc`，新增 `nicegui-usage.mdc`
- [ ] 全仓搜索 `import gradio`、`webui` 无运行时代码命中

**验收标准**：

- 无 Gradio 目录与依赖
- 启动入口指向 `nicegui_ui`

### Task 0.1：新增依赖

- [ ] 在依赖文件中加入 `nicegui`
- [ ] 从依赖文件移除 `gradio`
- [ ] 确认 `pip install -r requirements.txt` 成功

**验收标准**：

- Python 可导入 `nicegui`
- 不可导入 `gradio`（或未安装）

### Task 0.2：创建 NiceGUI 包骨架

- [ ] 新建 `nicegui_ui/app.py`（根目录唯一业务入口模块）
- [ ] 新建 `nicegui_ui/pages/`：`main.py`、`sidebar.py`、四个 `tab_*.py`（仅占位，不提前写业务）
- [ ] 新建 `nicegui_ui/components/`：`auth.py`、`session.py`、`activation.py`（占位）、`style.css`

**验收标准**：

- `python -m nicegui_ui.app` 能启动空白骨架页
- 根目录除 `app.py` 外无其它 `.py` 模块

### Task 0.3：确认 NiceGUI 基础组件

- [ ] 验证 `ui.splitter`
- [ ] 验证 `ui.tabs` / `ui.tab_panels`
- [ ] 验证 `ui.table`
- [ ] 验证 `ui.dialog`
- [ ] 验证 `ui.download.file`
- [ ] 验证 `app.storage.user` 与 `storage_secret`

**验收标准**：

- 空壳页面可以展示 splitter + tabs
- `app.storage.user` 刷新后仍能读取测试字段

---

## Phase 1：Shell Spike

**目标**：先证明 NiceGUI 能承载目标布局，再进入业务实现。

### Task 1.1：实现主页面 shell

- [ ] 在 `nicegui_ui/pages/main.py` 创建主页面函数
- [ ] 使用 `ui.splitter`
- [ ] `splitter.before` 放侧边栏
- [ ] `splitter.after` 放四个 tab
- [ ] 添加紧凑布局 CSS

**验收标准**：

- 页面不是单列布局
- 左侧栏、分隔条、右侧 tab 区位置正确

### Task 1.2：实现侧边栏模板列表

- [ ] 调用 `SortTemplates()`
- [ ] 调用 `UpdateJson()`
- [ ] 按 timeline 渲染模板列表
- [ ] 显示 `模板: 未选择` / `模板: {template_id}`
- [ ] 空模板时显示 `templates/ 中没有可用模板`

**验收标准**：

- 只显示 `templates/*.xlsx`
- 不显示任何 hardcoded demo 模板

### Task 1.3：实现 splitter 宽度与折叠记忆

- [ ] 读取 `app.storage.user['sidebar_width']`
- [ ] 读取 `app.storage.user['sidebar_collapsed']`
- [ ] 拖拽后写回宽度
- [ ] 折叠 / 展开后写回状态
- [ ] 刷新页面恢复状态

**验收标准**：

- 拖拽有效
- 折叠有效
- 刷新后状态保留

### Task 1.4：实现 tab 切换基础

- [ ] 创建 `输入`
- [ ] 创建 `Google 连接`
- [ ] 创建 `输入配置`
- [ ] 创建 `存储配置`
- [ ] 模板切换后切回 `输入`

**验收标准**：

- tab 顺序符合计划
- 模板点击后当前 tab 为 `输入`

---

## Phase 2：Principal、SessionRegistry 与模板激活

**目标**：建立多访问者安全的状态模型，并完成模板激活。

### Task 2.0：路由入口拦截与防串车基础

- [ ] 在 `nicegui_ui/app.py` 创建 `@ui.page('/')`
- [ ] 读取或颁发 `app.storage.browser['id']`，作为唯一的连接指纹
- [ ] 在 `nicegui_ui/components/auth.py` 实现 `DEFAULT_ADMIN`、`resolve_principal(browser_id)`
- [ ] 在 `nicegui_ui/components/session.py` 实现 `SessionRegistry.for_current()`，以 `browser_id + principal_id` 作为内存字典的隔离 Key
- [ ] 增加定时器或 LRU 淘汰机制，清除两小时内无活动的心跳过期的 `SessionState` 实例

**验收标准**：

- 同一浏览器开两个标签页（或换用无痕模式）不会共享 `draft` 数据。
- 绝不存在模块级共享的 `db` 或 `writer`。

### Task 2.1：SessionState 字段完整性

- [ ] 核对 `SessionState` 字段与 spec 一致
- [ ] 禁止无 key 的模块级单一 `SessionState` 实例

**验收标准**：

- 每个 `principal_id` 持有独立 `SessionState`

### Task 2.2：实现模板激活函数

- [ ] 在 `nicegui_ui/components/activation.py` 实现 `activate_template`
- [ ] `load_toml(template_id)`
- [ ] `verify_toml(template_path, cfg)`
- [ ] 构造 `SecureSQLite`
- [ ] 构造 `UiProvider`
- [ ] 构造 `Template2DB`
- [ ] 构造 `ExcelWriter(cfg, located)`
- [ ] `writer.max_instance_count(template_path)`

**验收标准**：

- 选择真实模板后可以得到完整 state
- `input_capacity` 正确写入 state

### Task 2.3：处理校验失败状态

- [ ] 显示校验错误
- [ ] 禁用输入
- [ ] 禁用下一行
- [ ] 禁用另存为
- [ ] 禁用打印
- [ ] 仍允许进入输入配置页修改 TOML

**验收标准**：

- 校验失败模板不能写回或导出
- 错误内容可见

### Task 2.4：模板切换刷新

- [ ] 清空 `draft`
- [ ] 清空 `session_rows`
- [ ] 重置 `current_instance_index`
- [ ] 刷新动态字段
- [ ] 刷新 DB 表
- [ ] 刷新 TOML 页面

**验收标准**：

- 从模板 A 切换到模板 B 后没有旧字段残留

---

## Phase 3：输入页

**目标**：完成主要录入闭环。

### Task 3.1：ghost input

- [ ] 创建弱化样式输入框
- [ ] blur 时调用 `record_from_textbox`
- [ ] 合并结果到 `draft`
- [ ] 设置 `suppress_id_search = True`
- [ ] 清空 ghost input

**验收标准**：

- 粘贴整行文本后动态字段自动填充
- 不直接落库

### Task 3.2：动态字段生成

- [ ] 使用 `@ui.refreshable`
- [ ] 从 `ui_provider.get_labels()` 生成字段
- [ ] id 字段显示 `★主键`
- [ ] 字段修改同步到 `draft`

**验收标准**：

- 不存在 hardcoded 输入字段
- TOML 字段变化后刷新有效

### Task 3.3：ID blur

- [ ] 只绑定主键字段
- [ ] 消费 `suppress_id_search`
- [ ] 查询 DB
- [ ] DB 命中时打开 dialog
- [ ] DB 未命中时查数据源
- [ ] 查询结果合并到 `draft`

**验收标准**：

- 程序填值不误触发 ID 查询
- 用户手动切换焦点触发查询

### Task 3.4：本次录入表格

- [ ] 使用 `ui.table` 或 refreshable 行
- [ ] 点击行载入 draft
- [ ] 选中行高亮
- [ ] 支持勾选
- [ ] 支持删除
- [ ] 支持清空

**验收标准**：

- 不使用隐藏 JSON 桥
- 表格与 `session_rows` 同步

### Task 3.5：下一行

- [ ] 检查 `verify_report.ok`
- [ ] 检查容量
- [ ] `persist_fields(draft)`
- [ ] 写入 `session_rows[current_instance_index]`
- [ ] 未满时 index + 1 并清空 draft
- [ ] 已满时提示并保留 draft

**验收标准**：

- 当前序号和容量显示正确
- DB 中能看到落库结果

### Task 3.6：另存为

- [ ] 生成固定输出路径
- [ ] 汇总 `session_rows`
- [ ] 当前 draft 未保存时纳入导出
- [ ] 调用 `writer.write_back`
- [ ] 更新 `exported_files`
- [ ] 更新 `last_export_path`
- [ ] 更新打印文件选择框

**验收标准**：

- xlsx 输出到 `exports/{template_id}/`
- 文件名符合规范

### Task 3.7：打印

- [ ] 读取导出文件列表
- [ ] 调用 `writer.get_print_areas`
- [ ] Windows 调用系统打印
- [ ] 非 Windows 提供下载

**验收标准**：

- 无导出文件时提示
- 非 Windows 不报错

---

## Phase 4：输入配置页

**目标**：完成 TOML 可视化编辑与全文编辑。

### Task 4.1：基础配置

- [ ] 渲染 `determiner`
- [ ] 渲染 `worksheet`
- [ ] 保存基础配置

**验收标准**：

- 保存后 TOML 文件内容变化
- 重新激活模板后状态一致

### Task 4.2：数据源配置

- [ ] 渲染 `[[sources]]`
- [ ] 支持本地路径
- [ ] 支持 Google Sheet URL
- [ ] 保存数据源

**验收标准**：

- 数据源只在配置页维护

### Task 4.3：输入区段

- [ ] 渲染单条 `input_section`
- [ ] 编辑 `input_area`
- [ ] 编辑 `move_to`
- [ ] 编辑 `offset`
- [ ] 禁止多条 section

**验收标准**：

- 不出现旧 `sections`

### Task 4.4：字段映射

- [ ] 渲染 `Input_label`
- [ ] 渲染 `value_from_label`
- [ ] 渲染 `value_offset`
- [ ] 渲染 `field`
- [ ] 渲染 `source_file`
- [ ] 渲染 `source_sheet`
- [ ] 渲染 `index`
- [ ] 渲染 `regex`
- [ ] 渲染 `id`

**验收标准**：

- 字段表包含所有新 TOML 键

### Task 4.5：全文 TOML

- [ ] 使用 `ui.codemirror` 或 `ui.textarea`
- [ ] 保存 TOML 文本
- [ ] 重置为磁盘内容
- [ ] 保存后重新校验

**验收标准**：

- 非法 TOML 显示错误
- 合法 TOML 保存后刷新 UI

---

## Phase 5：存储配置页

**目标**：完成本地 SQLite DB 管理。

### Task 5.1：当前 DB

- [ ] 使用 `list_db_paths`
- [ ] 当前 DB 默认选中
- [ ] 选择不同项才启用切换
- [ ] 切换后重新禁用按钮

**验收标准**：

- “切换”按钮状态正确

### Task 5.2：新建 DB

- [ ] 调用 `allocate_next_db_path`
- [ ] 打开新 DB
- [ ] 更新 DB 下拉列表
- [ ] 更新 `active_db_suffix`

**验收标准**：

- 新建后立即成为当前库

### Task 5.3：全部数据表

- [ ] 使用 `ui_provider.get_data`
- [ ] 表格支持选中行
- [ ] 选中状态可用于覆盖录入

**验收标准**：

- DB 内容变更后表格刷新

### Task 5.4：覆盖录入

- [ ] 要求先选中行
- [ ] 粘贴整段文本
- [ ] `record_from_textbox`
- [ ] 保留选中行 ID
- [ ] 覆盖保存
- [ ] 刷新表格

**验收标准**：

- 覆盖后同 ID 记录被替换

---

## Phase 6：Google 连接页

**目标**：在主流程稳定后迁移 Google 能力。

### Task 6.1：OAuth

- [ ] 上传 `oauth_client.json`
- [ ] 调用授权流程
- [ ] 显示授权状态

**验收标准**：

- 未授权时导入按钮不可用

### Task 6.2：模板自动连接

- [ ] 模板激活后检查 TOML sources
- [ ] 有 Google URL 时尝试连接
- [ ] 显示连接状态

**验收标准**：

- 切换模板后不会沿用旧 sheet 状态

### Task 6.3：主 ID 表

- [ ] 渲染 sheet rows
- [ ] 支持多选
- [ ] 支持全选 / 取消全选

**验收标准**：

- 表格选中状态可靠

### Task 6.4：导入选中行

- [ ] 获取完整行
- [ ] 转换为 TOML Input_label 记录
- [ ] 写入 DB
- [ ] 追加到输入页 `session_rows`
- [ ] 切换到输入页

**验收标准**：

- 导入后输入页立即显示记录

---

## Phase 7：收尾

### Task 7.1：启动方式

- [ ] 新增或记录 `python -m nicegui_ui.app`
- [ ] `run.bat` 已改为 `python -m nicegui_ui.app`

**验收标准**：

- 用户能独立启动 NiceGUI UI

### Task 7.2：Windows 本地体验

- [ ] 评估 `ui.run(native=True)`
- [ ] 评估打印对话框体验
- [ ] 评估窗口大小

**验收标准**：

- 明确是否启用 native 模式

### Task 7.3：回归验收

- [ ] 模板为空
- [ ] TOML 校验失败
- [ ] TOML 校验成功
- [ ] ghost input
- [ ] ID blur
- [ ] 下一行
- [ ] 另存为
- [ ] DB 切换
- [ ] 覆盖录入
- [ ] 非 Windows 下载 fallback

**验收标准**：

- 主流程能从模板选择走到导出文件

