# Excel 模板可视化录入

基于 Streamlit 的 Excel 模板 Web 填表工具：侧边栏切换模板，支持 Google Sheet 默认数据源与制表符粘贴，一键下载填好的 xlsx。

## 功能

- **多模板导航**：在 `config/templates.json` 注册模板，侧边栏自动列出（内置 GIN LOT Template / List 工作表）
- **添加数据源**：粘贴 Google Sheet URL，测试连接后保存为默认数据源；可配置工作表名称与 ID 列（默认 `PO`，对应模板 **P.O. No.**）
- **按 PO 查询填表**：配置数据源并完成 Google 认证后，输入 PO 编号即可从 Sheet 拉取一行并自动填入表单
- **源数据粘贴**：仍支持制表符分隔批量粘贴（PO、Container#、recv. date 等列与 Sheet 一致）
- **导出 Excel**：编辑后下载更新后的 xlsx

## 快速开始

```bash
# Windows：双击 install.bat 后 run.bat
# 或手动：
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

将 `GIN LOT TEMPLATE.xlsx` 复制为 `templates/gin_lot_template.xlsx`，或设置环境变量 `GIN_LOT_TEMPLATE_PATH` 指向原文件。

## Google 数据源（简要）

1. 侧边栏点击 **添加数据源**
2. 上传服务账号 JSON（并将 Sheet 共享给 `client_email`），或配置 `credentials/oauth_client.json` 后 OAuth 授权
3. 填写 Sheet URL，**测试连接** 成功后 **保存为默认数据源**
4. 在模板页输入 PO（如 `10073`）→ **查询并填入**

## 测试

```bash
pytest
```

## 文档

- 项目概览（CodeGraph 风格）：`docs/CODEGRAPH_OVERVIEW.md`
- Speckit 规划：`docs/plans/excel_template_viz/`
