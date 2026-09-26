# paddleocr_mcp_controller

`paddleocr-mcp` 的薄控制器:以 HTTP 子进程方式驱动 paddleocr-mcp,对外只暴露两个公开函数(签名与原 `paddle_ocr/` 兼容),并负责跨进程协调与卸载。

- **仅 CPU**。不依赖 PaddleOCR-VL、不依赖 GPU、不依赖 `llm_lmstudio`(LM 评分通过可选 `vision_fn` 回调注入)。
- **Python 3.10–3.11**(`requires-python = ">=3.10,<3.12"`)。
- **平台**:Windows 优先(树杀走 `taskkill /T /F`);POSIX 有回退(`psutil`/`killpg`)。

---

## 一、安装

### 1.1 独立安装(uv,推荐)

```text
cd paddleocr_mcp_controller
uv sync
paddleocr-mcp-install
```

- `uv sync`:装 `paddleocr-mcp[local-cpu]` + `paddlepaddle`(CPU 版) + 全部依赖(`pypdfium2` / `pypdf` / `pdfplumber` / `opencv-python-headless` / `pillow-heif` / `beautifulsoup4` / `fastmcp`)。
- `paddleocr-mcp-install`:下载 **PP-OCRv6** + **PP-StructureV3** 权重到 `models/`,prune 掉 PaddleOCR-VL 残留,跑 HealthCheck。加 `--no-warm` 跳过预热。

等价写法(无 console script 时):

```text
uv run python -m paddleocr_mcp_controller.install
```

> 旧文档里的 `python install.py` 已失效——`install.py` 在包内部,请用上面的 console script 或 `python -m` 形式。

### 1.2 作为主项目依赖

主项目 `bootup/pyproject.toml` 已配置为本地路径依赖:

```toml
[project.optional-dependencies]
ocr = [
    "paddleocr-mcp[local-cpu]>=0.8.5,<1.0",
    "paddleocr-mcp-controller",
    # ...
]

[tool.uv.sources]
paddleocr-mcp-controller = { path = "../paddleocr_mcp_controller" }
```

在主项目里 `uv sync --extra ocr` 即可,无需再单独进 controller 目录。首次使用仍需跑一次 `paddleocr-mcp-install` 下载权重。

### 1.3 安装校验

```text
uv run python -c "from paddleocr_mcp_controller import HealthCheck, EnsureModels; print(HealthCheck()); print(EnsureModels())"
```

`HealthCheck` 返回 `{"ok": True, ...}` 即 paddleocr-mcp 可导入;`EnsureModels` 返回 `(True, ...)` 即权重就绪。

### 1.4 跨机器部署 / models 复用

`models/` 是纯 Paddle 推理权重(可移植),跨机器复制即可复用,不必重新下载。models 路径由 `resolve_models_dir()` 解析,顺序:

1. 环境变量 `PADDLEOCR_MCP_MODELS_DIR`(显式指定,任意位置)
2. 环境变量 `PADDLE_PDX_CACHE_HOME`(paddleocr-mcp 自带 cache 变量)
3. 源码树内 `src/paddleocr_mcp_controller/models/`(默认,独立跑 / editable 时即此)

**复制即用(推荐)**:把整个 `paddleocr_mcp_controller/`(含 `src/.../models/`、`pyproject.toml`、`uv.lock`)拷到新机器同结构位置,**不带 `.venv`**;新机器:

```text
cd paddleocr_mcp_controller
uv sync
uv run paddleocr-pdf2md --input 你的.pdf
```

`uv sync` 重建虚拟环境并自动装 `paddleocr-mcp[local-cpu]`(新机器没有也由 uv 装上);独立跑时 uv 把根项目按 editable 装,`resolve_models_dir()` 回退到源码树内已复制的 `models/`,**不重下权重**。

**models 放包外(可选)**:若想让 models 与源码分离、或多机共享一份,把 `models/` 挪到任意位置,设一次环境变量即可,源码树里不必留权重:

```text
setx PADDLEOCR_MCP_MODELS_DIR "E:\shared\paddleocr-models"
```

此变量优先级最高,运行时缓存、`EnsureModels` 健康检查、下载三条路统一指向它,不再依赖包的安装位置。

---

## 二、运行

### 2.1 命令行(CLI)

两个 console script(`pyproject.toml` 已注册):

```text
# PDF → 每页 Markdown(默认)
paddleocr-pdf2md --input D:\docs\scan.pdf
paddleocr-pdf2md --input scan.pdf --output D:\out
paddleocr-pdf2md --input scan.pdf --no-multipages   # 合并成一个 {stem}.md

# 一键安装
paddleocr-mcp-install [--no-warm]
```

`--output` 规则:`None`/空 → PDF 同名文件夹;`.` → PDF 所在目录;其它 → 该目录。
`--multipages`(默认)→ 每页一个 `{stem}_p{page:04d}.md`;`--no-multipages` → 合并成一个 `{stem}.md`(返回额外带 `combined_path`)。

### 2.2 Python 调用

```python
from paddleocr_mcp_controller import run_ocr_job, PaddleOcr_PDF2MDs

# 图片 OCR / 版面
result = run_ocr_job("photo.jpg")                  # 整图 OCR
result = run_ocr_job("form.jpg", (10, 20, 400, 80)) # ROI (x, y, w, h)

# PDF → 每页 Markdown
info = PaddleOcr_PDF2MDs(r"D:\docs\scan.pdf")
# info = {"ok", "message", "output_dir", "pages": [...]}
```

**公开 API**(`from paddleocr_mcp_controller import ...`):

