# NiceGUI 独立 UI 技术规格

## 规格来源

本规格以 `docs/nicegui_ui/nicegui_ui_plan.md` 为产品约束来源，以 `app/services/core_*.py` 为业务能力来源。

本规格只定义 NiceGUI UI 层，不重新定义 core 行为。

## 总体系统

### 运行入口

目标入口：

```text
python -m nicegui_ui.app
```

目标模块：

```text
nicegui_ui/app.py
```

职责：

- 初始化 NiceGUI；
- 加载全局 CSS；
- 配置 `ui.run()`；
- 设置 `storage_secret`；
- 注册主页面。

### 页面结构

主页面只需要一个 route：

```text
/
```

页面结构：

```text
ui.splitter (w-full h-screen)
  before: 模板侧边栏 (overflow-y-auto)
  after: (overflow-y-auto)
    ui.tabs
      输入
      Google 连接
      输入配置
      存储配置
    ui.tab_panels
      输入页 (w-full min-w-0)
      Google 连接页
      输入配置页
      存储配置页
```

## 全局排版约束
- **零内边距/外边距：** HTML、body、.q-page 和 .q-layout 必须去除默认 paddings 和 margins (`html, body { margin: 0; padding: 0; width: 100vw; height: 100vh; overflow: hidden; }`)。
- **全屏充满：** `ui.splitter(value=240, limits=(150, 400)).props('unit=px').classes('w-full h-screen')`，禁止使用百分比宽度。
- **滚动条与容器：** 主页面 `splitter.after` 和内部各面板必须包含 `.classes('w-full h-full overflow-y-auto')`。所有弹性内部元素使用 `min-width: 0` 保证即使有很宽的 table 也可以内部横向滚动，不撑破 splitter。
- **响应式表单网格：** 输入区动态表单使用 `.classes('grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2 w-full')`，禁止写死 `columns=4`。

## 依赖

新增运行依赖：

```text
nicegui
```

注意：

- 不在 NiceGUI UI 中导入 `gradio`。
- 仓库不得保留 `gradio` 运行依赖；`webui/` 已废弃并删除。

## 状态模型

### Principal（访问主体）

每个 HTTP / WebSocket 连接必须映射到稳定的 `principal_id`，作为会话分区键。当前阶段可无登录用户名；未来加入用户名时，只扩展解析层，不重写各 Tab handler。

```python
@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str | None = None
```

解析策略：

| 阶段 | `principal_id` | 登录 |
|------|----------------|------|
| 单用户（默认） | `user:admin` | 不需要 |
| 多用户 | `user:{username}` | `known_usernames()` 多于 1 个时必需 |
| 未登录（多用户模式） | `user:unauthenticated` | 仅可访问登录页；无业务 `SessionState` |

规则：

- 默认账户恒为 `admin`；权限收紧时只调整各账户授权，不改为全局开关污染整个作用域。
- 所有 handler 通过 `SessionRegistry.for_current()` 取状态。
- 持久化偏好通过 `pref_key(name)`（如 `user:admin:sidebar_width`）。
- `SessionRegistry` 可为模块级 `dict[str, SessionState]`，但 key 必须是 `principal_id`。

未来加用户时改动面：

1. `nicegui_ui/components/auth.py` 的 `known_usernames()` 与权限表；
2. 登录页写入 `app.storage.user['username']`；
3. 可选 per-user 权限检查函数。

### SessionRegistry

```python
class SessionRegistry:
    _sessions: dict[str, SessionState] = {}

    @classmethod
    def for_current(cls) -> SessionState:
        principal = resolve_principal()
        # 结合 app.storage.browser['id'] 作为联合 key，彻底防止多标签页串号
        browser_id = app.storage.browser.get('id')
        session_key = f"{principal.principal_id}::{browser_id}"
        return cls._sessions.setdefault(session_key, SessionState())
```

多浏览器验收：两个不同浏览器 profile 同时录入，互不覆盖 `draft` 与 `session_rows`。

### SessionState

每个 `principal_id` 对应一份 `SessionState`。

推荐结构：

```python
@dataclass
class SessionState:
    template_id: str | None = None
    template_path: Path | None = None
    cfg: GetTomlValues | None = None
    verify_report: dict[str, Any] | None = None
    located: dict[str, dict[str, int]] = field(default_factory=dict)
    db_path: Path | None = None
    db: SecureSQLite | None = None
    ui_provider: UiProvider | None = None
    t2db: Template2DB | None = None
    writer: ExcelWriter | None = None
    input_capacity: int = 0
    current_instance_index: int = 0
    draft: dict[str, Any] = field(default_factory=dict)
    session_rows: list[dict[str, Any]] = field(default_factory=list)
    selected_session_index: int | None = None
    suppress_id_search: bool = False
    pending_id_value: int | None = None
    exported_files: list[Path] = field(default_factory=list)
    last_export_path: Path | None = None
    active_db_suffix: str | None = None
    selected_db_row_index: int | None = None
    google_connected: bool = False
    google_sheet_rows: list[dict[str, Any]] = field(default_factory=list)
```

