# Excel Template Viz · 0.1

> **版本 0.1** 对应 Git 分支 **`split-logic-core`**（NiceGUI 核心基线）。  
> 详细说明见 [`docs/RELEASE.md`](docs/RELEASE.md)。

## 安装

### 环境要求

- **Windows**（`.bat` 安装脚本）
- **Python 3.10** 或 **3.11**（推荐）
- 可联网（`pip install`）

### 一键安装

```bat
install.bat
```

### 启动

```bat
run.bat
```

或：

```bat
python -m nicegui_ui.app
```

访问：**http://127.0.0.1:8738**

## 项目目的

将 **Excel 业务模板**（`templates/*.xlsx` + 同名 TOML）变为浏览器中的 **录入、落库与导出** 工具。

- 业务逻辑：`app/`
- 界面：`nicegui_ui/`
- 设计：`docs/nicegui_ui/nicegui_ui_plan.md`
