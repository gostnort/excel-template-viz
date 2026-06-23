# Excel 模板可视化录入 / Excel Template Visualization

**全新 Gradio 版本**：基于 Gradio 的 Excel 模板 Web 填表工具，支持多区域检测、Google Sheet 数据源、Phi-4 智能字段匹配与批量导入。  
**New Gradio Version**: Gradio-based Excel template web app with multi-area detection, Google Sheets integration, Phi-4 smart field matching, and bulk import.

> **注意 / Note**: Gradio 版本现在是推荐版本。旧的 Streamlit 版本已在 `master` 分支保留，但不再维护。  
> The Gradio version is now recommended. The legacy Streamlit version is preserved in the `master` branch but no longer maintained.

## 新功能 / New Features

### ✨ Gradio UI 迁移
- **现代化界面**：使用 Gradio 4.0+ 构建，交互更流畅
- **会话管理**：正确的状态管理（`gr.State()`），支持多用户并发
- **防重复提交**：长时间操作自动禁用按钮，避免重复提交

### 🔧 多区域检测（新）
- **批量打印支持**：一页多个证书/标签/名片
- **自动区域检测**：根据 YAML 配置自动检测重复区域
- **灵活布局**：支持垂直（down/up）和水平（right/left）排列
- **配置示例**：见 `templates/examples/` 目录

### 🤖 智能字段匹配 (v2.0 优化)
- **Phi-4 模型**：使用 Phi-4-mini-instruct-GGUF 进行字段匹配
- **语义相似度**：批量计算 embeddings，余弦相似度匹配（<5s 匹配 12 字段）
- **智能 Regex**：自动建议正则表达式（内置模式库 + LLM 生成）
- **本地推理**：无需 API，完全离线运行
- **精确回退**：相似度过低时自动回退到精确匹配
- **模型缓存**：首次加载后复用，提升性能
- **进度显示**：详细的加载和匹配进度条（下载→加载→匹配）

### 📊 数据处理升级
- **Polars 集成**：Google Sheets 数据使用 Polars 处理（高性能）
- **Pandas 保留**：Excel 文件处理继续使用 Pandas（稳定）
- **批量导入**：支持从 Google Sheet 批量导入未录入数据
- **大数据保护**：自动限制显示行数（1000 行），防止内存溢出

## 功能 / Features

- **多模板导航**：将 xlsx 文件放入 `templates/`，自动发现并列出 / **Multi-template navigation**: drop xlsx files into `templates/` and see them in the sidebar.
- **模板配置**：同名 `.json` 或 `.paste.yaml` 保存字段映射与多区域配置 / **Template config**: sidecar JSON or YAML stores field mappings and multi-area sections.
- **数据源 Tab**：完成 OAuth 认证、连接 Sheet、工作表/ID 列选择 / **Data source tab**: OAuth authentication, connect Sheet, pick worksheet/ID column.
- **自动查询填表**：输入 ID 后自动从 Sheet 拉取并使用 Phi-4 智能匹配字段 / **Auto lookup**: enter an ID and auto-fetch with Phi-4 smart matching.
- **批量导入**：刷新未录入数据，勾选后批量导入 / **Bulk import**: refresh unrecorded data, select and import in batch.
- **多区域检测**：自动检测并填充多个重复区域（证书、标签等）/ **Multi-area detection**: auto-detect and fill multiple repeated areas (certificates, labels, etc.).
- **导出 Excel**：编辑后下载更新后的 xlsx / **Export Excel**: download the updated xlsx.

## 快速开始 / Quickstart

### Windows 用户

```batch
# 1. 安装依赖和下载模型
install.bat

# 2. 启动应用
run.bat
```

应用将在浏览器中自动打开：`http://127.0.0.1:8501`

### 其他系统

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt

# 2. 下载 Phi-4 模型
python scripts/download_phi4_model.py