| 函数 | 作用 |
| --- | --- |
| `run_ocr_job(pic, rectangle=None, status_callback=None, *, vision_fn=None)` | 一张图:解码→`HasTableGrid` 路由→PP-OCRv6 或 PP-StructureV3;`vision_fn` 非 None 时跑 LM 相似度校对 |
| `PaddleOcr_PDF2MDs(FilePath, OutputPath=None, multipages=True)` | PDF→每页/合并 Markdown |
| `HealthCheck()` | paddleocr-mcp 可导入性 + 版本 |
| `EnsureModels()` | 检查并补齐 PP-OCRv6/PP-StructureV3 权重,prune VL |
| `PaddleOcr(pic, rectangle=None, status_callback=None)` | 仅 PP-OCRv6(不读表) |
| `PpStructure(pic, rectangle=None, status_callback=None)` | 仅 PP-StructureV3 |
| `stop_mcp()` | 强制卸载所有 MCP 子进程(app 退出时调) |

### 2.3 Windows 脚本调用注意

直接调用 `PaddleOcr_PDF2MDs` 的脚本**必须**有 `if __name__ == "__main__":` 守卫——内部用 `multiprocessing.get_context("spawn").Pool` 并行表格页,spawn 子进程会重新 import `__main__`,无守卫会重跑脚本、重复登记导致 refcount 膨胀。包自带的 CLI 已加守卫,安全。

```python
# 正确
if __name__ == "__main__":
    PaddleOcr_PDF2MDs(r"D:\docs\scan.pdf")
```

---

## 三、行为与架构(简述)

### MCP 子进程
控制器把 `paddleocr-mcp` 作为 HTTP 子进程拉起(`mcp_entry.py` 入口,关 MKLDNN)。OCR 惰性启动常驻;Structure 走**动态池**(多端口,按需扩容到 `PDF2MD_PARALLEL_WORKERS`)。

### pdf2md 三分支逐页路由
1. **纯文本页**(有原生文本、无嵌入图)→ pypdfium2 原生抽文本,不调 MCP。
2. **矢量绘制表格页**(pdfplumber `edges` 检测到网格)→ 渲染整页 → PP-StructureV3 输出 markdown 表格。
3. **嵌入图页** → pdfplumber 文本块与各图按 `top` 交错;每图 `HasTableGrid` → 表格走 Structure、其余走 OCR。
4. **纯矢量轮廓页**(无原生文本、无嵌入图,如 `1.pdf`)→ 渲染整页 → `HasTableGrid` → Structure/OCR。

### 跨进程协调(`mcp_registry.py`)
多个 controller 进程(如两个 terminal 各跑一次 PDF2md)通过文件锁注册表(`temp/mcp_registry.json`)共享一个**热 paddleocr_mcp 守护**:
- **重 PDF2md 跨进程串行**:新进程登记后等待先登记的 pdf2md PID 全部退出,再按端口**采纳**已有 server(不重复 spawn,暖 handoff)。
- **轻 run_ocr_job 不等待**,并发复用同一批 server。
- **引用计数卸载**:全局 refcount 归零时树杀所有 MCP 子进程(含 paddleocr-mcp 子进程),无残留。Ctrl-C / 进程退出由 signal/atexit 清理;硬杀靠下个进程的 stale GC。

### 关键配置(`config.py`)

| 常量 | 默认 | 说明 |
| --- | --- | --- |
| `PDF2MD_RENDER_DPI` | 150 | 文本/OCR 页渲染 DPI |
| `PDF2MD_TABLE_RENDER_DPI` | 110 | 表格页渲染 DPI(降像素提速) |
| `PDF2MD_PARALLEL_WORKERS` | `max(1, cpu//2)` | 表格页并行 Structure worker 数 |
| `STRUCTURE_MCP_PORT_BASE` | 18090 | Structure 池端口起始 |
| `MCP_START_TIMEOUT_SEC` | 600 | 子进程就绪超时(模型加载慢) |
| `PDF2MD_TEXT_CHAR_MIN` | 80 | 判定"有原生文本"的字符阈值 |

---

## 四、目录

| 路径 | 职责 |
| --- | --- |
| `src/paddleocr_mcp_controller/__init__.py` | 公开 API + PEP 562 懒加载 |
| `src/paddleocr_mcp_controller/install.py` | 一键安装 CLI(`paddleocr-mcp-install`) |
| `src/paddleocr_mcp_controller/mcp_entry.py` | paddleocr-mcp 子进程入口 |
| `src/paddleocr_mcp_controller/mcp_runtime.py` | HTTP 子进程 + 动态池 + refcount + 信号清理 |
| `src/paddleocr_mcp_controller/mcp_registry.py` | 跨进程共享注册表(文件锁 + GC + 串行等待 + 采纳/spawn) |
| `src/paddleocr_mcp_controller/pdf2md.py` | `PaddleOcr_PDF2MDs` 三分支路由 |
| `src/paddleocr_mcp_controller/job.py` | `run_ocr_job` |
| `src/paddleocr_mcp_controller/table_grid.py` | `HasTableGrid` 廉价表格门 |
| `src/paddleocr_mcp_controller/image_decode.py` | HEIC + ROI 解码 |
| `src/paddleocr_mcp_controller/postprocess.py` | Markdown → string*/table* JSON |
| `src/paddleocr_mcp_controller/lm_similarity.py` | LM 评分(可插拔 `vision_fn`) |
| `src/paddleocr_mcp_controller/models_catalog.py` | 模型管理 + prune VL |
| `models/` | 本地权重(不进 git);路径可由 `PADDLEOCR_MCP_MODELS_DIR` 覆盖,见 1.4 |
| `temp/mcp_registry.json` | 跨进程注册表(运行时生成,不进 git) |
