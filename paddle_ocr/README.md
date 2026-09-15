# paddle_ocr

独立 OCR / 版面 / PDF 平台。不依赖 NiceGUI、SQLite、Excel 模板。外部程序只需本仓库的 Python 环境（`ocr` 或 `ocr-gpu` extra）即可 `import paddle_ocr`。

设计规格（内存分档、JSON 字段约定）：[`docs/embed_paddle_ocr.md`](../docs/embed_paddle_ocr.md)。

## 它不是 Cursor MCP 配置项

本目录里的 MCP 是 **paddleocr-mcp**（PaddleOCR 官方 MCP 服务器），由本平台用 **HTTP 子进程** 拉起，再通过 FastMCP Client 调工具。默认 **不会** 写进 Cursor 的 `mcp.json`。

| 模型（`--model`） | MCP 工具名 | 用途 |
| --- | --- | --- |
| `PP-OCRv6` | `ocr` | 图/PDF 文字检测与识别 |
| `PP-StructureV3` | `pp_structurev3` | 版面解析，产出 Markdown |

本平台 **不安装、不下载 PaddleOCR-VL**。CPU 上 `enable_mkldnn=False`（见 `mcp_entry.py`）。

进程入口永远走本仓库包装，不要直接调系统 PATH 上的 `paddleocr_mcp`（包装会设模型缓存、关 MKLDNN）：

```text
python -m paddle_ocr.mcp_entry
```

等价于官方 CLI，额外补了本机缓存与 CPU 补丁。

---

## 安装 paddleocr-mcp

在**仓库根目录**操作。Python `>=3.10,<3.12`。`ocr` 与 `ocr-gpu` **不可同装**。

### 1. 推荐：安装向导

```bat
install.bat
```

默认会装 OCR extra。跳过 OCR：`install.bat --skip-ocr`。强制 GPU：`install.bat --gpu`。

向导写入 `bootup/.install_profile`，之后请用 `.\uv_run.ps1` 跑命令，否则 `uv run --project bootup` 不带 extra 会把 OCR 包从 `bootup/.venv` 卸掉。

### 2. 手动 uv

CPU（含 `paddleocr-mcp[local-cpu]` + `pypdfium2`）：

```bat
uv sync --project bootup --extra ocr
```

GPU（`paddleocr-mcp[local]` + `paddlepaddle-gpu==3.3.1`，CUDA 12.9 源）：

```bat
uv sync --project bootup --extra ocr-gpu
```

已装 CPU paddle、要换成 GPU：

```bat
.\uv_run.ps1 python paddle_ocr/scripts/install_backend.py gpu
```

强制 CPU、清掉旧 VL 权重：

```bat
.\uv_run.ps1 python paddle_ocr/scripts/install_backend.py cpu
```

### 3. 门禁：下载模型并试跑

权重落到 `paddle_ocr/models/`（环境变量 `PADDLE_PDX_CACHE_HOME`）。首次推理会再拉 Structure 其余权重，可能较慢。

```bat
.\uv_run.ps1 python paddle_ocr/main.py
```

顺序：硬件探测 → `EnsureModels()`（缺则下载，并 prune VL）→ 对 `test/ocr_sample.jpg` 跑一次 `PaddleOcr`。退出码 0 表示 MCP 包与 fast 模型可用。

设备：环境变量 `OCR_PROFILE=cpu` 或 `gpu`；未设时有 GPU 包 + 能加载 `cudnn64_9.dll` 才用 gpu。

### 4. 本平台如何启动 MCP（默认，给 Python API 用）

调用 `PaddleOcr` / `PpStructure` / `PaddleOcr_PDF2MDs`（图片页）时会 **懒启动** 子进程，无需先开服务器。

命令形态（端口空闲时优先 18081 / 18082，被占则在 10000–65535 另选；避开 8000 与 9999）：

```text
python -m paddle_ocr.mcp_entry --http --host 127.0.0.1 --port 18081 --model PP-OCRv6 --ppocr_source local --device cpu
python -m paddle_ocr.mcp_entry --http --host 127.0.0.1 --port 18082 --model PP-StructureV3 --ppocr_source local --device cpu
```

