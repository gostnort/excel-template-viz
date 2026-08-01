# Excel Template Viz

## 版本

| 版本 | 分支 / 标签 | 说明 |
|------|-------------|------|
| **0.1** | `split-logic-core` · `v0.1` | NiceGUI 核心基线（无 OCR / Gemma4 平台） |
| **0.1.1** | `add-paddle-ocr` · `0.1.1` | 引入 PaddleOCR 视觉平台与 UI 拍照回填集成 |
| 开发中 | `toml-guide` | Gemma 4 智能向导（7 步全局悬浮窗）开发中 |

## 安装

依赖由 **uv** 管理（[`pyproject.toml`](pyproject.toml) + [`uv.lock`](uv.lock)）。详见 [`docs/install_uv_docker.md`](docs/install_uv_docker.md)。

### 环境要求

- **Windows**（`install.bat` / `run.bat`）；Linux/macOS 可用同一套 `uv` 命令
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** 在 PATH 中
- **Python 3.10** 或 **3.11**（`requires-python = ">=3.10,<3.12"`）
- 可联网（安装依赖；首次使用 Gemma 4 / PaddleOCR 时会下载模型）
- **可选 GPU**：NVIDIA 显卡；安装向导会探测并确认，OCR 走 `ocr-gpu`（`paddlepaddle-gpu` / VL）

### 一键安装（推荐）

```bat
install.bat
```

脚本调用 [`scripts/bootstrap_install.py`](scripts/bootstrap_install.py)：

1. 确认已安装 uv；`uv venv` 创建**唯一** `.venv`
2. 探测 NVIDIA，交互确认 GPU 或 CPU（可用 `--gpu` / `--cpu`）
3. 写入本地 `.install_profile`；`uv sync --extra llm`，按需互斥加 `--extra ocr` 或 `ocr-gpu`
4. 默认跑 OCR 门禁（`paddle_ocr/main.py`，日志 `temp/install_paddle_ocr.log`）
5. 创建 `temp/`、`exports/`、`models/gemma4`

```bat
install.bat --skip-ocr
install.bat --gpu
install.bat --cpu --force-profile
```

### 手动安装（uv）

```bat
uv sync --extra llm
uv sync --extra llm --extra ocr
uv sync --extra llm --extra ocr-gpu
uv run python paddle_ocr/main.py
```

勿同时安装 `ocr` 与 `ocr-gpu`。

### 启动

```bat
run.bat
```

或：

```bat
uv run python -m nicegui_ui.app
```

浏览器访问：**http://127.0.0.1:8738**

界面为 **NiceGUI**（`nicegui_ui/`）；原 Gradio `webui/` 已移除。

### 容器（CPU / GPU）

```bat
docker compose --profile cpu up --build
docker compose --profile gpu up --build
```

模型与 `templates/` / `exports/` 走卷挂载，不进镜像。见 [`docs/install_uv_docker.md`](docs/install_uv_docker.md)。

### 可选：Gemma 4 本地推理（`llm_gemma4/`）

本项目包含三套相对独立的平台：

| 环境 | 目录 | 用途 |
|------|------|------|
| **主应用** | `app/` + `nicegui_ui/` | Excel 模板录入、导出、Google 连接、字段拍照与 OCR 回填 |
| **LLM 平台** | `llm_gemma4/` | Gemma 4 E4B（LiteRT）本地推理、结构化判定、多模态读图 |
| **OCR 平台** | `paddle_ocr/` | 图片 → 结构 JSON；fast 路径 + Gemma 语义门禁 + 可选 PaddleVL 精修 |

Gemma 权重在**首次调用**时由 `hf_download` 后台拉取（约 3.66GB），也可预先下载：

```bat
uv run python -c "from llm_gemma4.hf_download import download_litert; print(download_litert())"
```

一次性问答 smoke test：

```bat
uv run python -m llm_gemma4 "用一句话介绍你自己"
```

**硬件 profile**（环境变量 `LLM_PROFILE` 或调用方传入；默认 `auto`）：

