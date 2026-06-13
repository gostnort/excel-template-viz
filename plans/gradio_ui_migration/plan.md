# Gradio UI 迁移计划

## 概述

创建全新的 `gradio-ui` 分支，将 Streamlit 应用完整迁移到 Gradio 框架。Excel 使用 pandas 处理，Google Sheets 使用 polars 处理。集成 Phi-4-mini-instruct-GGUF 模型用于 Sheet 字段匹配。扩展 YAML 配置支持多区域重复检测。实现批量数据导入功能。采用分阶段开发和质量检查流程。

**关键原则**：
- 全新分支，无需考虑旧版本兼容性
- 源数据为标准数据库表格式
- 每个 Phase 结束后由 sub-agent 检查代码质量和设计符合性
- 所有计划和 Speckit 文档写入 `plans/` 目录

## 主要变更

### 1. 技术栈替换

**UI 框架：Streamlit → Gradio**
- 当前应用使用 Streamlit 三个 Tab 布局（数据录入、粘贴映射、数据源）
- 迁移到 Gradio 使用 `gr.Tabs()` + `gr.TabItem()` 实现相同布局
- 替换核心入口文件：`streamlit_app.py` → `gradio_app.py`
- 核心组件：`app/main.py` → `app/gradio_main.py`

**数据处理：pandas（Excel）+ polars（Google Sheets）**
- **Excel 处理**：继续使用 pandas + openpyxl 读写 Excel 文件
  - `app/services/excel_parser.py` 保持 pandas 实现
  - 成熟稳定，无需迁移
  
- **Google Sheets 处理**：切换到 polars
  - `app/services/google_sheets.py` - 使用 polars DataFrame
  - 从 gspread 获取数据后转换为 `pl.DataFrame`
  - 批量导入等大数据操作使用 polars 提升性能

**LLM 集成：Phi-3.5 Vision → Phi-4-mini-instruct-GGUF**
- **删除**：
  - `app/services/phi35_vision_model.py`
  - `app/services/phi35_vision_paste_infer.py`
  - `app/components/paste_image_button.py`
  - `app/components/paste_image_button_frontend/`
  
- **新增**：
  - `app/services/phi4_field_matcher.py` - 使用 Phi-4-mini-instruct-GGUF
  - 功能：处理从 Google Sheets 获取的字段数据，匹配到 YAML 配置参数
  - 使用 `llama-cpp-python` 加载 GGUF 模型

### 2. YAML 配置扩展

**当前 YAML 结构**：
- 仅支持单行数据填充
- 字段映射规则：`filed`, `index`, `regex`, `ID: true`

**新 YAML 结构**：

源数据是**标准数据库表格式**，不再使用 `rows` 字段。

**区域配置（sections）**

定义 Excel 模板中的输入区域及其重复逻辑：

```yaml
sections:
  - input_area: "A1:M2"      # Excel 区域范围（例如：2行13列）
    move_to: "down"           # 移动方向："down", "up", "left", "right"
    offset: 2                 # 偏移量（行数或列数）
    
  - input_area: "B5:E10"
    move_to: "right"
    offset: 4                 # 向右移动 4 列
```

**区域检测逻辑**：
- 在加载模板时，根据 `input_area`、`move_to`、`offset` 自动检测多区域重复
- 计算下一个区域的坐标（例如 `A1:M2` + `down` + `offset=2` → `A3:M4`）
- 读取下一区域内容，**排除 Excel 公式**（有公式的单元格视为空）
- **停止条件**：
  1. 下一区域内容与第一区域格式不一致（不含公式的内容）
  2. 下一区域完全为空（border, color, formula, text_format 不算内容）
- 将检测到的所有区域添加到 dropdown 选项中

**dropdown 自动生成**

**无需在 YAML 中明确指定 dropdown 行为**，系统自动根据 `sections` 配置：
- 计算所有有效区域
- 为每个区域生成 dropdown 选项（例如："区域 1", "区域 2", ...）
- 用户选择某个区域后，表单自动切换到该区域的数据

### 3. 批量导入功能（步骤 9）

**需求**：增加刷新按钮导入未录入数据，通过勾选批量填写表格

**实现方案**：

在「数据录入」Tab 新增区域：
- 刷新按钮：从 Google Sheet 获取所有数据
- 数据预览表格：显示未录入的行，第一列为勾选框
- 导入按钮：批量添加勾选的行到表单

## 分阶段实施流程

每个 Phase 结束后，启动 sub-agent 进行代码质量检查和设计符合性验证。

### Phase 1: 项目初始化

**任务**：
1. 创建全新 `gradio-ui` 分支（不基于 main，无需兼容性）
2. 更新 `requirements.txt`：移除 Streamlit/OpenVINO/Phi-3.5，添加 Gradio/polars/llama-cpp-python
3. 创建批处理文件：`install.bat`, `run_gradio.bat`, `scripts/download_phi4_model.py`
4. 创建 Speckit 文档结构：`plans/gradio_ui_migration/`
5. 测试依赖安装和模型下载