- OCR 槽：`PaddleOcr` 返回后 **不停**。
- Structure 槽：`PpStructure` 返回后不停；`run_ocr_job` 与 `PaddleOcr_PDF2MDs` 在任务 `finally` 里 `stop_structure_mcp`。
- 日志：`temp/paddleocr_mcp_ocr.log`、`temp/paddleocr_mcp_structure.log`。
- Streamable HTTP 地址：`http://127.0.0.1:<port>/mcp`。

工具入参（本仓库实际发送）：

- `ocr`：`input_data` = 本地 jpg 路径，`file_type=image`，`output_mode=detailed`。
- `pp_structurev3`：同样 jpg 路径，`output_mode=simple`，`return_images=false`。图进 JSON 的路径会再把 Markdown **拆成** `string*` / `table*`；PDF2MD 的图片页保留 Markdown 原文。

### 5. 可选：把 MCP 接到 Cursor / Claude（stdio）

仅当你要在对话里直接调工具。每个 MCP 进程只能挂一个 `--model`，需要 OCR 与 Structure 就配两个服务器。把 `python.exe` 换成 `bootup/.venv\Scripts\python.exe` 的绝对路径。

```json
{
  "mcpServers": {
    "paddleocr-ocr": {
      "command": "E:/my_github/excel-template-viz/bootup/.venv/Scripts/python.exe",
      "args": [
        "-m", "paddle_ocr.mcp_entry",
        "--model", "PP-OCRv6",
        "--ppocr_source", "local"
      ]
    },
    "paddleocr-structure": {
      "command": "E:/my_github/excel-template-viz/bootup/.venv/Scripts/python.exe",
      "args": [
        "-m", "paddle_ocr.mcp_entry",
        "--model", "PP-StructureV3",
        "--ppocr_source", "local"
      ]
    }
  }
}
```

本地推理下：不要喂 Base64 PDF；本地文件路径不要传 `file_type`（`file_type` 只在 URL 时必填）。PDF → 每页 Markdown 请用下面的 `PaddleOcr_PDF2MDs`，不要把整本 PDF 一次性丢给 Cursor 里的工具。

---

## 运行约定

仓库根须在 `sys.path` 上。用包装器：

```bat
.\uv_run.ps1 python -c "from paddle_ocr import PaddleOcr"
```

或：

```bat
.\uv_run.ps1 python paddle_ocr/main.py
.\uv_run.ps1 python -m paddle_ocr.pdf2md --input D:\a.pdf
```

公开符号从 `paddle_ocr` 导入。图片入参 `pic`：`bytes` / `pathlib.Path` / `str` 路径。`rectangle`：OpenCV `(x, y, w, h)`，`None` 表示整图。

图进接口返回 JSON：`ok`、`message`（中文）、`engine`、`mode`，成功时还有 `string1`… 与 `table1`…（`[{ "row", "cells": [...] }]`）。

---

## 函数怎么跑

### `HealthCheck()`

不推理。探测 `paddleocr-mcp` 能否 import。

```python
from paddle_ocr import HealthCheck
print(HealthCheck())
# {"ok": True/False, "message": "...", "version": "0.8.x"}
```

### `EnsureModels()`

`HealthCheck` + 权重是否齐全；缺则 `scripts/download_models.py`（启动 MCP 用样图/空白图拉权重），并删除 PaddleOCR-VL 目录。

```python
from paddle_ocr import EnsureModels
ok, message = EnsureModels()
```

安装收尾和 `python paddle_ocr/main.py` 会走这里。`PaddleOcr()` **内部不调用** HealthCheck / EnsureModels。

### `PaddleOcr(pic, rectangle=None, status_callback=None)`

只跑 **PP-OCRv6**（MCP 工具 `ocr`）。不读表、不调 Structure、不调 LLM。懒启动 OCR daemon，返回后不停。

```python
from pathlib import Path
from paddle_ocr import PaddleOcr

result = PaddleOcr(Path("photo.jpg"))
result = PaddleOcr(Path("photo.jpg"), (10, 20, 400, 80))
# result["ok"], result["string1"], result["message"]
```

`status_callback` 若提供，会收到 `OcrStage.FAST_OCR`。

### `PpStructure(pic, rectangle=None, status_callback=None)`

