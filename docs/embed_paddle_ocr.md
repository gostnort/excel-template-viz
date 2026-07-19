# PaddleOCR · 嵌入运行时规格

> 状态：plan v2.1（`paddle_ocr/` 平台完整设计：统一 API、CLI、模型与安装、三引擎物理分层、**内存分级精修**；**不含** NiceGUI 实现）  
> 日期：2026-07-12  
> 阶段：**C2 / C3 / C3.1 / C3.2 / C3.3 已完成**（`gemma_only` 档视觉纠错：**放弃** C3.1 的纯文本纠错 `gate/gemma_correct.py`——实测纠错效率约等于零，已删除；改用 `gate/gemma_vision_correct.py`——**派生角色 character + `Pic2Str` 整图读图 + 逐单元择优合并（保结构）**，见 §3.2a「gemma_only 视觉纠错（C3.3）」）  
> 存储层：[`db_store.md`](db_store.md)（拍照落库、`input_label` 关联；**须先定稿并实现 `save_image`，再接 UI**）  
> 导出层：[`excel_transform.md`](excel_transform.md)（按需附图到 sheet）  
> 上游参考：[PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)（**3.x**；主路径 **PPStructureV3**，精修 **PaddleOCRVL v1.6**，**仅 GPU**）  
> **精修门禁**：[`embed_gemma4.md`](embed_gemma4.md) 的 Gemma 4 **逐单元**判定 fast 结果是否存在**语义问题**，**短路**至首个有问题单元。**内存预算** = max(可用 RAM, 可用 VRAM)：< 4GB 不精修；4-10GB（`gemma_only`）Gemma4 检查 → 有问题则 **C3.3 视觉纠错**（派生角色 + `Pic2Str` 整图读图 + 逐单元择优，保结构）；10-14GB Gemma4 检查→**卸载 Gemma4**→PaddleOCRVL(GPU) 推理（顺序，峰值 4.6+10.8=15.4GB 不能共存）；≥14GB Gemma4 检查的同时**异步**加载 PaddleVL，两者常驻。10GB+ 两档需 `AcceleratorAvailable`（GPU + `paddlepaddle-gpu`），否则降级 gemma_only。

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | `paddle_ocr/` 怎么装、**`PaddleOcr(pic, rectangle)`**（图进 → 结构 JSON 出）、fast→Gemma 语义门禁→**内存分级精修**（4/10/14GB 阈值）、串行任务、CLI `main()` 门禁 |
| [`db_store.md`](db_store.md) | 拍照怎么落盘、`input_label` 怎么关联、OCR 结果是否写回 store |
| [`nicegui_ui/nicegui_ui_plan.md`](nicegui_ui/nicegui_ui_plan.md) | 右键/长按菜单怎么编排、何时调本平台 / `core_store` |
| [`excel_transform.md`](excel_transform.md) | 用户要求时如何把已存图片附着到 Excel sheet |

**`paddle_ocr` 平台自身不带 UI。** NiceGUI **只调用一次** `PaddleOcr(...)`；不提供、不需要「重新识别」类菜单项。fast / Gemma 门禁 / PaddleVL 精修全部在函数内部完成。

**命名**：对外公开函数用 **CapitalCase**（如 `PaddleOcr`、`HealthCheck`）。包目录仍为 `paddle_ocr/`。

**不在本文件**：SQLite DDL 全文、Excel 坐标、NiceGUI 线框。

**核心分界**：**`PaddleOcr()`** 是平台主端口，只完成一次 OCR 任务（图 → §3.3 JSON）；**不做** `HealthCheck`。就绪探测、缺模型下载、样图试跑归 **`main()` CLI**，不归 `PaddleOcr()` 内部。

### 0.1 与 `core_store` 的实施顺序

| 顺序 | 工作 | 说明 |
|------|------|------|
| 1 | 定稿并实现 [`db_store.md`](db_store.md) 存图 API | 存图尚未就绪 |
| 2 | 实现本文件 `paddle_ocr/`（含 `PaddleOcr` + fast + Gemma 门禁 + PaddleVL） | 零 SQLite |
| 3 | NiceGUI 菜单 | 拍照 → store；OCR → **一次** `PaddleOcr`；可选写回 store |

---

## 1. 定位与目标

### 1.1 职责

| 负责 | 不负责 |
|------|--------|
| 主端口 **`PaddleOcr(pic, rectangle)`**：图进 → 结构 JSON 出 | 输入框菜单、相机 UI、框选 UI、**任何「重新识别」交互** |
| 串行处置 OCR 任务（单例 + 锁，见 §3.6） | SQLite / `core_store` |
| 自动探测图片格式；fast → Gemma 语义门禁 →（有问题）PaddleVL 精修 | HTTP / NiceGUI 页面 |
| CLI **`main()`**：`HealthCheck` → 缺模型则下载 → 样图跑一次 `PaddleOcr` | Excel 落图 |
| 模型下载脚本（供 CLI / install 调用） | 让 UI 选择 fast/VL；**在 `PaddleOcr` 内做 HealthCheck** |

### 1.2 分工

```
nicegui_ui                 paddle_ocr/                 app/core_store
──────────                 ───────────                 ──────────────
右键菜单、相机、框选         PaddleOcr()                 save_image()
一次调用、按 JSON 回填       （无 HealthCheck）          update_image_ocr()
ui.notify(message)         内部：fast → Gemma 语义门禁 → (有问题) PaddleVL

CLI / install.bat 收尾       main()：HealthCheck → download? → PaddleOcr(sample)
```

| 菜单项 | UI 行为 | 本平台 |
|--------|---------|--------|
| **拍照** | → `core_store.save_image` | 不参与 |
| **OCR** | 取图 → 框选 → **`PaddleOcr(pic, rectangle)` 一次** → 回填 | 内部自行 fast / Gemma / PaddleVL |

**禁止**：UI 增加「重新识别 / 精细识别 / 再用 VL」等二次入口。用户只点一次 OCR。

### 1.3 设计原则

1. 平台零外溢：逻辑与模型在 `paddle_ocr/`。
2. UI 只调 **`PaddleOcr`**（CapitalCase 公开 API）。
3. 存图归 store；OCR 默认可不落库。
4. 对人只暴露 `ok` + 中文 `message`。
5. 输出为 fast / VL 引擎原文 JSON；业务字段映射由 UI/其它模块做。
6. **fast 优先**；是否进 PaddleVL 由 **Gemma 语义门禁**决定，**不**以「fast 是否为空」作为唯一条件；对 UI 透明（可选返回 `mode` 供日志，非交互）。
7. **`PaddleOcr` 只管完成任务**：解码 → 推理 → 映射 JSON；**不**在函数开头或内部调用 `HealthCheck`。
8. **就绪与试跑**：仅 **`main()` CLI**（及 install 收尾）串联 `HealthCheck`、自动下载、一次 `PaddleOcr`。
9. **内存不足则降级**：项目启用 OCR 时**启动即测**可用内存与显存（预算 = max(RAM, VRAM)）；按 `RefineTier()` 分 4 档——< 4GB 仅 fast / 4-10GB Gemma4 检查 + C3.3 视觉纠错 / 10-14GB 顺序（卸载 Gemma4 再 VL）/ ≥14GB 两者常驻（§3.2a / §3.8）。

