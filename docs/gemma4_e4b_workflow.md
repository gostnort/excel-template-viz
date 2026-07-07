# Gemma 4 E4B · TOML 配置向导（应用层规格 v4）

> 状态：v4.0（应用编排 + 薄 UI 适配；与 NiceGUI 结构解耦）  
> 日期：2026-07-06  
> 平台依赖：[`embed_gemma4.md`](embed_gemma4.md)（`LlmBackend`、`ContextStore`、`BrowserSession`、`ActionParser`）  
> 业务依赖：[`toml_config_design.md`](toml_config_design.md)、[`connect_google.md`](connect_google.md)、`app/core_toml.py`

---

## 0. 分层

```
┌─────────────────────────────────────────────────────────┐
│  Host UI（可选）                                         │
│  NiceGUI「输入配置」Tab 上的一个按钮 → 打开对话框          │
│  只实现 WizardHostPort（§3.6）；不懂 TOML 语义、不懂 LiteRT │
└───────────────────────────┬─────────────────────────────┘
                            │ WizardHostPort
┌───────────────────────────▼─────────────────────────────┐
│  本文件 · Orchestrator + toml_io + prompts + state       │
│  固定阶段 A–G；E4B 窄 JSON；Python 写盘 + verify          │
└───────────────────────────┬─────────────────────────────┘
                            │ embed 接口
┌───────────────────────────▼─────────────────────────────┐
│  embed_gemma4.md · LiteRT / ContextStore / BrowserSession │
└─────────────────────────────────────────────────────────┘
```

| 文档 | 内容 |
|------|------|
| `embed_gemma4.md` | **驱动**：怎么 `generate`、怎么压缩上下文、Playwright 产出 `PageState` |
| **本文件** | **应用**：向导阶段、TOML patch、何时调 LLM/浏览器、业务验收 |
| Host UI | **壳**：进度条、按钮、一句文案；可替换为非 NiceGUI 实现 |

**不含**：`chat` 模式、PowerShell.MCP、IDE Browser MCP、任意 MCP 读写 TOML。

---

## 1. 设计原则（不可违背）

### 1.1 小模型边界

Gemma 4 E4B **不能** 自由 shell、长链 ReAct、全自主 MCP。向导采用：

| 原则 | 说明 |
|------|------|
| **Python 指挥** | 阶段 A–G 顺序、`user_step` 1–4 由 Orchestrator 固定 |
| **窄 JSON** | 每轮 E4B 只输出 **一个** `action`（§4.8）；经 `ActionParser` + `dispatch` |
| **Python 写 TOML** | `toml_io.apply_patch` → `app.core_toml.verify_toml`；**不**把全文或 shell 输出回灌 LLM |
| **非黑即白优先** | 能试跑判定的步骤 `thinking=False` |
| **thinking 仅 regex** | 唯一 `generate(thinking=True)` 场景 |
| **LLM 预算** | 单模板 ≤ **15** 次 `generate()` |
| **最少 token** | 进上下文：`digest`、`pending`、试跑成败、短 paste、regex 试错摘要 |
| **verify 时机** | 未配置完的 TOML **必然** verify 失败；完成前 **不** 据错误闸门或向用户报错；仅 **G. final_verify** 判定成败 |

### 1.2 与 Host UI 解耦

- Orchestrator 只依赖 **`WizardHostPort`**（§3.6），不 import NiceGUI 组件、不读 Tab 结构。  
- 对话框是 **主控面**；Playwright Edge 是 **操作台**（阶段 B / Sheet 授权），不是产品主界面。  
- Host 从已运行的工作台启动向导时 **禁止** HEAD 检查 8738——进程已在跑。  
- `probe` / `health_check` 全文 **不进** 默认 UI（仅调试折叠）。

### 1.3 导航与 TOML 同步

| 控件 | 行为 |
|------|------|
| **上一步** | `user_step` 回退（B 内先 ②→①）；收起 Edge；丢弃未确认问答；**不** 回滚已落盘 patch |
| **重新读取配置** | `reload_toml_from_disk()` → 刷新 `digest`、`pending`；完成前 **不** 据 verify 错误闸门 |
| 手工改 TOML | Host 工作台非向导区改 `templates/{id}/{id}.toml` 后点 **重新读取配置** |

### 1.4 `db_id` 与数据源（正交）

| 概念 | 说明 |
|------|------|
| **`db_id`** | 哪一列 `Input_label` 标识一条记录 |
| **数据源** | 字段是否绑定 `source_file`（本地 / Sheet / 仅粘贴） |

二者无关。在 **输入** Tab `Input_label` 正确展示之前 **不得** 问 `db_id`：

