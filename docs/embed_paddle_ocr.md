# PaddleOCR · 嵌入运行时规格

> 状态：plan v1.4（**仅** `paddle_ocr/` 平台：CLI、统一 API、模型与安装；**不含** NiceGUI 实现；**不在此轮写 C2 代码**）  
> 日期：2026-07-09  
> 存储层：[`db_store.md`](db_store.md)（拍照落库、`input_label` 关联；**须先定稿并实现 `save_image`，再接 UI**）  
> 导出层：[`excel_transform.md`](excel_transform.md)（按需附图到 sheet）  
> 上游参考：[PaddlePaddle/PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)（**3.x**；主路径 **PPStructureV3**）  
> LLM：项目内 Gemma 流水线（见 [`embed_gemma4.md`](embed_gemma4.md)）；由本平台在 fast 失败时**自动**调用，**无** UI「重新识别」按钮

---

## 0. 本文档是什么

| 文档 | 回答的问题 |
|------|------------|
| **本文件** | `paddle_ocr/` 怎么装、怎么调 `PaddleOcr(pic, rectangle)`、fast→LLM、模型放哪、CLI 怎么验 |
| [`db_store.md`](db_store.md) | 拍照怎么落盘、`input_label` 怎么关联、OCR 结果是否写回 store |
| [`nicegui_ui/nicegui_ui_plan.md`](nicegui_ui/nicegui_ui_plan.md) | 右键/长按菜单怎么编排、何时调本平台 / `core_store` |
| [`excel_transform.md`](excel_transform.md) | 用户要求时如何把已存图片附着到 Excel sheet |

**`paddle_ocr` 平台自身不带 UI。** NiceGUI **只调用一次** `PaddleOcr(...)`；不提供、不需要「重新识别」类菜单项。fast / LLM 切换全部在函数内部完成。

**命名**：对外公开函数用 **CapitalCase**（如 `PaddleOcr`、`HealthCheck`）。包目录仍为 `paddle_ocr/`。

**不在本文件**：SQLite DDL 全文、Excel 坐标、NiceGUI 线框。  
**不在本期写代码**：阶段 C2 实现（本文只定契约）。

### 0.1 与 `core_store` 的实施顺序

| 顺序 | 工作 | 说明 |
|------|------|------|
| 1 | 定稿并实现 [`db_store.md`](db_store.md) 存图 API | 存图尚未就绪 |
| 2 | 实现本文件 `paddle_ocr/`（含 `PaddleOcr` + fast/LLM） | 零 SQLite |
| 3 | NiceGUI 菜单 | 拍照 → store；OCR → **一次** `PaddleOcr`；可选写回 store |

---

## 1. 定位与目标

### 1.1 职责

| 负责 | 不负责 |
|------|--------|
| 统一 API：`PaddleOcr(pic, rectangle)` | 输入框菜单、相机 UI、框选 UI、**任何「重新识别」交互** |
| 自动探测图片格式 | SQLite / `core_store` |
| fast（PPStructureV3）→ 失败则自动 LLM | HTTP / NiceGUI 页面 |
| 模型下载与本地缓存 | Excel 落图 |
| CLI：`probe` / `download` / `smoke` / `bench` | 让 UI 选择 fast/LLM |

### 1.2 分工

```
nicegui_ui                 paddle_ocr/                 app/core_store
──────────                 ───────────                 ──────────────
右键菜单、相机、框选         PaddleOcr()                 save_image()
一次调用、按 JSON 回填       HealthCheck()               update_image_ocr()
ui.notify(message)         内部：fast → (fail) → LLM
```

| 菜单项 | UI 行为 | 本平台 |
|--------|---------|--------|
| **拍照** | → `core_store.save_image` | 不参与 |
| **OCR** | 取图 → 框选 → **`PaddleOcr(pic, rectangle)` 一次** → 回填 | 内部自行 fast/LLM |

**禁止**：UI 增加「重新识别 / 精细识别 / 再用 LLM」等二次入口。用户只点一次 OCR。

### 1.3 设计原则

