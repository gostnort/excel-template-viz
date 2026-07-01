# NiceGUI 独立 UI 迁移宪章

## 目的

本宪章定义 NiceGUI UI 迁移期间不可违反的设计原则。任何实现、重构或修复都必须先满足本文件，再满足任务文件。

## 原则 1：NiceGUI UI 必须独立运行

**原则**：NiceGUI UI 是新 UI，不是 Gradio UI 的局部补丁。

**规则**：

- 新代码放在 `nicegui_ui/`。
- 新入口独立运行。
- NiceGUI 页面不得导入 `gradio`。
- 不在 NiceGUI 组件中复用 Gradio 组件。
- 现有 `webui/` 已删除；可复用逻辑迁入 `nicegui_ui/` 后不得再引用 `webui` 路径。

**禁止模式**：

```python
import gradio as gr  # 禁止出现在 nicegui_ui/
```

如果必须复用旧逻辑，只允许复用纯 Python handler 或 core 调用思路，不能复用 Gradio component。

## 原则 2：运行时模板只来自 `templates/`

**原则**：文档、wireframe、测试样例都不是运行时模板来源。

**规则**：

- 模板发现只能通过 `core_registry.SortTemplates`。
- 实际模板文件只能是 `templates/*.xlsx`。
- 空模板目录必须显示空状态。
- 不得创建 runtime fallback 模板。
- 不得使用 `docs/nicegui_ui/*.html` 中的样例字段或样例记录作为运行时数据。

**禁止模式**：

```python
templates = ["sales_order", "demo2"]  # 禁止 hardcoded 模板
```

## 原则 3：UI 不计算 Excel 坐标

**原则**：Excel 标签扫描、值格定位、instance 平移都属于 core。

**规则**：

- UI 可以保存 `current_instance_index`。
- UI 可以保存 `input_capacity`。
- UI 可以保存 `draft` 和 `session_rows`。
- UI 不保存完整 Excel area 列表作为主流程状态。
- UI 不根据 `input_area`、`move_to`、`offset` 计算真实单元格。
- 写回必须调用 `ExcelWriter.write_back`。

**禁止模式**：

```python
row = base_row + current_instance_index * offset  # 禁止
ws.cell(row=row, column=col).value = value        # 禁止
```

## 原则 4：`verify_toml` 是写入前置条件

**原则**：TOML 未校验通过时，UI 不能允许录入写回。

**规则**：

- 模板激活必须调用 `verify_toml`。
- TOML 保存后必须重新调用 `verify_toml`。
- 校验失败时禁用：
  - 输入落库；
  - 下一行；
  - 另存为；
  - 打印。
- 校验失败时仍允许用户进入输入配置页修复 TOML。

**禁止模式**：

```python
writer = ExcelWriter(cfg)
writer.write_back(...)  # 未传入 located 或未校验，禁止
```

## 原则 5：绝对禁止模块级全局变量（防状态串车）

**原则**：NiceGUI 运行在一个长驻异步进程中，所有连接共享同一 Python 解释器。绝不允许任何用户上下文放入未分区的全局变量。

**规则**：

- 通过 `resolve_principal()` 得到 `principal_id`；单用户模式恒为 `user:admin`，无需登录。
- 仅当 `known_usernames()` 多于 1 个时才要求登录；权限变更只调整账户授权，不污染全局作用域。
- 运行时对象**必须且只能**保存在 `SessionRegistry.for_current()` 获取的每用户专属对象中。
- `app.storage.browser` 将作为浏览器指纹，结合 `principal_id`，杜绝多标签页或多电脑访问时互相覆盖。
- DB 连接、writer、provider 等不可序列化对象只在 `SessionState` 内存中，不存入磁盘 storage。
- **强制检查**：任何页面模块中如果出现 `draft = {}` 或 `current_index = 0` 的模块级初始化，代码审查即告失败。

**禁止模式**：

```python
session_rows = []       # 未按 principal 分区，禁止
current_cfg = None      # 未按 principal 分区，禁止
GLOBAL_STATE = SessionState()  # 全站单例，禁止
```

