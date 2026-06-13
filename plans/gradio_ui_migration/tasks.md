# Gradio UI 迁移 - 任务分解

本文档将迁移计划分解为可执行的具体任务，按照 6 个 Phase 组织。

## Phase 1: 项目初始化

### 1.1 创建 gradio-ui 分支
- [ ] 创建全新独立分支 `gradio-ui`（不基于 main）
- [ ] 清理不需要的 Streamlit 文件
- [ ] 初始化 Git 历史记录

### 1.2 更新依赖配置
- [ ] 修改 `requirements.txt`：
  - [ ] 移除：`streamlit`, `openvino`, `optimum-intel`, `transformers`（Vision 相关）
  - [ ] 新增：`gradio>=4.0`, `polars>=0.20`, `llama-cpp-python>=0.2.0`
  - [ ] 保持：`pandas`, `openpyxl`, `gspread`, `google-auth`, `PyYAML`, `Pillow`, `huggingface-hub`

### 1.3 创建批处理文件
- [ ] 创建 `install.bat`：
  - [ ] 创建虚拟环境逻辑
  - [ ] 安装依赖逻辑
  - [ ] 调用模型下载脚本
  - [ ] 成功提示和使用说明
- [ ] 创建 `run_gradio.bat`：
  - [ ] 激活虚拟环境
  - [ ] 启动 `gradio_app.py`
- [ ] 创建 `scripts/download_phi4_model.py`：
  - [ ] 使用 `huggingface_hub.hf_hub_download`
  - [ ] 下载 `bartowski/microsoft_Phi-4-mini-instruct-GGUF`
  - [ ] 保存到 `models/phi4/` 目录
  - [ ] 添加进度提示和错误处理

### 1.4 创建 Speckit 文档
- [x] 创建 `plans/gradio_ui_migration/` 目录
- [x] 编写 `plan.md`（主计划文档）
- [x] 编写 `spec.md`（技术规格）
- [ ] 编写 `tasks.md`（本文档）
- [ ] 编写 `constitution.md`（设计原则）

### 1.5 测试安装流程
- [ ] 在干净环境中运行 `install.bat`
- [ ] 验证依赖安装成功
- [ ] 验证 Phi-4 模型下载成功
- [ ] 检查模型文件大小和完整性

### 1.6 Phase 1 质量检查（sub-agent）
- [ ] 验证分支创建成功且独立
- [ ] 验证 `requirements.txt` 正确性
- [ ] 验证批处理文件可执行
- [ ] 验证模型下载成功
- [ ] 验证 Speckit 文档完整性

---

## Phase 2: 数据层和 LLM 集成

### 2.1 Google Sheets Polars 集成
- [ ] 修改 `app/services/google_sheets.py`：
  - [ ] 导入 `polars as pl`
  - [ ] 重写 `fetch_sheet_preview()` 返回 `pl.DataFrame`
  - [ ] 新增 `fetch_all_rows()` 用于批量导入
  - [ ] 修改 `fetch_row_by_id()` 使用 polars 查询，返回 `dict`
  - [ ] 保持 OAuth 流程不变
  - [ ] 保持 `run_oauth_flow()`, `find_oauth_client_path()` 等函数

### 2.2 确认 Excel Pandas 保持
- [ ] 确认 `app/services/excel_parser.py` 不做修改
- [ ] 确认 `read_template_sheet()` 继续使用 pandas
- [ ] 确认 `write_template_sheet()` 继续使用 pandas + openpyxl

### 2.3 实现 Phi-4 字段匹配器
- [ ] 创建 `app/services/phi4_field_matcher.py`
- [ ] 实现 `Phi4FieldMatcher` 类：
  - [ ] `__init__(model_path)` - 加载 GGUF 模型
  - [ ] `match_sheet_fields_to_yaml(sheet_row, yaml_config)` - 核心方法
  - [ ] `_build_matching_prompt(sheet_row, yaml_config)` - 构建 prompt
  - [ ] `_parse_matching_result(response_text)` - 解析 JSON 结果
  - [ ] 应用 `regex` 规则（如果 YAML 中定义）
  - [ ] 错误处理和日志记录

### 2.4 Prompt 工程
- [ ] 设计 Phi-4 匹配 prompt 模板
- [ ] 测试不同 prompt 格式的准确率
- [ ] 优化 prompt 以提高匹配准确率到 ≥90%

### 2.5 单元测试
- [ ] 创建 `tests/test_google_sheets_polars.py`：
  - [ ] 测试 `fetch_sheet_preview()` 返回 polars DataFrame
  - [ ] 测试 `fetch_all_rows()` 数据完整性
  - [ ] 测试 `fetch_row_by_id()` 查询正确性
  - [ ] 测试边界情况（空 Sheet、单行、特殊字符）
