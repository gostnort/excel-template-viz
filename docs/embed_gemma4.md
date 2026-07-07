# Gemma 4 E4B · LiteRT 运行时规格

> 状态：v6.0（**仅** 推理驱动与内容交互接口；不含向导编排、不含 UI）  
> 日期：2026-07-06  
> 应用层：[`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md)（TOML 配置向导如何 **使用** 本规格）  
> 模型：**Gemma 4 E4B（约 4B）** · [litert-community/gemma-4-E4B-it-litert-lm](https://huggingface.co/litert-community/gemma-4-E4B-it-litert-lm) · `gemma-4-E4B-it.litertlm`

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | 模型怎么加载、怎么 `generate`、上下文怎么装、Playwright 产出什么 **数据结构** |
| [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) | 向导 **何时** 调驱动、**何时** 调浏览器、TOML 怎么 patch、用户对话框显示什么 |

**不在本文件**：向导阶段、E4B action 表、NiceGUI 线框、`verify_toml` 业务闸门、Google Sheet 产品规则、实施 checklist。

**不在本期平台**：`chat` 模式、云端 API、PowerShell.MCP、Cursor Browser MCP、无校验自主 Agent、训练/微调。

---

## 1. 硬件与 profile

### 1.1 参考机器（客户机）

**Intel Core 7 150U**：Raptor Lake-U · **无** NPU GenAI · **Iris Xe 96EU** · 内存与核显共享带宽。

| 环境 | 推荐 profile | LiteRT backend |
|------|--------------|----------------|
| RTX 4070 测试机 | `cuda` | `Backend.GPU()` + MTP |
| Core 7 150U 客户机 | `openvino` | `Backend.GPU()` 核显（profile 名保留；**非** OpenVINO IR） |
| 兜底 | `cpu` | `Backend.CPU()` |

三档 **共用** `models/gemma4/gemma-4-E4B-it.litertlm`（约 3.66 GB）。

### 1.2 profile 参数

| 配置项 | `cpu` | `cuda` | `openvino` |
|--------|-------|--------|------------|
| `litert_backend` | `cpu` | `gpu` | `gpu` |
| MTP | `false` | `true` | `true` |
| `thinking_budget` | 512 | 1024 | 512 |
| `compress_trigger_ratio` | 0.65 | 0.75 | 0.65 |
| `compress_model_summary` | `false` | `true` | `false` |

### 1.3 配置来源优先级

1. 调用方显式传入 `profile`
2. 环境变量 `LLM_PROFILE`
3. `llm_gemma4/profiles/{profile}.toml`
4. CLI 交互菜单（**仅** `probe` / `wizard` 等 CLI 入口；见 workflow §5 页内静默策略）
5. 仅一个合法 profile → 自动选用；零个 → 报错

**禁止**在多个合法 profile 时 silent 乱选（页内嵌入调用见 workflow：通常只剩自动选用或 env 固定）。

---

## 2. 包布局（平台根 `llm_gemma4/`）

```
llm_gemma4/
  __main__.py              # probe | download | smoke | wizard（wizard 委托应用层）
  config.py
  models_catalog.py
  hf_download.py
  profiles/
    cpu.toml  cuda.toml  openvino.toml
  runtime/
    hardware_probe.py
    thinking.py
    context_store.py
    compressor.py
    context_config.py
  backends/
    base.py                # LlmBackend 协议
    factory.py
    litert/
      backend.py
      litert_probe.py
      requirements.txt
      scripts/
        download_litert.py
        smoke_test_litert.py
  tools/
    browser_playwright.py  # BrowserSession 实现
    browser_state.py       # DOM → PageState

models/gemma4/
  gemma-4-E4B-it.litertlm

test/llm_gemma4/
```

向导编排、`toml_io`、`action_parser`、持久化状态等 **应用模块** 由 workflow 定义归属；实现时可放在 `llm_gemma4/wizard/` 或同级包，但 **语义以 workflow 为准**。

**废弃路径**：`app/llm/`、GGUF、OpenVINO GenAI IR、`chat` 子命令、`mcp/` 服务端。

---

## 3. 推理驱动：`LlmBackend`

### 3.1 协议

```python
class LlmBackend(Protocol):
    def generate(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> GenerateResult: ...

    def count_tokens(self, text: str) -> int: ...

    def health_check(self) -> HealthReport: ...
```

| 字段 / 行为 | 说明 |
|-------------|------|
| `GenerateResult.text` | 模型最终 answer 通道文本（thought 已剥离） |
| `GenerateResult.raw` | 可选；调试 |
| `thinking=True` | 启用 Gemma 4 reasoning channel；由 **调用方** 决定何时开（workflow：仅 regex） |
| `temperature` | 固定 `0` |
| `health_check` | 返回 `profile`、`litert_backend`、MTP、`.litertlm` 路径；**不进** 向导用户 UI |

### 3.2 工厂

```
create_backend(profile: str) -> LlmBackend
  → 读 profiles/{profile}.toml
  → LiteRtBackend(Engine + Conversation)
```

### 3.3 Thinking 解析（`runtime/thinking.py`）

- 输入：含 `<|channel>thought` … `<channel|>` 的原始输出  
- 输出：`(thought, answer)`；**thought 不得写入 `ContextStore` 长期层**  
- `thinking_budget` 超限：截断 thought，保留 answer 解析

### 3.4 CLI：探测 / 下载 / 冒烟

```bat
python -m llm_gemma4 probe
python -m llm_gemma4 probe --json
python -m llm_gemma4 download --profile all
python -m llm_gemma4 smoke --profile cuda
```

| 子命令 | 用途 |
|--------|------|
| `probe` | `hardware_probe.detect()`；不加载权重 |
| `download` | `hf_download.download_litert()` → `models/gemma4/` |
| `smoke` | 短 prompt 生成；验收 tok/s 与 backend 实际路径 |

**探测项**（`HardwareReport`）：CPU 厂商/型号、LiteRT 是否可 import、NVIDIA（`nvidia-smi`）、Intel 核显、可选 `ram_gb`。

**权重下载**（需 `hf auth login` + Gemma 许可）：

```bat
hf download litert-community/gemma-4-E4B-it-litert-lm ^
  gemma-4-E4B-it.litertlm --local-dir models/gemma4
```

**废弃权重**：GGUF `google/gemma-4-E4B-it-qat-q4_0-gguf`、OV IR `OpenVINO/gemma-4-E4B-it-int4-ov`。

### 3.5 依赖

```bat
pip install -r llm_gemma4/backends/litert/requirements.txt
pip install huggingface-hub playwright psutil
playwright install msedge
```

`litert-lm-api` 为三档 profile 唯一推理包。不再安装 `llama-cpp-python`、`openvino-genai`。

**Windows + NVIDIA**：LiteRT `Backend.GPU()` 走 WebGPU/ML Drift；失败时可 `allow_cpu_fallback=true`，以 `health_check` 打印的 **实际 backend** 为准。

---

## 4. 上下文接口：`ContextStore` + `Compressor`

应用层（向导）组 prompt 前经此层装填与裁剪。

### 4.1 分层

```
Layer 0  system_prompt（固定）
Layer 1  task_anchor（任务锚点，不丢）
Layer 2  recent_turns（最近 K 轮完整对话）
Layer 3  tool_trace_summary（更早轮 bullet 摘要）
Layer 4  latest_browser_state（仅最新一帧 PageState 摘要）
```

| profile | `recent_turns` K |
|---------|------------------|
| cuda | 4 |
| openvino / cpu | 3 |

### 4.2 触发

`estimate_tokens(layers) > n_ctx * compress_trigger_ratio` → `Compressor.run()`。

估算：优先 `backend.count_tokens()`；否则 `len(text)//3`。

### 4.3 压缩档位

**档 A（openvino / cpu 默认）**：删最旧 2 轮 → 压成 ≤8 行 bullet 入 Layer 3；丢弃历史 browser 帧；剥离漏网 thought。

**档 B（cuda 可选）**：无 thinking 单轮 ≤200 字摘要入 Layer 3；openvino/cpu **默认关闭**。

### 4.4 写入约束（平台强制）

| 允许入栈 | 禁止入栈 |
|----------|----------|
| 截断后的 tool observation | 完整 `.toml` 原文 |
| digest / pending 摘要（由应用层提供） | `subprocess` stdout 全文 |
| 压缩后的 regex 试错 bullet | 完整 DOM |
| 短 paste 片段 | thought 全文 |

单条 observation 上限：`tool_observation_max_chars`（profile 可配）。

### 4.5 溢出防护

| 场景 | 行为 |
|------|------|
| `generate` 前仍超 90% `n_ctx` | 仅保留 task_anchor + 最近 1 轮 + 最新 PageState 摘要 |
| `finish_reason=length` | 降 `max_tokens`，压缩后重试 1 次 |

---

## 5. 浏览器接口：`BrowserSession` + `PageState`

Playwright 封装；**不** 定义向导何时展开窗口（见 workflow §4.4）。

### 5.1 启动

| 项 | 值 |
|----|-----|
| 默认 | `chromium.launch(channel="msedge")` |
| 备选 | 环境变量 `BROWSER_CHANNEL=firefox` |
| 目标 URL | 由调用方传入（通常 NiceGUI `http://127.0.0.1:8738/`） |
| `headless` | 由调用方传入 |

**不用**：内置 Chromium 作默认、Chrome channel、Cursor Browser MCP、CDP 附着（除非调用方显式高级配置）。

### 5.2 `PageState`（唯一 DOM 观测结构）

```text
url, title, active_tab, template_id,
form_fields[{label, value}],
paste_ghost_value,
session_table_summary,
interactive_refs[]（≤40，可点击优先）,
dom_excerpt（截断）,
screenshot_path（可选；仅路径进上下文）
```

### 5.3 `BrowserSession` 方法（平台 API）

| 方法 | 返回 |
|------|------|
| `start()` / `close()` | — |
| `navigate(url)` | — |
| `click_tab(name)` | — |
| `collect_input_tab(template_id)` | `PageState` |
| `probe_google_connection()` | `PageState` + 连接提示字段 |

`browser_state.py` 在返回前截断 `dom_excerpt`、`interactive_refs`；超长则返回错误对象供应用层重试。

### 5.4 与压缩衔接

- 仅 **最新** PageState 摘要进入 ContextStore Layer 4  
- 截图文件落 `test/llm_gemma4/_shots/` 或调用方指定目录；**不进** 模型上下文二进制

---

## 6. 模型输出解析接口：`ActionParser`

平台提供 **从 answer 文本提取一个 JSON 对象** 的能力；**不** 定义 action 语义表（属 workflow §4.8）。

```python
def parse_action(text: str) -> dict:
    """返回 {"action": str, ...}；失败抛 ActionParseError。"""
```

约定：

- 每轮期望 **一个** JSON 对象  
- 解析失败：应用层可重试 1 次 `generate`  
- JSON 字段校验与 `dispatch` 由 **应用层** 实现

---

## 7. 单进程原则

`LlmBackend`、`ContextStore`、`BrowserSession` 由应用进程持有；**不** 另起推理 HTTP 服务；**不** 为 LLM 另开端口。

---

## 8. 平台验收（非向导产品验收）

1. `probe` 在 4070 / 150U / 纯 CPU 上给出正确 profile 列表  
2. `download` 得到 `models/gemma4/gemma-4-E4B-it.litertlm`  
3. `smoke --profile cuda` 在 4070 通过  
4. `smoke --profile openvino` 在 150U 通过（建议门禁 ≥5 tok/s）  
5. `smoke --profile cpu` 通过  
6. `health_check` 打印实际 `litert_backend` 与 MTP 状态  
7. Playwright Edge 能导航调用方 URL 并产出 `PageState`  

向导产品验收见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §9。

---

## 9. 相关文档

- [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) — TOML 配置向导（应用层）  
- [`toml_config_design.md`](toml_config_design.md) — 字段语义（业务，非平台）  
- [`connect_google.md`](connect_google.md) — OAuth（业务）
