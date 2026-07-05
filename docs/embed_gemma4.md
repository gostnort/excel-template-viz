# Gemma 4 本地 Agent 方案（Core 7 150U 核显重设版）

> 状态：草案 v4.6（AVX-512F CPU 分档 + HF 下载 + 实施计划）  
> 日期：2026-07-04  
> 前提：**不沿用** `app/llm/` 等过期实现；从零新建。  
> 模型：**Gemma 4 E4B（约 4B）**——测试机独显与客户机共享核显内存均足够承载 4B 级量化权重。

---

## 0. 硬件事实（v3 → v4 修正依据）

**Intel Core 7 150U**（客户机）经 Intel ARK / 规格库复核：

| 项 | 事实 |
|----|------|
| 架构 | Raptor Lake-U Refresh（**非** Core Ultra / Meteor Lake） |
| NPU | **无** AI Boost NPU（仅有 GNA 3.0，不用于 LLM GenAI 管线） |
| 核显 | **Intel Iris Xe Graphics 96EU**（共享系统内存） |
| 内存 | 通常 LPDDR5/DDR5，与核显共享带宽 |

**结论**：v3 中「NPU 强制 / INT8 / `max_prompt_tokens=1024` / 禁止 CPU 回落」等约束 **全部作废**。客户机 OpenVINO 路径改为 **`device=GPU`（核显）+ INT4**，并允许在算子不兼容时 **CPU fallback**。

---

## 1. 目标

在 Windows 本机构建本地 Agent，**推理层按机器分流**：

| 环境 | 硬件 | 推荐 profile | 代码位置 |
|------|------|--------------|----------|
| **测试机** | RTX 4070 + 任意 CPU | **`cuda`**（可选 `cpu` 调试） | `llm_gemma4/backends/llamacpp/` |
| **客户机** | Core 7 150U · Iris Xe | **`openvino`**（可选 `cpu` 兜底） | `llm_gemma4/backends/openvino/` |
| **通用/兜底** | 无 NVIDIA、不装 OpenVINO | **`cpu`** | `llm_gemma4/backends/llamacpp/` |

**单一平台根目录** `llm_gemma4/`：Agent、Thinking、压缩、Playwright 与 **三个 profile**（cpu / cuda / openvino）**同包**。

启动时在 **调用 LLM 之前** 完成硬件探测与 profile 选择，再由 `backends/factory.py` 加载对应子模块。

| 能力 | 说明 |
|------|------|
| Thinking | Gemma 4 原生 reasoning channel，解析 thought / answer |
| 上下文追踪 | 多轮 + 工具轨迹 |
| 上下文压缩 | 核显路径 **强化** DOM/工具轨迹裁剪，防止共享内存与 `n_ctx` 双爆 |
| 浏览器操控 | DOM + 截图 → `PageState`；**Playwright 默认 Edge**（见 §7） |
| 项目配置 | 白名单 TOML 读写 + `verify_toml`；**业务向导**见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) |

**文档分工**

| 文档 | 层级 |
|------|------|
| **本文件** | 平台：推理 backend、**Python 指挥层**、Playwright、压缩 |
| [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) | 应用：TOML 向导、JSON→Python 读写、E4B 状态机 |

E4B 为 **约 4B 小模型**：选型以 **最少 token + 同等准确度** 为准；TOML **默认 Python 直跑**（`load_toml` / patch / `verify_toml`），**不**把全文或 shell 输出回灌上下文。PowerShell.MCP 仅作 Cursor 开发可选，非 wizard 运行时依赖。

**不在本期**：云端 API、多用户鉴权、训练/微调、无校验的全自主 MCP 编排。

---

## 2. 总体架构：共享 Agent + 三档推理 profile

推理实现落在 **两个后台子包** 内，运行时通过 **三个 profile** 选择其一：

| profile | 后台子包 | 适用硬件 | 运行时 |
|---------|----------|----------|--------|
| **`cpu`** | `backends/llamacpp/` | 普通 CPU（**无**可用 NVIDIA GPU、**不**走 OpenVINO） | llama.cpp **CPU** wheel |
| **`cuda`** | `backends/llamacpp/` | 检测到 **NVIDIA** GPU | llama.cpp **CUDA** wheel |
| **`openvino`** | `backends/openvino/` | **Intel** 平台（核显 / CPU；含客户机 150U Iris Xe） | OpenVINO GenAI · GPU/CPU |

```
llm_gemma4/
  runtime/
    hardware_probe.py          ← 启动时检测 CPU/GPU/NPU/厂商
  agent/  tools/  profiles/
  backends/
    factory.py  base.py
         │
    ┌────┴────────────┐
    ▼                 ▼
 llamacpp/         openvino/
  · profile=cpu     · profile=openvino
  · profile=cuda    · INT4 · device=GPU/CPU
  GGUF Q4_0         OV IR
```

**启动时必须经硬件探测 + profile 选择**（见 §2.4），再进入 `resolve_backend_config()` → `LlmBackend`。

### 2.1 调用 LLM 前的配置分流

```
main()
  → hardware_probe.detect()           # §2.4
  → resolve_profile_choice()          # CLI / 环境变量 / 交互菜单
  → resolve_backend_config(profile)
  → 校验 profile 与硬件、已装依赖
  → 构造 LlmBackend 单例 → AgentLoop
```

| 配置项 | `cpu` | `cuda` | `openvino` |
|--------|-------|--------|------------|
| 后台子包 | `llamacpp` | `llamacpp` | `openvino` |
| 权重 | GGUF Q4_0 · `models/gemma4/` | 同左 | OV INT4 · `models/gemma4-openvino-int4/` |
| `n_gpu_layers` | `0` | `-1` | — |
| OpenVINO device | — | — | `GPU` 优先，可 CPU fallback |
| thinking_budget | 512 | 1024 | 512 |
| 典型场景 | 普通 PC、无 NVIDIA、不用 OpenVINO | RTX 4070 测试机 | Intel 150U 客户机 |

**运行时互斥（推荐）**：`openvino` 不 import `llama_cpp`；`cpu`/`cuda` 不 import `openvino`。venv 可同时装两套依赖，只加载所选 profile。