1. 平台零外溢：逻辑与模型在 `paddle_ocr/`。
2. UI 只调 **`PaddleOcr`**（CapitalCase 公开 API）。
3. 存图归 store；OCR 默认可不落库。
4. 对人只暴露 `ok` + 中文 `message`。
5. 输出为引擎/LLM 原文 JSON；业务字段映射由 UI/其它模块做。
6. **fast 优先，失败才 LLM**；对 UI 透明（可选返回 `mode` 供日志，非交互）。

---

## 2. 平台包布局

```
paddle_ocr/
  main.py                  # PaddleOcr / HealthCheck + CLI
  config.py
  models_catalog.py
  requirements.txt         # paddle + paddleocr + paddlex[ocr] + pillow-heif
  models/                  # OCR/structure 权重（gitignored）
  models/llm/              # 可选：本平台侧 LLM 适配缓存（与 Gemma 权重策略见 embed_gemma4）
  runtime/
    structure_backend.py   # fast：PPStructureV3
    llm_refine.py          # LLM 模式：校正/补全 JSON（调项目 LLM，不造第二套 UI）
    ocr_backend.py         # 可选字段级调试
    image_decode.py
    postprocess.py         # → stringN / tableN
  scripts/
    download_models.py
    smoke_test.py
```

---

## 3. 统一 API：`PaddleOcr(pic, rectangle)`

### 3.1 签名

```python
def PaddleOcr(
    pic: bytes | Path | str,
    rectangle: tuple[int, int, int, int] | None = None,
) -> dict: ...

def HealthCheck() -> dict: ...
```

| 参数 | 含义 |
|------|------|
| `pic` | 原图；**不传格式**；自动探测 JPEG/PNG/HEIC 等 |
| `rectangle` | OpenCV `(x, y, w, h)`；`None` = 整图 |

### 3.2 内部两段式（对 UI 不可见）

```
PaddleOcr(pic, rectangle)
  → 解码 + 裁剪
  → [fast] PPStructureV3 → 映射 string*/table*
  → 若判定 fast 失败 → [llm] 用裁剪图 + fast 草稿（若有）→ 同形 JSON
  → 返回统一 JSON（可含 mode: "fast"|"llm"）
```

**无 UI 二次点击。** NiceGUI 一次调用等最终结果即可（可显示 loading）。

#### fast 失败门禁（自动进入 LLM；实施时钉死）

| 条件 | 进 LLM？ |
|------|----------|
| 解码/选区非法 | **否**（直接 `ok=false`，LLM 救不了坏图） |
| 引擎未安装 / 模型缺失 | **否**（`ok=false`，中文提示装环境） |
| fast 推理抛错 | **是**（若 LLM 可用） |
| fast `ok` 但无任何 `string*` 且无任何 `table*` 行 | **是** |
| fast 有表/字符串 | **否**（即使手写有错字也不自动 LLM，避免每次都慢） |

> 手写错字**不**单独触发 LLM（否则几乎张张表都跑 LLM）。若产品以后要「低置信度也进 LLM」，另开配置项，默认关。

#### LLM 模式职责

- 输入：裁剪后图像 +（可选）fast 草稿 JSON。
- 输出：**同一** §3.3 JSON 形状。
- 实现：调用项目已有 LLM 能力（Gemma 等，见 `embed_gemma4.md`）；细节在 `runtime/llm_refine.py`，**不**在 NiceGUI 里分支。
- LLM 也失败：若有可用的 fast 草稿则返回草稿并 `message` 说明未精修；否则 `ok=false`。

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

**Spike（2026-07-09）**：fast（PPStructureV3）全图可得到标题 + 4 行表 + 脚注形状。手写格仍可能错；默认不因此自动 LLM。

### 3.4 裁剪与格式

- OpenCV `(x,y,w,h)`；平台内裁剪；contiguous BGR。
- 格式自动探测；HEIC → `pillow-heif`。

### 3.5 引擎

| 模式 | 引擎 |
|------|------|
| fast | PPStructureV3（`paddlex[ocr]`） |
| llm | 项目 LLM（Gemma 等）校正/补全同形 JSON |

### 3.6 并发

单例 + 串行锁（含 LLM 段，避免双通道打满）。

