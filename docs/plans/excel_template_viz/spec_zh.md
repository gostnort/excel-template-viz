# Excel 模板可视化功能规格 (spec_zh.md)

## 1. 用户场景

### P1：通过可视化表单填写 GIN LOT List 工作表
* **用户故事**：作为仓库操作员，我希望在浏览器中打开 GIN LOT 模板，将 List 工作表列显示为带标签的字段，录入或编辑行数据，并导出回 Excel，无需打开桌面 Excel。
* **验收标准**：
  * 侧边栏显示「GIN LOT Template」导航项。
  * 表单展示列：order、YY、MM、DD、P.O. No.、Container No.、Container Seal No.、Lot No.、Receiving Date、Product Description、Supplier、Truck Line。
  * 显示工作簿中已有示例行且可编辑。
  * 用户可下载更新后的工作簿。

### P2：验证 Google Sheets 访问（终端用户）
* **用户故事**：作为开发者无 Google 表格权限的场景下的终端用户，我希望粘贴 Sheet URL/ID、选择认证方式（服务账号或 OAuth），并看到是否能读取前几行，以便自行排查共享与凭证问题。
* **验收标准**：
  * 独立侧边栏页面「Google Sheet 连通性测试」。
  * 输入：Sheet URL 或 ID、工作表名（可选）、认证方式。
  * 服务账号：上传 JSON 密钥。
  * OAuth：浏览器授权流程，令牌仅保存在会话中。
  * 成功：表格展示前 N 行并绿色确认。
  * 失败：红色错误及可能原因（403、404、无效 JSON、工作表名错误）。

### P3：注册更多模板
* **用户故事**：作为维护者，我希望通过编辑 JSON 注册表添加模板，而无需修改核心导航代码。
* **验收标准**：
  * `config/templates.json` 定义 id、显示名、文件路径、工作表名、标题行、数据起始行。
  * 新条目在应用重启后自动出现在侧边栏。

---

## 2. 功能需求

### FR-001：模板注册表
* 启动时加载 `config/templates.json`；工作簿路径不存在时在 UI 警告并跳过。

### FR-002：List 工作表解析
* 使用 pandas/openpyxl 读取；工作表名大小写不敏感匹配。
* 配置的标题行作为列名；从 `data_start_row` 起为数据行。

### FR-003：Streamlit 表单渲染
* 每列每行提供可编辑字段（`st.data_editor` 紧凑表格）。
* 保留标题中的尾随空格（如 "Lot No. "）。

### FR-004：Excel 导出
* 将编辑后的 DataFrame 写回同名工作表；提供 `.xlsx` 下载按钮。

### FR-005：Google Sheets 连接器
* 从 URL 或原始 ID 解析 spreadsheet ID。
* 服务账号：`gspread.service_account_from_dict`。
* OAuth：`InstalledAppFlow`，只读 spreadsheets 范围。
* 按名称或首个工作表读取；返回前几行 DataFrame。

### FR-006：自动化测试钩子
* pytest 模块默认不发起 live Google 调用，验证 ID 解析与 mock/错误路径。

---

## 3. 非功能需求

### NFR-001：本地优先
* 使用 `streamlit run app/app.py` 运行；MVP 无需云部署。

### NFR-002：密钥安全
* 禁止提交服务账号 JSON；`.gitignore` 排除凭证类 `*.json`（`config/templates.json` 除外）。

### NFR-003：文档
* README（中文）说明安装、运行、模板注册与 Google 测试步骤。
