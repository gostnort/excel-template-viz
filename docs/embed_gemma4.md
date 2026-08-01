# Gemma 4 E4B · LiteRT 运行时规格

> 状态：**v7.0**（推理驱动 + 结构化判定；**不含**向导编排、UI、业务 prompt）  
> 日期：2026-07-26  
> 应用层：[`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md)（TOML 向导）；[`embed_paddle_ocr.md`](embed_paddle_ocr.md)（OCR 语义门禁）  
> 模型：**Gemma 4 E4B（约 4B）** · [litert-community/gemma-4-E4B-it-litert-lm](https://huggingface.co/litert-community/gemma-4-E4B-it-litert-lm) · `gemma-4-E4B-it.litertlm`

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | 模型怎么加载、三条推理路径（无状态 / 主 Session / 字段子 Session）各自怎么用、`run_judgment` 怎么收成 `JudgmentResult` |
| [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) | 向导何时调主对话、何时派子 agent、TOML 怎么 patch、UI 显示什么 |
| [`embed_paddle_ocr.md`](embed_paddle_ocr.md) | fast OCR 草稿何时算语义有问题、何时调 PaddleVL |

**不在本文件**：向导 7 步业务、NiceGUI 线框、`verify_toml`、Google Sheet 产品规则、OCR 单元语义、PaddleVL。

**不在本期平台**：`chat` 模式、云端 API、Playwright / 浏览器自动化、无校验自主 Agent、训练/微调、独立 LLM HTTP 服务。

### 0.1 解耦原则（底座 vs 应用）

```
llm_gemma4/（本规格）                    应用层
─────────────────────                    ────────────────────
generate / run_judgment                  paddle_ocr：HasOcrSemanticProblem
ConversationOnce / Pic2Str               paddle_ocr：GemmaVisionCorrect
StartGemma / EndGemma
open_session + SessionOptions            gemma4_e4b_workflow：主对话 + 字段子 agent
```

| 层 | 职责 | 禁止 |
|----|------|------|
| **底座** `llm_gemma4/` | 加载权重、无状态 `generate`、有状态 `open_session`、`run_judgment` 三态规范化 | 引用 `paddle_ocr`、拼 OCR/向导业务 prompt |
| **应用** | 组 domain prompt、编排主/子 Session、JSON 字段解析、`WizardState` | 在底座内写 OCR 或向导特例 |

### 0.2 已落地 vs 待实现（与代码现状对齐）

**已落地且被 Paddle-OCR 使用（冻结，勿破坏语义）**：

| API | 调用方 |
|-----|--------|
| `StartGemma()` / `EndGemma()` / `ResetBackend()` | `paddle_ocr/main.py` |
| `run_judgment(backend, spec)` | `paddle_ocr/gate/semantic_gate.py` |
| `ConversationOnce(...)` | `paddle_ocr/gate/gemma_vision_correct.py` |
| `Pic2Str(...)` | `paddle_ocr/gate/gemma_vision_correct.py` |
| `create_backend()` → `LiteRtBackend.generate` / `generate_vision` / `warm` / `health_check` | 上述路径间接使用 |

**待实现（仅 TOML 向导需要；与现有向导原型代码无兼容义务）**：

| API | 用途 |
|-----|------|
| `open_session(session_id, *, options: SessionOptions)` | 主对话 `wizard_main`、字段子 agent `field_{label}_{attempt}` |
| `SessionOptions.system_message` | 创建 Conversation 时注入 system prompt |
| `SessionOptions.thinking` | 会话级 Thinking（失败重试时**新开** thinking session，不在同 session 内切换） |
| `SessionOptions.max_tokens` | 子 agent 输出预算；thinking 重试读 profile `thinking_budget` |

向导内的 JSON 解析、`re.search` 回验、7 步状态机、主对话摘要注入 — **一律归** `llm_gemma4/wizard/`（见 workflow 文档），**不**在底座新增 `ActionParser` / `BrowserSession` / 完整 `ContextStore`。

---

## 1. 硬件与 profile

### 1.1 参考机器与实测结论

**Intel Core 7 150U**：Raptor Lake-U · 无 NPU GenAI · Iris Xe 96EU。

| 环境 | 显式 profile | `profile="auto"` 预期落点 |
|------|--------------|---------------------------|
| RTX 4070 测试机 | `cuda` → `Backend.GPU()` | `gpu` |
| Core 7 150U 客户机 | `openvino` → `Backend.GPU()` 核显 | 待实机（预期 `gpu` 或 `npu`） |
| 兜底 | `cpu` → `Backend.CPU()` | 级联最终兜底 |

权重：`models/gemma4/gemma-4-E4B-it.litertlm`（约 3.66 GB）。

**实测（2026-07-11，RTX 4070，`litert-lm==0.14.0`）**：

- `Backend.GPU()` 走 WebGPU（Windows → Direct3D 12）；无 CUDA 专属 backend、无 ONNX/OpenVINO-IR 路径。
- GPU 冷启动含 shader 编译约 10–12s；CPU 冷启动约 0.4s。
- 同一 `Engine` 复用：第 2 轮起 GPU 累计耗时优于 CPU；10 轮总耗时 GPU 约为 CPU 的 24%。
- **结论**：长生命周期进程应复用单 `Engine`；`auto` 默认 NPU → GPU → CPU 级联。

### 1.2 profile 参数（`profiles/*.toml`）

| 配置项 | `cpu` | `cuda` | `openvino` |
|--------|-------|--------|------------|
| `litert_backend` | `cpu` | `gpu` | `gpu` |
| `thinking_budget` | 512 | 1024 | 512 |

`thinking_budget`：**向导字段子 agent 在 thinking 重试阶段**读取；OCR `run_judgment` 不使用 thinking。

MTP、压缩比等字段可从 profile TOML 删除或保留占位，**不属于 v7.0 平台范围**。

### 1.3 配置来源优先级

1. 调用方显式 `profile`（`cpu`/`cuda`/`openvino` → 强制 backend，失败抛错）
2. 环境变量 `LLM_PROFILE`
3. 都没给 → `DEFAULT_PROFILE = "auto"` → `hardware_probe.build_engine()` 级联

---

## 2. 包布局（`llm_gemma4/`）

```
llm_gemma4/
  __main__.py           # ConversationOnce / Pic2Str / StartGemma / EndGemma
  __init__.py
  config.py
  hf_download.py
  profiles/
    cpu.toml  cuda.toml  openvino.toml
  runtime/
    hardware_probe.py
    thinking.py
    judgment.py         # parse_judgment / normalize_judgment
    judge.py            # run_judgment
  backends/
    base.py             # LlmBackend / LlmSession / SessionOptions 协议
    factory.py
    litert/
      backend.py        # LiteRtBackend
      session.py        # LiteRtSession
  wizard/               # 应用层；语义见 gemma4_e4b_workflow.md
    orchestrator.py
    prompts.py
    toml_patcher.py
    context.py          # 主对话外挂摘要（task_anchor、fields_done）；非底座

models/gemma4/
  gemma-4-E4B-it.litertlm
```

**废弃、不再规划**：`app/llm/`、GGUF、OpenVINO GenAI IR、`tools/browser_playwright.py`、`context_store.py`（全量 Layer 0–4）、`compressor.py`、`action_parser` 平台模块、`mcp/` 服务端。

---

## 3. 推理驱动：`LlmBackend`

### 3.1 三条会话生命周期

| 路径 | 调用方 | 接口 | Conversation | thinking |
|------|--------|------|--------------|----------|
| **无状态单次** | OCR `run_judgment`、一次性问答 | `generate(...)` | 临时，发完即关 | 否 |
| **主对话** | TOML 向导编排 | `open_session("wizard_main", options=...)` | 跨 7 步持久 | 否（拆任务/汇总用普通模式） |
| **字段子 agent** | 向导步骤 3/4/5 | `open_session("field_{label}_{attempt}", options=...)` | 单字段短生命周期 | 第 1 轮否；失败重试**新 session** 开 thinking |

三条路径 **共用** 同一 `Engine` 单例；`Conversation` 实例彼此隔离。OCR **不得**复用向导 session，**不得**向向导上下文写入 fast JSON 全量。

### 3.2 协议

```python
@dataclass(frozen=True)
class SessionOptions:
    system_message: str | None = None
    thinking: bool = False          # 会话级；litert_lm 创建 Conversation 时定死
    max_tokens: int | None = None   # None → 按 backend 自决（§3.4a）
    temperature: float = 0.0


class LlmBackend(Protocol):
    def generate(
        self,
        messages: list[dict],
        *,
        thinking: bool = False,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        judgment_tool: JudgmentToolSpec | None = None,
    ) -> GenerateResult: ...

    def generate_vision(
        self, image: str | Path | bytes, prompt: str, *, ...
    ) -> GenerateResult: ...

    def open_session(
        self, session_id: str, *, options: SessionOptions | None = None,
    ) -> LlmSession: ...

    def warm(self) -> None: ...
    def health_check(self) -> HealthReport: ...
    def close(self) -> None: ...


class LlmSession(Protocol):
    def send_turn(
        self, message: Mapping[str, Any], *, max_output_tokens: int | None = None,
    ) -> GenerateResult: ...
    def close(self) -> None: ...
    @property
    def token_count(self) -> int: ...
```

**litert_lm 约束（实测 0.14.0）**：`thinking` / `temperature` 在 `create_conversation(...)` 时设定，**不能**在同一 `Conversation` 内逐轮切换。子 agent「普通 → thinking 重试」= `close()` 旧 session + `open_session(..., thinking=True)` 新 session。

`send_turn` 只发 **user** 内容；`system_message` 仅在 `open_session` 的 `SessionOptions` 传入。

### 3.3 顶层便捷 API（OCR 路径 · 已落地）

#### `ConversationOnce` / `Pic2Str`

见 `llm_gemma4/__main__.py`。薄封装 `generate` / `generate_vision`；不做 JSON 解析。`max_tokens` 不对外暴露，由 backend 按硬件自决（§3.4a）。

单例 `_backend` 进程内有效；`create_backend(enable_vision=True)` 合并文本与视觉（实测显存差 ~0.4GB，可忽略）。

#### `StartGemma` / `EndGemma`

`StartGemma()` = `_get_backend().warm()`（必须 `warm()` 才提前扛冷启动）。`EndGemma()` = `ResetBackend()`。

CLI 最小形态：`python -m llm_gemma4 "问题"`（新进程单发，不享受单例复用）。

### 3.4 Thinking 解析（`runtime/thinking.py`）

`enable_thinking=True` 时响应含顶层 `"channels": {"thought": "..."}`，与 `"content"` 平级；**无需**正则切标签。

| 场景 | 处理 |
|------|------|
| `max_output_tokens` 太小 | `content` 可能为空；thinking 场景需更大预算 |
| thought 留痕 | **不得**写入向导主对话长期摘要 |

### 3.4a `max_tokens` 自决默认值

`generate(..., max_tokens=None)` 时按实测 backend：

```python
{"cpu": 512, "gpu": 1024, "npu": 512}
```

`run_judgment` 由调用方显式传 `spec.max_tokens`；约束解码路径下限 **200**（§3.6.1a）。

### 3.5 依赖

```bat
uv sync --extra llm
```

（`litert-lm==0.14.0` 与 `huggingface-hub` 在根 `pyproject.toml` 的 `llm` extra。）

**不需要** `playwright`（浏览器自动化已废弃）。

权重下载（需 `hf auth login` + Gemma 许可）：

```bat
hf download litert-community/gemma-4-E4B-it-litert-lm ^
  gemma-4-E4B-it.litertlm --local-dir models/gemma4
```

或由 `hf_download.ensure_model_async()` 在首次推理前后台拉取。

**原生日志静默**：首次构造 `Engine` 前 `set_min_log_severity(ERROR)`；调试设 `LLM_GEMMA4_VERBOSE=1`。

### 3.6 单次判定：`run_judgment`（OCR · 已落地）

供 `HasOcrSemanticProblem` 等「是/否/不确定」调用。**不走** `open_session`、**不开** thinking。

核心类型：`JudgmentSpec`、`JudgmentDraft`、`JudgmentResult`（`affirmative` / `negative` / `unknown`）。

约束解码走合成 tool + `enable_constrained_decoding=True`（§3.6.1a 实测要点保留）：

- 参数值可能是字符串 `"true"` → `normalize_judgment` 必须跑同义词表
- `max_output_tokens` < 200 时 tool call 可能静默退化为纯文本
- `verdict_key` 字母序须排在 `reason_key` 之前

应用层映射（`paddle_ocr/gate/semantic_gate.py`）：`affirmative`→调精修；`negative`/`unknown`→保守返回 false。

---

## 4. 主对话上下文（应用层 · 非底座）

全量 `ContextStore` Layer 0–4 + `Compressor` + 浏览器 `PageState` **已废弃**。

向导主对话如需跨步提醒，在 `llm_gemma4/wizard/context.py` 维护**极简摘要**，每轮 `send_turn` 前拼入 user 消息前缀（不重放完整历史——`Conversation` KV cache 已持有轮次）：

| 片段 | 内容 |
|------|------|
| `task_anchor` | 模板 id、目标 `db_id`、当前步骤 |
| `fields_done` | 已完成字段 bullet 列表 |
| `pending` | 排队中的 `Input_label` |

单条 observation 截断上限由 wizard 配置。主对话 KV 接近 4096 时，wizard 可丢弃最旧摘要 bullet 或提示用户结束向导——**不要求**底座实现 `Compressor`。

---

## 5. 单进程原则

`LlmBackend` 由 NiceGUI / `paddle_ocr` 进程持有；不另起推理 HTTP 服务；不为 LLM 另开端口。

---

## 6. 平台验收

### 6.1 OCR 路径（已验收项，回归时保留）

1. `profile="auto"` 在 4070 上落到 `gpu`
2. `hardware_probe.build_engine()` NPU/GPU 失败时正确降级
3. `run_judgment` stub：`{"has_problem": true}` / 非法文本 → 稳定三态
4. `run_judgment(use_constrained_decoding=True)` 无 `tool_calls` 时退回纯文本，不抛异常
5. `StartGemma` → `ConversationOnce` / `Pic2Str` / `run_judgment` 复用同一 Engine
6. `health_check` 报告实际 `litert_backend` 与模型路径

### 6.2 向导 Session 路径（待实现后验收）

1. `open_session("wizard_main", options=SessionOptions(system_message=...))` 创建带 system 的 Conversation
2. 同 `session_id` 复用同一 `Conversation`；`close()` 后重开为新实例
3. `open_session(..., thinking=True)` 响应含 `channels.thought`（当 budget 足够）
4. 字段子 agent：普通 session 与 thinking session 为**不同** `session_id`，互不污染
5. 向导与 OCR 并发调用时仍共用单 `Engine`，无重复加载权重

向导产品验收见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §7。OCR 验收见 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §7。

---

## 7. 相关文档

- [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) — TOML 配置向导（主对话 + 子 agent）
- [`embed_paddle_ocr.md`](embed_paddle_ocr.md) — OCR 语义门禁
- [`toml_config_design.md`](toml_config_design.md) — 字段语义（业务）