# 3. 启动应用
python gradio_app.py
```

将需要使用的 xlsx 文件复制到 `templates/` 目录，启动后会自动识别。  
Copy your xlsx files into `templates/`; the app will detect them on startup.

## v2.0 优化特性 / v2.0 Optimizations

### 🚀 性能提升
- **语义相似度匹配**：从逐字段 LLM 推理改为批量 embedding 匹配
- **匹配速度**：12 字段从 36s 降至 < 5s（10倍提升）
- **模型缓存**：首次加载后复用，后续调用即时响应
- **准确率**：≥90%（测试集验证）

### 📊 进度显示
- **模型加载进度**：检查版本→定位文件→确认缓存→加载 Tokenizer→加载模型→就绪（10个阶段）
- **下载进度**：实时显示速度和百分比（MB/s）
- **匹配进度**：逐字段显示进度（3/12）

### 🎯 Regex 自动建议
- **内置模式库**：PO号、容器号、日期、邮箱、电话等常见模式
- **LLM 生成**：基于样本值生成定制 regex
- **样本验证**：匹配率 ≥50% 才返回建议
- **YAML 应用**：测试后一键应用到配置文件

### 🔄 输出格式改进
- **YAML 配置格式**：测试输出可直接应用到 `.paste.yaml`
- **包含元数据**：相似度分数、regex 建议标记、样本值
- **应用到 YAML**：点击按钮自动更新配置文件

## 使用流程 / Usage Flow

### 1. 准备模板

1. 在 Excel 中设计模板（单区域或多区域）
2. 创建同名 `.paste.yaml` 配置文件
3. 将两个文件放入 `templates/` 目录

**示例配置** 见 `templates/examples/` 目录，包含：
- 简单员工信息表
- 垂直排列的证书打印
- 商品标签批量打印
- 水平排列的名片打印

### 2. 配置数据源

1. 打开 Gradio UI，选择模板
2. 切换到"数据源"Tab
3. 点击"开始授权"连接 Google 账号
4. 输入 Sheet URL 并连接
5. 选择工作表和 ID 列
6. 配置自动保存

### 3. 数据录入

**方式 1：手动查询**
- 在 ID 字段输入编号
- Phi-4 自动匹配字段并填充

**方式 2：批量导入**
1. 展开"批量导入"面板
2. 点击"刷新数据"
3. 勾选要导入的行
4. 点击"导入选中行"

### 4. 导出

点击"导出 Excel"下载填充完成的文件。

## YAML 配置 / YAML Configuration

### 基本结构

```yaml
determiner: tab          # 字段分隔符
worksheet: "Sheet1"      # 工作表名称

# 多区域配置（可选，用于批量打印）
sections:
  - input_area: "A1:M2"  # 第一个区域
    move_to: "down"      # 移动方向（down/up/right/left）
    offset: 3            # 偏移量（行数或列数）

# 字段映射
FieldName:
  - filed: "源字段名"
    index: 0             # Excel 列索引（从 0 开始）
    regex: "\\d+"        # 正则表达式（可选）
    ID: true             # 是否为 ID 字段（可选）
```

### 完整文档

- **YAML 配置指南**：[docs/yaml_config_guide.md](docs/yaml_config_guide.md)
- **配置示例**：[templates/examples/](templates/examples/)

## Google 数据源（简要）/ Google Data Source (Brief)

1. 侧边栏选择模板，打开"数据源"Tab  
   Select a template in the sidebar, then open the "数据源" tab.

2. 点击"开始授权"，浏览器弹出后登录并允许  
   Click "开始授权", sign in in the browser, and allow access.

3. 填写 Sheet URL 并连接；选择工作表与 ID 列，配置自动保存  
   Enter the Sheet URL and connect; then pick worksheet/ID column, config auto-saves.

4. 切换到"数据录入"Tab，输入 ID 或使用批量导入  
   Switch to "数据录入", type an ID or use bulk import.

## 技术栈 / Tech Stack

- **UI 框架**：Gradio 4.0+
- **数据处理**：
  - Polars（Google Sheets）
  - Pandas（Excel 文件）
- **LLM**：Phi-4-mini-instruct-GGUF（via llama-cpp-python）
- **Excel 操作**：openpyxl
- **Google API**：gspread, google-auth, google-auth-oauthlib

## 文档 / Docs

- **YAML 配置指南** / YAML Configuration Guide: [docs/yaml_config_guide.md](docs/yaml_config_guide.md)
- **配置示例** / Configuration Examples: [templates/examples/](templates/examples/)
- **快速开始** / Quickstart: [QUICKSTART.md](QUICKSTART.md)
- **Speckit 规划** / Speckit Plans: [plans/gradio_ui_migration/](plans/gradio_ui_migration/)
- **数据流核心（Data Sheet Core）** / Data Sheet Core: [plans/data_sheet_core/](plans/data_sheet_core/)（蓝本：[docs/data_flow_design.md](docs/data_flow_design.md)）
- **数据录入 Tab 控件说明** / Data Entry Tab (UI controls, Chinese): [plans/data-input-tab/spec.md](plans/data-input-tab/spec.md)
- **项目概览** / Project Overview: [plans/CODEGRAPH_OVERVIEW.md](plans/CODEGRAPH_OVERVIEW.md)

## 分支说明 / Branch Information

- **`gradio-ui`** (推荐): 新的 Gradio 版本，包含所有新功能
- **`master`**: 旧的 Streamlit 版本（已停止维护，仅作历史保留）

## 贡献 / Contributing

欢迎提交 Issue 和 Pull Request！

## License

MIT
