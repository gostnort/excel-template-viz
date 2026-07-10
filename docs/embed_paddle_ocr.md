# PaddleOCR · 嵌入运行时规格

> 状态：plan v1.7（**仅** `paddle_ocr/` 平台：统一 API、CLI、模型与安装；**不含** NiceGUI 实现）  
> 日期：2026-07-10  
> 存储层：[`db_store.md`](db_store.md)（拍照落库、`input_label` 关联；**须先定稿并实现 `save_image`，再接 UI**）  
> 导出层：[`excel_transform.md`](excel_transform.md)（按需附图到 sheet）  
> 上游参考：[PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)（**3.x**；主路径 **PPStructureV3**）  
> **精修门禁**：[`embed_gemma4.md`](embed_gemma4.md) 的 Gemma 4 判定 fast 结果是否存在**语义问题**；仅当判为有问题时**自动**调用 PaddleOCR-VL 精修。**可用内存 < 7GB 时整段精修路径（Gemma + PaddleVL）在启动时关闭**（见 §3.8）。

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | `paddle_ocr/` 怎么装、**`PaddleOcr(pic, rectangle)`**（图进 → 结构 JSON 出）、fast→Gemma 语义门禁→PaddleVL、**7GB 内存门禁**、串行任务、CLI `main()` 门禁 |
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
9. **内存不足则降级**：项目启用 OCR 时**启动即测**可用内存；**< 7GB** 时**不加载、不调用** Gemma 语义门禁与 PaddleVL，仅保留 fast 路径（§3.8）。

---

## 2. 平台包布局

```
paddle_ocr/
  main.py                  # PaddleOcr / PaddleOcrTasks / HealthCheck + main() CLI
  config.py                # OCR 开关、内存阈值、RefinePathEnabled 缓存
  models_catalog.py
  requirements.txt         # paddle + paddleocr + paddlex[ocr] + pillow-heif
  models/                  # OCR/structure 权重（gitignored）
  models/llm/              # 可选：本平台侧 LLM 适配缓存（与 Gemma 权重策略见 embed_gemma4）
  runtime/
    structure_backend.py   # fast：PPStructureV3 / 字段 PP-OCR（网格路由）
    semantic_gate.py       # Gemma 4：HasOcrSemanticProblem(fast_json) → bool
    memory_guard.py        # 启动时测可用内存；RefinePathEnabled()
    llm_refine.py          # VL 精修：PaddleOCRVL（Paddle 自有 VL 权重）
    table_grid.py          # OpenCV HasTableGrid → fast 路由
    field_backend.py       # 无网格裁剪 → mobile PP-OCR
    image_decode.py
    postprocess.py         # → stringN / tableN
  scripts/
    download_models.py     # 拉取/暖机 structure 权重（CLI 在缺模型时调用）
```

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
  → 若 RefinePathEnabled() → HasOcrSemanticProblem(fast_json)   # Gemma 4
  → 若存在语义问题 → [vl] PaddleOCRVL（裁剪图 + fast 草稿）→ 同形 JSON
  → 否则直接返回 fast
  → 返回统一 JSON（可含 mode: "fast"|"llm"）