### 2.2 配置来源优先级

1. CLI：`--profile cpu|cuda|openvino`（非交互）
2. 环境变量：`LLM_PROFILE`
3. `llm_gemma4/profiles/{profile}.toml`
4. **交互菜单**（§2.4）：列出探测允许的 profile，用户选编号
5. 仅 **一个** profile 可用 → 自动选用并打印；**零** 可用 → 报错并提示装依赖

**禁止** silent 自动选 backend（除非只剩唯一合法选项）。

### 2.3 单进程原则

Agent、Compressor、Playwright 与 Backend 单例同进程；不另起 `llama-server`。

### 2.4 硬件探测与启动选项（`runtime/hardware_probe.py`）

启动 `python -m llm_gemma4`（或 `chat` 子命令）时 **先探测、再选 profile**。

#### 独立探测（不加载模型）

```bat
python -m llm_gemma4 probe
python -m llm_gemma4 probe --json
```

实现：`llm_gemma4/runtime/hardware_probe.py`；子探测：`backends/llamacpp/cpu_features.py`、`cuda_probe.py`、`openvino/ov_probe.py`。

#### 探测项

| 探测 | 方法（Windows） | 写入 `HardwareReport` |
|------|-----------------|------------------------|
| CPU 厂商 | `platform` / WMI | `cpu_vendor`: intel / amd / other |
| CPU 型号 | WMI `Win32_Processor.Name` | `cpu_model` |
| SIMD | CPUID / `cpu_features` | `avx` / `avx2` / `avx512f`；**CPU wheel 版本看 AVX-512F**（非 AVX2） |
| CPU profile | 见下表「SIMD 与 profile」 | `cpu_llama_eligible`、`llama_cpp_cpu_wheel` |
| NVIDIA 独显 | `nvidia-smi` | `has_nvidia_cuda`, `nvidia_gpu_name` |
| Intel 核显 | OpenVINO `Core().available_devices` | `has_intel_gpu`, `openvino_devices` |
| NPU | OpenVINO 含 `NPU`（150U **无**） | `has_npu` |
| 内存 | `psutil`（可选） | `ram_gb` |

#### SIMD 与 profile（CPU 老路径 vs OpenVINO）

llama.cpp **CPU wheel 版本**由 **`cpu_features.recommended_llama_cpp_version()`** 决定，检测 **AVX-512F**（不是 AVX2）：

| CPU SIMD | llama.cpp CPU wheel | 说明 |
|----------|---------------------|------|
| **有 AVX-512F** | **0.3.29** | 新 CPU 路径（`LLAMA_CPP_VERSION_AVX512`） |
| **无 AVX-512F**，有 AVX2 | **0.3.28** | 老 CPU 路径（如 Ryzen 5600X、多数 Zen3） |
| 仅 AVX / 无 AVX | 可能不可用 | probe 警告，不建议选 `cpu` |

| profile | 进入菜单条件 |
|---------|----------------|
| **`cpu`** | x86 上至少 **AVX2**（无 AVX-512 仍可跑 0.3.28） |
| **`cuda`** | `has_nvidia_cuda == true` |
| **`openvino`** | **Intel** + **AVX-512F** + OpenVINO 已装（150U 等较新 Core；**不是** AVX2 即可） |

说明：

- **AMD + NVIDIA（Ryzen 5600X + RTX 4070）**：`cuda` + `cpu`；无 AVX-512 → wheel **0.3.28**；**无** `openvino`。
- **Intel 150U（有 AVX-512F + Iris Xe）**：`openvino` + `cpu`（OV 失败可改 `cpu`）；无 NVIDIA 则无 `cuda`。
- **极老 CPU（无 AVX2）**：probe 警告；三档可能均不可用。

#### 可选 profile 规则（汇总）

| 条件 | 加入菜单 |
|------|----------|
| `cpu_llama_eligible`（AVX2+） | **`cpu`** |
| `has_nvidia_cuda` | **`cuda`** |
| Intel + **AVX-512F** + OpenVINO 已装 | **`openvino`** |

#### 交互菜单示例（TTY · Intel 150U）

```
[Gemma4] 硬件探测
  CPU: Intel Core 7 150U | RAM: 16.0 GB
  NVIDIA CUDA: 否 | Intel GPU: 是 (Iris Xe) | NPU: 否

可选推理后端:
  [1] openvino  — OpenVINO · 核显 INT4（推荐）
  [2] cpu       — llama.cpp · CPU GGUF（较慢，通用兜底）

请输入编号 [1]: 
```

#### 交互菜单示例（AMD + NVIDIA）

```
[Gemma4] hardware probe
  CPU: AMD Ryzen 5 5600X (amd)
  SIMD: AVX, AVX2 (source=cpuid)
  llama.cpp CPU wheel hint: 0.3.28 (AVX-512F -> 0.3.29, else 0.3.28)
  CPU profile: AVX2 only (no AVX-512F): use llama-cpp-python 0.3.28 CPU wheel
  NVIDIA CUDA: yes (NVIDIA GeForce RTX 4070)
  Intel GPU (OpenVINO): no | NPU: no
  OpenVINO profile: OpenVINO profile skipped: CPU vendor is amd

Available profiles:
  [1] cuda - llama.cpp · CUDA GGUF (NVIDIA)
  [2] cpu  - llama.cpp · CPU GGUF (fallback)
```

非交互：`python -m llm_gemma4 chat --profile cuda --task "..."`

#### `health_check` 输出

选定 profile 后打印：`profile`、探测摘要、wheel/OV 版本、实际 device（如 `cuda:0` / `GPU:0` / `CPU`）。

---

## 3. 目录结构

**约定**：Gemma4 平台只有一个根目录 `llm_gemma4/`；CUDA 与 OpenVINO 是其中的 **两个后台推理子包**，不拆到项目根。