- [ ] 创建 `tests/test_phi4_matcher.py`：
  - [ ] 测试模型加载
  - [ ] 测试字段匹配准确率（准备测试数据集）
  - [ ] 测试 regex 应用
  - [ ] 测试错误情况（模型不可用、无效输入）

### 2.6 Phase 2 质量检查（sub-agent）
- [ ] 验证 polars 集成无错误
- [ ] 验证 Phi-4 模型加载和推理
- [ ] 验证字段匹配准确率 ≥90%
- [ ] 验证数据类型转换正确
- [ ] 验证错误处理完善

---

## Phase 3: YAML 扩展和区域检测

### 3.1 扩展 YAML 配置解析
- [ ] 修改 `app/services/paste_parse_config.py`：
  - [ ] 定义 `SectionConfig` 数据类
  - [ ] 更新 `PasteParseConfig` 添加 `sections` 字段
  - [ ] 实现 `parse_sections_config(yaml_dict)` 解析 sections
  - [ ] 实现 `validate_sections_config(sections)` 验证配置
  - [ ] 更新 `load_paste_parse_config()` 支持 sections

### 3.2 实现区域检测器
- [ ] 创建 `app/services/section_detector.py`
- [ ] 实现核心函数：
  - [ ] `parse_area_range(area_str)` - 解析 "A1:M2" 为坐标
  - [ ] `calculate_next_area(input_area, move_to, offset)` - 计算下一区域
  - [ ] `is_cell_empty_content(cell)` - 判断单元格是否为空（公式视为空）
  - [ ] `detect_multi_areas(workbook, sheet_name, section_config)` - 核心检测算法
- [ ] 实现检测逻辑：
  - [ ] 读取第一区域作为参考格式
  - [ ] 循环计算和读取下一区域
  - [ ] 比较内容一致性（排除公式）
  - [ ] 实现停止条件判断
  - [ ] 返回检测结果列表

### 3.3 处理边界情况
- [ ] 处理合并单元格
- [ ] 处理空行/空列
- [ ] 处理仅有公式的单元格
- [ ] 处理仅有格式无内容的单元格
- [ ] 处理区域超出工作表边界

### 3.4 单元测试
- [ ] 创建 `tests/test_section_detector.py`：
  - [ ] 测试 `parse_area_range()` 各种格式
  - [ ] 测试 `calculate_next_area()` 四个方向
  - [ ] 测试 `is_cell_empty_content()` 各种单元格类型
  - [ ] 测试垂直多区域检测
  - [ ] 测试横向多区域检测
  - [ ] 测试停止条件（内容不一致、完全为空）
  - [ ] 测试边界情况

### 3.5 创建测试 Excel 模板
- [ ] 创建 `tests/fixtures/test_template_single.xlsx` - 单区域模板
- [ ] 创建 `tests/fixtures/test_template_vertical.xlsx` - 垂直多区域模板
- [ ] 创建 `tests/fixtures/test_template_horizontal.xlsx` - 横向多区域模板

### 3.6 Phase 3 质量检查（sub-agent）
- [ ] 验证 YAML 解析正确
- [ ] 验证区域检测算法逻辑正确
- [ ] 验证多区域场景覆盖完整
- [ ] 验证边界情况处理合理
- [ ] 验证测试用例充分

---

## Phase 4: Gradio UI 核心

### 4.1 创建 Gradio 应用入口
- [ ] 创建 `gradio_app.py`：
  - [ ] 导入 `app.gradio_main.build_app`
  - [ ] 调用 `app.launch()`
  - [ ] 配置端口 8501
  - [ ] 配置 `share=False`, `inbrowser=True`

### 4.2 实现主应用构建器
- [ ] 创建 `app/gradio_main.py`
- [ ] 实现 `build_app()` 函数：
  - [ ] 创建 `gr.Blocks()` 容器
  - [ ] 定义全局状态：`current_template`, `credentials_state`, `form_data`, `detected_areas`
  - [ ] 左侧栏布局（scale=1）
  - [ ] 右侧主区域布局（scale=4）
  - [ ] 绑定模板加载事件
  - [ ] 绑定模板切换事件
  - [ ] 返回 `gr.Blocks` 对象

### 4.3 实现模板加载逻辑
- [ ] 实现 `load_templates()` 函数：
  - [ ] 调用 `registry.load_templates()`
  - [ ] 返回模板显示名称列表
  - [ ] 错误处理和日志记录
- [ ] 实现 `on_template_change()` 函数：
  - [ ] 加载选中模板配置
  - [ ] 触发区域检测
  - [ ] 更新状态
  - [ ] 返回更新后的组件

### 4.4 实现数据录入 Tab
- [ ] 创建 `app/components/gradio_template_form.py`
- [ ] 实现 `build_form_tab()` 函数：
  - [ ] Sheet 选择器
  - [ ] 区域选择器
  - [ ] 动态表单容器
  - [ ] 批量导入折叠面板
  - [ ] 导出和打印按钮
  - [ ] 绑定所有事件