---

## 2. 平台包布局

三个独立大模块（**pp-ocr** / **pp-structure** / **paddle-vl**）各自有专属文件夹 `engines/`；精修门禁（Gemma 语义判定 + 内存门禁）归 `gate/`；**每次 `PaddleOcr()` 都走的热路径共享工具**归 `runtime/`；**安装时/CLI 才跑的下载脚本**归 `scripts/`。`runtime/` 与 `scripts/` 语义严格分开——前者是推理热路径，后者是 install/CLI 工具，不可混放。

```
paddle_ocr/
  main.py                  # PaddleOcr / PaddleOcrTasks / HealthCheck / EnsureModels + main() CLI（编排引擎 + 门禁）
  config.py                # OCR 开关、内存阈值、VL 版本、RefinePathEnabled 缓存键
  models_catalog.py        # fast 必需模型 + 可选 VL 模型清单；prune 逻辑（VL 按硬件去留）
  requirements.txt         # paddle + paddleocr + paddlex[ocr] + pillow-heif + psutil
  models/                  # OCR/structure/VL 权重（PADDLE_PDX_CACHE_HOME，gitignored）
    official_models/       # PP-OCRv4 mobile / PP-DocLayout_plus-L / SLANeXt / RT-DETR / PP-DocLayoutV3 / PaddleOCR-VL-1.6
  engines/                 # 三个独立 OCR 引擎，物理隔离
    pp_ocr/
      backend.py           # FieldStripBackend：mobile PP-OCR，细条裁剪用（无网格路由命中）
    pp_structure/
      backend.py           # StructureBackend：PPStructureV3，整图/有网格；细条委托给 pp_ocr
    paddle_vl/
      backend.py           # VlBackend：PaddleOCRVL v1.6 精修（**仅 GPU，device="gpu"**；无加速器不构造）
  gate/                    # 精修路径门禁（仅 RefineTier != none 时生效）
    hardware_probe.py      # 启动时硬件探测：detect_accelerator()->gpu/npu/cpu；AcceleratorAvailable()（GPU+paddlepaddle-gpu）
    memory_guard.py        # 测可用 RAM+VRAM；RefineTier()->none/gemma_only/sequential/both_resident（4/10/14GB 阈值）
    semantic_gate.py       # Gemma 4：HasOcrSemanticProblem 逐单元短路
    gemma_vision_correct.py # C3.3：GemmaVisionCorrect——Pic2Str 整图读图 + 角色 character + 逐单元择优合并（保结构）
    # 旧的纯文本纠错 gemma_correct.py（C3.1，GemmaCorrectUnits）已验证效率约等于零并删除。
  runtime/                 # 共享热路径工具（每次 PaddleOcr 都调；非脚本）
    image_decode.py        # 自动探测格式 + 裁剪（OpenCV xywh）+ HEIC（is_heic/decode_heic 公开入口；pillow-heif）
    postprocess.py         # StructureResultToJson / HtmlTableToRows / FieldPredictToStringJson / HasContent（table 空→string 降级）
    table_grid.py          # OpenCV HasTableGrid → fast 路由启发式
    infer_lock.py          # INFER_LOCK 串行锁（fast 与 VL 推理共用）
  scripts/
    download_models.py     # install 时拉取/暖机权重（CLI / install.bat；VL 暖机仅 AcceleratorAvailable 时）
    install_backend.py     # 首次启动硬件探测 + 装 paddlepaddle-gpu（GPU）/ prune VL（CPU）；不能在已 import paddle 的进程内热替换
    _warm_vl_gpu.py        # install_backend 装好 GPU paddle 后在全新子进程构造 PaddleOCRVL(gpu) 触发 VL 模型下载
```

**依赖方向**：`main` → `engines.pp_structure`（fast 主入口）→ 委托 `engines.pp_ocr`（细条）；`main` → `gate.semantic_gate` → `llm_gemma4`；`main` → `engines.paddle_vl`（精修）。三个引擎**共用** `runtime/` 的解码/后处理/锁/网格判定——这些是每次推理都走的热路径，不属于任何单一引擎，也不属于 `scripts/`。`pp_structure` 对 `pp_ocr` 的依赖是**域耦合**（细条裁剪业务上要委托字段 OCR），分文件夹不消除该依赖，只让它显式跨包。

---

## 3. 主端口：`PaddleOcr(pic, rectangle)`

**本平台对外最重要的入口。** 契约：**图片进 → 结构 JSON 出**（§3.3）。调用方（NiceGUI、脚本、测试）只关心这一次任务是否完成、返回什么 JSON。

**`PaddleOcr` 不做 `HealthCheck`。** 若引擎未装、模型缺失或推理失败，通过返回 JSON 的 `ok` / `message` 表达；不在函数内单独跑就绪探测。

### 3.1 签名

```python
def PaddleOcr(
    pic: bytes | Path | str,
    rectangle: tuple[int, int, int, int] | None = None,
) -> dict: ...
```

| 参数 | 含义 |
|------|------|
| `pic` | 原图；**不传格式**；自动探测 JPEG/PNG/HEIC 等 |
| `rectangle` | OpenCV `(x, y, w, h)`；`None` = 整图 |

另提供 **`HealthCheck()`**（§4.1），**仅供 CLI / 安装收尾**；**UI 的 OCR 菜单不调用**。

多图/多选区请用 **`PaddleOcrTasks`**（§3.7），**不要**给 `PaddleOcr` 增加多图参数。

### 3.2 任务流水线（对 UI 不可见）

```
PaddleOcr(pic, rectangle)
  → 解码 + 裁剪
  → [fast] 网格路由 → PPStructureV3 或字段 PP-OCR → 映射 string*/table*
  → RefineTier()  (预算 = max(可用 RAM, 可用 VRAM))
  → none(<4GB)            → 返回 fast
  → gemma_only(4-10GB)    → Gemma4 检查 → 有问题则 C3.3 Pic2Str 整图读图 + 逐单元择优合并（保结构）(mode="gemma_vision_corrected")
  → sequential(10-14GB)   → Gemma4 检查 → 有问题则 卸载 Gemma4 → PaddleOCRVL(gpu) 推理 (mode="llm")
  → both_resident(≥14GB)  → Gemma4 检查 → 有问题则 PaddleOCRVL(gpu) 推理 (两者常驻) (mode="llm")
  → 无问题 → 返回 fast
  → 返回统一 JSON（mode: "fast"|"llm"）
```

**无 HealthCheck 步骤。** **无 UI 二次点击。** NiceGUI 一次调用等最终结果即可（可显示 loading）。

#### 3.2a 内存分级精修（C3.2：Gemma4 4.6GB + VL 10.8GB 峰值合计 15.4GB → 10-14GB 档不能同时驻留）

**实测峰值占用**：Gemma4（LiteRT 底座）**4.6GB VRAM**；PaddleOCRVL 0.9B **10.8GB VRAM**；两者合计 **15.4GB**。阈值定在峰值之下——Paddle-VL 与 LiteRT 都会往内存倒垃圾/复用，实际需求略低于峰值（4/10/14GB）。VL 在纯 CPU 上 268s/页，已弃用（仅 GPU）。故精修按**内存预算**分 4 档，预算 = `max(measure_available_ram_gb(), measure_available_vram_gb())`（`gate/memory_guard.py`）：

