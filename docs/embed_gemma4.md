# Gemma 4 E4B · LiteRT 运行时规格

> 状态：v6.1（**仅** 推理驱动、结构化判定接口与内容交互；不含向导编排、不含 UI、**不含** 各业务域 prompt）  
> 日期：2026-07-10  
> 应用层：[`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md)（TOML 向导）；[`embed_paddle_ocr.md`](embed_paddle_ocr.md)（OCR 语义门禁，**调用方** 实现）  
> 模型：**Gemma 4 E4B（约 4B）** · [litert-community/gemma-4-E4B-it-litert-lm](https://huggingface.co/litert-community/gemma-4-E4B-it-litert-lm) · `gemma-4-E4B-it.litertlm`

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | 模型怎么加载、怎么 `generate`、**单次判定**怎么从模糊输出收成明确 `JudgmentResult`、多轮上下文怎么装、Playwright 产出什么 **数据结构** |
| [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) | 向导 **何时** 调驱动、**何时** 调浏览器、TOML 怎么 patch、用户对话框显示什么 |
| [`embed_paddle_ocr.md`](embed_paddle_ocr.md) | fast OCR 草稿 **何时** 算语义有问题、**何时** 调 PaddleVL；`HasOcrSemanticProblem` 与 prompt **归 OCR 平台** |

**不在本文件**：向导阶段、E4B action 表、NiceGUI 线框、`verify_toml` 业务闸门、Google Sheet 产品规则、OCR JSON / `string*` / `table*` 语义、PaddleVL、实施 checklist。

**不在本期平台**：`chat` 模式、云端 API、PowerShell.MCP、Cursor Browser MCP、无校验自主 Agent、训练/微调。

### 0.1 解耦原则（底座 vs 应用）

```
llm_gemma4/（本规格）              应用层（各自文档）
─────────────────────              ────────────────────
LlmBackend.generate                gemma4_e4b_workflow：向导编排
run_judgment / parse / normalize   embed_paddle_ocr：semantic_gate
JudgmentResult（明确三态）          HasOcrSemanticProblem → bool
```

| 层 | 职责 | 禁止 |
|----|------|------|
| **底座** `llm_gemma4/` | 加载权重、`generate`、从 answer **解析** JSON、把同义词/缺字段 **规范** 为稳定枚举 | 引用 `paddle_ocr`、拼 OCR 业务 prompt、决定「是否调 PaddleVL」 |
| **应用** `paddle_ocr/runtime/semantic_gate.py` 等 | 组 domain prompt、把 `JudgmentResult` **映射** 为业务布尔/分支 | 在底座内写 OCR 特例 |

模型输出 **天然不稳定**（措辞、字段名、布尔写法每次可能不同）。底座只保证：**同一套 normalize 规则下，调用方拿到可预测的 `JudgmentResult`**；业务上的「通过 / 不通过 / 默认保守」由应用层 **单独函数** 包装（例如 `HasOcrSemanticProblem`）。

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
    judgment.py            # parse_judgment / normalize_judgment（通用，无业务域）
    judge.py               # run_judgment：单次 generate + 解析 + 规范化
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

OCR 语义门禁的 prompt、`fast_json` 序列化、`semantic_problem` → `ShouldTryVl` 等 **一律在** `paddle_ocr/runtime/semantic_gate.py`（见 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §3.2），**不得**放进 `llm_gemma4/`。

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

### 3.6 单次判定接口：`run_judgment`（无业务域）

供 OCR 语义门禁、未来其它「是/否/不确定」类调用；**不**走 `ContextStore`、**不**开 `thinking`、**不**挂 `BrowserSession`。

#### 3.6.1 数据类型

```python
@dataclass(frozen=True)
class JudgmentSpec:
    """调用方传入；底座不内置任何 domain 文案。"""
    system: str
    user: str
    verdict_key: str = "verdict"          # 期望 JSON 中的判定字段名
    max_tokens: int = 256


@dataclass(frozen=True)
class JudgmentDraft:
    """parse 之后、normalize 之前；仍可能含糊。"""
    raw_text: str
    payload: dict | None
    parse_error: str | None


@dataclass(frozen=True)
class JudgmentResult:
    """底座对外稳定结果；业务层再映射为 bool / 分支。"""
    verdict: Literal["affirmative", "negative", "unknown"]
    reason: str
    raw_text: str
    normalized_from: Literal["json", "keyword", "default"]  # 规范化来源，便于日志
```

| `verdict` | 含义 |
|-----------|------|
| `affirmative` | 模型倾向「是 / 有问题 / 成立」类结论 |
| `negative` | 模型倾向「否 / 无问题 / 不成立」 |
| `unknown` | 解析失败、字段缺失、或落在同义词表之外 |

底座 **不** 定义 `affirmative` 在 OCR 里是否等于 `semantic_problem: true`；该映射在 `paddle_ocr`。

#### 3.6.2 调用链（底座内）

```python
def run_judgment(backend: LlmBackend, spec: JudgmentSpec) -> JudgmentResult: ...

def parse_judgment(text: str, *, verdict_key: str) -> JudgmentDraft: ...

def normalize_judgment(
    draft: JudgmentDraft,
    *,
    verdict_key: str,
    affirmative: frozenset[str],
    negative: frozenset[str],
    default_on_ambiguous: Literal["affirmative", "negative", "unknown"] = "unknown",
) -> JudgmentResult: ...
```

```
run_judgment
  → backend.generate([system, user], thinking=False, temperature=0, max_tokens=spec.max_tokens)
  → parse_judgment(answer_text, verdict_key=spec.verdict_key)
  → normalize_judgment(draft, affirmative=..., negative=..., default_on_ambiguous=...)
  → JudgmentResult
```

| 步骤 | 职责 |
|------|------|
| `generate` | 只产出自然语言 / JSON 字符串 |
| `parse_judgment` | 从 answer 抽出 **一个** JSON 对象（容忍 markdown 围栏、前后缀废话）；失败则 `payload=None` |
| `normalize_judgment` | 把布尔、字符串、`yes/no/是/否/true/false/1/0` 等同义词 **映射** 到三态；**禁止**把 OCR 字段名写死在此文件 |

#### 3.6.3 `parse_judgment` 约定

- 与 `ActionParser`（§6）共用「单 JSON 对象」抽取策略时可复用内部 helper，但 **判定字段校验** 独立于 wizard `action` 表。
- 解析失败 **不** 抛给应用层；返回 `JudgmentDraft(parse_error=...)`，由 `normalize_judgment` 落 `unknown` 或 `default_on_ambiguous`。
- `finish_reason=length`：降 `max_tokens` 重试 1 次（与 §4.5 一致），仍失败 → `unknown`。

#### 3.6.4 `normalize_judgment` 约定（模糊 → 明确）

模型每次措辞可能不同；规范化规则 **钉死在底座**，保证同输入分布下结果稳定：

| 原始值（`payload[verdict_key]` 或全文关键词） | 映射 |
|-----------------------------------------------|------|
| `true` / `yes` / `是` / `有` / `problem` / `1`（及 `affirmative` 集内其它） | `affirmative` |
| `false` / `no` / `否` / `无` / `ok` / `0`（及 `negative` 集内其它） | `negative` |
| 缺失、无法解析、同时命中正反、模棱两可 | `default_on_ambiguous`（默认 `unknown`） |

`reason`：优先取 JSON 内 `reason` / `explanation` 字符串；否则截断 `raw_text` ≤200 字。

**应用层包装示例**（文档归属 [`embed_paddle_ocr.md`](embed_paddle_ocr.md)，**不在** `llm_gemma4` 实现）：

```python
# paddle_ocr/runtime/semantic_gate.py（应用层）
def HasOcrSemanticProblem(fast_result: dict) -> bool:
    spec = _build_ocr_judgment_spec(fast_result)   # OCR 专用 prompt + verdict_key
    result = run_judgment(_lazy_backend(), spec)
    return _ocr_semantic_to_bool(result)             # 单独函数：三态 → 是否调 PaddleVL
```

`_ocr_semantic_to_bool` 建议策略（产品层，可测）：

| `JudgmentResult.verdict` | `HasOcrSemanticProblem` |
|--------------------------|-------------------------|
| `affirmative` | `True` |
| `negative` | `False` |
| `unknown` | `False`（保守：不调 VL，避免误触发；fast 抛错时由 OCR 平台 **不经 Gemma** 直接视为问题） |

#### 3.6.5 与向导路径的关系

| 路径 | ContextStore | thinking | 典型调用方 |
|------|--------------|----------|------------|
| 向导多轮 | 是 | 按需 | `gemma4_e4b_workflow` |
| 单次判定 | **否** | **否** | `paddle_ocr/semantic_gate`、未来其它门禁 |

两路径 **共用** `create_backend()` 与进程内单例；OCR 判定 **不得** 向 `ContextStore` 写入 fast JSON 全量。

---

## 4. 上下文接口：`ContextStore` + `Compressor`

应用层（向导）组 prompt 前经此层装填与裁剪。**单次判定（§3.6）不得经过本层。**

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

## 8. 平台验收（非向导 / 非 OCR 产品验收）

1. `probe` 在 4070 / 150U / 纯 CPU 上给出正确 profile 列表  
2. `download` 得到 `models/gemma4/gemma-4-E4B-it.litertlm`  
3. `smoke --profile cuda` 在 4070 通过  
4. `smoke --profile openvino` 在 150U 通过（建议门禁 ≥5 tok/s）  
5. `smoke --profile cpu` 通过  
6. `health_check` 打印实际 `litert_backend` 与 MTP 状态  
7. Playwright Edge 能导航调用方 URL 并产出 `PageState`  
8. `run_judgment` 对固定 stub backend：`{"verdict": true}` / `{"verdict": "否"}` / 非法文本 → 稳定 `JudgmentResult` 三态（**不**测 OCR prompt）  

向导产品验收见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §9。OCR 语义门禁与 PaddleVL 联动验收见 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §7。

---

## 9. 相关文档

- [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) — TOML 配置向导（应用层）  
- [`embed_paddle_ocr.md`](embed_paddle_ocr.md) — OCR fast → Gemma 门禁 → PaddleVL（`HasOcrSemanticProblem` 属应用层）  
- [`toml_config_design.md`](toml_config_design.md) — 字段语义（业务，非平台）  
- [`connect_google.md`](connect_google.md) — OAuth（业务）
