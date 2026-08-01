# uv 本机安装与 Docker（CPU / GPU）

依赖真相源：根目录 [`pyproject.toml`](../pyproject.toml) + [`uv.lock`](../uv.lock)。已删除旧版 `requirements.txt`；勿再用 pip `-r` 安装。

## 本机（推荐）

### 前置

1. 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Python **3.10** 或 **3.11**（`requires-python = ">=3.10,<3.12"`）

Windows 一键：

```bat
install.bat
```

等价于 `python scripts/bootstrap_install.py`，流程：

1. `uv venv` → 单一项目 `.venv`
2. 探测 NVIDIA（`nvidia-smi`）并确认 **GPU / CPU**
3. 写入本地 [`.install_profile`](../.install_profile)（已 gitignore）
4. `uv sync --extra llm`；若启用 OCR 则互斥再加 `--extra ocr` 或 `--extra ocr-gpu`
5. OCR 时调用 `paddle_ocr/scripts/install_backend.py`（GPU 预热 VL / CPU prune）并跑门禁

### 常用参数

| 参数 | 含义 |
|------|------|
| `--skip-ocr` | 只装 core + llm |
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

### 手动 uv

```bat
uv sync --extra llm
uv sync --extra llm --extra ocr
uv sync --extra llm --extra ocr-gpu
uv run python -m nicegui_ui.app
```

启动也可用 `run.bat`（优先 `uv run`）。

## 容器

模型与业务数据**不进镜像**，用卷挂载。

| Profile | 镜像 | 依赖 extra | 宿主机 |
|---------|------|------------|--------|
| `cpu` | `excel-template-viz:cpu` | `llm` + `ocr` | 无特殊要求 |
| `gpu` | `excel-template-viz:gpu` | `llm` + `ocr-gpu` | NVIDIA 驱动 + Container Toolkit；`--gpus all` |

```bat
docker compose --profile cpu up --build
docker compose --profile gpu up --build
```

默认挂载：

- `./models` → Gemma
- `./paddle_ocr/models` → Paddle / VL
- `./templates`、`./exports`、`./temp`、`./certs`

入口脚本在缺权重时打印下载提示；首次仍可在容器内执行 HF / `paddle_ocr/main.py` 拉取。

本机 `.install_profile` 的 `accelerator=cpu|gpu` 与 compose profile **语义对齐**，便于对照文档与排障。