- 阶段 A **不问** `db_id`  
- 阶段 B ① 确认标签展示  
- 阶段 C 有 `form_snapshot` 后 **先** 问 `db_id`  

`test_source_row` 只验证某源能读一行，**不替代** 定 `db_id`。

---

## 2. 用户旅程（业务脚本）

Host UI 按此展示；Orchestrator 按 §4.1 执行。`WizardHostPort` 见 §3.6。

### 阶段 A · 基本设置

用户点 **配置向导** → Host 显示「正在准备…」。

后台：静默 preflight（Playwright 可 import）→ `create_backend(profile)`（页内静默选 profile，见 §5.2）→ `read_toml_digest()` → `digest` + `pending`。

E4B 根据 digest **逐项**问模板级必填（工作表名、分隔符、`input_area` 等；**不含** `db_id`）。本地源 → `test_source_row`；Sheet 源 → `BrowserSession` 授权（按需 **展开** Edge）。**不问**「要不要 Google」总开关。

Step **1/4：基本设置**

### 阶段 B · 粘贴样例

① 确认 Input_label 已正确识别（否 → 上一步或重新读取配置）。  
② 确认后 **展开 Edge**。  
③ 用户在 **输入** Tab 顶部粘贴并填表（勿点「下一行」）→ **回对话框** 点继续。

后台采集 `paste_sample` + `form_snapshot`。

Step **2/4：粘贴样例**

### 阶段 C · 字段对齐

有 `form_snapshot` 后 **先** 定 `db_id`（`ask_user` / 选项）。

对 `index < 0` 字段逐批（≤5）：启发式 → LLM 试跑 → regex 轮（`thinking=True`）。

Host 默认显示「字段 x / y」；仅 `ask_user` / `db_id` 时显示选项。

Step **3/4：字段对齐**

### 阶段 D · 完成

`final_verify()` → 通过：「请 **应用配置**」；失败：仅 **业务错误** 列表。

Step **4/4：完成**

---

## 3. Host UI（薄适配层）

实现参考：`nicegui_ui/wizard_panel.py`（可整体重写）。**规范以本节为准**，不绑定 NiceGUI 布局细节。端口协议见 §3.6。

### 3.1 Stepper（唯一合法进度）

```
[ 基本设置 ] → [ 粘贴样例 ] → [ 字段对齐 ] → [ 完成 ]
```

禁止在 stepper / 主文案出现：`PRECHECK`、`cuda`、`litert`、`digest`、`HTTP 200`、`检查通过` 等。

### 3.2 壳层状态（与 Orchestrator 解耦）

| `host_state` | 用户看到 |
|--------------|----------|
| `PREPARING` | 「正在准备…」 |
| `PROMPT` | 当前一问或指引 |
| `WORKING` | 「正在处理…」或 `字段 x / y` |
| `DONE` | 完成 + [应用配置] |
| `FAILED` | 一句人话 + [关闭] |

Orchestrator 的 `user_step` / `paste_substep` **不得** 直接驱动 stepper 文案。

### 3.3 底栏

除 `PREPARING` 外每屏：**[ 上一步 ]**、**[ 重新读取配置 ]**、**[ 继续 / 确认 ]**（`WORKING` 时禁用）。

### 3.4 线框（示意）

对话框标题：`配置向导 · {template_id}`。主文案区 **同一时刻一事**。技术详情默认折叠（仅开发）。

### 3.5 Playwright 与 Host 分工

| 时机 | Edge | 对话框 |
|------|------|--------|
| 阶段 B ① | 不展开 | 确认标签 |
| 阶段 B ②③ | **展开** | 粘贴指引；用户 **回对话框** 点继续 |
| Sheet 授权（阶段 A） | 按需展开 | 「完成后点继续」 |
| 其余 | headless 或短暂开关 | 主控 |

### 3.6 `WizardHostPort`（Orchestrator ↔ UI 唯一耦合面）

```python
class WizardHostPort(Protocol):
    def on_state(self, host_state: str, *, step: int, message: str, **kwargs) -> None: ...
    def ask_choice(self, prompt: str, options: list[str]) -> str: ...
    def ask_confirm(self, prompt: str) -> bool: ...
    def wait_continue(self, prompt: str) -> None: ...
    def on_apply_config(self, template_id: str) -> None: ...
    def debug_detail(self, text: str) -> None: ...
```

| 方法 | 用途 |
|------|------|
| `on_state` | 更新 stepper、`WORKING` 进度 |
| `ask_choice` / `ask_confirm` | `ask_user`、单选确认 |
| `wait_continue` | 阶段 B 粘贴完成、Sheet 授权后 |
| `on_apply_config` | Host 侧重载 TOML、重建引擎（`ensure_exists` 流水线） |
| `debug_detail` | 可选折叠区；默认不调用 |