```
llm_gemma4/                          # 平台根（唯一）
  __init__.py
  __main__.py                        # python -m llm_gemma4
  config.py
  profiles/
    cpu.toml                       # llama.cpp CPU · n_gpu_layers=0
    cuda.toml
    openvino.toml
  agent/
    loop.py                      # chat 模式 ReAct 循环（可选）
    wizard_runner.py             # wizard CLI 入口：Backend + WizardRunner
    context_store.py             # LLM 上下文分层
    compressor.py
    prompts.py                   # chat 模式 prompt
  wizard/                        # TOML 向导 · Python 指挥层（见 §3.1、§6.2）
    runner.py                    # 状态机 INIT→DONE
    action_parser.py             # E4B 回复 → 单 action JSON
    tools.py                     # 窄 tool 注册 + dispatch
    toml_io.py                   # digest / apply_patch / backup
    precheck.py                  # Node / Playwright 环境探测
    state.py                     # temp/wizard/{id}.json 持久化
    prompts.py                   # 各阶段 prompt 模板
  runtime/
    hardware_probe.py              # 启动探测 + 菜单可选 profile 列表
    thinking.py
  tools/
    browser_playwright.py
    browser_state.py
    file_config.py
  mcp/
    server.py
  backends/
    base.py                          # LlmBackend 协议
    factory.py                       # profile → llamacpp | openvino
    llamacpp/                        # profile=cpu | cuda
      __init__.py
      backend.py                     # 按 profile 分支：CpuBackend / CudaBackend
      cpu_features.py                # AVX-512F -> 0.3.29, else 0.3.28
      cuda_probe.py
      requirements-cpu.txt           # CPU wheel index
      requirements-cuda.txt          # CUDA wheel index
      scripts/
        download_gguf.py
        smoke_test_cpu.py
        smoke_test_cuda.py
    openvino/                        # 后台 B：客户机 150U · 核显 INT4
      __init__.py
      backend.py                     # OpenVinoGpuBackend
      ov_probe.py
      requirements.txt
      scripts/
        download_ov_int4.py
        export_ov_int4_sym.py
        smoke_test_openvino.py
  requirements.txt                   # 共享：playwright、psutil 等

models/                              # 权重仍在项目根（.gitignore）
  gemma4/
  gemma4-openvino-int4/

test/llm_gemma4/                     # 测试也收在同一平台名下
  test_thinking_parser.py
  test_compressor.py
  backends/
    test_hardware_probe.py
    test_llamacpp_cpu_smoke.py
    test_llamacpp_cuda_smoke.py
    test_openvino_smoke.py
  e2e_agent_nicegui.py
```

**废弃**：`app/llm/*`；v3 的 NPU / INT8 / `browser_cursor.py` / Cursor MCP 双轨。

**说明**：开发时你仍可在 Cursor 里用 IDE 能力写**非 Agent** 代码；但 **Agent 的观测与工具执行必须走 Playwright**，保证 `PageState` 与 e2e 一致。

### 3.1 模块职责（指挥层 + 平台）

E4B **只产 JSON**；下列 **Python 模块**负责解析、调度、落盘与校验。业务语义（TOML 字段含义、`verify_toml` 规则）**只读**依赖 `app/core_toml.py`，不复制到 `llm_gemma4/`。

| 模块 | 包 | 职责 |
|------|-----|------|
| `__main__.py` | `llm_gemma4` | CLI 子命令 `wizard` / `chat`；调 `hardware_probe` |
| `wizard_runner.py` | `agent/` | 组装 `LlmBackend` + `ContextStore` + `WizardRunner.run(template_id)` |
| `runner.py` | `wizard/` | **状态机**：阶段转移、`WAIT_USER`、是否调用 LLM、调用预算 |
| `action_parser.py` | `wizard/` | 从 `backend.generate()` 输出解析 **一个** `action` JSON；失败重试 1 次 |
| `tools.py` | `wizard/` | 窄 tool **注册表** + `dispatch(action)` → 调下层实现 |
| `toml_io.py` | `wizard/` | `build_toml_digest`、`apply_patch`、`.bak` 备份/回滚；内部调 `app.core_toml` |
| `precheck.py` | `wizard/` | `shutil`/`subprocess` 探测 Node、Playwright；**无 LLM、无 MCP** |
| `state.py` | `wizard/` | 读写 `temp/wizard/{template_id}.json`（阶段、用户答复、regex 试错） |
| `prompts.py` | `wizard/` | 各阶段 system/user 模板（含 digest 占位，**不含** TOML 全文） |
| `browser_playwright.py` | `tools/` | Edge 启动、`browser_snapshot`、`browser_click` |
| `browser_state.py` | `tools/` | DOM → `PageState`、截断后 observation |
| `thinking.py` | `runtime/` | 剥离 thought / 最终 answer |
| `context_store.py` | `agent/` | 分层上下文；wizard 与 chat 共用 |
| `compressor.py` | `agent/` | 超 `n_ctx` 比例时压缩 tool 轨迹 |
| `factory.py` + `backends/*` | `backends/` | profile → `LlmBackend.generate()` |
| — | `app/core_toml.py` | **外部业务**：`load_toml`、`verify_toml`、`TomlGenerator`（wizard **只 import**） |

**指挥链（wizard 主路径）：**

```
__main__.py wizard
  → agent/wizard_runner.py
  → wizard/runner.py          # 当前阶段
       ├─ precheck / Playwright 阶段：不调 LLM，直接 tools.dispatch 或 precheck
       └─ 需 LLM 阶段：
            → wizard/prompts.py 组 prompt
            → context_store + compressor
            → backends/*.generate()
            → runtime/thinking.py
            → wizard/action_parser.py
            → wizard/tools.py.dispatch(action)
                 ├─ toml_io.*        → app.core_toml
                 ├─ browser_*       → tools/browser_playwright.py
                 └─ test_regex 等    → wizard/tools.py 内纯 Python
            → 短 observation 写回 context_store
```

窄 tool 清单与阶段说明见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §3、§6；本节只定 **平台侧模块归属**。

---

## 4. Gemma 4 E4B 三档 profile 部署

### 4.0 Hugging Face 权重下载（平台统一）

权重落在项目根 `models/`（`.gitignore`），**不由** E4B 或向导下载；由 `llm_gemma4/backends/*/scripts/` 或 `python -m llm_gemma4 download` 完成。

#### 4.0.1 仓库与本地路径