| 档位 | 触发条件 | 行为 |
|------|----------|------|
| `none` | 预算 < 4GB | 仅 fast，直接返回（不够装 Gemma4 4.6GB） |
| `gemma_only` | 4GB ≤ 预算 < 10GB，**或** 10GB+ 但无加速器 | Gemma4 检查 → 有问题则 **C3.3 `GemmaVisionCorrect`**（派生角色 + `Pic2Str` 整图读图 + 逐单元择优合并，保结构；`mode="gemma_vision_corrected"`） |
| `sequential` | 10GB ≤ 预算 < 14GB **且** `AcceleratorAvailable` | Gemma4 检查 → 有问题则**卸载 Gemma4**（`ResetBackend`）→ 加载 `PaddleOCRVL(device=gpu)` 推理（峰值 4.6+10.8=15.4 不能共存） |
| `both_resident` | 预算 ≥ 14GB **且** `AcceleratorAvailable` | 启动时 Gemma4 + 异步预热 VL（两者常驻，峰值合计 15.4GB）；有问题则直接 VL 推理 |

- **`gate/memory_guard.py`**：`measure_available_vram_gb()`（`nvidia-smi --query-gpu=memory.free`）/ `available_budget_gb()`=max(RAM,VRAM) / `RefineTier()`→none/gemma_only/sequential/both_resident / `RefinePathEnabled()`=`tier!="none"`。`init_refine_path()` 启动测一次预算并缓存。
- **`gate/hardware_probe.py`**：`AcceleratorAvailable()`=GPU 硬件 + `paddlepaddle-gpu`（CUDA 版）。10GB+ 档需它，否则降级 `gemma_only`。
- **`main.PaddleOcr` 分支**：fast `ok=false`→返回；`tier=none`→返回 fast；`HasOcrSemanticProblem(fast)` 为 false→返回 fast；为 true：`gemma_only`→`GemmaVisionCorrect(pic, rectangle, fast)`（C3.3 视觉纠错）；`sequential`→`_unload_gemma4()`→`LlmRefine`；`both_resident`→`LlmRefine`（VL 已热）。VL/视觉纠错失败→返回 fast + `MSG_LLM_PARTIAL`。
- **启动预热**（`main._warm_for_tier`）：`none`→不预热；`gemma_only`/`sequential`→`StartGemma()`（Gemma4 常驻做检查）；`both_resident`→`StartGemma()` + **异步线程**预热 `GetVlBackend().warm()`（不阻塞 CLI）；`sequential` 的 VL 按需在 `PaddleOcr` 内卸载 Gemma4 后加载。
- **库文件安装**：`paddlepaddle`(CPU)→`paddlepaddle-gpu` 不能在已 import paddle 的进程内热替换。首次启动检测到 GPU 硬件但未装 GPU paddle 时 `main()` 提示运行 `scripts/install_backend.py`（卸载 CPU paddle → 装 `paddlepaddle-gpu==3.3.1` CUDA 12.9 index → 全新子进程 `_warm_vl_gpu.py` 构造 PaddleOCRVL(gpu) 触发 VL 模型下载），装好后重启。本次会话降级 `gemma_only`。
- **VL 模型去留按硬件**：`EnsureModels`/`download_models` 用 `detect_accelerator()`——有加速器硬件则保留/补下载 VL 模型；纯 CPU 则 `prune_extra_official_models(keep_vl=False)` 释放磁盘。

#### gemma_only 视觉纠错（C3.3，已完成）

**背景 / 为何放弃 C3.1 方案**：C3.1 的 `gate/gemma_correct.py`（`GemmaCorrectUnits`）把 Gemma4 判有问题的单元**纯文本**扔给 `ConversationOnce` 自由改字。在 `test_paddlevl_gemma_e2e.py` 实测中纠错效率约等于零——Gemma4 拿到的只是已经错乱的 OCR 字符串本身，**没有任何独立信息源**可用来判断哪个字才是对的，模型只能在原文附近做保守微调（多数情况原样抄回或只改标点）。已确认放弃并删除该文件（连同 `semantic_gate.ShouldTryGemmaCorrection` 死代码、`config.MSG_GEMMA_CORRECTED`、相关单测一并清理）。

**已实施方案**（`gate/gemma_vision_correct.py` · `GemmaVisionCorrect(pic, rectangle, fast)`）：用 Gemma4 的**视觉识别**（[`embed_gemma4.md`](embed_gemma4.md) §3.1d 的 `Pic2Str`）提供独立信息源，再逐单元判别式择优，不让模型凌空猜字：

1. **派生角色 character**：`_derive_character(fast)` 调 `ConversationOnce`，从 fast 结果判断这份文档的类型/角色背景，返回一句中文描述（如"机场地勤人员的旅客遗失物品交接单"、"银行支票"）。**角色是关键约束**——幻觉可接受的前提就是角色把再创造限制在正确语义域内。
2. **`Pic2Str` 整图读图**：`_encode_cropped_jpg(pic, rectangle)` 把裁剪区编码成 jpg 字节；`_build_pic_prompt(fast)` 要求输出与 fast **同形 JSON**（键 / table 行列数写死，强制可对齐）；`Pic2Str(jpg, prompt, system="你是文档 OCR 引擎。背景：{character}")` 得到 Gemma4 自己的整份读数。**整图一次调用**，避免 C3.1 旧方案"单元→bbox 映射缺失"的前置阻塞。
3. **逐单元择优**：`_pick_better(fast_text, gemma_text, character)` 调 `ConversationOnce`（纯文本裁判，不看图）——在"这是{character}"语境下判 A=fast / B=gemma 哪个更可能正确，只输出 A/B；歧义/异常保守保留 fast。string* 逐键、table* 逐格择优。
4. **合并保结构**：deepcopy fast，按单元写回胜者；**键 / 行数 / 列数不变**（gemma 多出的格丢弃，少的保留 fast）；`mode="gemma_vision_corrected"`，`message=MSG_GEMMA_VISION`。Gemma4 不可用 / 读图失败 / JSON 解析失败 → 保留 fast + `MSG_LLM_PARTIAL`。

**与 C3.1 的关键区别**：C3.1 是「单一信息源 + 自由生成」（在原错误附近打转）；C3.3 是「两个独立信息源（文本管线 + 视觉管线）+ 判别式择优」（Gemma4 只挑更合理的一行，不凌空猜字）。

**幻觉策略**（见 `embed_gemma4.md` §3.1d 末段）：Pic2Str 对密集小字中文会"编出通顺但与图不符的文字"。本模块**接受该幻觉**——fast 的错字本就不可读，视觉犯错是人类也会犯的；幻觉作为语义上的"模糊/再创造"可接受，角色 character 是约束它的关键。逐单元择优只在 gemma 明显更顺时替换 fast，不会把好的 fast 单元换掉。

**成本**：`gemma_only` 档本身是"预算不够常驻 VL"的降级路径；本方案 1 次 `Pic2Str` + N 次 `ConversationOnce` 比对（N=单元数）。纯 CPU 下延迟可接受（Gemma4 CPU 纠错本就快，见 C3.1 立项理由）。

#### Gemma 语义门禁（是否调精修；实施时钉死）