```

**无 HealthCheck 步骤。** **无 UI 二次点击。** NiceGUI 一次调用等最终结果即可（可显示 loading）。

#### Gemma 语义门禁（是否调用 PaddleVL；实施时钉死）

**前置**：`RefinePathEnabled()` 为 `false`（可用内存 < 7GB，见 §3.8）时，**整段跳过**本门禁与 PaddleVL；`ShouldTryVl` 恒为 `false`。

```python
# paddle_ocr/runtime/semantic_gate.py
def HasOcrSemanticProblem(fast_result: dict) -> bool: ...
```

**`ShouldTryVl(fast)`** = `RefinePathEnabled()` **且** `HasOcrSemanticProblem(fast)`（`runtime/semantic_gate.py`）。
应用层通过 [`llm_gemma4`](embed_gemma4.md) §3.6 `run_judgment` 调用底座：由 `semantic_gate` 组 OCR 专用 `JudgmentSpec`（fast 草稿 JSON：`string*` / `table*` / `message`），底座返回 `JudgmentResult` 三态，再由 **`_ocr_semantic_to_bool`（应用层单独函数）** 映射为是否调 PaddleVL。**禁止**在 `llm_gemma4` 内写 OCR 逻辑；**禁止**直接读裸 `generate` 文本当最终判定；**禁止**用 `HasContent`（是否为空）代替语义判定。

| 条件 | 调 PaddleVL？ |
|------|----------------|
| **可用内存 < 7GB**（OCR 启用时启动已判定，`RefinePathEnabled=false`） | **否**（**不**调 Gemma、**不**调 PaddleVL；仅 fast；含 fast 推理抛错亦不进 VL） |
| 解码/选区非法 | **否**（直接 `ok=false`，VL 救不了坏图） |
| fast 引擎未安装 / 模型缺失 | **否**（`ok=false`，中文提示装环境） |
| Gemma 未安装 / 不可用 | **否**（返回 fast 结果；`message` 可注明未做语义复核） |
| fast 推理抛错 | **是**（草稿不可信，视为语义问题；**仅当** `RefinePathEnabled` 且 VL 可用） |
| Gemma 返回 `semantic_problem: true` | **是**（含：结构错乱、表头与值不符、明显乱码、应有版面却近乎全空等） |
| Gemma 返回 `semantic_problem: false` | **否**（**即使** fast 有 `string*`/`table*` 也直接返回 fast；个别手写错字但整表自洽时典型为 false） |
| fast 无 `string*`/`table*` 但 Gemma 认为选区本就没有可读语义 | **否**（`ok=true`，`message` 提示调整选区；**不**因「空」自动 VL） |

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

#### PaddleVL 精修职责

- **触发**：仅当上表允许且 `HasOcrSemanticProblem` 为 `true`（或 fast 推理抛错）。
- **输入**：裁剪后图像 +（可选）fast 草稿 JSON。
- **输出**：**同一** §3.3 JSON 形状；`mode: "llm"`。
- **实现**：**PaddleOCR 自有** `PaddleOCRVL`（默认 `v1.6` / `PaddleOCR-VL-1.6` 权重，走 `PADDLE_PDX_CACHE_HOME`）；细节在 `runtime/llm_refine.py`。**Gemma 只做门禁，不做 VL 推理**；NiceGUI 不分支。
- VL 也失败：若有可用的 fast 草稿则返回草稿并 `message` 说明未精修；否则 `ok=false`。

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
- 格式自动探测；HEIC → `pillow-heif`。
- **检测缩放**：`text_det_limit_type=max`（**禁止放大**）。有 `rectangle` 时按裁剪图 **原始长边** 做检测（`limit_side_len=max(h,w)`）。整图才用 `960` 做超长边缩小。
- **路由（裁剪图）**：`HasTableGrid`（OpenCV 横竖线网格启发式）→ **无网格** → mobile 字段 `PaddleOCR`；**有网格（可缺角）** → `PPStructureV3`。整图（`rectangle=None`）始终走 Structure。

### 3.5 引擎

| 阶段 | 引擎 | 说明 |
|------|------|------|
| fast（无网格裁剪） | mobile `PaddleOCR` | `field_backend.py` |
| fast（有网格 / 整图） | PPStructureV3 | `structure_backend.py` |
| 语义门禁 | Gemma 4 E4B（LiteRT） | `semantic_gate.py` → `llm_gemma4` |
| vl 精修 | PaddleOCR-VL（`PaddleOCRVL`） | `llm_refine.py`；**需** `RefinePathEnabled` |

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
# paddle_ocr/runtime/memory_guard.py
REFINE_MIN_AVAILABLE_RAM_GB = 7

def measure_available_ram_gb() -> float: ...   # 如 psutil.virtual_memory().available

def RefinePathEnabled() -> bool:
    """进程内单例；OCR 启用时 init 一次：available >= 7GB → True。"""
```

| 可用内存（启动时） | `RefinePathEnabled` | Gemma 语义门禁 | PaddleVL |
|--------------------|---------------------|----------------|----------|
| **≥ 7 GB** | `true` | 按 §3.2 表执行 | 按门禁执行 |
| **< 7 GB** | `false` | **跳过**（不加载 Gemma  backend） | **跳过**（不初始化 `PaddleOCRVL`） |

- **可用内存**：操作系统报告的**剩余可分配**物理内存（非总装容量）。实现推荐 `psutil`；Windows / Linux 一致用 `available` 字段。
- **7 GB**：硬编码默认阈值（`REFINE_MIN_AVAILABLE_RAM_GB`）；精修路径专用，与 fast 无关。
- **对用户透明**：`PaddleOcr` 仍一次调用；低内存时恒为 `mode=fast`。日志可打 `refine_disabled=low_memory`；**不必**单独弹窗，除非调试。

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

**内存**：启用 OCR 时启动测量可用 RAM；**< 7GB** 时不装/不暖机 Gemma 与 VL 精修路径（`RefinePathEnabled=false`），仅 fast。`requirements` 可仍含 `psutil`（与 `llm_gemma4` 探测共用）。OCR `--skip-ocr` 时整段 OCR 含内存探测均跳过。

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

---

## 8. 分阶段（计划；**本轮不写 C2 代码**）

| 阶段 | 交付物 | 门禁 |
|------|--------|------|
| S0 | store 存图 | `save_image` 可测 |
| C2 | `PaddleOcr` 图进 JSON 出 + `main()` CLI | `main()` 三步全绿 |
| C3 | `semantic_gate` + `memory_guard` + `llm_refine` | ≥7GB 时 Gemma 判有问题才 VL；<7GB 仅 fast |
| E | NiceGUI **一次**调用 `PaddleOcr` | C2/C3 + S0；**无**重新识别按钮 |

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
| 内存 | OCR 启用时测可用 RAM；**< 7GB** → 屏蔽 Gemma + PaddleVL |
| 并发 | 单例 + 串行锁，任务排队处置 |
| 输出 | `string*` + `table*` + 可选 `mode` |