### 持久状态

`app.storage.user` 只存轻量持久字段（NiceGUI 已按浏览器 cookie 隔离）：

- `{principal_id}:sidebar_width` 或无前缀的 `sidebar_width`（当前单用户浏览器场景）
- `sidebar_collapsed`
- `last_template_id`（可选）

实现时推荐封装 `pref_key(name: str) -> str`，便于未来统一加 `principal_id` 前缀。

不建议把 `SecureSQLite`、`UiProvider`、`Template2DB`、`ExcelWriter` 这类对象放入持久 storage。

## core API 契约

### 模板注册

使用：

```python
registry = SortTemplates()
registry.UpdateJson()
registry.TemplateIDs
registry.template_display_names
registry.sort_templates_timeline
registry.LastUseTemplate
```

约束：

- 只读取 `templates/*.xlsx`。
- 跳过 Excel 锁文件。
- 不读取 `docs/` 样例。

### TOML

使用：

```python
ensure_exists(template_id, template_path)
cfg = load_toml(template_id)
report = verify_toml(template_path, cfg)
```

约束：

- `verify_toml` 是 UI 是否可录入和写回的前置条件。
- UI 不扫描工作表标签。
- UI 不修正或猜测坐标。

### DB

使用：

```python
db_path = default_db_path(template_id)
db = SecureSQLite(db_path)
ui_provider = UiProvider(cfg, db)
list_db_paths(template_id)
allocate_next_db_path(template_id)
```

约束：

- 通过 `UiProvider.persist_fields` 落库。
- 通过 `UiProvider.get_data` 获取 DB 表格。
- 覆盖录入使用 TOML 主键规则。

### Excel 写回

使用：

```python
writer = ExcelWriter(cfg, located)
input_capacity = writer.max_instance_count(template_path)
writer.write_back(template_path, output_path, records, instance_k=0)
writer.get_print_areas(exported_path)
```

约束：

- UI 不计算值格坐标。
- UI 不保存完整 area 列表。
- `current_instance_index` 只是 UI 序号。

## 模板激活规格

触发：

- 初次进入页面；
- 点击侧边栏模板；
- TOML 保存成功后重新激活当前模板。

流程：

1. 从 registry 得到 `template_id` 和 `template_path`。
2. `ensure_exists(template_id, template_path)`。
3. `cfg = load_toml(template_id)`。
4. `verify_report = verify_toml(template_path, cfg)`。
5. 如果失败：
   - 保存 `cfg` 和 `verify_report`；
   - 清空 writer / ui_provider / t2db；
   - 禁用输入、下一行、另存为、打印；
   - 在输入页和配置页展示错误。
6. 如果成功：
   - 保存 `located = verify_report['located']`；
   - 打开 DB；
   - 构造 `UiProvider`、`Template2DB`、`ExcelWriter`；
   - 计算 `input_capacity`；
   - 清空 `draft`、`session_rows`；
   - `current_instance_index = 0`；
   - 刷新全部 refreshable 区域；
   - 切换到 `输入` tab。

## 页面规格

### 侧边栏

组件：

- 顶部标题：`模板: {template_id}` 或 `模板: 未选择`
- 模板列表：按 timeline 排序
- 空状态：`templates/ 中没有可用模板`

事件：

- 点击模板：调用模板激活。
- 激活后更新高亮。

### 输入页

组件：

- ghost input
- 动态字段区
- ID 冲突 dialog
- 本次录入表格
- 清空 / 删除按钮
- 另存为 / 下一行按钮
- 容量提示
- 打印文件 select
- 打印区域 select
- 打印按钮

事件：

#### ghost input blur

输入：整行文本。

处理：

1. `ui_provider.record_from_textbox(raw)`。
2. 合并到 `draft`。
3. `suppress_id_search = True`。
4. 刷新动态字段。

#### 动态字段 change

处理：

- `draft[label] = value`。

#### 主键 blur

处理：

1. 如果 `suppress_id_search` 为 True：置回 False 并返回。
2. 规范化 ID。
3. 查询 DB。
4. 若 DB 存在：打开 dialog。
5. 若 DB 不存在：`t2db.fetch_row_by_id`。
6. 合并返回记录到 `draft`。

#### 下一行

前置：

- `verify_report.ok` 为 True。
- `ui_provider` 存在。
- `current_instance_index < input_capacity`。

处理：

1. `ui_provider.persist_fields(draft)`。
2. `session_rows[current_instance_index] = draft`。
3. 如果下一 index 超出容量：提示已满，不清空。
4. 否则 index + 1，清空 draft。