| 用途 | profile | Hugging Face 仓库 | 本地目录 | 主文件 |
|------|---------|-------------------|----------|--------|
| **GGUF Q4**（llama.cpp） | `cpu` / `cuda` | [**google/gemma-4-E4B-it-qat-q4_0-gguf**](https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf) | `models/gemma4/` | `gemma-4-E4B_q4_0-it.gguf` |
| **OpenVINO INT4**（预转换） | `openvino` | [**OpenVINO/gemma-4-E4B-it-int4-ov**](https://huggingface.co/OpenVINO/gemma-4-E4B-it-int4-ov) | `models/gemma4-openvino-int4/` | `openvino_model.xml` + `openvino_model.bin` 等 |
| **基座**（仅 B2 本地导出用） | — | [**google/gemma-4-E4B-it**](https://huggingface.co/google/gemma-4-E4B-it) | 缓存 / 临时 | PyTorch / Safetensors |

GGUF 单文件约 **2–3 GB**（Q4_0）；OV INT4 包约 **2–3 GB**。访问 Google / OpenVINO 模型可能需 HF 账号并接受许可。

#### 4.0.2 下载命令（推荐 `hf` CLI）

前置：`pip install huggingface_hub` 或 [HF CLI](https://huggingface.co/docs/huggingface_hub/guides/cli)；已登录：`hf auth login`。

**GGUF（cpu + cuda 共用）：**

```bat
hf download google/gemma-4-E4B-it-qat-q4_0-gguf ^
  gemma-4-E4B_q4_0-it.gguf ^
  --local-dir models/gemma4
```

或平台脚本（Phase 1 实现）：

```bat
python llm_gemma4/backends/llamacpp/scripts/download_gguf.py
python llm_gemma4/backends/llamacpp/scripts/download_gguf.py --auto
```

**OpenVINO INT4（方案 B1）：**

```bat
hf download OpenVINO/gemma-4-E4B-it-int4-ov ^
  --local-dir models/gemma4-openvino-int4
```

或：

```bat
python llm_gemma4/backends/openvino/scripts/download_ov_int4.py
```

**验收：** 文件存在且 `python -m llm_gemma4 probe` 不报错；各 profile 的 `smoke_test_*.py` 能加载并 `generate` 一句。

#### 4.0.3 与过期脚本的关系

| 旧路径 | 状态 |
|--------|------|
| `app/llm/download_gemma4_model.py` | **废弃**；GGUF URL 同上，迁移到 `backends/llamacpp/scripts/download_gguf.py` |
| `app/llm/gemma4_field_matcher.py` | **废弃**；Phase 6 删除 |

#### 4.0.4 计划 CLI（Phase 1）

```bat
python -m llm_gemma4 probe
python -m llm_gemma4 download --profile cuda
python -m llm_gemma4 download --profile openvino
python -m llm_gemma4 download --all
python -m llm_gemma4 smoke --profile cuda
```

实现：`llm_gemma4/__main__.py` 子命令 `download` → 调用各 `scripts/download_*.py`。

---

### 4.1 模型体量

| 资源 | cuda (4070) | openvino (150U) | cpu (兜底) |
|------|-------------|-----------------|------------|
| 权重 | Q4 GGUF ~2–3 GB | INT4 OV ~2–3 GB | 同 cuda |
| 瓶颈 | VRAM | 核显共享内存带宽 | CPU 算力 + RAM |

### 4.2 profile `cpu` — llama.cpp CPU（通用兜底）

| 项 | 选择 |
|----|------|
| 适用 | **无 NVIDIA**、未选/未装 OpenVINO 的 x86 PC；或 cuda/OV 失败时手动改选 |
| 模型 | GGUF · §4.0.1 · `models/gemma4/gemma-4-E4B_q4_0-it.gguf` |
| 运行时 | `llama-cpp-python` **CPU** wheel；**检测 AVX-512F** → 0.3.29，否则 **0.3.28** |
| 加载 | `n_ctx=8192`, **`n_gpu_layers=0`** |

```bat
REM 按 probe 提示安装（5600X 等无 AVX-512 用 0.3.28）
python -m pip install llama-cpp-python==0.3.28 ^
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

```toml
# profiles/cpu.toml
profile = "cpu"
model_path = "models/gemma4/gemma-4-E4B_q4_0-it.gguf"
n_ctx = 8192
n_gpu_layers = 0
thinking_budget = 512
compress_model_summary = false
```

### 4.3 profile `cuda` — llama.cpp CUDA（测试机）

| 项 | 选择 |
|----|------|
| 模型 | 同 GGUF · §4.0.1 |
| HF 页 | https://huggingface.co/google/gemma-4-E4B-it-qat-q4_0-gguf |
| 运行时 | `llama-cpp-python` CUDA wheel |
| 加载 | `n_ctx=8192`, `n_gpu_layers=-1` |

```bat
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
```

**Windows cu124 + Ryzen（无 AVX-512）**：CUDA wheel 自带 AVX-512 版 `ggml-cpu.dll`，纯 AVX2 CPU 会加载失败。`cuda_env.prepare_cuda_runtime()` 会在加载前把 pip 的 `nvidia/*/bin` 与 `llama_cpp/lib` 加入 PATH，并在需要时用 CPU wheel 的 `ggml-cpu.dll` 替换（原文件备份为 `ggml-cpu.dll.cuda_bak`）。无需手动改 shell PATH。

```toml
# profiles/cuda.toml
profile = "cuda"
model_path = "models/gemma4/gemma-4-E4B_q4_0-it.gguf"
n_ctx = 8192
n_gpu_layers = -1
thinking_budget = 1024
temperature = 0.0
compress_model_summary = true    # 4070 可承受额外一轮摘要
```

### 4.4 profile `openvino` — 核显 INT4（Intel 客户机）

**硬件门槛：** Intel CPU + **AVX-512F**（`hardware_probe`）；与 profile `cpu` 的 wheel 分档规则一致，OpenVINO 不接受「仅 AVX2」的 Intel 机进入菜单。

#### 为何放弃 INT8 与 NPU

| 原 v3 假设 | v4 修正 |
|------------|---------|
| Core Ultra + NPU | **Core 7 150U，无 NPU** |
| `OpenVINO/gemma-4-E4B-it-int8-ov` | **不用**；INT8 在共享内存核显上带宽压力大，token 极慢 |
| `device=NPU` | **`device=GPU`**（OpenVINO 中 GPU = 核显/独显；150U 仅核显） |
| `max_prompt_tokens=1024` | **删除**（NPU 静态管线约束不适用） |

#### 权重来源（二选一，Phase 1 实机定夺）

**方案 B1 — HF 预转换 INT4（上手快，§4.0.2）**

| 项 | 值 |
|----|-----|
| 仓库 | [**OpenVINO/gemma-4-E4B-it-int4-ov**](https://huggingface.co/OpenVINO/gemma-4-E4B-it-int4-ov) |
| 量化 | NNCF **INT4_ASYM**，`group_size=128` |
| 状态 | EXPERIMENTAL；OpenVINO ≥ 2026.1.0 |
| 下载 | `hf download OpenVINO/gemma-4-E4B-it-int4-ov --local-dir models/gemma4-openvino-int4` |

**方案 B2 — 本地导出 INT4 symmetric（核显带宽更优，推荐尝试）**

基座：[**google/gemma-4-E4B-it**](https://huggingface.co/google/gemma-4-E4B-it)
社区与 Intel 文档均指出：核显 / 部分 Intel 路径上 **INT4 symmetric（channel-wise，`--sym --group-size -1`）** 比 INT8 更稳、更快。若 B1 在 Iris Xe 上速度 <5 tok/s 或编译失败，改用：

```text
optimum-cli export openvino --model google/gemma-4-E4B-it \
  --task text-generation-with-past \
  --weight-format int4 --sym --group-size -1 \
  models/gemma4-openvino-int4
```

（具体 CLI 以 Phase 1 锁定 OpenVINO / optimum-intel 版本为准；Gemma4 可能需实验性 optimum 分支。）

#### 运行时与 profile

| 项 | 选择 |
|----|------|
| API | `openvino-genai` → `LLMPipeline(model_dir, "GPU")` |
| 设备 | **`GPU`**；`ov_probe` 确认 Iris Xe 可见 |
| Fallback | GPU 编译/推理失败 → **CPU**（`allow_cpu_fallback=true`，记录告警） |
| 模态 | 包含视觉塔；本期 Agent **纯文本**，不传 `image` |

```toml
# profiles/openvino.toml
profile = "openvino"
model_dir = "models/gemma4-openvino-int4"
device = "GPU"
weight_format = "int4"
n_ctx = 8192
thinking_budget = 512
allow_cpu_fallback = true
temperature = 0.0

# 上下文（见 §8）
compress_trigger_ratio = 0.65      # 比 cuda 更早压缩（0.75 → 0.65）
dom_excerpt_max_chars = 6000
browser_observation_max_chars = 8000
compress_model_summary = false     # 核显默认不做额外摘要推理
```

### 4.5 Thinking（三档一致）

- 启用：system 注入 `<|think|>` / `enable_thinking`
- 解析：`<|channel>thought` … `<channel|>` + answer（`thinking.py`）
- **thought 全文不进 ContextStore**；仅 answer 与 tool 轨迹保留
- openvino：`thinking_budget=512`，超长 thought 截断

### 4.6 依赖隔离

| 文件 | 用途 |
|------|------|
| `requirements.txt` | NiceGUI 主应用 |
| `llm_gemma4/requirements.txt` | Agent 共享 |
| `llm_gemma4/backends/llamacpp/requirements-cpu.txt` | CPU wheel |
| `llm_gemma4/backends/llamacpp/requirements-cuda.txt` | CUDA wheel |
| `llm_gemma4/backends/openvino/requirements.txt` | openvino-genai 等 |

```bat
install.bat --llm cpu
install.bat --llm cuda
install.bat --llm openvino
install.bat --llm all          REM 开发机：三套都装，启动时仍只选一个 profile
```

---

## 5. LlmBackend 协议

`AgentLoop` 仅依赖抽象接口：`generate()`、`count_tokens()`、`health_check()`。  
`health_check` 须打印：`profile`、**`hardware_probe` 摘要**、wheel/OV 版本、实际 device（`cuda:0` / `GPU:0` / `CPU`）。

---

## 6. Agent 循环

### 6.1 两种运行模式

| 模式 | 入口 | 适用 |
|------|------|------|
| **`wizard`** | `python -m llm_gemma4 wizard --template {id}` | **TOML 首次配置**（主场景，见 `gemma4_e4b_workflow.md`） |
| **`chat`** | `python -m llm_gemma4 chat --task "..."` | 短任务、调试（步数上限更严） |

**向导模式（推荐生产路径）**

```
WizardRunner（Python 状态机，步骤固定）
  → 每步如需 LLM：窄 tool 列表 + 单 action JSON
  → backend.generate(thinking=按阶段)
  → 代码执行 tool（Playwright / toml_io.apply_patch / test_regex）
  → verify_toml · 失败回滚 · WAIT_USER
```

**chat 模式（通用，非 TOML 向导主路径）**

```
用户输入 → ContextStore → Compressor → backend.generate
  → ThinkingParser → tool JSON? → browser / file_config
  → max_steps=8（小模型易漂移，生产 TOML 配置请用 wizard）
```

共同约束：`temperature=0`；openvino/cpu 默认 `thinking_budget=512`。

### 6.2 Python 指挥层（Orchestrator）

**原则：** E4B 是「建议器」；**指挥权在 Python**。模型不读文件、不跑 shell、不选下一阶段——全部由 `wizard/runner.py` 状态机决定。

#### 6.2.1 三层分工

| 层 | 模块 | 输入 | 输出 |
|----|------|------|------|
| **推理** | `backends/*` + `runtime/thinking.py` | prompt + 上下文 | thought（丢弃）+ 含 `action` 的文本 |
| **解析** | `wizard/action_parser.py` | 模型文本 | `{ "action": "...", ... }` 或解析错误 |
| **执行** | `wizard/tools.py` + `toml_io` / `browser_*` | action dict | **短** observation（digest、verify 错误、PageState 摘要） |

#### 6.2.2 `tools.dispatch(action)` 路由

| `action` | 执行模块 | 说明 |
|----------|----------|------|
| `read_toml` | `wizard/toml_io.py` | `build_toml_digest`；**不进**全文 |
| `set_top_level` | `wizard/toml_io.py` | `apply_patch(patch)` 顶层键 |
| `patch_field` | `wizard/toml_io.py` | `apply_patch` 单条 `field_rules` |
| `test_paste_split` | `wizard/tools.py` | 纯 Python 拆粘贴 |
| `test_regex` | `wizard/tools.py` | `re.match` 试跑 |
| `test_source_row` | `wizard/tools.py` | 调 `app` 数据源读一行 |
| `browser_snapshot` | `tools/browser_playwright.py` | → `browser_state` 截断 |
| `browser_click` | `tools/browser_playwright.py` | 有限 DOM 交互 |
| `ask_user` | `wizard/runner.py` | 挂起 `WAIT_USER`（CLI / NiceGUI） |

每次 TOML 写入路径：

```
action → tools.dispatch
  → toml_io.apply_patch
  → backup(.bak)
  → TomlGenerator.ConfigToToml 落盘
  → app.core_toml.verify_toml
  → 失败 restore；observation = compact_report(errors only)
```

#### 6.2.3 与 `chat` 模式的区别

| 项 | `wizard` | `chat` |
|----|----------|--------|
| 编排 | `wizard/runner.py` 固定阶段 | `agent/loop.py` ReAct |
| 工具面 | §6.2.2 窄表 | `browser_*` + `file_config`（更宽，步数 ≤8） |
| TOML | **必须**经 `toml_io` + verify | 同白名单，但不走向导状态机 |
| 推荐用途 | 生产 TOML 首次配置 | 调试 |

#### 6.2.4 Token 约束（指挥层强制）

- `toml_io.build_toml_digest`：仅关键键 + verify 错误 + 当前 batch 字段  
- `tools.dispatch` 返回值：单条 observation ≤ 平台配置的 `tool_observation_max_chars`  
- 禁止把 `Path.read_text()` 全文、`subprocess`  stdout 全文写入 `context_store`  

---

## 7. 浏览器：Playwright（默认 Edge）

### 7.0 为何不用 Chrome / Cursor Browser MCP

| 方式 | 实际启动的是 | 本项目 |
|------|--------------|--------|
| `playwright.chromium.launch()` **无 channel** | Playwright **自带的 Chromium**（与系统已装的 Google Chrome **不是**同一二进制） | **不用**作默认 |
| `channel='chrome'` | 系统 **Google Chrome** | **不用**：新版 Chrome 对 Cursor **Browser MCP** 类自动化限制加强，MCP 控制不可靠 |
| `channel='msedge'` | 系统 **Microsoft Edge** | **默认**（已在 `test/mcp_general/edge_nicegui_smoke.py` 验证） |
| `firefox.launch()` | Playwright Firefox | 备选 |
| **CDP** `connect_over_cdp(...)` | 附着用户**已打开**的 Chrome/Edge（需 `--remote-debugging-port`） | 可选；与 MCP 无关，走 DevTools 协议 |

说明：

- 本机装了 Chrome，Playwright **默认仍不会**去开 Chrome，除非显式 `channel='chrome'`。
- **Cursor 内置 Browser MCP**（`cursor-ide-browser`）在新版 Chrome 上往往**不能**像旧版那样直接驱动；若必须用 Chrome，应 **CDP 附着**已开启调试端口的实例，而不是指望 MCP 启动/控制 Chrome。
- **交付给客户的 `llm_gemma4` Agent** 不依赖 Cursor MCP；统一用 **Playwright Python API**，与 IDE 无关。

### 7.1 默认配置

| 项 | 选择 |
|----|------|
| 驱动 | **Playwright** · `chromium.launch(channel='msedge')` |
| 备选 | `BROWSER_CHANNEL=firefox` → `firefox.launch()` |
| CDP 模式 | `BROWSER_CDP_URL=http://127.0.0.1:9222` → `connect_over_cdp`（高级/Debug） |
| 模块 | `tools/browser_playwright.py` + `browser_state.py` |
| 目标 | `http://127.0.0.1:8738/`（NiceGUI） |
| Google OAuth / Sheet 探测 | 建议 **`headless=False`**，便于用户手工授权 |
| 截图 | `test/llm_gemma4/_shots/`；仅路径进上下文 |

```python
# 默认（已验证）
browser = pw.chromium.launch(channel="msedge", headless=False)

# 勿作为 Agent 默认
# browser = pw.chromium.launch()              # 内置 Chromium，非 Chrome
# browser = pw.chromium.launch(channel="chrome")  # Chrome + MCP 限制
```

### 7.2 PageState（Agent 唯一观测格式）

```text
url, title, active_tab, template_id,
form_fields[], session_table_summary,
interactive_refs[]（限量）,
dom_excerpt（截断后）,
screenshot_path
```

### 7.3 与上下文压缩的衔接

`browser_state.py` 在写入 ContextStore **之前** 必须：

1. `interactive_refs` 最多保留 **40** 条（可点击优先）
2. `dom_excerpt` 超过 `dom_excerpt_max_chars` 时保留首尾 + 省略标记
3. 单条 tool observation 超过 `browser_observation_max_chars` 时拒绝整段入栈，改为「请再次 browser_snapshot」错误反馈给 Agent

**开发时在 Cursor 内**仍可用 Browser MCP 做人工探索，但 **Agent 运行时** 只认 Playwright 产出的 `PageState`（避免 MCP/CDP/Playwright 三套 DOM 不一致）。

### 7.4 PowerShell.MCP（可选 · 仅开发）

**TOML 读写不走 PowerShell.MCP。** 向导运行时一律 **JSON → Python**（`wizard/toml_io.py` + `app.core_toml`），原因：同等准确度下 **token 更少**（digest + verify 错误，而非 `Get-Content` 全文或 MCP 回显）。

[PowerShell.MCP](https://github.com/yotsuda/PowerShell.MCP) 可在 **Cursor 开发** 时注册，供人工在 pwsh 控制台试命令；与 Playwright 之于 Browser MCP 的关系相同：**IDE 探索用，Agent 运行时不依赖**。

| MCP tool | 用途（开发侧） |
|----------|----------------|
| `start_console` | 启动持久 pwsh 控制台 |
| `execute_command` | 人工试 CLI / 模块 |
| `get_current_location` / `cancel` / `close_console` | 会话管理 |

安装（可选）：`Install-PSResource PowerShell.MCP`；Cursor 配置见上游 README（建议 `--no-profile`）。

**禁止：** 把 PowerShell.MCP 6 个 tool 全量注册给 E4B；wizard 运行时经 MCP 读写 TOML。

---

## 8. 上下文追踪与压缩（核显重点）

核显路径无 NPU 的 1024 prompt 硬顶，但 **DOM + 多轮 tool 轨迹** 仍会撑满 `n_ctx` 并加剧内存带宽压力。压缩是客户机可用性的核心。

### 8.1 ContextStore 分层

```
Layer 0  system_prompt + 工具说明（固定）
Layer 1  task_anchor（用户原始目标，永不丢）
Layer 2  recent_turns（完整对话，K 轮）
Layer 3  tool_trace_summary（更早轮次 bullet 摘要）
Layer 4  latest_browser_state（仅保留最新一帧，旧帧丢弃）
```

| profile | `recent_turns` K | `compress_trigger_ratio` |
|---------|------------------|--------------------------|
| cuda | 4 | 0.75 |
| openvino | **3** | **0.65** |
| cpu | **3** | **0.65**（与 openvino 同级，CPU 更慢不宜撑满 ctx） |

### 8.2 触发条件

`estimate_tokens(all_layers) > n_ctx * compress_trigger_ratio` → `Compressor.run()`。

token 估算：优先 `backend.count_tokens()`；否则 `len(text)//3`。

### 8.3 压缩档位

**档 A — 规则裁剪（openvino 默认，零额外推理）**

1. 删除 Layer 2 最旧 **2** 轮（openvino / cpu）或 **1** 轮（cuda）
2. 将被删轮中的 tool 结果压成 **≤8 行** bullet 写入 Layer 3
3. 清空一切历史 `browser_state`，只留 Layer 4 最新一帧
4. 剥离 assistant 消息中的 thought 残留（若解析漏网）

**档 B — 模型摘要（仅 cuda 默认开启）**

- 关闭 thinking，单轮生成 ≤200 字摘要 → Layer 3  
- **openvino / cpu 默认关闭**（避免慢后端上再跑一轮 LLM）

### 8.4 溢出防护（Agent 工具层）

| 场景 | 行为 |
|------|------|
| 单次 `dom_excerpt` 过长 | `browser_state` 预截断 |
| 连续 3 次 tool 无进展 | `loop.py` 强制 `Compressor.run()` |
| `generate` 前仍超 90% n_ctx | 丢弃 Layer 3 全文，仅保留 task_anchor + 最近 1 轮 + 最新 PageState |
| finish_reason=length | 降 `max_tokens`，提示 Compressor，重试 1 次 |

### 8.5 thinking 与压缩的交互

| 内容 | 进长期上下文 |
|------|--------------|
| thought 全文 | **否** |
| tool args/result | **是**（截断后） |
| 最终用户可见答案 | **是** |

---

## 9. 文件配置与白名单

| 路径 | 权限 |
|------|------|
| `templates/**/{id}.toml` | read + write（**须** verify + `.bak` 回滚，见 workflow §5） |
| `templates/**/*.toml.bak.*` | write（向导备份） |
| `temp/wizard/**` | read + write（向导状态） |
| `templates/**/*.history.json` | read + write |
| `docs/**` | read only（向导运行期） |
| `nicegui_ui/**`、`app/**` | read only（调用 `core_toml` / `core_connect`） |
| `credentials/**` | **禁止** LLM 直接读写 |
| `exports/**`、`temp/**`（除 wizard） | read only |

写入路径（**全部 Python**，见 `gemma4_e4b_workflow.md` §5）：

1. E4B 输出 JSON `action` + `patch`  
2. `wizard/toml_io.py` → `load_toml` → merge → `TomlGenerator.ConfigToToml` → 落盘  
3. **`verify_toml`**；失败回滚 `.bak`；observation **仅** 错误 bullet  

**不进 LLM 上下文：** 完整 `.toml` 原文、PowerShell/MCP shell 输出。

---

## 10. 集成与启动

```bat
run.bat

REM TOML 首次配置向导（主场景）
python -m llm_gemma4 wizard --template Ginger_Lots --profile openvino

REM 通用短对话（调试）
python -m llm_gemma4 chat --profile cuda --task "..."
```

---

## 11. 分阶段实施计划

### 总览

| Phase | 目标 | 可独立验收命令 |
|-------|------|----------------|
| **0** | 方案评审 | 文档 |
| **1a** | 探测 + 下载 | `python -m llm_gemma4 probe` |
| **1b** | 三档推理 smoke | `smoke_test_{cpu,cuda,openvino}.py` |
| **2** | 指挥层骨架 | wizard W0～W3 无 LLM |
| **3** | Playwright | `edge_nicegui_smoke` / e2e |
| **4** | TOML 向导 + E4B | `wizard --template …` |
| **5** | chat / MCP 可选 | `chat --task` |
| **6** | 清理 | 删 `app/llm/` |

应用层 W0～W5 与 Phase 对齐见 [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) §13。

---

### Phase 0 — 评审（完成）

- [x] 客户机：**Core 7 150U，无 NPU，Iris Xe 96EU**
- [x] OpenVINO：**device=GPU，INT4**，允许 CPU fallback
- [x] 浏览器：**Playwright + Edge**
- [x] 三档 profile + **hardware_probe**
- [x] TOML：**JSON→Python** 指挥层（§3.1、§6.2）
- [x] HF 下载 URL 归入 **§4.0**
- [ ] Phase 1 实机：150U 核显 INT4 **≥5 tok/s**

---

### Phase 1a — 探测与权重下载

| # | 任务 | 模块 / 脚本 | 验收 |
|---|------|-------------|------|
| 1.1 | 硬件探测 CLI | `runtime/hardware_probe.py` · `probe` 子命令 | [x] `python -m llm_gemma4 probe` |
| 1.2 | GGUF 下载 | `backends/llamacpp/scripts/download_gguf.py` | [x] 脚本 + `download` CLI |
| 1.3 | OV INT4 下载 | `backends/openvino/scripts/download_ov_int4.py` | [x] 脚本 + `download --profile openvino` |
| 1.4 | 统一 download CLI | `__main__.py download` | [x] |
| 1.5 | profile TOML | `profiles/{cpu,cuda,openvino}.toml` | [x] |

**本机（5600X + 4070）先做：** 1.2 + cuda wheel + `smoke_test_cuda`；cpu 用 **0.3.28**（无 AVX-512F）。

**150U 再做：** 1.3 + `smoke_test_openvino`；确认 **AVX-512F** 后 `openvino` 进菜单。

---

### Phase 1b — 推理后端与 smoke

| # | 任务 | 模块 | 验收 |
|---|------|------|------|
| 1.6 | `LlmBackend` 协议 | `backends/base.py` | [x] |
| 1.7 | factory | `backends/factory.py` | [x] |
| 1.8 | llama.cpp CPU/CUDA | `backends/llamacpp/backend.py` | [ ] `smoke_test_cpu` / `smoke_test_cuda` 实机 |
| 1.9 | OpenVINO GPU | `backends/openvino/backend.py` | [ ] `smoke_test_openvino`（150U） |
| 1.10 | Thinking 解析 | `runtime/thinking.py` | [x] 单测 |
| 1.11 | B2 导出（可选） | `export_ov_int4_sym.py` | B1 不达标时启用 |

---

### Phase 2 — Agent + 压缩 + 向导骨架（无 LLM）

- [x] `agent/context_store.py` + `compressor.py` + `context_config.py`
- [x] `wizard/runner.py` · `action_parser.py` · `state.py` · `precheck.py`
- [x] `wizard/toml_io.py`（digest / patch / verify / `.bak`）
- [x] `wizard/tools.py` dispatch
- [x] `agent/wizard_runner.py` + `__main__.py wizard`
- [x] **W0～W3** `--no-llm` 可跑通

---

### Phase 3 — Playwright

- [x] `tools/browser_playwright.py` + `browser_state.py`
- [x] GOOGLE_PROBE + COLLECT_PASTE wired in `wizard/runner.py`
- [x] 复用 `edge_nicegui_smoke` 模式（`channel=msedge`）

---

### Phase 4 — TOML 向导 + E4B

- [x] `wizard/tools.py` dispatch（§6.2.2）— 9 action 路由齐全；单测 `test_dispatch_*`
- [x] `wizard/prompts.py` + FIELD_MAP_LOOP — `runner._step_field_map_loop` + FakeBackend 单测
- [x] `test_regex` / `test_source_row` — `toml_io.py` + `tools.dispatch`；单测覆盖
- [x] 单模板 LLM 调用 ≤15 次（`prompts.MAX_LLM_CALLS`）；`ginger_lots` `verify_ok=True`
- [ ] 实机 `--llm` E2E（需 `llama-cpp-python` + `download --profile`）；本机未装 wheel 时用 FakeBackend 单测代替

---

### Phase 5 — 可选 chat / MCP

- [x] `agent/loop.py`（max_steps=8）
- [x] `mcp/server.py` 窄 tool 子集
- [x] `__main__.py chat`

---

### Phase 6 — 清理

- [x] 删除 `app/llm/`（含旧 `download_gemma4_model.py`）
- [x] README：双环境 + `probe` / `download` / `wizard` 命令

---

### 建议实施顺序（现在起）

```
Week A  1.2 download_gguf → 1.8 smoke_test_cuda（4070）
Week A  1.8 smoke_test_cpu（0.3.28 wheel）
Week B  1.3 download_ov_int4 → 1.9 smoke_test_openvino（150U）
Week B  Phase 2 wizard/toml_io W0～W3
Week C  Phase 3 Playwright + Phase 4 E4B FIELD_MAP
```

---

## 12. 风险与对策

| 风险 | 对策 |
|------|------|
| v3 NPU 方案在 150U 上必崩 | **已修正**：全面改 iGPU + INT4 |
| 核显带宽瓶颈、tok/s 过低 | INT4 sym 自导出；`thinking_budget=512`；激进压缩；smoke **≥5 tok/s** 门禁 |
| 官方 `int4-ov` 在部分 Intel GPU 编译/性能差 | B2 自导出；`allow_cpu_fallback`；记录 health_check |
| DOM 撑爆上下文 | `browser_state` 预截断 + §8 多层压缩 |
| Playwright 双轨不一致 | **已修正**：仅 Playwright |
| HF 包 EXPERIMENTAL | 锁定 OV / 驱动版本；Phase 1 实机验收 |
| E4B tool JSON / 长链 Agent 不稳定 | **TOML 主路径用 wizard 状态机**；窄 tool；见 `gemma4_e4b_workflow.md` |
| TOML 读写 token 膨胀 | **Python digest + patch**；禁全文/shell 进上下文；见 workflow §5.4 |

---

## 13. 验收标准

1. **探测**：`hardware_probe` 在 4070 / 150U / 纯 CPU 机上给出正确可选列表  
2. **cpu**：`smoke_test_cpu` 通过；**无 AVX-512F** 时 wheel **0.3.28**  
3. **cuda**：4070 `smoke_test_cuda` 通过  
4. **openvino**：150U · **AVX-512F** · `device=GPU` · ≥5 tok/s  
5. **菜单**：无 `--profile` 时交互选择；仅一项时自动选用  
6. **wizard**：`Ginger_Lots` 无 Google 时可完成 TOML 配置且 `verify_toml` 通过（`gemma4_e4b_workflow.md` §11）

---

## 14. 相关文档

- [`gemma4_e4b_workflow.md`](gemma4_e4b_workflow.md) — TOML 向导、JSON→Python、E4B 窄 tool  
- [PowerShell.MCP](https://github.com/yotsuda/PowerShell.MCP) — 可选 Cursor 开发工具（**非** wizard TOML 路径）
- [`toml_config_design.md`](toml_config_design.md) — 字段语义  
- [`connect_google.md`](connect_google.md) — Google 连接