只跑 **PP-StructureV3**（MCP 工具 `pp_structurev3`），把返回的 Markdown 拆成 `string*` / `table*`。不调 `PaddleOcr`、不 judge。懒启动 Structure，**返回后不停**（由 `run_ocr_job` / PDF2MD 负责停）。

```python
from paddle_ocr import PpStructure
result = PpStructure("form.jpg")
```

### `PaddleOcrTasks(tasks)`

按列表串行调用 `PaddleOcr`。一项失败继续下一项。

```python
from paddle_ocr import PaddleOcrTasks
rows = PaddleOcrTasks([("a.jpg", None), ("b.jpg", (0, 0, 100, 40))])
```

### `run_ocr_job(pic, rectangle=None, status_callback=None)`

给 UI / 作业用的编排入口：解码 → 选模板 → 事件表调度（可能 OCR、Structure、LM 语义、相似度）。Structure 在 `finally` 释放，OCR daemon 保持。`status_callback` 收到的是事件 kind 字符串（如 `infer.ocr`），不是 `OcrStage`。

```python
from paddle_ocr import run_ocr_job
final = run_ocr_job("shot.jpg")
# 除识别 JSON 外可能带 engine_draft / lm_draft / lm_scores / lm_adopted
```

无 LM Studio 时仍可跑 OCR/Structure 段。

### `semantic_judge(draft)`

只根据已有 `string*` / `table*` JSON 问本机 LM Studio：语义是否通顺。不 OCR、不 load_model。失败则 `keep_draft`。

```python
from paddle_ocr import semantic_judge
print(semantic_judge({"ok": True, "string1": "hello"}))
```

### `lm_similarity_score(pic, rectangle, engine_draft)`

对照原图与引擎草稿，按字段/单元格打 0–100；仅低于阈值的格子采纳模型修改。不改 `engine_draft` 副本。

```python
from paddle_ocr import PaddleOcr, lm_similarity_score
draft = PaddleOcr("shot.jpg")
scored = lm_similarity_score("shot.jpg", None, draft)
```

### `PaddleOcr_PDF2MDs(FilePath, OutputPath=".")`

把 PDF **按页**写成 Markdown。不改上面图进 JSON 契约。

1. 拆页（pypdfium2）。
2. 抽出可复制文本，去空白后 `< 80` 字视为扫描/图片页。
3. 文字页：原生文本整理成段落 Markdown（不启 OCR/Structure）。若整理后仍空，改走 Structure。
4. 图片页：渲染（默认 150 DPI）→ `pp_structurev3`，**保留 Markdown 原文**。
5. 写出 `{stem}_p0001.md`。有图片页才启 Structure，整份 PDF 结束后关掉。

`OutputPath="."` 或空 = **PDF 所在目录**，不是进程 cwd。

```python
from paddle_ocr import PaddleOcr_PDF2MDs

info = PaddleOcr_PDF2MDs(r"D:\docs\scan.pdf")
info = PaddleOcr_PDF2MDs(r"D:\docs\scan.pdf", r"D:\out")
# info["ok"], info["output_dir"], info["pages"]
# pages[].kind: "text" | "image"
```

CLI：

```bat
.\uv_run.ps1 python -m paddle_ocr.pdf2md --input D:\docs\scan.pdf
.\uv_run.ps1 python -m paddle_ocr.pdf2md --input D:\docs\scan.pdf --output D:\out
```

---

## 目录

| 路径 | 职责 |
| --- | --- |
| `main.py` | 公开 API + `python paddle_ocr/main.py` 门禁 |
| `mcp_entry.py` | paddleocr-mcp 进程入口 |
| `mcp_runtime.py` | HTTP 子进程生命周期与工具调用 |
| `pdf2md/` | PDF 拆页分流 |
| `engines/pp_ocr/` | PP-OCRv6 |
| `engines/pp_structure/` | PP-StructureV3 |
| `job/` | `run_ocr_job` 事件表 |
| `gate/` | 硬件、内存、LM 判定 |
| `scripts/` | 安装后端、下模型、预热 |
| `models/` | 本地权重（不进 git） |

外部程序不要直接调 `mcp_runtime.call_ocr_mcp` / `call_structure_mcp`；走上面的公开函数。
