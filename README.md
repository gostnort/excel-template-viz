# Excel 模板可视化录入 / Excel Template Visualization

基于 Streamlit 的 Excel 模板 Web 填表工具：侧边栏切换模板，支持 Google Sheet 默认数据源与制表符粘贴，一键下载填好的 xlsx。  
Streamlit-based Excel template web app: switch templates in the sidebar, use Google Sheets as default data source or tab-separated paste, and download filled xlsx files.

## 功能 / Features

- **多模板导航**：将 xlsx 文件放入 `templates/`，侧边栏自动发现并列出 / **Multi-template navigation**: drop xlsx files into `templates/` and see them in the sidebar.
- **模板配置**：同名 `.json` 或 `.config.json` 保存默认工作表与数据源 / **Template config**: sidecar JSON stores sheet defaults and data sources.
- **数据源 Tab**：在模板页「数据源」Tab 内完成认证、连接 Sheet、工作表/ID 列选择与列映射 / **Data source tab**: authenticate, connect Sheet, pick worksheet/ID column, and edit mappings per template.
- **自动查询填表**：在「数据录入」Tab 的 ID 字段输入值，稳定 2 秒后自动从 Sheet 拉取并填入 / **Auto lookup**: enter an ID in the form; after 2 seconds it fetches and fills mapped fields.
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

1. 侧边栏选择模板，打开 **数据源** Tab。  
   Select a template in the sidebar, then open the **数据源** tab.
2. 点击 **连接 Google 账号**，浏览器弹出后登录并允许即可。  
   Click **Connect Google account**, sign in in the browser, and allow access.
3. 填写 Sheet URL 并 **连接 Sheet**；成功后从下拉框选择工作表与 ID 列，所有的列映射和设置都会在修改后**自动即时保存**。  
   Enter the Sheet URL and click **Connect Sheet**; then pick worksheet/ID column from dropdowns, and edit mappings. All changes are **auto-saved instantly**.
4. 切换到 **数据录入** Tab，在 ID 对应字段输入编号（如 `10073`），稳定 2 秒后自动填表。  
   Switch to **数据录入**, type an ID (e.g. `10073`); fields auto-fill after 2 seconds.

## 文档 / Docs

- 项目概览（CodeGraph 风格）/ Project overview: `plans/CODEGRAPH_OVERVIEW.md`
- Speckit 规划 / Speckit plans: `plans/`
- YAML 驱动的 Google Sheet 查表计划 / YAML-driven Google Sheet lookup plan: `plans/yaml_driven_sheet_lookup/`
- 项目清理计划（死代码与 pytest 移除）/ Project cleanup plan: `plans/project_cleanup/`
- 快速开始 / Quickstart: `QUICKSTART.md`
- 弃用说明 / Deprecation: 旧的双语 Speckit 文档（如 `plan_zh.md`）已按计划删除；英文 Speckit 保留作历史档案。/ Legacy bilingual Speckit docs (e.g. `plan_zh.md`) were removed per `plans/project_cleanup/`; English Speckit kept for history.
