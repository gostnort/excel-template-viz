# Gemma 4 E4B · LiteRT 运行时规格

> 状态：v6.6（**仅** 推理驱动、结构化判定接口与内容交互；不含向导编排、不含 UI、**不含** 各业务域 prompt）  
> 日期：2026-07-11  
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

| 环境 | 显式 profile（手动强制） | `profile="auto"`（默认）实测落点 |
|------|--------------------------|----------------------------------|
| RTX 4070 测试机 | `cuda` → `Backend.GPU()` | `gpu`（无 OpenVINO/NPU，探测直接命中 GPU） |
| Core 7 150U 客户机 | `openvino` → `Backend.GPU()` 核显（profile 名保留；**非** OpenVINO IR） | 待实机验证（预期 `gpu`，若该机 NPU GenAI 可用则 `npu`） |
| 兜底 | `cpu` → `Backend.CPU()` | 前两档都失败时的最终兜底 |

三档 **共用** `models/gemma4/gemma-4-E4B-it.litertlm`（约 3.66 GB）。

**实测已核实（2026-07-11，RTX 4070 + Windows，`litert-lm==0.14.0`）**：`Backend.GPU()` 在 Python 层 **零参数、零校验**，真正的探测只发生在 `Engine(model_path, backend=...)` 内部：它驱动一个跨厂商的 WebGPU delegate（Windows 上映射到 Direct3D 12，日志会打印 `Selected adapter: NVIDIA GeForce RTX 4070 ... backend=Direct3D 12`），因此**同一个 `GPU()` 类天然覆盖 NVIDIA / AMD / Qualcomm**，不需要分别探测「CUDA 兼容 GPU」和「通用 GPU（AMD/Qualcomm）」——litert-lm **没有** CUDA 专属 backend，也**没有** ONNX 权重或 OpenVINO-IR 推理路径，这些都是 llama.cpp/OpenVINO-GenAI 栈的概念，本运行时不存在。GPU 冷启动要多付一次性 shader 编译开销（本机约 10–12s），随后 decode 吞吐优于 CPU；CPU 冷启动仅约 0.4s（mmap，无编译）。

**多轮场景的成本回收已实测（2026-07-11，RTX 4070，`test/llm_gemma4/probe_gpu_breakeven.py`，64 tokens/轮，同一 `Conversation` 连续 10 轮）**：CPU 稳态约 8.8s/轮（约 7 tok/s），GPU 稳态约 1.0s/轮（约 64 tok/s，≈9x）。GPU 首轮含加载共 11.7s，比 CPU 首轮（8.7s）慢；但**第 2 轮起** GPU 累计耗时就已反超 CPU（12.75s vs 17.81s），10 轮后 GPU 总耗时（20.9s）只有 CPU（88.0s）的 24%。结论：**只有「整进程只调用一次 `generate()` 就退出」这种纯单发场景 CPU 更划算**；只要 `Engine` 会被复用（`LiteRtBackend` 当前就是这么做的——同一 backend 实例内所有 `generate()`/`open_session()` 共享一个缓存的 `Engine`），哪怕只有 2 轮对话或 2 次独立判定调用，GPU 就已经值回加载成本，这也是 §1.3 把 `auto` 默认级联到 GPU（而不是默认 CPU 只在探测到「多轮」时才升级）的依据。

Intel OpenVINO 在本运行时**唯一**的落点是 NPU：`Backend.NPU()` 若不显式传 `litert_dispatch_lib_dir`，会在 `sys.platform == "win32"` 时尝试 `import openvino` 并检查 `"NPU" in ov.Core().available_devices`；探测失败（未装 `openvino` 包，或无 NPU 设备）时**构造函数直接抛 `RuntimeError`**——这是唯一一个「构造即探测」的 Backend。本测试机未装 `openvino`，故 NPU 探测恒为不可用，`auto` 级联直接命中 GPU。

### 1.2 profile 参数

| 配置项 | `cpu` | `cuda` | `openvino` |
|--------|-------|--------|------------|
| `litert_backend` | `cpu` | `gpu` | `gpu` |
| MTP | `false` | `true` | `true` |
| `thinking_budget` | 512 | 1024 | 512 |
| `compress_trigger_ratio` | 0.65 | 0.75 | 0.65 |
| `compress_model_summary` | `false` | `true` | `false` |