**前置**：`RefineTier() == "none"`（预算 < 4GB）时，**整段跳过**本门禁与精修。

```python
# paddle_ocr/gate/semantic_gate.py
def HasOcrSemanticProblem(fast_result: dict) -> bool: ...   # 逐单元 run_judgment + 短路
# paddle_ocr/gate/memory_guard.py
def RefineTier() -> str: ...   # none / gemma_only / sequential / both_resident
```

**判定粒度（逐单元 + 短路）**：`HasOcrSemanticProblem` 把 fast 草稿拆成单元（`string1..stringN` 每条一段；`table1..tableN` 每行 `cells` 拼成一段），**逐单元**调 `run_judgment`。一旦某单元 `affirmative`（有问题），**立即短路返回 `true`**。全部 `negative`/`unknown` → `false`。

应用层通过 [`llm_gemma4`](embed_gemma4.md) §3.6 `run_judgment` 调底座：`semantic_gate` 组 OCR 专用 `JudgmentSpec`（每单元文本作 `user`），底座返回 `JudgmentResult` 三态，`_ocr_semantic_to_bool` 映射：`affirmative`→`True`（调精修）；`negative`/`unknown`→`False`（保守）。`verdict_key="has_problem"`；`use_constrained_decoding=True`；`max_tokens ≥ 200`。**禁止**在 `llm_gemma4` 内写 OCR 逻辑；**禁止**用 `HasContent` 代替语义判定。

| 条件 | 走 VL(GPU)？ | 走 gemma_only 纠错？ |
|------|----------------|----------------|
| 预算 < 4GB（`none`） | 否 | 否（仅 fast） |
| 4-10GB（`gemma_only`） | 否（VL 不加载） | **是**（C3.3 `GemmaVisionCorrect`：Pic2Str 整图 + 逐单元择优） |
| 10-14GB + 加速器（`sequential`） | 是（先卸载 Gemma4 再 VL） | 否（Gemma4 仅检查，不纠错） |
| ≥14GB + 加速器（`both_resident`） | 是（两者常驻） | 否（Gemma4 仅检查） |
| 10GB+ 但无加速器 | 否（降级 `gemma_only`） | 是（同上 C3.3） |
| 解码/选区非法 / fast 未装 / 模型缺失 / Gemma 不可用 | 否 | 否（返回 fast；`ok=false` 坏状态两路径都不进） |
| Gemma `has_problem: true` | `sequential`/`both_resident`→是 | `gemma_only`→`GemmaVisionCorrect` 视觉纠错 |
| Gemma `has_problem: false` | 否 | 否 |

语义问题示例（Gemma 应倾向 `true`）：

- 表格行列错位、单元格与表头语义明显不符（如「航班号」格为人名）。
- 标题/脚注与表格内容主题完全对不上。
- 大面积乱码或断句，无法构成可读表单语义。
- 选区明显是表格/表单版面，fast 却几乎无结构化内容。

非语义问题示例（Gemma 应倾向 `false`）：

- 个别手写识别偏差，但行列标签与邻格关系仍合理（如签字栏 OCR 错字）。
- 用户框选空白区域，fast 为空属预期。
- fast 已给出完整、自洽的标题 + 表 + 脚注形状。

> **与旧规格的差异**：不再使用「fast 无内容 → 自动 VL」。空结果是否精修，完全由 Gemma 语义判定决定。

#### PaddleVL 精修职责（仅 GPU）

- **触发**：仅当 `ShouldTryVl` 为真（`RefinePathEnabled` + `AcceleratorAvailable` + `HasOcrSemanticProblem`）。
- **输入**：裁剪后图像 +（可选）fast 草稿 JSON。
- **输出**：**同一** §3.3 JSON 形状；`mode: "llm"`。
- **实现**：**PaddleOCR 自有** `PaddleOCRVL`（默认 `v1.6` / `PaddleOCR-VL-1.6` 权重，走 `PADDLE_PDX_CACHE_HOME`），`engines/paddle_vl/backend.py`，**`device="gpu"`**；无加速器时 `_ensure_engine` 返回 `no_accelerator` 不构造。VL `predict()` 返回 `parsing_res_list`（`block_label`/`block_content`/`block_bbox`，与 PPStructureV3 同形），表格块的 `block_content` 是 HTML（由 VLM 的 OTSL 输出经 `convert_otsl_to_html` 转换）→ 经 `runtime/postprocess.py` 的 `HtmlTableToRows` 解析为 §3.3 的 `[{row, cells}, ...]`；表格块 HTML 解析为空但 `block_content` 非空时降级为 `string*`（不丢内容）。**Gemma 只做门禁，不做 VL 推理**；NiceGUI 不分支。
- VL 也失败：若有可用的 fast 草稿则返回草稿并 `message` 说明未精修；否则 `ok=false`。

#### gemma_only 纠错职责（CPU-only；C3.1 已删除，C3.3 已完成）

**当前状态**：`gemma_only` 档 Gemma4 判有问题时调 `gate/gemma_vision_correct.py` 的 `GemmaVisionCorrect(pic, rectangle, fast)`——派生角色 character + `Pic2Str` 整图读图 + 逐单元择优合并（保结构），`mode="gemma_vision_corrected"`。C3.1 的 `GemmaCorrectUnits`/`ShouldTryGemmaCorrection`/`MSG_GEMMA_CORRECTED` 已删除（纯文本纠错实测效率约等于零）。详见上方「gemma_only 视觉纠错（C3.3）」。

### 3.3 输出 JSON

```json
{
  "ok": true,
  "mode": "fast",
  "string1": "机上旅客遗失物品交接单",
  "table1": [
    {"row": 1, "cells": ["日期", "7.5", "航班号", "CA987", "航段", "PEK-LAX"]},
    {"row": 2, "cells": ["捡拾物品人员姓名", "张清林", "捡拾物品位置", "40JKL行李架", "交接地点", "机上"]},
    {"row": 3, "cells": ["捡拾物品详述", "40JKL 行李架捡到一袋免税品（内含化妆品 NARS）. 未拆封."]},
    {"row": 4, "cells": ["接收部门", "", "接收人签字", "", "移交人签字", "孙雅静"]}
  ],
  "string2": "备注：物品详述要填写物品名称、数量、币种、金额、信用卡种类等内容。",
  "message": "识别完成。"
}
```

| 字段 | 规则 |
|------|------|
| `ok` | 是否成功 |
| `mode` | `"fast"` 或 `"llm"`（日志/调试；UI 可不展示） |
| `string1`…`stringN` | 表外文本，自上而下 |
| `table1`…`tableN` | `[{ "row", "cells": [...] }, …]` |
| `message` | 中文状态 |

**Spike（2026-07-09）**：fast 全图可得到标题 + 4 行表 + 脚注形状。手写格仍可能错字；**是否**自动 PaddleVL 由 Gemma 语义门禁决定，**不**再因「有错字」或「非空」硬编码跳过/触发。

### 3.4 裁剪与格式

