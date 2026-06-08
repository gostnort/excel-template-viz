# Excel 模板可视化项目宪章 (constitution_zh.md)

## 1. 核心原则

Excel 模板可视化项目基于 Streamlit，用于填写结构化 Excel 模板并验证 Google Sheets 连通性。所有设计与实现必须遵守：

* **模板驱动 UI**：每个已注册模板对应侧边栏一项；主区域根据模板 schema 渲染表单，而非硬编码控件。
* **Excel 结构保真**：解析器读取指定工作表（名称大小写不敏感），保留源工作簿的列标题与行结构。
* **用户自持凭证**：Google Sheets 访问使用终端用户提供的凭证（服务账号 JSON 或 OAuth）；开发环境不得依赖预配置的 Google 权限。
* **权限反馈清晰**：Google 连通性测试须明确报告成功或失败，并给出可操作的排查信息（认证方式、Sheet ID、权限范围、共享设置）。
* **范围最小化**：仅实现各模板所需能力；在需求明确前不引入通用表格引擎或导出流水线。

---

## 2. 技术栈约束

### 2.1 运行时
* **UI**：Streamlit（侧边栏多区块导航）。
* **Excel**：`openpyxl` + `pandas` 读写。
* **Google Sheets**：`gspread` + `google-auth` + `google-auth-oauthlib`。
* **配置**：`config/templates.json` 模板注册表。

### 2.2 Python 编码规范
* **导入**：所有 `import` 置于文件顶部。
* **路径**：仅使用 `pathlib.Path`，禁止 `os.path`。
* **注释**：代码内使用中文。
* **函数间距**：函数之间严格 2 空行；函数体内禁止空行。
* **最小范围**：遵循现有模块布局，避免过早抽象。

### 2.3 项目布局
```
excel-template-viz/
├── app/                 # Streamlit 入口与页面
├── config/              # 模板注册 JSON
├── templates/           # 内置示例工作簿（可选）
├── docs/plans/          # Speckit 规划文档
└── tests/               # pytest（连通性辅助、解析器）
```