NiceGUI 实现：按钮在「输入配置」Tab 打开 `ui.dialog`；**不** 要求改 splitter / 其他 Tab 结构。

### 3.7 入口

| 项 | 说明 |
|----|------|
| 触发 | 「输入配置」页 **配置向导** 按钮 |
| 语义 | LLM 辅助改 TOML；**始终** 可启动（不以 verify 通过为闸门） |
| 进程 | 同进程 worker；不默认弹终端 |
| CLI | `python -m llm_gemma4 wizard --template {id}`（开发/CI） |

---

## 4. Orchestrator（应用核心）

### 4.1 阶段 A–G

```
WizardHostPort（对话框）
        │
        ▼
┌────────────────── Orchestrator ──────────────────────────┐
│  A. silent_preflight()     Playwright import；页内不查 8738   │
│  B. load_backend()         embed create_backend；失败→FAILED │
│  C. read_toml_digest()     → digest, pending（忽略 verify 错误）│
│  D. basic_config_loop()    E4B 逐项（**不含 db_id**）+ dispatch │
│  E. collect_paste()                                            │
│       E1. PROMPT 确认 Input_label（否 → go_back → D）           │
│       E2. 展开 Edge → 指引 → wait_continue                     │
│       E3. BrowserSession.collect_input_tab → paste + snapshot  │
│  F. field_map_loop()       db_id → 启发式 → LLM → regex        │
│  ※ go_back_user_step() / reload_toml_from_disk() 任意 PROMPT   │
│  G. final_verify()         verify_toml → DONE / 业务错误         │
└──────────────────────────────────────────────────────────────┘
        │
        ▼
templates/{id}/{id}.toml    temp/wizard/{id}.json
```

| `user_step` | 阶段 | 后台 |
|-------------|------|------|
| — | 准备 | A + B |
| 1 | A | C + D |
| 2 | B | E1→E2→E3 |
| 3 | C | F |
| 4 | D | G |

### 4.2 平台接口用法

| 嵌入接口 | 向导用法 |
|----------|----------|
| `create_backend(profile)` | B；`generate(thinking=…)` 在 D/F |
| `ContextStore` + `Compressor` | 每轮 LLM 前装填；遵守 embed §4 写入禁令 |
| `ActionParser.parse_action` | 解析 E4B 输出 |
| `BrowserSession` | E3、Sheet 授权；**不由 E4B JSON 触发** |
| `health_check` | 仅日志 / `debug_detail` |

### 4.3 环境检查

| 检查项 | 页内 | CLI |
|--------|------|-----|
| Playwright | 静默；失败→FAILED | 同左 |
| Node.js | 仅 debug | 同左 |
| 8738 HTTP | **不检查** | 可选 |
| LiteRT + 权重 | 静默加载 | 同左 |

### 4.4 Playwright 策略（应用层）

在 embed `BrowserSession` 之上：

| 项 | 规则 |
|----|------|
| 通道 | Edge `channel=msedge` |
| 展开 | 阶段 B（确认标签后）、Sheet 授权 |
| 其余 | headless 或短暂开关 |
| 禁止 | 对话框刷 DOM/截图；把 Edge 当主界面 |

### 4.5 `toml_io`（应用模块）

| 操作 | 行为 |
|------|------|
| `read_toml_digest` | `digest` + `pending`；verify 错误预期存在，**完成前不消费** |
| `apply_patch` | backup `.bak` → 落盘 → `verify_toml`；失败回滚 |
| 试跑 | `test_regex` / `test_paste_split` / `test_source_row` |
| patch 失败 observation | 压缩错误 bullet 进 LLM；**不** 向用户刷屏 |

业务语义 **只读** `app/core_toml.py`（`load_toml`、`verify_toml`、`TomlGenerator`）。

### 4.6 Google Sheet

| 规则 | 说明 |
|------|------|
| 不问总开关 | 按 digest 缺项逐项处理 |
| 触发 | 配置项需要 Sheet 或字段 `source_file` 指向 Sheet |
| 放弃 | `skip_google`；后续不写 Sheet 源 |
| 失败 | 见 `connect_google.md`；`--resume` 续跑 |

### 4.7 E4B 调用策略

| 环节 | `thinking` |
|------|------------|
| 基本设置 | `False` |
| `db_id` | `False` |
| index / 数据源试跑 | `False` |
| regex | `True` |
| 预算耗尽 | 停止 F；Host 报告未映射项 |

### 4.8 E4B JSON action（应用层窄表）

每轮一个 JSON → `dispatch(action)`：