`auto` 不在此表：它不强制上述任何一档的调参，只决定 `runtime/hardware_probe.py` 用哪个 `Backend` 构造 `Engine`；MTP/`thinking_budget`/压缩比调参（本表其余四行）目前**尚未接入代码**（仍是 TOML 占位，见 §1.3 step 3）。

### 1.3 配置来源优先级

1. 调用方显式传入 `profile`（`cpu`/`cuda`/`openvino` 三者之一 → 强制该 backend，失败直接抛错，不降级；用于调试/低算力兜底路径）
2. 环境变量 `LLM_PROFILE`
3. `llm_gemma4/profiles/{profile}.toml`（MTP/thinking_budget/压缩比调参，**尚未接入**代码）
4. CLI 交互菜单（**仅** `probe` / `wizard` 等 CLI 入口；见 workflow §5 页内静默策略；**尚未实现**）
5. 都没给 → `DEFAULT_PROFILE = "auto"`：`runtime/hardware_probe.build_engine()` 按 **NPU → GPU → CPU** 优先级级联尝试，每一档失败（NPU 构造异常 / `Engine(GPU())` 构造异常）就落到下一档，CPU 视为恒可用的最终兜底。

**已弃用**：旧版「仅一个合法 profile → 自动选用；零个 → 报错」的歧义规则（曾用于禁止多档同时合法时 silent 乱选）。用户明确要求「有 GPU 就该用 GPU，都没有才退回纯 CPU」，`auto` 级联按固定优先级取第一个能力构造成功的 backend，不再要求「恰好一个合法」，也不会因为 CPU 恒可用而报错。

---

## 2. 包布局（平台根 `llm_gemma4/`）