**质量检查（sub-agent）**：验证分支、依赖、批处理文件、文档完整性

### Phase 2: 数据层和 LLM 集成

**任务**：
1. 更新 `app/services/google_sheets.py`：使用 polars DataFrame
2. 保持 `app/services/excel_parser.py`：继续使用 pandas
3. 实现 `app/services/phi4_field_matcher.py`：Phi-4 GGUF 字段匹配
4. 单元测试：polars 集成、Phi-4 推理

**质量检查（sub-agent）**：验证数据处理正确性、LLM 字段匹配准确率（≥90%）

### Phase 3: YAML 扩展和区域检测

**任务**：
1. 扩展 `app/services/paste_parse_config.py`：解析 `sections` 配置
2. 实现 `app/services/section_detector.py`：区域检测核心算法
3. 单元测试：区域坐标计算、多区域检测、停止条件

**质量检查（sub-agent）**：验证 YAML 解析、区域检测算法、边界情况处理

### Phase 4: Gradio UI 核心

**任务**：
1. 实现 `gradio_app.py` 和 `app/gradio_main.py`：主布局
2. 实现 `app/components/gradio_template_form.py`：数据录入 Tab、动态表单、ID 自动查询
3. 状态管理：`gr.State()` 存储模板配置、表单数据、credentials、区域检测结果

**质量检查（sub-agent）**：验证 UI 布局、组件交互、动态表单、ID 查询流程、状态管理

### Phase 5: 数据源和批量导入

**任务**：
1. 实现 `app/components/gradio_data_source_settings.py`：OAuth、Sheet 连接、配置保存
2. 实现批量导入功能：刷新、预览、勾选、导入
3. OAuth 流程保持不变

**质量检查（sub-agent）**：验证 OAuth 流程、Sheet 连接、批量导入逻辑、性能

### Phase 6: 集成测试和文档

**任务**：
1. 完整流程测试：模板发现、区域检测、OAuth、Sheet 查询、ID 查询、批量导入、导出、打印
2. 编写 `docs/yaml_config_guide.md`：YAML 配置完整说明
3. 创建 `templates/examples/`：单区域、垂直多区域、横向多区域示例
4. 更新 README.md：Gradio 版本运行说明

**质量检查（sub-agent）**：验证端到端流程、文档完整性、示例可用性

## 成功标准

### 功能完整性
- Gradio 应用正常启动，显示模板列表
- Excel 模板自动发现和加载
- 多区域检测：垂直和横向重复区域正确识别
- Dropdown 自动生成：基于区域检测结果
- Google OAuth 流程：认证、token 持久化、Sheet 连接
- ID 自动查询：输入 ID 后自动填充表单
- Phi-4 字段匹配：Sheet 列名准确匹配到 YAML 参数（≥90% 准确率）
- 批量导入：刷新、预览、勾选、导入流程完整
- Excel 导出：正确写入多区域数据
- 打印预览：功能保持正常

### 性能指标
- 应用启动时间 < 10s
- 模板切换响应 < 2s
- ID 查询响应 < 3s
- 批量导入 100 行 < 30s
- Excel 导出 < 5s

### 代码质量
- 每个 Phase 通过 sub-agent 质量检查
- 无明显代码异味（重复代码、过长函数、魔法数字）
- 错误处理完善，用户提示友好
- 日志记录清晰，便于调试

### 文档完整性
- Speckit 文档齐全（plan, spec, tasks, constitution）
- YAML 配置指南详细准确
- 示例 YAML 可直接使用
- README 更新，包含 Gradio 版本说明
- 批处理文件注释清晰

### 用户体验
- UI 布局合理，操作直观
- 错误提示友好，指导性强
- 加载状态明确（使用 `gr.Info()`, `gr.Warning()`）
- 批量操作有进度提示
- 无明显卡顿或崩溃

## 风险和注意事项

1. **全新分支策略**：无需兼容旧版本，可以大胆重构，但要确保核心业务逻辑不丢失
2. **Phi-4 GGUF 模型**：模型大小 2-8GB，确保磁盘空间；CPU 推理较慢，考虑 GPU 加速
3. **区域检测算法复杂度**：需要处理各种 Excel 格式（合并单元格、空行、公式）
4. **Polars 学习曲线**：API 与 pandas 有差异，需熟悉 polars 表达式语法
5. **Gradio 状态管理**：`gr.State()` 需要显式传递，注意内存管理
6. **OAuth 回调**：Gradio 应用需要正确处理浏览器回调
7. **批量导入性能**：大数据量时使用 polars 优势明显，但 UI 需要分页或虚拟滚动