- OpenCV `(x,y,w,h)`；平台内裁剪；contiguous BGR。
- 格式自动探测；HEIC/HEIF → `pillow-heif`（公开入口 `is_heic(image)` / `decode_heic(image)`，`decode_image` 内部共用同一套底层逻辑）。**关键**：`_decode_heic_bytes` 用 `np.array(heif, copy=True)` 显式 copy——`np.asarray(heif)` 返回的是 pillow_heif 内部缓冲的 view，heif 对象 GC 后 view 悬空，后续读像素（`array_equal` / `predict` / crop）会触发 0xC0000005 访问冲突（已修复，2026-07-12）。
- **检测缩放**：`text_det_limit_type=max`（**禁止放大**）。有 `rectangle` 时按裁剪图 **原始长边** 做检测（`limit_side_len=max(h,w)`）。整图才用 `960` 做超长边缩小。
- **路由（裁剪图）**：`HasTableGrid`（OpenCV 横竖线网格启发式）→ **无网格** → mobile 字段 `PaddleOCR`；**有网格（可缺角）** → `PPStructureV3`。整图（`rectangle=None`）始终走 Structure。

### 3.5 引擎

| 阶段 | 引擎 | 说明 |
|------|------|------|
| fast（无网格裁剪） | mobile `PaddleOCR` | `engines/pp_ocr/backend.py` |
| fast（有网格 / 整图） | PPStructureV3 | `engines/pp_structure/backend.py`（细条委托 `pp_ocr`） |
| 语义门禁 | Gemma 4 E4B（LiteRT） | `gate/semantic_gate.py` → `llm_gemma4`（逐单元短路） |
| vl 精修 | PaddleOCR-VL（`PaddleOCRVL` v1.6） | `engines/paddle_vl/backend.py`；**需** `RefinePathEnabled` |

### 3.8 内存门禁（精修路径）

Gemma 语义门禁与 PaddleVL 叠加占用大（Gemma ~4GB 权重 + VL 推理峰值）。**内存不够时直接屏蔽整段精修功能**，避免把机器拖死；**fast 路径不受影响**。

#### 何时测量

| 时机 | 行为 |
|------|------|
| **项目加载且启用 OCR** | 测量一次**当前可用内存**（剩余可分配 RAM），写入进程内缓存 |
| 每次 `PaddleOcr` | **不**重复测；读缓存的 `RefinePathEnabled()` |
| `--skip-ocr` / OCR 未启用 | **不**测、不初始化精修相关模块 |

「启用 OCR」指：应用或 CLI 未跳过 OCR 安装/导入，且会加载 `paddle_ocr` 平台（NiceGUI 主程序、`python paddle_ocr/main.py` 等）。

#### 阈值与判定

```python
# paddle_ocr/gate/memory_guard.py
REFINE_MIN_RAM_GB = 4            # < 4GB → none（不够装 Gemma4 4.6GB）
REFINE_VL_MIN_GB = 10            # 4-10GB → gemma_only；10GB+ → 可加载 VL（峰值 10.8GB）
REFINE_BOTH_RESIDENT_MIN_GB = 14 # ≥14GB → both_resident（Gemma4 4.6 + VL 10.8 = 15.4GB 峰值同时常驻）

def measure_available_ram_gb() -> float: ...   # psutil.virtual_memory().available
def measure_available_vram_gb() -> float: ...  # nvidia-smi --query-gpu=memory.free
def available_budget_gb() -> float: ...        # max(RAM, VRAM)
def RefineTier() -> str: ...   # none / gemma_only / sequential / both_resident
```

| 预算 = max(RAM, VRAM) | `RefineTier` | Gemma4 检查 | gemma_only 纠错 | PaddleVL(GPU) |
|--------------------|---------------------|----------------|------------|----------|
| **< 4 GB** | `none` | **跳过** | 跳过 | 跳过 |
| **4–10 GB** | `gemma_only` | 执行 | **是**（C3.3 `GemmaVisionCorrect`：Pic2Str 整图 + 逐单元择优，保结构） | **不加载** |
| **10–14 GB** + 加速器 | `sequential` | 执行 | 否（仅检查） | 有问题则**卸载 Gemma4 后**加载 VL |
| **≥ 14 GB** + 加速器 | `both_resident` | 执行 | 否（仅检查） | 有问题则执行（两者常驻，启动异步预热 VL） |
| 10GB+ 但**无加速器** | `gemma_only`（降级） | 执行 | 暂无（同上） | 不加载（VL 仅 GPU） |

- **可用内存/显存**：OS 报告的**剩余可分配**物理内存（`psutil` available）与 NVIDIA GPU 剩余显存（`nvidia-smi memory.free`）。预算取大者（"内存或显存" whichever larger）。
- **阈值**：4 / 10 / 14 GB（`config.py` 三常量），定在实测峰值之下（Paddle-VL/LiteRT 会往内存倒垃圾/复用，实际需求略低于峰值）：Gemma4 峰值 4.6GB → 4GB；VL 峰值 10.8GB → 10GB；两者峰值合计 15.4GB → 14GB。精修路径专用，与 fast 无关。10-14GB 档峰值 4.6+10.8=15.4 不能同时驻留，必须顺序 load/unload。
- **对用户透明**：`PaddleOcr` 仍一次调用；低内存时恒为 `mode=fast`。日志可打 `RefineTier()`；**不必**单独弹窗，除非调试。

#### 与 fast 的关系

| 路径 | 低内存时 |
|------|----------|
| PPStructureV3 / 字段 PP-OCR | **照常** |
| `HasTableGrid` 路由 | **照常** |
| Gemma `HasOcrSemanticProblem` | **不触发** |
| `PaddleOCRVL` | **不触发** |

低内存下 fast 失败或语义存疑：**只返回 fast 结果**（或 `ok=false`），**不**尝试 Gemma / VL 补救。

### 3.6 串行任务处置（设计目标）

多路同时调用 `PaddleOcr` 时，平台以 **单例引擎 + 串行锁** 排队执行，一次只跑一个 OCR 任务（fast、Gemma 门禁与 PaddleVL 段均在同锁内），避免双通道占满 CPU/GPU。

- **设计目标**：稳定、可预期的任务处置，而非高并发吞吐。
- **调用方**：无需自管队列；重复点击 OCR 由平台串行化。
- **与 HealthCheck 无关**：锁只包推理路径，就绪探测在 CLI 层。

### 3.7 多任务端口：`PaddleOcrTasks(tasks)`

`PaddleOcr` **只接受一张图、一个可选 rectangle**。批量场景用独立端口：

```python
def PaddleOcrTasks(
    tasks: list[tuple[bytes | Path | str, tuple[int, int, int, int] | None]],
) -> list[dict]: ...
```

| 项 | 约定 |
|----|------|
| 输入 | 有序列表；每项为 `(pic, rectangle)`，语义同 §3.1 |
| 输出 | 与输入等长的 `list[dict]`，每项为对应一次的 §3.3 JSON |
| 执行 | **严格串行**：按列表顺序依次调用 `PaddleOcr`；共享引擎锁，不并行 |
| HealthCheck | **不**在 `PaddleOcrTasks` 内调用 |

失败策略：某一任务 `ok=false` 时仍继续后续任务；调用方按索引处理各 `message`。

---

## 4. `main.py` 门面

### 4.1 CLI：`main()`

**无** `probe` / `smoke` / `bench` 等子命令。安装或开发者在项目根执行：

```text
python paddle_ocr/main.py
```

（或 `install.bat` 收尾等价调用。）

**固定三步**（顺序不可打乱）：

