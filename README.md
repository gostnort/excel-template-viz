# Excel Template Viz

## 版本

| 版本 | 分支 / 标签 | 说明 |
|------|-------------|------|
| **0.1** | `split-logic-core` · `v0.1` | NiceGUI 核心基线（无 OCR / Gemma4 平台） |
| **0.1.1** | `add-paddle-ocr` · `0.1.1` | 引入 PaddleOCR 视觉平台与 UI 拍照回填集成 |
| 开发中 | `feature-llm-toml-4` | LM Studio 推理 + TOML 动态向导 CLI |

## 安装

依赖真相源：[`bootup/pyproject.toml`](bootup/pyproject.toml) + [`bootup/uv.lock`](bootup/uv.lock)。已删除旧版 `requirements.txt`；勿再用 `pip -r` 安装，也勿同时安装 `ocr` 与 `ocr-gpu`。

### 环境要求

- **Windows**（`install.bat` / `run.ps1`）；Linux/macOS 可用同一套 `uv` 命令
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** 在 PATH 中
- **Python 3.10** 或 **3.11**（`requires-python = ">=3.10,<3.12"`）
- 可联网（安装依赖；首次使用 PaddleOCR 时会下载模型；LLM 由本机 LM Studio 提供）
- **可选 GPU**：NVIDIA 显卡；安装向导会探测并确认，OCR 走 `ocr-gpu`（`paddlepaddle-gpu` / PP-OCRv6 + PP-StructureV3）

### 一键安装（推荐）

Windows:

```bat
install.bat
```

Linux / macOS:

```bash
chmod +x install.sh run.sh
./install.sh
```

等价于 `python bootup/bootstrap_install.py`，流程：

1. `uv venv` → `bootup/.venv`
2. 探测 NVIDIA（`nvidia-smi`）并确认 **GPU / CPU**
3. 写入本地 `.install_profile`（已 gitignore）
4. `uv sync`；默认再加 `--extra ocr` 或 `--extra ocr-gpu`（仅 `--skip-ocr` 跳过）
5. OCR 时调用 `paddle_ocr/scripts/install_backend.py`（GPU 预热 PP-OCRv6 / PP-StructureV3；CPU prune 旧 VL）并跑门禁

常用参数：

| 参数 | 含义 |
|------|------|
| `--skip-ocr` | 只装 core |
| `--gpu` / `--cpu` | 强制 OCR 栈，不交互 |
| `--force-profile` | 忽略已有 `.install_profile`，重新确认 |
| `--python 3.10` | 指定 uv venv 解释器 |
| `--frozen` | `uv sync --frozen`（按 lock 复现） |

`.install_profile` 示例：

```
accelerator=gpu
ocr=true
```

`ocr` 与 `ocr-gpu` **不可同装**。改档位：带 `--force-profile` 重跑安装，或删掉 `.install_profile` 后重装。

### 手动安装（uv）

```bat
uv sync --project bootup
uv sync --project bootup --extra ocr
uv sync --project bootup --extra ocr-gpu
uv run --project bootup --extra ocr python -m nicegui_ui.app
.\uv_run.ps1 python -m nicegui_ui.app
```

`uv run --project bootup` **必须带上**当前 extra（`ocr` 或 `ocr-gpu`），否则会把 OCR 包从 `bootup/.venv` 卸掉。`.\uv_run.ps1` / `.\run.ps1` 会读 `bootup/.install_profile` 自动附加 `--extra`。

### 启动

Windows:

```powershell
.\run.ps1
```

Linux / macOS:

```bash
./run.sh
```

或：

```bat
.\uv_run.ps1 python -m nicegui_ui.app
```

浏览器访问：**https://127.0.0.1:8738**

界面为 **NiceGUI**（`nicegui_ui/`）；原 Gradio `webui/` 已移除。

### 容器（CPU / GPU）

模型与业务数据**不进镜像**，用卷挂载。

| Profile | 镜像 | 依赖 extra | 宿主机 |
|---------|------|------------|--------|
| `cpu` | `excel-template-viz:cpu` | `ocr` | 无特殊要求 |
| `gpu` | `excel-template-viz:gpu` | `ocr-gpu` | NVIDIA 驱动 + Container Toolkit；`--gpus all` |

