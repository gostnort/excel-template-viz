# Excel 模板可视化录入

基于 Streamlit 的 Excel 模板可视化填写工具，支持多模板侧边栏导航与 Google Sheets 连通性自测。

## 功能

- 每个 Excel 模板在侧边栏占一项，主区域展示可编辑表格表单
- 内置 **GIN LOT Template**（List 工作表）配置
- **Google Sheet 连通性测试** 页面：终端用户可自行验证 Sheet ID、凭证与共享权限

## 环境要求

- Python 3.10+
- Windows / macOS / Linux

## 安装

```bash
cd excel-template-viz
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

## 准备 GIN LOT 模板文件

任选其一：

1. 将 `GIN LOT TEMPLATE.xlsx` 复制为 `templates/gin_lot_template.xlsx`
2. 设置环境变量指向原文件：

```powershell
$env:GIN_LOT_TEMPLATE_PATH = "C:\path\to\GIN LOT TEMPLATE.xlsx"
```

> 示例文件常见路径（微信接收）：  
> `C:\Users\<用户>\Documents\WeChat Files\...\GIN LOT TEMPLATE.xlsx`  
> 工作表名称为 **List**（首字母大写）。

## 运行

在项目根目录执行：

```bash
streamlit run app/app.py
```

浏览器打开后，侧边栏选择模板或「Google Sheet 连通性测试」。

## Google Sheet 连通性测试（终端用户）

开发者若无 Google 表格权限，请由**有权限的终端用户**在本机运行应用并完成以下步骤：

### 方式 A：服务账号

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建项目并启用 **Google Sheets API**
2. 创建服务账号并下载 JSON 密钥
3. 在目标 Google Sheet 的「共享」中添加 JSON 中的 `client_email`（查看权限即可）
4. 在应用中打开「Google Sheet 连通性测试」，上传 JSON，粘贴 Sheet URL，点击「测试连接」

### 方式 B：OAuth 用户

1. 在 Google Cloud 创建 OAuth 客户端（桌面应用类型）
2. 将客户端 JSON 保存为 `credentials/oauth_client.json`
3. 在测试页选择「OAuth 用户授权」，点击「启动 OAuth 授权」并完成浏览器登录
4. 粘贴 Sheet URL，点击「测试连接」

成功时显示绿色提示及前几行数据；失败时显示红色错误与排查建议。

## 添加新模板

编辑 `config/templates.json`，增加条目：

```json
{
  "id": "my_template",
  "display_name": "我的模板",
  "description": "说明文字",
  "file_path": "templates/my_template.xlsx",
  "sheet_name": "Sheet1",
  "header_row": 0,
  "data_start_row": 1
}
```

重启 Streamlit 后侧边栏自动出现新项。

## 运行测试

```bash
pytest
```

默认测试不访问 Google 网络；仅验证 ID 解析与 Excel 读写逻辑。

## 项目结构

```
excel-template-viz/
├── app/                    # Streamlit 应用
├── config/templates.json   # 模板注册表
├── docs/plans/             # Speckit 规划文档
├── templates/              # 本地 xlsx 模板
└── tests/                  # pytest
```

## Speckit 文档

规划产物位于 `docs/plans/excel_template_viz/`：

- `constitution.md` / `constitution_zh.md`
- `spec.md` / `spec_zh.md`
- `plan.md` / `plan_zh.md`
- `tasks.md` / `tasks_zh.md`
