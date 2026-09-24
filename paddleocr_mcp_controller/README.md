# paddleocr_mcp_controller

paddleocr-mcp 的薄控制器。只暴露两个公开函数，签名和返回 JSON 与原 `paddle_ocr/` 兼容：

- `run_ocr_job(pic, rectangle=None, status_callback=None, lm_scorer=None) -> dict`
- `PaddleOcr_PDF2MDs(FilePath, OutputPath=None, multipages=True) -> dict`

仅 CPU。不依赖 PaddleOCR-VL、不依赖 GPU、不依赖 `llm_lmstudio`（LM 评分通过可选 `lm_scorer` 回调注入）。

## 安装

```text
cd paddleocr_mcp_controller
uv sync
python install.py
```

`uv sync` 装 `paddleocr-mcp[local-cpu]` + `paddlepaddle`(CPU) + 全部依赖。
`python install.py` 下载 PP-OCRv6 + PP-StructureV3 权重到 `models/`，prune VL 残留，跑 HealthCheck。

## 作为主项目依赖

主项目 `bootup/pyproject.toml`：

```toml
paddleocr-mcp-controller = { path = "../paddleocr_mcp_controller" }
```

## 运行

```python
from paddleocr_mcp_controller import run_ocr_job, PaddleOcr_PDF2MDs

# 图片 OCR / 版面
result = run_ocr_job("photo.jpg")
result = run_ocr_job("form.jpg", (10, 20, 400, 80))

# PDF → 每页 Markdown
info = PaddleOcr_PDF2MDs(r"D:\docs\scan.pdf")
```

## 目录

| 路径 | 职责 |
| --- | --- |
| `src/paddleocr_mcp_controller/` | 包源码 |
| `src/paddleocr_mcp_controller/install.py` | 一键安装 CLI |
| `src/paddleocr_mcp_controller/mcp_entry.py` | paddleocr-mcp 进程入口（关 MKLDNN） |
| `src/paddleocr_mcp_controller/mcp_runtime.py` | HTTP 子进程 + 工具调用 |
| `src/paddleocr_mcp_controller/postprocess.py` | Markdown → string*/table* JSON |
| `src/paddleocr_mcp_controller/image_decode.py` | HEIC + ROI 解码 |
| `src/paddleocr_mcp_controller/table_grid.py` | HasTableGrid 廉价表格门 |
| `src/paddleocr_mcp_controller/pdf2md.py` | PaddleOcr_PDF2MDs |
| `src/paddleocr_mcp_controller/job.py` | run_ocr_job |
| `src/paddleocr_mcp_controller/lm_similarity.py` | LM 评分（可插拔 vision_fn） |
| `src/paddleocr_mcp_controller/models_catalog.py` | 模型管理 + prune VL |
| `src/paddleocr_mcp_controller/scripts/download_models.py` | 模型下载/预热 |
| `models/` | 本地权重（不进 git） |