## 原则 6：优先使用 NiceGUI 原生组件

**原则**：迁移 NiceGUI 的目标是减少 DOM hack 和隐藏事件桥。

**规则**：

- 布局优先使用 `ui.splitter`。
- Tab 优先使用 `ui.tabs` / `ui.tab_panels`。
- 弹窗优先使用 `ui.dialog`。
- 表格优先使用 `ui.table`。
- 动态区域优先使用 `@ui.refreshable`。
- 事件优先使用 Python `on_click` / `on('blur')`。
- JS 只作为最后手段。

**禁止模式**：

```python
hidden_json_bridge = ui.input(visible=False)  # 非必要时禁止
```

如果 `ui.table` 不能满足某个交互，可使用 refreshable 自定义行，但仍要直接绑定 Python 事件。

## 原则 7：TOML 新模型不可回退

**原则**：NiceGUI UI 只服务当前 TOML 模型。

**必须支持**：

- 顶层 `worksheet`
- 单条 `[[input_section]]`
- `Input_label`
- `value_from_label`
- `value_offset`
- `field`
- `source_file`
- `source_sheet`
- `index`
- `regex`
- `id`

**禁止**：

- 旧 `sections`
- 多 section 主流程
- 把 `index` 当 Excel 列号
- 用表头匹配替代 `verify_toml` 的 located

## 原则 8：TOML 保存后必须重建对象

**原则**：配置保存改变了字段、定位和数据源，旧对象不可继续使用。

**规则**：

TOML 保存后必须：

1. 重新加载 cfg。
2. 重新校验。
3. 重建 `UiProvider`。
4. 重建 `Template2DB`。
5. 重建 `ExcelWriter`。
6. 重算 `input_capacity`。
7. 清空 `draft`。
8. 清空 `session_rows`。
9. 重置 `current_instance_index = 0`。
10. 刷新输入、配置、DB 和 Google 相关区域。

## 原则 9：导出与打印必须可降级

**原则**：打印是本地 Windows 增强功能，不是跨平台基础能力。

**规则**：

- Windows：允许 `os.startfile(path, 'print')`。
- 非 Windows：使用 `ui.download.file(path)`。
- 没有导出文件时不能打印。
- 打印区域只来自 `writer.get_print_areas(exported_path)`。

**禁止**：

- 打印逻辑参与 TOML 定位。
- 打印失败导致会话状态损坏。

## 原则 10：Google 连接不能阻塞核心录入

**原则**：核心闭环是模板 → 输入 → 落库 → 导出。

**规则**：

- Google 页可以晚于输入、TOML、DB 页实现。
- OAuth 未授权时，只禁用 Google 导入能力。
- 不得因为 Google 连接失败禁用本地模板录入。
- 数据源 URL 只在输入配置页维护。

## 原则 11：实现前先做 Shell Spike

**原则**：NiceGUI 迁移的第一风险是布局承载能力。

**规则**：

正式写业务逻辑前必须先完成：

- `ui.splitter` 左右布局；
- 侧边栏模板列表；
- 四个 tab；
- 宽度记忆；
- 折叠；
- 空模板状态。

如果 shell spike 不能满足布局，应先更新本计划，而不是继续业务开发。

## 原则 12：计划优先于实现

**原则**：如果实现时发现本 Speckit 与实际 core API 不一致，先更新计划和规格。

**规则**：

- 不因方便而绕过 core。
- 不临时添加未记录的 UI 状态。
- 不在实现中偷偷改变命名、目录或数据来源。
- 任何新增 core API 必须先说明用途、输入、输出和调用时机。

## 最终判定

满足以下条件才可认为 NiceGUI 迁移进入可替换阶段：

1. 新 UI 可独立启动。
2. 不导入 Gradio。
3. 主流程使用真实 `templates/*.xlsx`。
4. 校验失败能正确阻断写入。
5. 输入、TOML、DB 三个核心页稳定可用。
6. 导出文件符合约定路径。
7. 所有 Excel 坐标逻辑仍在 core。