```
llm_gemma4/
  main.py                  # ConversationOnce：单函数一次性问答；`python llm_gemma4/main.py "问题"` 可直接跑
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
    base.py                # LlmBackend / LlmSession 协议
    factory.py
    litert/
      backend.py           # LiteRtBackend：Engine 单例 + generate（临时 Conversation）
      session.py           # LiteRtSession：session_id → 持久 Conversation 缓存
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
| `GenerateResult.thought` | 可选；`response["channels"]["thought"]` 原文（见 §3.3 实测结论） |
| `GenerateResult.raw` | 可选；调试 |
| `thinking=True` | 启用 Gemma 4 reasoning channel；**底层落地为** `create_conversation(extra_context={"enable_thinking": True})`（见 §3.3）——**会话级**设置，非逐次 `send_message` 的形参 |
| `temperature` | 固定 `0` |
| `health_check` | 返回 `profile`、`litert_backend`、MTP、`.litertlm` 路径；**不进** 向导用户 UI |

**实测约束（2026-07-11，真实 `litert_lm` 0.14.0 + `gemma-4-E4B-it.litertlm`）**：真实 `Conversation.send_message(message, *, max_output_tokens=None)` **没有** `thinking`/`temperature` 逐次形参——`temperature` 走 `SamplerConfig`（`create_conversation(sampler_config=...)`），`thinking` 走 `extra_context`（均为**会话级**，创建时定死）。因此 `LiteRtBackend.generate(messages, thinking=..., temperature=...)` 内部对每次调用**临时开的 Conversation** 是：`create_conversation(sampler_config=SamplerConfig(temperature=temperature), extra_context={"enable_thinking": thinking} if thinking else None)` → `send_message(...)`。`LlmSession`（§3.2.1，持久会话）的 `thinking`/`temperature` 只能在 `open_session` 时定一次，**同一 session 内逐轮不可再切换**（要切换则必须关旧开新）。

#### 3.1a `max_tokens` 是什么、是否按硬件区分

`generate`/`run_judgment` 里的 `max_tokens` 全部原样传给 `Conversation.send_message(..., max_output_tokens=max_tokens)`——它只是**本次回复最多生成多少 token（输出上限）**，不是输入/上下文长度限制。模型总上下文容量（`gemma-4-E4B-it.litertlm` 实测 `max_tokens: 4096`，即 KV cache 容量）是权重文件本身固定的属性，`EngineSettings` 打印出来的这个 4096 在 CPU/GPU 两种 backend 下完全一样（已实测核对）——**输入长度从不按硬件区分**。

但**输出预算**（这次最多生成多少 token）确实值得按硬件区分：GPU 解码比 CPU 快约 9 倍（§1.1 实测），同样的输出长度 GPU 划算得多，值得给更大的默认预算。这一点**已经接入代码**：`LiteRtBackend.generate(..., max_tokens=None)` 时——即调用方不传——由 `LiteRtBackend` 自己在 `_ensure_engine()` 探测出实际落地的 backend 后，按 `_DEFAULT_MAX_TOKENS_BY_BACKEND = {"cpu": 512, "gpu": 1024, "npu": 512}`（沿用 §1.2 `thinking_budget` 的数值，未另开新表）自行决定，**不需要调用方猜一个固定值**——调用方所在的开发机硬件不一定等于实际运行机器的硬件，这个决策必须留到运行时、由探测到的真实 backend 决定。调用方仍可显式传 `max_tokens` 覆盖这个自决默认值（例如 `run_judgment` 就总是显式传 `spec.max_tokens`，不受此逻辑影响）。

#### 3.1b `ConversationOnce`：最简单入口

给不需要 `JudgmentSpec`/`LlmSession` 的调用方（例如"随便问一句话拿一个回答"），放在包顶层 `llm_gemma4/__main__.py`（2026-07-11 由 `main.py` 改名回 `__main__.py`，好处是 `python -m llm_gemma4 "问题"` 可以直接跑），同时在包 `__init__.py` 直接导出：

```python
# llm_gemma4/__main__.py，顶层也直接导出：from llm_gemma4 import ConversationOnce
def ConversationOnce(
    input_string: str,
    *,
    system: str | None = None,
    thinking: bool = False,
    temperature: float = 0.0,
) -> str: ...
```

`system` 是可选的系统提示词，用来设定模型角色/口吻/回答规则（比如"你是一个只用一句话回答的助手"），跟 `input_string`（每次变化的问题本身）分开传。**没有** `max_tokens` 形参——见 §3.1a，这个值不该由调用方猜，交给 `LlmBackend` 自己按探测到的硬件决定。

内部持有**一个模块级单例 backend**（首次调用时 `create_backend()`，之后复用），不是每次调用都新建——这是 §1.1 GPU 成本回收实测的直接结论：只要连续调用 ≥2 次，复用 `Engine` 就已经比重新构建划算。`reset_backend()` 用于测试/进程退出时显式关闭。**不**做判定/解析/规范化——需要稳定三态判定的场景仍用 §3.6 `run_judgment`，`ConversationOnce` 只是 `generate()` 的薄封装，返回 `GenerateResult.text`。

**这个单例只在同一个 Python 进程存活期间有效**——`_backend` 是模块级变量，进程退出时随进程整个内存空间一起被系统回收，**不会跨进程持久化**。`python -m llm_gemma4 "问题"` 每次调用都是全新进程：解释器起来、`_backend` 初值是 `None`、第一次（也是唯一一次）调 `ConversationOnce` 触发冷启动、打印答案、进程退出——引擎被"卸载"是必然的，跟有没有做缓存无关。缓存能生效、看得到效果的场景是**同一进程内连续调用 ≥2 次**，例如：

```python
from llm_gemma4 import ConversationOnce
ConversationOnce("1+1 is what? one word.")   # 冷启动，实测 ~11s（GPU 路径，含 shader 编译）
ConversationOnce("2+2 is what? one word.")   # 复用同一个 Engine，实测 ~0.09s
```

这两行必须在**同一个 `python` 进程**里连续跑才会看到第二次变快（已实测验证，约快 120 倍）。想让 `paddle_ocr` 之类的下游服务真正吃到这份"引擎常驻内存"的收益，下游服务必须自己是一个**长生命周期进程**（常驻的 worker/服务进程，启动时 `import llm_gemma4` 一次、之后处理多个请求都调同一个已导入的 `ConversationOnce`），而不是每处理一条数据就 `subprocess` 拉一次 `python -m llm_gemma4`——后者跟直接连续两次跑 CLI 一样，每次都是新进程、每次都要冷启动，单例缓存在这种用法下天然帮不上忙。

### 3.2 工厂

```
create_backend(profile: str) -> LlmBackend
  → 读 profiles/{profile}.toml
  → LiteRtBackend(Engine)   # Engine 长期存活；Conversation 生命周期见 §3.2.1