---

## 4. `main.py` 门面

### 4.1 CLI

| 命令 | 作用 |
|------|------|
| `probe` | 环境 / HealthCheck |
| `download` | structure（+ 所需）权重 |
| `smoke` | `PaddleOcr(sample, None)`：须有 `string1` 与 `table1`（允许 `mode=fast`） |
| `bench` | 可选 |

### 4.2 程序化

```python
from paddle_ocr.main import PaddleOcr, HealthCheck

result = PaddleOcr(pic_bytes, rectangle=None)
if not result["ok"]:
    ui.notify(result["message"])
# UI 不根据 mode 再调一次；不提供「重新识别」
```

### 4.3 UI 契约

| API | 输入 | 输出 |
|-----|------|------|
| `PaddleOcr` | `pic`；`rectangle` | §3.3 JSON |
| `HealthCheck` | — | 中文就绪 |

| 菜单 | 调用 |
|------|------|
| 拍照 | `core_store.save_image` |
| OCR | **仅** `PaddleOcr(pic, rectangle)` |

---

## 5. 中文 message（示例）

| 场景 | `ok` | `message` |
|------|------|-----------|
| fast 或 llm 成功 | `true` | 识别完成。 |
| 成功但无内容 | `true` | 未识别到文字，请调整选区或重新拍照。 |
| 坏图 / 坏选区 | `false` | 无法读取图片… / 选区无效… |
| 组件未就绪 | `false` | OCR 组件未就绪… |
| 模型缺失 | `false` | OCR 模型未就绪… |
| LLM 不可用且 fast 已失败 | `false` | 文字识别失败，请稍后重试。 |

---

## 6. 安装

默认装；`--skip-ocr` 可跳过。`requirements` 含 `paddlex[ocr]`。磁盘约 1GB+（structure）。`enable_mkldnn=False`。

LLM 依赖跟项目 Gemma/install 既有链路，不在 OCR skip 开关里单独再做一个「跳过 LLM」除非产品要求。

---

## 7. 测试要点

- `PaddleOcr(sample, None)` → `ok`；`string1`；`table1`。
- 坏图 / 非法 rectangle → `ok=false`，**不**进 LLM。
- 模拟 fast 空结果 → 若 LLM 可用则 `mode=llm` 或明确失败 message。
- 无「二次识别」API 测试（不存在该入口）。
- 并发串行。

---

## 8. 分阶段（计划；**本轮不写 C2 代码**）

| 阶段 | 交付物 | 门禁 |
|------|--------|------|
| S0 | store 存图 | `save_image` 可测 |
| A–C | field 骨架（历史） | probe / 旧 smoke |
| C2 | `PaddleOcr` + structure JSON + download/smoke | 结构 smoke |
| C3 | fast 失败门禁 + `llm_refine` | 空结果自动 LLM 可测 |
| E | NiceGUI **一次**调用 `PaddleOcr` | C2/C3 + S0；**无**重新识别按钮 |

---

## 9. 边界

| 操作 | 模块 |
|------|------|
| 拍照 | `core_store` |
| OCR（含 fast/LLM） | `PaddleOcr` |
| 写回 DB | `core_store.update_image_ocr`（UI 可选） |
| 导出附图 | `core_transform` |

---

## 10. 后续

- 可选：低置信度也进 LLM（默认关）
- GPU / 异步队列 / 多语言包

---

## 附录 A：时序

```
用户 → 菜单「OCR」（仅一次）
    → 取图 + 框选
    → PaddleOcr(pic, rectangle)
         → fast (PPStructureV3)
         → 若门禁失败 → LLM 精修（自动，无第二次点击）
    → UI 用 JSON 回填 / notify(message)
```

## 附录 B：结论

| 项 | 结论 |
|----|------|
| 公开 API 名 | **`PaddleOcr`**、**`HealthCheck`**（CapitalCase） |
| UI | 只调一次；**无**「重新识别」 |
| 主路径 | fast = PPStructureV3 |
| 回退 | 自动 LLM；坏图/未安装不进 LLM |
| 输出 | `string*` + `table*` + 可选 `mode` |
