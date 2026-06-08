# 快速开始 / Quickstart

以下步骤适用于 Windows 与本地运行环境。  
The steps below apply to Windows and local development.

## 安装与运行 / Install & Run

```bash
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

将需要使用的 xlsx 文件复制到 `templates/` 目录，启动后会自动识别。  
Copy your xlsx files into `templates/`; the app will detect them on startup.

## 数据源配置（简要）/ Data Source Setup (Brief)

1. 侧边栏点击 **添加数据源**。  
   Click **Add data source** in the sidebar.
2. 上传服务账号 JSON（并将 Sheet 共享给 `client_email`），或配置 `credentials/oauth_client.json` 后 OAuth 授权。  
   Upload a service account JSON (share the Sheet with `client_email`) or configure `credentials/oauth_client.json` for OAuth.
3. 填写 Sheet URL，**测试连接** 成功后 **保存为默认数据源**。  
   Enter the Sheet URL, **Test connection**, then **Save as default**.
4. 在模板页输入 PO（如 `10073`）→ **查询并填入**。  
   Enter a PO number (e.g. `10073`) → **Query & fill**.
