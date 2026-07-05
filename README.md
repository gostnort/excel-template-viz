# Excel Template Viz

## 安装

### 环境要求

- **Windows**（当前脚本为 `.bat`）
- **Python 3.10**（推荐；`llama-cpp-python` 预编译 wheel 兼容性最好）
- 可联网（安装依赖；可选下载 Gemma 模型）

### 一键安装（推荐）

在项目根目录双击或执行：

```bat
install.bat
```

脚本会：

1. 检测 Python 版本，必要时切换到 `py -3.10`
2. 创建虚拟环境 `.venv`
3. 根据 CPU 特性安装匹配的 `llama-cpp-python` CPU wheel
4. 执行 `pip install -r requirements.txt`
5. 创建运行时目录 `temp/`、`exports/`

### 手动安装

```bat
py -3.10 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip

REM 按 CPU 选择 llama-cpp-python 版本（见 requirements.txt 注释）
pip install llama-cpp-python==0.3.28 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu

REM NVIDIA CUDA (RTX 4070): cu124 index + runtime DLLs (see docs/embed_gemma4.md section 4.3)
pip install llama-cpp-python==0.3.28 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12
REM or: install.bat --llm cuda


pip install -r requirements.txt
mkdir temp exports
```

### 启动

```bat
run.bat
```

或激活虚拟环境后：

```bat
python -m nicegui_ui.app
```

浏览器访问：**http://127.0.0.1:8738**

### 可选：Gemma 4 本地 Agent（`llm_gemma4/`）

本项目包含两套相对独立的环境：

| 环境 | 目录 | 用途 |
|------|------|------|
| **主应用** | `app/` + `nicegui_ui/` | Excel 模板录入、导出、Google 连接 |
| **LLM 平台** | `llm_gemma4/` | Gemma 4 E4B 本地推理、TOML 配置向导、Playwright 浏览器操控 |

主应用通过 NiceGUI「TOML」页启动向导子进程：`python -m llm_gemma4 wizard --template {id}`。

**硬件 profile**（启动 LLM 前由 `probe` 探测并选择）：

| profile | 适用硬件 | 推理后端 |
|---------|----------|----------|
| `cpu` | 无 NVIDIA、不走 OpenVINO | llama.cpp CPU wheel |
| `cuda` | NVIDIA GPU（如 RTX 4070） | llama.cpp CUDA wheel |
| `openvino` | Intel 核显 / CPU（如 Core 7 150U） | OpenVINO GenAI INT4 |



```bat
.venv\Scripts\activate.bat
python app/download_gemma4_model.py --auto
```

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
2. **Web 表单替代手工填表**：NiceGUI 提供侧边栏选模板、输入区动态字段、会话行列表、数据库存储与 Google 表格按 ID 拉取。
3. **落库与回写分离**：`app/core_store.py` 负责 SQLite 落库与 UI 字段供给；`app/core_transform.py` 负责按 TOML 坐标写回 xlsx、计算打印区域。
4. **导出与打印**：「另存为」生成 `exports/{template_id}/` 下带时间戳的 xlsx；可在浏览器内预览打印区域并打印，无需安装 Excel。
5. **可扩展**：TOML 支持 `regex` 规范化粘贴内容、`[[sources]]` 连接 Google Sheet；可选 **Gemma 4 本地 Agent**（`llm_gemma4/`）辅助 TOML 首次配置。

业务逻辑集中在 `app/`；界面在 `nicegui_ui/`。结构依赖图见 `plans/codegraph.html` 与 `plans/CODEGRAPH_OVERVIEW.md`。

更细的设计说明：

- `docs/data_flow_design.md` — 数据流与落库策略
- `docs/toml_config_design.md` — TOML 字段语义与校验
- `docs/connect_google.md` — Google 连接配置
- `docs/embed_gemma4.md` — Gemma 4 本地 Agent 平台
- `docs/gemma4_e4b_workflow.md` — TOML 向导与 E4B 工作流