```

真实 `litert_lm` Python API 是**有状态**的：`Engine` 是长期持有的运行时（本平台单例，进程内只开一次，随进程退出或显式 `close()` 关闭）；`Conversation` 内部维护自己的 KV cache / 对话历史，语义上更接近 OpenAI 的「session」而非「每次传全部 messages 的无状态 chat completion」。因此 `LlmBackend` 协议按**调用方生命周期**拆成两条路径：

### 3.2.1 两条会话生命周期（按调用方选择，**在实现前钉死**）

| 调用方 | 生命周期 | 接口 | 原因 |
|--------|----------|------|------|
| **OCR 语义门禁**（§3.6 `run_judgment`；单次判定） | **每次调用新开一个 `Conversation`**，发一条 system+user，取回答后立即关闭 | `LlmBackend.generate(messages)`（无状态） | 判定之间无业务关联，禁止互相污染；重复 prefill 成本对单条短 prompt 可接受 |
| **TOML 向导多轮**（`gemma4_e4b_workflow`） | **同一 session 内复用同一个 `Conversation`**，跨轮不重开（避免重复 prefill 整段历史） | `LlmBackend.open_session(session_id) -> LlmSession`；`LlmSession.send_turn(message, ...)` | 向导轮次多、上下文重，`ContextStore` 的分层增量假设「模型自己记得之前轮次」，重放全量历史既慢又违背分层压缩的意义 |

```python
class LlmBackend(Protocol):
    def generate(
        self, messages: list[dict], *, thinking: bool = False,
        max_tokens: int | None = None, temperature: float = 0.0,
    ) -> GenerateResult: ...
    """无状态单次调用：内部临时开一个 Conversation，发完即关。"""

    def open_session(self, session_id: str) -> "LlmSession": ...
    """有状态多轮：session_id 相同则复用同一个 Conversation（进程内 dict 缓存）。"""

    def count_tokens(self, text: str) -> int: ...
    def health_check(self) -> HealthReport: ...


class LlmSession(Protocol):
    def send_turn(
        self, message: dict, *, thinking: bool = False, max_tokens: int | None = None,
    ) -> GenerateResult: ...
    """向已存在的 Conversation 发一轮；不重放历史，历史由 Conversation 自己的 KV cache 持有。"""

    def close(self) -> None: ...
    """结束该 session 的 Conversation；`gemma4_e4b_workflow` 在向导结束/异常退出时调用。"""
```

**`ContextStore` 分层（§4）在有 session 时改为「注入提醒」而非「重放历史」**：Layer 0–4 组装出的文本仍随每轮 `send_turn` 的 `message` 一起送入，但**不再需要把此前完整对话重新塞进去**——那部分已经在 `Conversation` 自己的 KV cache 里。`Compressor` 的职责因此从「压缩要重放的历史」变为「压缩要在每轮里外挂提醒的摘要」（task_anchor、tool_trace_summary、latest_browser_state 等）。

**溢出/重启衔接**（对应 §4.5）：当 `send_turn` 因 `kMaxNumTokensReached`（KV cache 满）报错或 `finish_reason=length` 时，`LlmSession` **关闭当前 `Conversation`、开一个新的**，用 `Compressor` 产出的压缩摘要重新起一条 system/preface 消息「续接」，而不是retry 同一个 `Conversation`。`gemma4_e4b_workflow` 感知不到这次重启，只看到 `send_turn` 正常返回。

### 3.3 Thinking 解析（`runtime/thinking.py`）

**实测结论（2026-07-11，取代此前「正则切 `<|channel>thought` 标签」的假设）**：Gemma 4 E4B 的 `.litertlm` prompt template 内部确实用 `<|channel>thought\n...<channel|>` 原始文本定界（模型元数据 `channels { channel_name: "thought" ... }`），**但真实 `litert_lm` 0.14.0 的 `send_message` 返回值已经帮我们拆好了**——只要 `create_conversation(extra_context={"enable_thinking": True})`，响应字典会多一个 **顶层** `"channels"` 键，跟 `"content"` 平级：

```json
{
  "role": "assistant",
  "content": [{"type": "text", "text": "17 × 24 = 408。"}],
  "channels": {"thought": "1. 目标：计算 17×24 ...（略）"}
}
```

因此 `runtime/thinking.py` **不需要任何正则/标签解析**，只需读字段：

```python
def split_thought_answer(response: Mapping[str, Any]) -> tuple[str | None, str]:
    """response 是 send_message 的原始返回 dict。"""
    thought = (response.get("channels") or {}).get("thought")
    parts = response.get("content") or []
    answer = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
    return thought, answer
