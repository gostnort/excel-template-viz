# llm_cli 设计：工人检索与 MCP 就绪检测

状态：feature-llm-toml-5  
包：[`llm_cli/`](../llm_cli/)  
运行：`.\uv_run.ps1 python -m llm_cli`

本 CLI 用 LM Studio 的 OpenAI 兼容 `/v1/chat/completions` 做推理（`tool_calls` 由 Python 执行）。**不要**把 LM Studio Chat 里的整套 MCP 工具 schema 灌进 CLI 的 completions——视觉模型（Gemma 4、Ornith 1.5）会因此 prefill 到上万 token。LM Studio 的 MCP 配置仍要配齐，供 Chat UI 与本机二进制探活使用。

## 检索分工

| 场景 | 承担方 | 做法 |
|------|--------|------|
| 未知名词、术语、专名 | MCP **desktop-commander** | `read_file`，`path` 为 Wikipedia 页或搜索 URL，`isUrl=true`。同时可用同一工具读本地文件（`isUrl` 省略或 false）。 |
| 百科不够、需要网页摘要 | **Playwright**（备选） | 自带 Chromium 打开 `https://www.bing.com/search?q=...`，只抽结果卡片。不要求用户级 Chrome，不用 Google。 |

工人子代理（`ask_worker`）工具：

1. `wikipedia_lookup` — 首选。desktop-commander 拉 Wikipedia，HTML 剥成短文本再交给模型。
2. `read_local_file` — desktop-commander 读本地路径。
3. `web_search` — Bing 备选；仅在百科失败、条目不存在、或用户明确要网上近况时用。

主代理仍然只有 `ask_worker`。工人输出过长则经压缩子代理，只有短摘要进入主对话 history。

## 两个 MCP 在 LM Studio 里要满足的条件

服务器登记：`%USERPROFILE%\.lmstudio\mcp.json` 的 `mcpServers` 必须同时有：

- `desktop-commander`（command 一般为 `desktop-commander`）
- `playwright`（command 一般为 `playwright-mcp`）

本机二进制要能在 PATH 上找到（Windows 含 `.cmd`）。插件目录存在：

- `~/.lmstudio/extensions/plugins/mcp/desktop-commander/manifest.json`
- `~/.lmstudio/extensions/plugins/mcp/playwright/manifest.json`

默认对话启用：LM Studio `settings.json` → `chat.pinnedPlugins` 含 `mcp/desktop-commander` 与 `mcp/playwright`（钉到新对话）。当前选中对话的 `plugins` 数组也应包含这两项。

同意运行全部工具：`chat.neverAskForToolConfirmation == true`，或 `chat.skipToolConfirmationPatterns` 含通配：

- `mcp/desktop-commander:*`
- `mcp/playwright:*`

Bing 备选另需 Playwright 自带 Chromium（`.\uv_run.ps1 playwright install chromium`），与是否安装用户 Chrome 无关。

## 启动检测与状态文件

第一次启动 CLI 即跑检测。四类条件（二进制存在、`mcp.json` 登记、默认对话钉住/当前对话启用、允许全部工具）**全部为真**才算就绪。

- 未就绪：每次启动都重新检测，并打印警告（缺哪条说哪条）。
- 已就绪：若状态文件里的指纹与当前 `mcp.json` / `settings.json` / 选中对话 `plugins` 一致，则静默，不再刷屏。
- 指纹变化（用户改了配置）：再检测一次；仍就绪则更新指纹且无警告，否则恢复每次警告。

状态写入 gitignore 文件 [`llm_cli/lm_studio/mcp_ready.json`](../llm_cli/lm_studio/mcp_ready.json)（勿提交）。内容包括 `all_ok`、`fingerprint`、`checked_at`、各分项 `ok`/`detail`、`warnings`。

`health` 命令始终打印当前分项，不依赖「上次已就绪就跳过」。

## 视觉模型

Gemma 4 / Ornith 1.5 等 `capabilities.vision=true` 的权重，在 LM Studio Chat 里挂满 MCP 仍会极慢。CLI 路径不受影响（只带上述三个工人工具）。Chat UI 用视觉模型时不要额外再开 chrome-devtools 等无关 MCP。

## 包布局

- [`llm_cli/`](../llm_cli/) — Agent / 壳 / LM Studio 客户端
- [`mcp_desktop/`](../mcp_desktop/) — desktop-commander stdio（Wikipedia + 本地文件）
- [`mcp_playwright/`](../mcp_playwright/) — Playwright Chromium + Bing