### 4.5 实现动态表单渲染
- [ ] 实现 `render_dynamic_form()` 函数：
  - [ ] 根据 `input_area` 解析字段列表
  - [ ] 11 列网格布局
  - [ ] 动态创建 `gr.Textbox()` 组件
  - [ ] 存储字段组件引用
  - [ ] 返回表单容器和组件列表

### 4.6 实现 ID 自动查询
- [ ] 实现 `handle_id_lookup()` 函数：
  - [ ] 获取 ID 字段值
  - [ ] 调用 `fetch_row_by_id()`
  - [ ] 调用 `phi4_match_fields()`
  - [ ] 更新表单字段值
  - [ ] 显示 `gr.Info()` 或 `gr.Warning()`
- [ ] 动态绑定 ID 字段 `.change()` 事件

### 4.7 实现区域切换
- [ ] 实现 `load_area_data()` 函数：
  - [ ] 读取选中区域的 Excel 数据
  - [ ] 更新表单字段值
  - [ ] 返回更新后的组件

### 4.8 实现导出和打印
- [ ] 实现 `handle_export()` 函数：
  - [ ] 收集表单数据
  - [ ] 调用 `write_template_sheet()`
  - [ ] 返回 Excel 文件供下载
- [ ] 实现 `handle_print()` 函数：
  - [ ] 复用 `excel_print.py` 逻辑
  - [ ] 打开打印预览对话框

### 4.9 Phase 4 质量检查（sub-agent）
- [ ] 验证 UI 布局正确
- [ ] 验证组件交互响应
- [ ] 验证动态表单生成正确
- [ ] 验证 ID 自动查询流程
- [ ] 验证状态管理无内存泄漏
- [ ] 验证错误处理和用户提示

---

## Phase 5: 数据源和批量导入

### 5.1 实现数据源 Tab
- [ ] 创建 `app/components/gradio_data_source_settings.py`
- [ ] 实现 `build_datasource_tab()` 函数：
  - [ ] OAuth 状态显示
  - [ ] 连接/断开 Google 账号按钮
  - [ ] Sheet URL 输入框
  - [ ] 连接 Sheet 按钮
  - [ ] 工作表选择器
  - [ ] ID 列选择器
  - [ ] 数据预览表格
  - [ ] 绑定所有事件

### 5.2 实现 OAuth 流程
- [ ] 实现 `handle_oauth_connect()` 函数：
  - [ ] 复用 `google_sheets.run_oauth_flow()`
  - [ ] 更新 `credentials_state`
  - [ ] 更新 OAuth 状态显示
  - [ ] 显示成功/失败提示
- [ ] 实现 `handle_oauth_disconnect()` 函数：
  - [ ] 清除 credentials
  - [ ] 删除 token 文件
  - [ ] 更新状态

### 5.3 实现 Sheet 连接
- [ ] 实现 `handle_sheet_connect()` 函数：
  - [ ] 解析 Sheet URL
  - [ ] 验证 credentials
  - [ ] 获取工作表列表
  - [ ] 预览数据
  - [ ] 更新工作表选择器
  - [ ] 显示预览数据
  - [ ] 错误处理和提示

### 5.4 实现工作表和 ID 列选择
- [ ] 工作表选择器 `.change()` 事件：
  - [ ] 加载选中工作表数据
  - [ ] 更新 ID 列选择器（列名列表）
  - [ ] 更新预览数据
- [ ] ID 列选择器 `.change()` 事件：
  - [ ] 保存配置到 template config
  - [ ] 显示保存成功提示

### 5.5 实现批量导入功能
- [ ] 在数据录入 Tab 实现批量导入 UI：
  - [ ] 使用 `gr.Accordion("批量导入")`
  - [ ] 刷新按钮
  - [ ] 预览表格（可勾选）
  - [ ] 导入按钮
- [ ] 实现 `handle_refresh_unrecorded()` 函数：
  - [ ] 调用 `fetch_all_rows()` 获取所有数据
  - [ ] 获取本地已录入 ID 列表
  - [ ] 对比筛选未录入行
  - [ ] 返回预览数据（带勾选框）
- [ ] 实现 `handle_import_selected()` 函数：
  - [ ] 获取勾选的行
  - [ ] 对每行调用 `phi4_match_fields()`
  - [ ] 批量添加到表单数据
  - [ ] 显示导入成功提示
  - [ ] 更新表单显示

### 5.6 实现配置自动保存
- [ ] 修改 `data_source.py` 支持 Gradio 调用
- [ ] 工作表、ID 列选择后自动保存
- [ ] Sheet URL 连接成功后自动保存