```

| 场景 | 实测现象 | 处理 |
|------|----------|------|
| `enable_thinking=True` 且 `max_output_tokens` 太小 | thought 把预算全部用完，`content` 为空字符串（**无报错**，见 §4.5） | 调用方需给 thinking 场景更大的 `max_output_tokens`（实测 96 不够、160 也可能不够写完一次除法思考） |
| `enable_thinking` 未设置 / `False` | 响应字典**没有** `"channels"` 键（不是空字典，是键缺失） | `split_thought_answer` 用 `.get("channels") or {}` 兜底 |
| thought 要不要留痕 | **thought 不得写入 `ContextStore` 长期层**（不变） | 同旧结论 |

**废弃**：不再需要 `thinking_budget` 触发的「正则查找 `<|channel|>` 截断保留 answer」逻辑——`channels`/`content` 已经是分离好的结构，`thinking_budget` 只用于控制 `max_output_tokens` 分配给 thinking 场景的预算大小。

### 3.4 CLI：探测 / 下载 / 冒烟

```bat
python -m llm_gemma4 probe
python -m llm_gemma4 probe --json
python -m llm_gemma4 download --profile all
python -m llm_gemma4 smoke --profile cuda
```

| 子命令 | 用途 |
|--------|------|
| `probe` | 打印 `hardware_probe.planned_backend_hint("auto")`（不加载权重，NPU 探测除外——那是构造即探测，见 §1.1） |
| `download` | `hf_download.download_litert()` → `models/gemma4/` |
| `smoke` | 短 prompt 生成；验收 tok/s 与 backend 实际路径 |

**探测项**（`HardwareReport`）：CPU 厂商/型号、LiteRT 是否可 import、NVIDIA（`nvidia-smi`）、Intel 核显、可选 `ram_gb`。

**已实现的最小先行版（2026-07-11）**：上面的 `probe`/`download`/`smoke` 子命令**尚未实现**；`__main__.py` 里的 `if __name__ == "__main__":` 只取第一个位置参数当问题，其余参数用 `ConversationOnce` 的默认值（无 `--system`/`--thinking` 这类 flag，要用这些参数请直接 `import` 后调 `ConversationOnce(...)`）：

```bat
python -m llm_gemma4 "你的问题"
```

Windows 终端若看到中文乱码（`涓浗...`），是控制台代码页问题，跟 `ConversationOnce` 本身无关：先 `chcp 65001` 切到 UTF-8 代码页即可正常显示。**后续**接入 `probe`/`download`/`smoke`/`wizard` 子命令时，这个直接问答形态要挪到某个子命令下（例如 `ask`），不能跟未来的子命令解析冲突。**每次 `python -m llm_gemma4` 都是新进程**（见 §3.1b 末段）：这个 CLI 只适合手测/单次调用，不适合需要"引擎常驻"收益的高频调用场景——那种场景应该让调用方作为一个长生命周期进程直接 `import llm_gemma4` 后反复调 `ConversationOnce`，而不是反复拉起这个 CLI。

**原生日志静默**：litert_lm 的 C++ 层（absl/glog）直接写进程的 stderr fd，绕过 Python 的 `logging` 模块，靠 shell 重定向（`2>$null`）没法从库层面解决——只要有人把 `llm_gemma4` 当库 `import` 而不是走 CLI，那些 `INFO:`/`WARNING:`/`I0000 ...` 噪音一样会混进去。`hardware_probe._silence_native_logs()` 在**第一次**构造 `Backend()`/`Engine()` 之前调 `litert_lm.set_min_log_severity(LogSeverity.ERROR)`（每进程只需成功一次，用模块级标志位 `_native_logging_silenced` 记忆），所以 `ConversationOnce()`、CLI、以后任何直接 `import llm_gemma4` 的服务，标准输出/标准错误里都只有真正的 `ERROR` 及以上和最终答案文本，不会再看到 accelerator 注册、WebGPU shader 编译、线程池启停这类调试噪音。要临时调试硬件探测问题、想看到原始日志时，设环境变量 `LLM_GEMMA4_VERBOSE=1` 即可关掉这层静默。

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

**实测已核实（2026-07-11，`pip install litert-lm` → 装入 `litert-lm==0.14.0` + 依赖 `litert-lm-api==0.14.0`（原生 wheel）+ `litert-lm-builder==0.14.0`）**：三档 profile 只需 `pip install litert-lm`（`import litert_lm`），会自动拉入 `litert-lm-api`/`litert-lm-builder` 两个子包；**不必**单独 `pip install litert-lm-api`。不再安装 `llama-cpp-python`、`openvino-genai`。

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
    verdict_key: str = "has_problem"       # 工具参数名；**字母序必须排在 reason_key 之前**（见 §3.6.1a）
    reason_key: str = "reason"
    max_tokens: int = 256                  # 纯文本路径预算；约束解码路径见 use_constrained_decoding 分支自动加码
    use_constrained_decoding: bool = True  # True 时走 §3.6.1a 工具调用；response 缺 tool_calls 自动退化为纯文本兜底


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

#### 3.6.1a 约束解码：实测确认走「工具调用」，不是原始 JSON Schema 形参（**2026-07-11 已用真实模型验证**）

`litert_lm` **C++** 层文档写的 `decoding_constraint`/`LlGuidanceConstraintArg`（任意 JSON Schema / Regex / Lark）**在当前 Python 绑定（`litert-lm` 0.14.0）里没有对应的逐消息形参**——`Conversation.send_message(message, *, max_output_tokens=None)` 只有这两个参数。真实可用的约束解码入口是 **`Engine.create_conversation(..., enable_constrained_decoding=bool, tools=[...], automatic_tool_calling=False)`**：把判定 schema 包装成一个「工具」，强制模型**只能通过调用该工具**给出结构化参数。已用 `gemma-4-E4B-it.litertlm`（CPU backend）实测通过：

```python
def report_verdict(has_problem: bool, reason: str) -> None:
    """Call this tool exactly once. has_problem must be reported before reason."""