| action | 说明 | thinking |
|--------|------|----------|
| `set_top_level` | 模板级 patch | 否 |
| `patch_field` | 字段 patch | 否 |
| `test_paste_split` | 试分列 | 否 |
| `test_source_row` | 试数据源一行 | 否 |
| `test_regex` | 试 regex | 是 |
| `ask_user` | 挂起 → `WizardHostPort` | 否 |
| `read_toml` | 刷新 digest（后台） | 否 |

**不在 E4B JSON 中**：`browser_snapshot`、`browser_click`——Orchestrator 直接调 `BrowserSession`。

### 4.9 持久化

`temp/wizard/{template_id}.json`：

`user_step`、`paste_substep`、`paste_sample`、`form_snapshot`、`skip_google`、`llm_calls`、`field_cursor`、`db_id_resolved`

### 4.10 文件白名单（应用写权限）

| 路径 | 权限 |
|------|------|
| `templates/**/{id}.toml` | 读写（须 verify + `.bak`） |
| `templates/**/*.toml.bak.*` | 写 |
| `temp/wizard/**` | 读写 |
| `app/**`、`nicegui_ui/**` | 只读 |
| `credentials/**` | **禁止** LLM 直接读写 |
| `exports/**` | 只读 |

### 4.11 `go_back` 与 `reload`

见 §1.3。`reload` 以磁盘为准；业务错误仅在 G / 阶段 D 展示。

---

## 5. 触发与 profile（应用策略）

| 条件 | 行为 |
|------|------|
| 用户点「配置向导」 | **始终** 可启动 |
| 首次 `ensure_exists` 后 | 可建议运行向导（可选） |
| 页内 `profile` | `hardware_probe` 后：env `LLM_PROFILE` → 若仅一个合法 profile 则自动选用 → 否则用机器默认（如 150U→`openvino`，4070→`cuda`）；**不** 弹 TTY 菜单 |
| CLI `wizard` | 可走 embed 交互菜单或 `--profile` |

---

## 6. 模块归属（实现参考）

| 模块 | 职责 |
|------|------|
| `wizard/orchestrator.py` | A–G、`user_step`、调 embed 接口 |
| `wizard/toml_io.py` | digest / patch / 试跑 |
| `wizard/dispatch.py` | §4.8 action 路由 |
| `wizard/prompts.py` | system/user 模板 |
| `wizard/state.py` | `temp/wizard/*.json` |
| `wizard/preflight.py` | Playwright import 探测 |
| `host/nicegui_wizard.py` | `WizardHostPort` 的 NiceGUI 实现 |
| `__main__.py wizard` | CLI 入口 → orchestrator |

embed 包内 **不含** 上述应用语义；`wizard` 子命令仅委托应用层。

---

## 7. 废弃（v2.x 及误加能力）

- `chat` 子命令与 ReAct `agent/loop.py`  
- PowerShell.MCP、Cursor Browser MCP 读写 TOML 或驱动浏览器  
- stepper 展示 `WizardPhase` / `PRECHECK` / `READ_TOML`  
- 页内 HEAD `8738`、运维成功刷屏  
- Google 总开关、Input_label 未确认前问 `db_id`  
- 非 regex 默认 `thinking=True`  
- 对话日志瀑布 / Chat 式向导 UI  
- verify 未通过才允许打开向导  

---

## 8. 验收标准（产品）

1. Host 启动向导，无运维刷屏。  
2. Stepper 仅 4 个业务名；失败信息业务化。  
3. 基本设置逐项问；不问 `db_id`；无 Google 总开关。  
4. 粘贴：确认标签 → 展开 Edge → 输入 Tab 粘贴填表 → 回对话框继续。  
5. 字段对齐：`form_snapshot` 后先 `db_id`；仅 regex 开 thinking。  
6. 每屏有上一步 / 重新读取配置；手工改 TOML 后可 reload。  
7. 对话框主控；Edge 仅操作台。  
8. 换一套实现 `WizardHostPort` 时，Orchestrator 与 embed 无需改动。  
9. `Ginger_Lots` 无 Google 时可跑通且 `final_verify` 通过。  

平台 smoke/probe 验收见 [`embed_gemma4.md`](embed_gemma4.md) §8。

---

## 9. 相关文档

| 主题 | 文档 |
|------|------|
| LiteRT、上下文、BrowserSession | `embed_gemma4.md` |
| TOML 字段语义 | `toml_config_design.md` |
| Google OAuth | `connect_google.md` |

---

*应用层唯一权威：§2 用户旅程、§4 Orchestrator、§3 Host 适配。实现 `llm_gemma4/` 自零开始时先 embed §3–§6，再本文件 §4–§6。*