### 5.7 Phase 5 质量检查（sub-agent）
- [ ] 验证 OAuth 流程完整
- [ ] 验证 Sheet 连接稳定
- [ ] 验证批量导入逻辑正确
- [ ] 验证数据对比准确
- [ ] 验证大数据量性能（测试 100、500、1000 行）
- [ ] 验证错误处理和恢复

---

## Phase 6: 集成测试和文档

### 6.1 端到端流程测试
- [ ] 测试模板自动发现流程
- [ ] 测试区域检测（单区域、垂直多区域、横向多区域）
- [ ] 测试 Google OAuth 认证流程
- [ ] 测试 Sheet 连接和数据获取
- [ ] 测试 ID 自动查询流程
- [ ] 测试 Phi-4 字段匹配准确率
- [ ] 测试批量导入流程（小、中、大数据量）
- [ ] 测试 Excel 导出功能
- [ ] 测试打印预览功能
- [ ] 测试错误场景恢复

### 6.2 性能测试
- [ ] 测试应用启动时间
- [ ] 测试模板切换响应时间
- [ ] 测试区域检测性能（不同区域数量）
- [ ] 测试 ID 查询响应时间
- [ ] 测试 Phi-4 推理时间（不同字段数量）
- [ ] 测试批量导入性能（100、500、1000 行）
- [ ] 测试 Excel 导出时间（不同数据量）
- [ ] 测试内存占用
- [ ] 测试 CPU 占用

### 6.3 编写 YAML 配置指南
- [ ] 创建 `docs/yaml_config_guide.md`
- [ ] 文档内容：
  - [ ] YAML 结构概述
  - [ ] sections 配置详解：
    - [ ] `input_area` 格式说明
    - [ ] `move_to` 方向说明
    - [ ] `offset` 偏移量说明
  - [ ] 字段映射规则：
    - [ ] `filed` 字段名匹配
    - [ ] `index` 索引说明
    - [ ] `regex` 正则表达式
    - [ ] `ID: true` 标记说明
  - [ ] 完整示例和注释
  - [ ] 常见问题和技巧
  - [ ] 故障排除指南

### 6.4 创建示例 YAML 模板
- [ ] 创建 `templates/examples/` 目录
- [ ] 创建 `single_area.paste.yaml`：
  - [ ] 单区域示例
  - [ ] 详细注释
- [ ] 创建 `multi_area_vertical.paste.yaml`：
  - [ ] 垂直多区域示例
  - [ ] sections 配置 `move_to: "down"`
  - [ ] 详细注释
- [ ] 创建 `multi_area_horizontal.paste.yaml`：
  - [ ] 横向多区域示例
  - [ ] sections 配置 `move_to: "right"`
  - [ ] 详细注释

### 6.5 更新 README.md
- [ ] 添加 Gradio 版本说明
- [ ] 更新依赖安装指令
- [ ] 添加 Phi-4 模型下载说明
- [ ] 更新快速开始指南
- [ ] 添加 YAML 配置链接
- [ ] 更新截图（如果需要）

### 6.6 代码质量检查
- [ ] 代码格式化（使用 black 或 ruff）
- [ ] 类型注解检查（mypy）
- [ ] 代码异味检查（pylint）
- [ ] 死代码清理
- [ ] 导入优化
- [ ] 日志记录完善
- [ ] 注释和文档字符串完善

### 6.7 Phase 6 质量检查（sub-agent）
- [ ] 验证所有功能端到端流程
- [ ] 验证性能指标达标
- [ ] 验证文档完整性和准确性
- [ ] 验证示例 YAML 可用性
- [ ] 验证用户手册清晰度
- [ ] 验证错误处理和用户提示友好性
- [ ] 验证代码质量和可维护性

---

## 任务优先级说明

### P0（必须完成）
- Phase 1-6 的所有主要任务
- 每个 Phase 的质量检查
- 核心功能实现
- 基础文档

### P1（重要）
- 性能优化
- 完整的错误处理
- 详细的文档和示例
- 单元测试

### P2（可选）
- UI 美化和用户体验优化
- 高级功能（如批量导入分页）
- 扩展文档（故障排除、最佳实践）

## 估算工时

| Phase | 预估时间 | 备注 |
|-------|---------|-----|
| Phase 1 | 2-3 小时 | 项目初始化，依赖配置 |
| Phase 2 | 4-6 小时 | 数据层迁移，LLM 集成 |
| Phase 3 | 6-8 小时 | YAML 扩展，区域检测算法 |
| Phase 4 | 8-10 小时 | Gradio UI 核心，动态表单 |
| Phase 5 | 6-8 小时 | 数据源，批量导入 |
| Phase 6 | 4-6 小时 | 集成测试，文档 |
| **总计** | **30-41 小时** | 约 4-5 个工作日 |

*注：以上为开发时间估算，不含质量检查和修复时间*