conversation = engine.create_conversation(
    tools=[report_verdict],
    automatic_tool_calling=False,   # 不让 SDK 自动"执行"工具；我们要的是它回传的参数
    enable_constrained_decoding=True,
    system_message="You are a strict JSON judge. Call report_verdict exactly once.",
)
response = conversation.send_message(user_text, max_output_tokens=200)
# response == {"role": "assistant", "tool_calls": [
#   {"type": "function", "function": {"name": "report_verdict",
#     "arguments": {"has_problem": "true", "reason": "Fields are mismatched in the row."}}}
# ]}
```

**三个实测踩坑点，写进 `run_judgment` 实现前必须知道**：

| 坑 | 现象 | 应对 |
|----|------|------|
| **参数值仍是字符串** | `arguments["has_problem"]` 拿到的是字符串 `"true"`，**不是** Python `bool True` | `normalize_judgment` 的同义词表**必须**照常跑，约束解码只保证「字段存在、JSON 结构合规」，**不**保证值类型/语义正确 |
| **`max_output_tokens` 太小会导致工具调用「压根没触发」** | 96 tokens 时模型把 `<\|tool_call>` 原始文本写到一半被截断，SDK **解析失败后静默退化**为普通 `content` 文本（未闭合的 `<\|tool_call>call:report_verdict{reason:...`，`response` 里根本没有 `tool_calls` 键）；200 tokens 才稳定拿到结构化 `tool_calls` | `JudgmentSpec.max_tokens` 对约束解码路径要给足预算（**不能**沿用纯文本路径的小预算）；`run_judgment` 必须检查 `"tool_calls" in response`，缺失则按 §3.6.2 走纯文本兜底，**不能假设**约束解码一定生效 |
| **字段生成顺序按 key 字母序，不按 schema 声明顺序** | prompt template 用 `dictsort`（`format_argument`）→ 例子里 `has_problem`（字母序更靠前的字段名）先出，`reason` 后出；如果长解释字段名字母序更靠前，短判定字段可能因截断而生成不全 | `JudgmentSpec` 的工具参数命名要让**判定字段字母序排在理由字段之前**（如 `has_problem` < `reason` ✓；避免用 `verdict` 这种排在 `reason` 之后的名字），或干脆约束解码路径不要 `reason`，理由另外用非约束的一次 `generate` 单独要 |

**结论**：`use_constrained_decoding=True` 时，`run_judgment` 走「合成工具 + `enable_constrained_decoding`」；`parse_judgment`/`normalize_judgment` **永远**保留运行（不是「探测不到才跑」，而是「跑了但输入更干净，仍可能拿到字符串化的布尔值」）。

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
  → 若 spec.use_constrained_decoding:
      tool = _build_judgment_tool(spec)   # 合成一个 report_verdict(has_problem, reason) 式函数/Tool
      conversation = engine.create_conversation(
          tools=[tool], automatic_tool_calling=False, enable_constrained_decoding=True,
          system_message=spec.system,
      )
      response = conversation.send_message(spec.user, max_output_tokens=max(spec.max_tokens, 200))
      conversation.close()
      若 "tool_calls" in response and response["tool_calls"]:
          draft = JudgmentDraft(raw_text=str(response), payload=response["tool_calls"][0]["function"]["arguments"], parse_error=None)
      否则:
          draft = parse_judgment(_content_text(response), verdict_key=spec.verdict_key)  # 退化为纯文本兜底
  → 否则（use_constrained_decoding=False）:
      conversation = engine.create_conversation(system_message=spec.system)
      response = conversation.send_message(spec.user, max_output_tokens=spec.max_tokens)
      conversation.close()
      draft = parse_judgment(_content_text(response), verdict_key=spec.verdict_key)
  → normalize_judgment(draft, affirmative=..., negative=..., default_on_ambiguous=...)
  → JudgmentResult
```

**约束解码路径的 `max_output_tokens` 下限钉死 200**（§3.6.1a 实测：96 不够、200 稳定）；纯文本兜底路径仍用 `spec.max_tokens`（默认 256）。`_content_text(response)` = `"".join(p["text"] for p in response.get("content", []) if p.get("type") == "text")`（同 §3.3 `split_thought_answer` 的 answer 部分）。

| 步骤 | 职责 |
|------|------|
| `generate` | 只产出自然语言 / JSON 字符串 |
| `parse_judgment` | 从 answer 抽出 **一个** JSON 对象（容忍 markdown 围栏、前后缀废话）；失败则 `payload=None` |
| `normalize_judgment` | 把布尔、字符串、`yes/no/是/否/true/false/1/0` 等同义词 **映射** 到三态；**禁止**把 OCR 字段名写死在此文件 |

#### 3.6.3 `parse_judgment` 约定

- 与 `ActionParser`（§6）共用「单 JSON 对象」抽取策略时可复用内部 helper，但 **判定字段校验** 独立于 wizard `action` 表。
- 解析失败 **不** 抛给应用层；返回 `JudgmentDraft(parse_error=...)`，由 `normalize_judgment` 落 `unknown` 或 `default_on_ambiguous`。
- 无 `finish_reason` 信号可用（§4.5 实测结论）：解析失败就当作「大概率被截断」，**加大** `max_tokens` 重试 1 次，仍失败 → `unknown`。

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

| 路径 | 接口 | Conversation | ContextStore | thinking | 典型调用方 |
|------|------|---------------|--------------|----------|------------|
| 向导多轮 | `open_session` + `send_turn` | **持久**（session 内复用） | 是 | 按需 | `gemma4_e4b_workflow` |
| 单次判定 | `generate` | **临时**（每次新开即关） | **否** | **否** | `paddle_ocr/semantic_gate`、未来其它门禁 |

两路径 **共用** `create_backend()` 返回的同一个 `Engine` 单例（模型权重只加载一次）；`Conversation` 生命周期各自独立。OCR 判定 **不得** 向 `ContextStore` 写入 fast JSON 全量，也 **不得** 复用向导的 session。

---

## 4. 上下文接口：`ContextStore` + `Compressor`

应用层（向导）经此层组装**每轮外挂提醒文本**（非重放完整历史，见 §3.2.1：`Conversation` 自身持有历史）。**单次判定（§3.6）不得经过本层。**

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

**实测确认（2026-07-11）**：真实 `litert_lm.Conversation` 有只读属性 `token_count`（`get_token_count()`，KV cache 已用 token 数，prefill+decode 累计，非估算）。持久 session 路径（§3.2.1 `LlmSession`）**优先直接读 `conversation.token_count`** 作为 `estimate_tokens` 的真实来源，不必猜；只有在**尚未真正 `send_turn`**（比如预估下一轮要不要提前压缩）时才退回 `backend.count_tokens()` / `len(text)//3` 的估算。单次判定路径（`run_judgment`，Conversation 用完即关）不涉及此项。

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

**实测确认（2026-07-11）**：真实 `send_message` **没有** `finish_reason` 之类的截断信号——`max_output_tokens` 打满时**静默**返回已生成的部分内容，形状跟正常完成的响应**完全一样**（同 `{"role", "content"}` 结构），调用方无法从返回值本身分辨「答完了」还是「被截断」。因此 §4.5 原「`finish_reason=length` → 降 max_tokens 重试」**没有信号可挂**，改为以下两种可操作的启发式：

| 场景 | 行为 |
|------|------|
| `send_turn`/`generate` 前仍超 90% `n_ctx`（用 §4.2 的 `conversation.token_count` 或估算） | 仅保留 task_anchor + 最近 1 轮 + 最新 PageState 摘要 |
| 怀疑被截断（`parse_action`/`parse_judgment` 解析失败，或 thinking 场景 `content` 为空但 `channels.thought` 非空，见 §3.3） | 视为「大概率被截断」，**加大** `max_output_tokens` 重试 1 次；不依赖不存在的 `finish_reason` 字段 |
| `Conversation` 抛 `RuntimeError`（KV cache 真正满，见 §3.2.1 溢出/重启衔接） | `LlmSession` 关闭当前 `Conversation`、用压缩摘要开新的续接 |

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

1. `profile="auto"` 在 4070 上通过 `hardware_probe.build_engine()` 落到 `gpu`（已实测核实，§1.1）；150U / 纯 CPU 机器待验证  
1a. `hardware_probe.build_engine()` 级联对（NPU 探测失败 / `Engine(GPU())` 构造失败）分别正确降级到下一档，全部失败时抛出携带最后一次错误信息的 `RuntimeError`（faked `litert_lm` 单测覆盖，见 `test/llm_gemma4/test_hardware_probe.py`）  
2. `download` 得到 `models/gemma4/gemma-4-E4B-it.litertlm`  
3. `smoke --profile cuda` 在 4070 通过（强制 GPU，跳过级联）  
4. `smoke --profile openvino` 在 150U 通过（建议门禁 ≥5 tok/s）  
5. `smoke --profile cpu` 通过  
6. `health_check` 打印实际 `litert_backend` 与 MTP 状态  
7. Playwright Edge 能导航调用方 URL 并产出 `PageState`  
8. `run_judgment` 对固定 stub backend：`{"verdict": true}` / `{"verdict": "否"}` / 非法文本 → 稳定 `JudgmentResult` 三态（**不**测 OCR prompt）  
9. `run_judgment(use_constrained_decoding=True)` 对 stub backend：`response` 含 `tool_calls` → 走结构化解析；`response` 不含 `tool_calls`（模拟截断/降级）→ 自动退回纯文本 `parse_judgment`，**不抛异常**  
10. `open_session("s1")` 两次返回同一个底层 `Conversation`（同一 session_id 复用）；`open_session("s2")` 返回不同实例；`LlmSession.close()` 后同 session_id 再次 `open_session` 应重开新 `Conversation`  
11. 模拟 `kMaxNumTokensReached` → `LlmSession.send_turn` 内部重启 `Conversation`（用压缩摘要续接）后仍返回正常 `GenerateResult`，调用方无感知  

向导产品验收见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §9。OCR 语义门禁与 PaddleVL 联动验收见 [`embed_paddle_ocr.md`](embed_paddle_ocr.md) §7。

---

## 9. 相关文档

- [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) — TOML 配置向导（应用层）  
- [`embed_paddle_ocr.md`](embed_paddle_ocr.md) — OCR fast → Gemma 门禁 → PaddleVL（`HasOcrSemanticProblem` 属应用层）  
- [`toml_config_design.md`](toml_config_design.md) — 字段语义（业务，非平台）  
- [`connect_google.md`](connect_google.md) — OAuth（业务）