```bat
docker compose --profile cpu up --build
docker compose --profile gpu up --build
```

默认挂载：

- `./paddle_ocr/models` → PaddleOCR（PP-OCRv6 / PP-StructureV3）
- `./templates`、`./exports`、`./temp`、`./certs`

LLM 不进容器：在宿主机运行 LM Studio，并把 `llm_lmstudio/user.toml` 的 `api_url` 指到可达地址。本机 `.install_profile` 的 `accelerator=cpu|gpu` 与 compose profile **语义对齐**。

### 可选：LM Studio（`llm_lmstudio/`）

本项目包含三套相对独立的平台：

| 环境 | 目录 | 用途 |
|------|------|------|
| **主应用** | `app/` + `nicegui_ui/` | Excel 模板录入、导出、Google 连接、字段拍照与 OCR 回填 |
| **LLM 平台** | `llm_lmstudio/` | 连接本机 LM Studio：load/unload、chat、多模态探测 |
| **向导** | `llm_toml_wizard/` | TOML 动态 agents（CLI 验收主线） |
| **OCR 平台** | `paddle_ocr/` | 图片 → 结构 JSON；PP-OCRv6 fast + LM Studio 语义门禁 + 可选 PP-StructureV3 精修 |

权重由 LM Studio 管理。配置见 `llm_lmstudio/user.toml.example`（默认 `http://localhost:9999`）。NiceGUI 顶栏可编辑模型名，开关遥控加载/卸载。规格：`docs/llm_lmstudio.md`。

一次性问答：

```bat
.\uv_run.ps1 python -m llm_lmstudio ask "用一句话介绍你自己"
```

TOML 配置向导规格见 `docs/toml_wizard.md`；NiceGUI「TOML」页提供校验、全文编辑与 Graph 事件驱动的配置工作流。

### 安装（TOML 向导 CLI）

向导 CLI 与主应用共用同一套环境。先完成上文安装。`uv sync` 会安装 `dev` 依赖组中的 `pytest`，用于下面的冒烟测试。

```bat
uv sync --project bootup
```

### `dialog demo`

离线验收（默认 `--mock --stub`，不连接 LM Studio；每次提交前建议跑通）：

```bat
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog demo --spec toml
.\uv_run.ps1 pytest tests/test_cli_dialog_toml.py -q
```

期望退出码 0，stdout 含 `[event] finished` 与 `field_match`。查看动作表：

```bat
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog catalog --spec toml
```

### `dialog run --live`

本机 LM Studio 已加载（或可由客户端 load）对应模型时：

```bat
.\uv_run.ps1 python -m llm_toml_wizard.cli dialog run --spec toml --live --release
```

真人输入对应四类中断：`ask_sources` / `ask_layout` / `ask_sample` / `ask_db_id`。无 LM Studio 时请用上一节 `dialog demo`。

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
5. **可扩展**：TOML 支持 `regex` 规范化粘贴内容、**`determiner` 多分隔符（如 `\r\n` 与 `\t` 数组支持）拆分**、`[[sources]]` 连接 Google Sheet；可选 **LM Studio**（`llm_lmstudio/`）作 OCR 语义纠正与向导推理，**PaddleOCR**（`paddle_ocr/`）作 PP-OCRv6 / PP-StructureV3 识别管线。

业务逻辑集中在 `app/`；界面在 `nicegui_ui/`。结构依赖图见 `plans/codegraph.html` 与 `plans/CODEGRAPH_OVERVIEW.md`。

更细的设计说明：

- `docs/data_flow_design.md` — 数据流与落库策略
- `docs/toml_config_design.md` — TOML 字段语义与校验
- `docs/connect_google.md` — Google 连接配置
- `docs/nicegui_ui/nicegui_ui_plan.md` — NiceGUI 迁移与交互规格
- `docs/llm_lmstudio.md` — LM Studio REST 与顶栏开关
- `docs/embed_paddle_ocr.md` — PaddleOCR 平台与内存分级精修
- `docs/toml_wizard.md` — TOML 配置工作流（Graph 事件驱动、中断对话框、FAB）
- `docs/db_store.md` — 附图落库与 `input_label` 关联