| 步 | 动作 | 说明 |
|----|------|------|
| 1 | `HealthCheck()` | 探测 paddle / paddleocr / PPStructureV3 能否初始化 |
| 2 | 若未就绪或模型目录空 → `download_models()` | 自动拉取/暖机；失败则退出非 0 |
| 3 | `PaddleOcr(config.SAMPLE_IMAGE, None)` **跑一次** | 用 `test/ocr_sample.jpg` 验证图进 JSON 出链路 |

退出码：`HealthCheck`、下载、样图 `PaddleOcr` 任一步失败 → 非 0；全部成功 → 0。

**`HealthCheck()` 定义**（程序化，但 **不** 被 `PaddleOcr` 调用）：

```python
def HealthCheck() -> dict:
    """返回 { ok, message, version }；仅 CLI / 安装收尾使用。"""
```

### 4.2 程序化（UI / 业务）

```python
from paddle_ocr.main import PaddleOcr

result = PaddleOcr(pic_bytes, rectangle=None)
if not result["ok"]:
    ui.notify(result["message"])
# UI 不调用 HealthCheck；不根据 mode 再调一次；不提供「重新识别」
```

### 4.3 UI 契约

| API | 谁调用 | 输入 | 输出 |
|-----|--------|------|------|
| `PaddleOcr` | NiceGUI OCR 菜单、业务代码 | `pic`；`rectangle` | §3.3 JSON |
| `PaddleOcrTasks` | 多图/多选区批量 OCR | `tasks: list[(pic, rectangle)]` | `list` of §3.3 JSON |
| `HealthCheck` | **仅** `main()` CLI / install 收尾 | — | `{ ok, message, version }` |

| 菜单 | 调用 |
|------|------|
| 拍照 | `core_store.save_image` |
| OCR | **仅** `PaddleOcr(pic, rectangle)` |

---

## 5. 中文 message（示例）

| 场景 | `ok` | `message` |
|------|------|-----------|
| fast 或 vl 成功 | `true` | 识别完成。 |
| fast 成功、Gemma 无问题、内容为空 | `true` | 未识别到文字，请调整选区或重新拍照。 |
| fast 成功、Gemma 无问题、有内容 | `true` | 识别完成。 |
| 坏图 / 坏选区 | `false` | 无法读取图片… / 选区无效… |
| 组件未就绪 | `false` | OCR 组件未就绪… |
| 模型缺失 | `false` | OCR 模型未就绪… |
| Gemma 判有问题但 PaddleVL 不可用 / 精修失败 | `false` 或带 fast 草稿 | 文字识别失败… / 未能精修，已返回初稿。 |
| 低内存（`RefinePathEnabled=false`） | `true` 或 `false`（视 fast） | 识别完成。 / fast 失败时的原 `message`；**不**提示装 VL |

---

## 6. 安装

默认装；`--skip-ocr` 可跳过。`requirements` 含 `paddlex[ocr]`。磁盘约 1GB+（structure + 可选 VL）。`enable_mkldnn=False`。

**Gemma 语义门禁**依赖 [`llm_gemma4`](embed_gemma4.md) 与 `models/gemma4/`（与项目 install 既有链路一致）。**PaddleVL** 权重走 `PADDLE_PDX_CACHE_HOME`。

**内存**：启用 OCR 时启动测量可用 RAM + VRAM，按 `RefineTier()` 分档预热——`none`(<4GB) 不预热；`gemma_only`(4-10GB) `StartGemma()`；`sequential`(10-14GB) `StartGemma()`（VL 按需）；`both_resident`(≥14GB) `StartGemma()` + 异步预热 VL。`requirements` 含 `psutil`（与 `llm_gemma4` 探测共用）。OCR `--skip-ocr` 时整段 OCR 含内存探测均跳过。

---

## 7. 测试要点

**CLI 门禁**（`python paddle_ocr/main.py`）：

- `HealthCheck` → `ok`；缺模型时自动 `download_models` 后再检。
- 样图 `PaddleOcr(sample, None)` 跑一次 → `ok`；宜含 `string1` 与 `table1`（结构链路通即可，不以手写准确率为准）。

**`PaddleOcr` 单测 / 回归**（pytest，见 `test/paddle_ocr/`）：

- 坏图 / 非法 `rectangle` → `ok=false`，**不**调 Gemma / PaddleVL。
- mock `RefinePathEnabled=false` → 任意 fast 草稿均 `mode=fast`，不 mock Gemma / VL。
- mock fast 草稿 + `RefinePathEnabled=true` + Gemma `semantic_problem: true` → `mode=llm`（VL 可用时）。
- mock fast 空草稿 + Gemma `semantic_problem: false` → 保持 `mode=fast`，**不**进 VL。
- 无「二次识别」API（不存在该入口）。
- 多线程并发调用 → 串行完成、无交错写引擎。
- **`PaddleOcr` 内不 mock / 不依赖 `HealthCheck`。**

**PaddleVL × Gemma4 顺序流 e2e**（`test/paddle_ocr/test_paddlevl_gemma_e2e.py`，`@pytest.mark.integration`，需 gemma 权重 + **`AcceleratorAvailable`（GPU + paddlepaddle-gpu）** + VL 模型；无加速器时 skip）。**两个测试函数**，按样图类型走不同 fast 路径：

- **`test_paddlevl_gemma_e2e_jpg`**（`test/ocr_sample.jpg`，机场地勤遗失物交接单，**有网格**）：
  - (a) `REGION1` 字段细条 → `GetFieldStripBackend().Run` → 一句话。
  - (b) pp-structure 整图 → JSON（有网格 → 走 structure）。
  - (c1/c2) Gemma4 逐单元判定 pp-ocr / pp-structure（短路日志）。
  - (c3) `GemmaVisionCorrect(sample, None, struct)`——派生角色 + `Pic2Str` 整图读图 + 逐单元择优合并（`mode="gemma_vision_corrected"`）。
  - (d) 卸载 Gemma4 → 加载 VL；(e) `LlmRefine(sample, None)` 整图重算（`mode="llm"` + `gemma_main._backend is None`）。
- **`test_paddlevl_gemma_e2e_heic`**（`test/ocr_check.heic`，BMO 银行支票，**无网格 → 走字段 PP-OCR，不触发 pp-structure**；整图文本错位多，拆两个竖向 ROI）：
  - (a) `area1`(1006,662-1149,2220) + `area2`(1643,674-1840,3376) 各跑 `GetFieldStripBackend().Run`（`is_heic`/`decode_heic` 端到端）。
  - (c1/c2) Gemma4 逐单元判定 area1 / area2。
  - (c3) 每个 ROI `GemmaVisionCorrect(sample, box, field)`——派生角色（应为"银行支票"类）+ `Pic2Str` 裁剪图读图 + 逐单元择优。
  - (d) 卸载 Gemma4 → 加载 VL；(e) `LlmRefine(sample, None)` 整图重算对比（field 路径 vs VL 结构化重算）。
- **HTML→JSON 校验**：`_assert_table_shape` 确认每个 `table*` 为 `[{row, cells}]`。
- **日志**：每步打印 elapsed + string*/table* 内容 + 纠错前后 diff，供肉眼对比。
- **运行**：`python -m pytest test/paddle_ocr/test_paddlevl_gemma_e2e.py -v -s -m integration`（全跑）或 `-k heic` / `-k jpg`。实测 jpg≈66s / heic≈38s。