#### 另存为

处理：

1. 汇总 `session_rows`，必要时包含当前 draft。
2. 生成输出路径。
3. `writer.write_back(...)`。
4. 更新 `exported_files`、`last_export_path`。
5. 刷新打印文件 select。

#### 打印

处理：

- Windows：`os.startfile(path, 'print')`。
- 非 Windows：`ui.download.file(path)`。

### Google 连接页

组件：

- oauth_client.json 上传
- 授权按钮
- 授权状态
- 连接状态
- 主 ID 表格
- 全选 / 取消全选 / 导入选中行

事件：

- 授权：调用 `ConnectGoogle`。
- 模板激活：如果已授权且 TOML sources 有 URL，则自动连接。
- 导入：选中行落库并追加到输入页 `session_rows`。

### 输入配置页

组件：

1. 基础配置
2. 数据源表
3. 输入区段
4. 字段映射表
5. TOML 全文编辑

事件：

#### 校验配置

处理：

- 当前编辑内容转 cfg。
- 调用 `verify_toml`。
- 展示报告。

#### 保存 TOML

处理：

1. 保存 TOML。
2. 重新 load。
3. 重新 verify。
4. 成功后重建 core 对象。
5. 清空输入会话状态。
6. 刷新所有页面区域。

### 存储配置页

组件：

- DB select
- 切换按钮
- 新建库按钮
- 全部数据表
- 覆盖录入输入框
- 覆盖保存按钮

事件：

- DB select 变化：若不同于 active suffix，启用切换。
- 切换：打开新 DB 并重建 `UiProvider`。
- 新建库：调用 `allocate_next_db_path`。
- 表格选中：保存 selected row index。
- 覆盖保存：将 raw text 解析为 incoming，使用选中行 ID 覆盖保存。

## 刷新策略

推荐使用：

```python
@ui.refreshable
def render_input_fields():
    ...
```

需要 refresh 的区域：

- sidebar
- input fields
- session table
- TOML config sections
- DB table
- Google sheet table
- toolbar status

禁止重建整个页面作为常规更新手段。

## 样式规格

全局风格：

- 中文界面；
- 紧凑布局；
- 统一按钮宽高；
- 表格有边框、hover、高亮；
- ghost input 弱化显示；
- 侧边栏列表 active / muted 区分。

实现手段优先级：

1. Tailwind classes（首选，直接控制密度和间距）；
2. Quasar props（如 `.props('dense flat')`）；
3. `.style()`；
4. `ui.add_css()`；
5. JS（非必要不使用）。

## 错误与通知

使用 `ui.notify`：

- TOML 校验失败；
- 文本拆分失败；
- ID 无法解析；
- 数据源找不到；
- 容量已满；
- 导出失败；
- 非 Windows 打印降级为下载。

使用 `ui.dialog`：

- ID 冲突；
- 删除确认（可选）；
- 覆盖确认（可选）。

## 安全与边界

- 文件选择与导出必须限制在项目约定目录。
- 不暴露任意服务器路径下载。
- 不把数据库连接放入持久 storage。
- 不在 UI 层执行任意用户输入代码。

## 8. `ui.run()` Baseline（极简启动配置）

针对 NiceGUI 所谓的“极度复杂配置”，我们只需严格遵守以下极简模版，即可打通本地化和安全会话：

```python
from pathlib import Path
from nicegui import ui, app

ui.add_css(Path(__file__).parent.joinpath('components', 'style.css').read_text(encoding='utf-8'))

# 页面路由与认证拦截
@ui.page('/')
def index_page():
    # 利用 app.storage.browser 的唯一 ID 作为会话主键，确保即便是默认 admin 也不会跨标签页串车
    browser_id = app.storage.browser.get('id')
    if not browser_id:
        import uuid
        app.storage.browser['id'] = str(uuid.uuid4())
    
    # 渲染 Main Shell
    from nicegui_ui.pages.main import render_shell
    render_shell()

if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='Excel Template Viz',
        storage_secret='local-offline-secret-key-2026',  # 必须项：开启浏览器 Cookie 存储
        reload=True,                                     # 开发期热重载
        native=False,                                    # 暂不使用 pywebview 避免多窗口渲染问题
        language='zh-CN',
        show=False,                                      # 防止每次热重载都弹新网页
    )
```

**布局实现注记**：不需要任何复杂的 JS 注入来强行重写 DOM，所有“零间距”和 HTML 草稿同步，全部依靠在 Python 层面书写 Tailwind CSS：
例如：`ui.row().classes('w-full gap-0 p-0 m-0')` 和 `ui.input().props('dense flat')`。

Use `ui.download.file` for exported xlsx when not printing. Use `ui.notify` for validation errors and capacity warnings.
