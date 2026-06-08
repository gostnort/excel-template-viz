# Excel 模板可视化录入 / Excel Template Visualization

基于 Streamlit 的 Excel 模板 Web 填表工具：侧边栏切换模板，支持 Google Sheet 默认数据源与制表符粘贴，一键下载填好的 xlsx。  
Streamlit-based Excel template web app: switch templates in the sidebar, use Google Sheets as default data source or tab-separated paste, and download filled xlsx files.

## 功能 / Features

- **多模板导航**：将 xlsx 文件放入 `templates/`，侧边栏自动发现并列出 / **Multi-template navigation**: drop xlsx files into `templates/` and see them in the sidebar.
- **模板配置**：同名 `.json` 或 `.config.json` 保存默认工作表与数据源 / **Template config**: sidecar JSON stores sheet defaults and data sources.
- **添加数据源**：粘贴 Google Sheet URL，测试连接后保存为默认数据源 / **Add data source**: paste a Sheet URL, test, then save as default.
- **数据源汇总**：填写侧「数据源」Tab 集中查看全部模板的 Sheet 配置 / **Data source overview**: the form-side **数据源** tab lists all template Sheet configs.
- **按 PO 查询填表**：配置数据源并完成认证后，输入 PO 编号即可填表 / **Fill by PO**: query a PO and auto-fill from the Sheet.
- **源数据粘贴**：支持制表符分隔批量粘贴 / **Paste data**: bulk paste tab-separated rows.
- **导出 Excel**：编辑后下载更新后的 xlsx / **Export Excel**: download the updated xlsx.

## 快速开始 / Quickstart

Windows 可直接双击 `install.bat` 后运行 `run.bat`。  
On Windows, you can double-click `install.bat` then run `run.bat`.

```bash
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

将需要使用的 xlsx 文件复制到 `templates/` 目录，启动后会自动识别。  
Copy your xlsx files into `templates/`; the app will detect them on startup.

## Google 数据源（简要）/ Google data source (brief)

1. 侧边栏点击 **添加数据源**。  
   Click **Add data source** in the sidebar.
2. 上传服务账号 JSON（并将 Sheet 共享给 `client_email`），或配置 `credentials/oauth_client.json` 后 OAuth 授权。  
   Upload a service account JSON (share the Sheet with `client_email`) or configure `credentials/oauth_client.json` for OAuth.
3. 填写 Sheet URL，**测试连接** 成功后 **保存为默认数据源**。  
   Enter the Sheet URL, **Test connection**, then **Save as default**.
4. 在模板页输入 PO（如 `10073`）→ **查询并填入**。  
   Enter a PO number (e.g. `10073`) → **Query & fill**.

## 测试 / Tests

```bash
pytest
```

## 文档 / Docs

- 项目概览（CodeGraph 风格）/ Project overview: `plans/CODEGRAPH_OVERVIEW.md`
- Speckit 规划 / Speckit plans: `plans/`
- 快速开始 / Quickstart: `QUICKSTART.md`
- 弃用说明 / Deprecation: 旧的双语 Speckit 文档（如 `plan_zh.md`）已弃用，仅保留历史参考。/ Legacy bilingual Speckit docs (e.g. `plan_zh.md`) are deprecated and kept for historical reference.