**内存分级单测**（`test/paddle_ocr/test_cpu_only_gemma_correct.py`，纯 mock，不打 integration 标记）：

- mock `RefineTier="none"` → `PaddleOcr` 直接返回 fast（不调 Gemma）。
- mock `RefineTier="gemma_only"` + Gemma 判 `affirmative` → `PaddleOcr` 走 `GemmaVisionCorrect`，返回 `mode="gemma_vision_corrected"`（C3.3 已实施）。
- mock `RefineTier="gemma_only"` + Gemma 判 `negative` → 返回 fast。
- mock `AcceleratorAvailable=false` → `VlBackend._ensure_engine()` 返回 `None`、`init_error="no_accelerator"`（VL 未构造）。

---

## 8. 分阶段（C2 / C3 / C3.1 / C3.2 / C3.3 已完成）

| 阶段 | 交付物 | 门禁 | 状态 |
|------|--------|------|------|
| S0 | store 存图 | `save_image` 可测 | 待定 |
| C2 | `PaddleOcr` 图进 JSON 出 + `main()` CLI（fast：`engines/pp_ocr` + `engines/pp_structure`） | `main()` 三步全绿 | ✅ 完成 |
| C3 | 文件夹重排 + `gate/memory_guard` + `gate/semantic_gate`（逐单元短路） + `engines/paddle_vl/backend.py` + `main.PaddleOcr` 接线 + VL 模型按 `RefinePathEnabled` 下载 + VL×Gemma4 热态全量测试 | ≥7GB 且 Gemma 判有问题才 VL；VL HTML→`[{row,cells}]` | ✅ 完成 |
| **C3.1** | ~~放弃 CPU VL：`gate/hardware_probe` + `ShouldTryVl` 需 `AcceleratorAvailable` + `gate/gemma_correct`（CPU-only Gemma4 改字）+ `scripts/install_backend.py`（装 paddlepaddle-gpu）+ VL 模型按 `detect_accelerator` 去留~~ | 有加速器→VL(GPU)；无加速器→Gemma4 纠错 | ✅ 完成（**`gate/gemma_correct.py` 纠错部分已于 C3.3 前置清理中删除**，`hardware_probe`/`install_backend.py`/VL 去留逻辑仍保留） |
| **C3.2** | **内存分级精修**：`measure_available_vram_gb` + `RefineTier()`（none/gemma_only/sequential/both_resident，4/10/14GB）+ `main.PaddleOcr` 分档分支 + sequential 卸载 Gemma4 再 VL + both_resident 异步预热 VL + `main._warm_for_tier` | 峰值 Gemma4 4.6+VL 10.8=15.4GB；<4GB 仅 fast；4-10GB Gemma4 检查；10-14GB 顺序；≥14GB 常驻 | ✅ 完成 |
| **C3.3** | **gemma_only 视觉纠错**：`gate/gemma_vision_correct.py`（`GemmaVisionCorrect`）——派生角色 character + `Pic2Str` 整图读图（同形 JSON）+ 逐单元 `_pick_better` 择优合并（保结构）；`main.PaddleOcr` 的 `gemma_only` 分支接线；`MSG_GEMMA_VISION`。幻觉可接受（角色约束）。见 §3.2a「gemma_only 视觉纠错（C3.3）」 | 纯文本纠错验证效率≈0（已删 C3.1）；新方案整图 Pic2Str 避开单元→bbox 映射阻塞 | ✅ 完成 |
| **E** | **NiceGUI 一次调用 `PaddleOcr`（双模式回填）**：整表识别走 GHOST 模式回填全量 JSON 并通过 blur 分拆；单字段/覆盖录入走 FIELD 模式自动组合纯文本并回填单格。 | C2/C3.1 + S0；**无**重新识别按钮 | ✅ 完成 |

### C3.1 实施清单（本轮）

1. **`gate/hardware_probe.py`**：`detect_gpu_hardware()`（nvidia-smi -L）/ `detect_npu_hardware()`（OpenVINO Core.available_devices）/ `paddle_is_cuda()`（importlib.metadata 查 paddlepaddle-gpu）/ `detect_accelerator()`→gpu/npu/cpu / `AcceleratorAvailable()`（GPU 硬件 + paddlepaddle-gpu）/ `VlBackendKind()` / `ResetHardwareCache()`。
2. **`engines/paddle_vl/backend.py` 重构**：删除 CPU PaddleOCRVL 路径；`_ensure_engine` 仅 `AcceleratorAvailable` 时构造 `PaddleOCRVL(device="gpu")`，否则 `init_error="no_accelerator"` 不构造；`Run` 无加速器直接返回 `ok=false`。
3. **`gate/gemma_correct.py`**：`GemmaCorrectUnits(fast)` 逐单元 `run_judgment`，`affirmative` 的单元 `ConversationOnce`（纠错系统提示）改字，写回 `string*`/`table*:rowN`（cells 数一致才替换），返回 `mode="gemma_corrected"` `MSG_GEMMA_CORRECTED`。
4. **`gate/semantic_gate.py` 重构**：`ShouldTryVl` 加 `AcceleratorAvailable()` 前置；新增 `ShouldTryGemmaCorrection`（`RefinePathEnabled` + **非**`AcceleratorAvailable` + `HasOcrSemanticProblem`）。
5. **`main.PaddleOcr` 分支重构**：fast `ok=false`→返回；`ShouldTryVl`→`LlmRefine`（GPU）；`ShouldTryGemmaCorrection`→`GemmaCorrectUnits`；否则 fast。`EnsureModels` 用 `detect_accelerator()` 决定 VL 模型去留（有加速器硬件则保留，纯 CPU 则 prune）；`main()` 检测到 GPU 硬件但未装 GPU paddle 时提示跑 `install_backend.py`，本次走 CPU-only Gemma4 纠错。
6. **`scripts/install_backend.py` + `_warm_vl_gpu.py`**：探测硬件；GPU→`pip uninstall paddlepaddle` + `pip install paddlepaddle-gpu==3.3.1 -i …/cu129/` → 全新子进程 `_warm_vl_gpu.py` 构造 `PaddleOCRVL(device=gpu)` 触发 VL 模型下载；CPU→prune VL 模型；NPU→stub（未来 OpenVINO）。不能在已 import paddle 的进程内热替换库。
7. **`models_catalog.py` + `download_models.py` 重构**：VL 模型按 `detect_accelerator()` 去留；`_warm_vl` 仅 `AcceleratorAvailable` 时暖机。
8. **`config.py`**：新增 `MSG_GEMMA_CORRECTED`；`DEFAULT_VL_PIPELINE_VERSION="v1.6"`；catalog VL 名修为 `PaddleOCR-VL-1.6`（去掉错误的 `-0.9B` 后缀）。
9. **测试**：`test_paddlevl_gemma_e2e.py` 加 `AcceleratorAvailable` skip（无加速器不跑 VL）；新增 CPU-only Gemma4 纠错路径单测（mock `AcceleratorAvailable=false`，断言 `mode="gemma_corrected"`、VL 未构造）。

### C3.2 实施清单（本轮）