| profile | 含义 | LiteRT 后端 |
|---------|------|-------------|
| `auto` | 自动级联 | NPU → GPU → CPU |
| `cpu` | 强制 CPU | `Backend.CPU()` |
| `cuda` | 强制 GPU（含 NVIDIA 独显） | `Backend.GPU()` |
| `openvino` | 保留名；本运行时走 GPU 档 | `Backend.GPU()` |

TOML 配置向导（应用层编排）规格见 `docs/gemma4_e4b_workflow.md`；NiceGUI「TOML」页当前提供校验与全文编辑，向导智能悬浮窗正在 `toml-guide` 分支开发中。

### 可选：PaddleOCR（`paddle_ocr/`）

- 对外 API：`paddle_ocr.main.PaddleOcr(pic, rectangle)` → `string*` / `table*` JSON
- NiceGUI「输入」页字段右键菜单：**拍照** / **OCR**（`nicegui_ui/components/ocr_menu.py`）
- 安装门禁：`python paddle_ocr/main.py`（健康检查、缺模型下载、样图试跑）
- 设计规格：`docs/embed_paddle_ocr.md`

### 可选：Google 表格连接

将 OAuth 凭证放在 `credentials/`（勿提交仓库）。在应用内「Google 连接」页面上传或配置；字段与表格 URL 写在各模板的 `{id}.toml` 中。详见 `docs/connect_google.md`。

### 模板文件

将 Excel 模板（`.xlsx`）放入 `templates/`。每个模板可有同名子目录，内含：

- `{id}.toml` — 字段规则、数据源、输入区配置
- `{id}.history.json` — Google 导入屏蔽列表（可选）

仓库仅保留 `templates/README.txt`；本地模板数据默认不入库。

---

## 项目目的

本项目把 **Excel 业务模板** 变成可在浏览器中操作的 **数据录入与导出工具**，面向重复性表格作业（批次标签、冷库单据、发货清单等）。

核心思路：

1. **模板即产品**：在 `templates/` 放置 `.xlsx`，用同名 TOML 描述每个字段在表上的位置、粘贴拆分规则、外部数据源与主键。
2. **Web 表单替代手工填表**：NiceGUI 提供可折叠侧边栏选模板、输入区动态字段、会话行列表、数据库存储与 Google 表格按 ID 拉取；字段支持拍照缓存与一次 OCR 回填。
3. **落库与回写分离**：`app/core_store.py` 负责 SQLite 落库、附图与 UI 字段供给；`app/core_transform.py` 负责按 TOML 坐标写回 xlsx、计算打印区域。
4. **导出与打印**：「另存为」生成 `exports/{template_id}/` 下带时间戳的 xlsx；可在浏览器内预览打印区域并打印，无需安装 Excel。
5. **可扩展**：TOML 支持 `regex` 规范化粘贴内容、**`determiner` 多分隔符（如 `\r\n` 与 `\t` 数组支持）拆分**、`[[sources]]` 连接 Google Sheet；可选 **Gemma 4**（`llm_gemma4/`）作 OCR 语义纠正与向导推理，**PaddleOCR**（`paddle_ocr/`）作 fast/VL 识别管线。

业务逻辑集中在 `app/`；界面在 `nicegui_ui/`。结构依赖图见 `plans/codegraph.html` 与 `plans/CODEGRAPH_OVERVIEW.md`。

更细的设计说明：

- `docs/data_flow_design.md` — 数据流与落库策略
- `docs/toml_config_design.md` — TOML 字段语义与校验
- `docs/connect_google.md` — Google 连接配置
- `docs/nicegui_ui/nicegui_ui_plan.md` — NiceGUI 迁移与交互规格
- `docs/embed_gemma4.md` — Gemma 4 LiteRT 运行时
- `docs/embed_paddle_ocr.md` — PaddleOCR 平台与内存分级精修
- `docs/install_uv_docker.md` — uv 单环境安装与 CPU/GPU 容器
- `docs/gemma4_e4b_workflow.md` — TOML 智能向导 7 步工作流与全局悬浮窗规格
- `docs/db_store.md` — 附图落库与 `input_label` 关联
