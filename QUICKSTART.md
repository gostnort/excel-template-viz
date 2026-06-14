# 快速开始 / Quickstart

以下步骤适用于 Windows 与本地运行环境。  
The steps below apply to Windows and local development.

## 安装与运行 / Install & Run

```bash
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Windows 用户也可使用 `install.bat` 完成安装与模型下载。

启动应用（端口 **8501**）：

```batch
run.bat
```

或：

```bash
python gradio_app.py
```

将需要使用的 xlsx 文件复制到 `templates/` 目录，启动后会自动识别。  
Copy your xlsx files into `templates/`; the app will detect them on startup.

## 数据源配置（简要）/ Data Source Setup (Brief)

1. 侧边栏点击 **添加数据源**。  
   Click **Add data source** in the sidebar.
2. 点击 **连接 Google 账号**，在浏览器中完成授权。  
   Click **Connect Google account** and complete authorization in the browser.
3. 填写 Sheet URL，**连接 Sheet** 成功后 **保存为默认数据源**。  
   Enter the Sheet URL, **Connect Sheet**, then **Save as default**.
4. 在模板页输入 PO（如 `10073`）→ **查询并填入**。  
   Enter a PO number (e.g. `10073`) → **Query & fill**.