1. **`config.py`**：阈值改 4 档——`REFINE_MIN_RAM_GB=4` / `REFINE_VL_MIN_GB=10` / `REFINE_BOTH_RESIDENT_MIN_GB=15`（C3.3 后改 14，定在实测峰值之下：Gemma4 4.6GB / VL 10.8GB / 合计 15.4GB，Paddle-VL/LiteRT 会往内存倒垃圾/复用故实际需求略低；替换旧 `REFINE_MIN_AVAILABLE_RAM_GB=7`）。
2. **`gate/memory_guard.py` 重构**：`measure_available_vram_gb()`（`nvidia-smi --query-gpu=memory.free`）/ `available_budget_gb()`=max(RAM,VRAM) / `init_refine_path()` 测一次预算并缓存 / `RefineTier()`→none/gemma_only/sequential/both_resident（10GB+ 档需 `_hw.AcceleratorAvailable()`，否则降级 gemma_only）/ `RefinePathEnabled()`=`tier!="none"` / `ResetRefinePathCache()`。通过 `import paddle_ocr.gate.hardware_probe as _hw` 模块级访问以便测试 monkeypatch。
3. **`main.PaddleOcr` 分档分支**：fast `ok=false`→返回；`tier=none`→返回 fast；`HasOcrSemanticProblem` false→返回 fast；true：`gemma_only`→`GemmaCorrectUnits`（C3.3 后改为 `GemmaVisionCorrect`）；`sequential`→`_unload_gemma4()`（`ResetBackend`）→`LlmRefine`；`both_resident`→`LlmRefine`（VL 已热）。VL 失败→fast + `MSG_LLM_PARTIAL`。
4. **`main._warm_for_tier` + `main()`**：启动按档预热——`none`→不预热；`gemma_only`/`sequential`→`StartGemma()`；`both_resident`→`StartGemma()` + **异步线程** `GetVlBackend().warm()`（不阻塞 CLI）；`sequential` 的 VL 按需在 `PaddleOcr` 内卸载 Gemma4 后加载。`main()` 打印 `RefineTier()` 档位。
5. **`engines/paddle_vl/backend.py`**：`AcceleratorAvailable` 改模块级访问（`import ... as _hw`）以便测试 monkeypatch。
6. **测试重构**：`test_cpu_only_gemma_correct.py` 改 mock `RefineTier`（none/gemma_only/gemma_only-无问题 + VL 无加速器不构造）；`test_paddlevl_gemma_e2e.py` 改 a-e 顺序流：(a) pp-ocr 一句话 (b) pp-structure JSON (c) Gemma4 判定+纠错+输出 (d) 卸载 Gemma4+加载 VL (e) VL 全面重算+输出。

### C3.3 实施清单（本轮已完成）

**前置清理**（早于本轮）：删除 `gate/gemma_correct.py`（C3.1 纯文本纠错）、`ShouldTryGemmaCorrection` 死代码、`MSG_GEMMA_CORRECTED`；`main.PaddleOcr` 的 `gemma_only` 分支曾临时占位 `return fast`。

**本轮实施**（C3.3 视觉纠错）：

1. **`paddle_ocr/config.py`**：阈值 `REFINE_BOTH_RESIDENT_MIN_GB=14`（4/10/14，原 15 改 14：Gemma4 4GB + VL <10GB → 14GB 即可同时驻留）；新增 `MSG_GEMMA_VISION="识别完成（Gemma4 视觉纠错）。"`。
2. **`gate/gemma_vision_correct.py` 新增**：`_derive_character(fast)`（ConversationOnce 派生角色）/ `_encode_cropped_jpg(pic, rectangle)`（jpg 字节）/ `_build_pic_prompt(fast)`（同形 JSON 要求）/ `_parse_gemma_json(text)`（宽容解析）/ `_pick_better(fast, gemma, character)`（A/B 文本裁判，歧义保守保留 fast）/ `GemmaVisionCorrect(pic, rectangle, fast)`（主流程：派生角色→Pic2Str 整图读图→逐单元择优合并→`mode="gemma_vision_corrected"`，保结构）。
3. **`main.PaddleOcr`**：`gemma_only` 分支改为 `GemmaVisionCorrect(pic, rectangle, fast)`；异常回退 fast + `MSG_LLM_PARTIAL`。docstring 同步。
4. **幻觉策略**：接受 Pic2Str 幻觉（fast 错字本不可读，视觉犯错人类也会犯）；角色 character 是约束再创造的关键；逐单元择优只在 gemma 更顺时替换，不动好单元。
5. 本文档：全篇 `gemma_only` 纠错相关描述改为「C3.3 视觉纠错」，§3.2a 重写为已实施方案。

**遗留 / 可选后续**：

- 单元→bbox 映射（`runtime/postprocess.py` 的 `StructureResultToJson` 不回传 bbox）：C3.3 用「整图 Pic2Str + 同形 JSON 对齐」绕开了该阻塞，**无需**解决；若未来想改"只对有问题单元裁图 Pic2Str"再补。
- 金样比对准确率验证：C3.3 接受幻觉策略，验证重心从"Pic2Str 绝对精度"转为"逐单元择优是否不比 fast 更差"，可在 e2e 测试里肉眼对比纠错前后。

---

## 9. 边界

| 操作 | 模块 |
|------|------|
| 拍照 | `core_store` |
| OCR（含 fast / Gemma / PaddleVL） | `PaddleOcr` |
| 写回 DB | `core_store.update_image_ocr`（UI 可选） |
| 导出附图 | `core_transform` |

---

## 10. 后续

- Gemma 门禁 prompt / 判例集回归（与 `test/ocr_sample.jpg` 金样对齐）
- GPU / 异步队列 / 多语言包

---

## 附录 A：时序

```
用户 → 菜单「OCR」（仅一次）
    → 取图 + 框选
    → PaddleOcr(pic, rectangle)
         → fast（PPStructure / 字段 OCR）
         → RefinePathEnabled? → HasOcrSemanticProblem（Gemma 4）
         → 若语义有问题 → PaddleOCRVL 精修（自动，无第二次点击）
         → 否则 → 直接 fast 结果
    → UI 用 JSON 回填 / notify(message)
```

## 附录 B：结论

| 项 | 结论 |
|----|------|
| **主端口** | **`PaddleOcr`**：单图 → 结构 JSON；**内含无 HealthCheck** |
| 批量端口 | **`PaddleOcrTasks`**：多 `(pic, rectangle)` 串行打包 |
| 辅助 API | **`HealthCheck`**：仅 CLI / install |
| CLI | **`main()`** = HealthCheck → 自动 download → 样图 `PaddleOcr` 一次 |
| UI | 只调 **`PaddleOcr`** 一次；**无**「重新识别」 |
| 主路径 | fast = 网格路由 → PPStructureV3 或字段 PP-OCR |
| 精修门禁 | Gemma 4 `HasOcrSemanticProblem`；**非**「是否为空」；**需** `RefinePathEnabled` |
| 精修引擎 | PaddleOCR-VL；坏图/未安装/低内存不进 VL |
| 内存 | OCR 启用时测可用 RAM+VRAM；`RefineTier()` 分 4 档（4/10/14GB） |
| 并发 | 单例 + 串行锁，任务排队处置 |
| 输出 | `string*` + `table*` + 可选 `mode` |
