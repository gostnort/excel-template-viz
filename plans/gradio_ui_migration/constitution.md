# Gradio UI 迁移 - 设计原则和约束

## 1. 核心设计原则

### 1.1 全新分支，零兼容负担

**原则**：gradio-ui 分支是完全独立的新实现，不考虑与旧 Streamlit 版本的兼容性。

**实践**：
- 可以大胆重构代码结构
- 可以删除不再需要的功能（如截图粘贴）
- 可以采用新的技术方案（polars for Sheets）
- 不保留旧代码的技术债务

**约束**：
- 核心业务逻辑不能丢失（模板发现、Excel 读写、Google Sheets 连接、数据填充）
- 用户数据格式保持兼容（Excel 模板、YAML 配置、OAuth tokens）

### 1.2 数据源分治

**原则**：不同数据源使用最适合的工具处理。

**实践**：
- **Excel 处理使用 pandas**：成熟稳定，openpyxl 集成完善，无需迁移
- **Google Sheets 处理使用 polars**：性能优秀，适合大数据量批量操作
- **UI 层数据使用简单结构**：`list[dict[str, str]]`，便于 Gradio 组件交互

**约束**：
- 不在 pandas 和 polars 之间频繁转换
- 仅在数据源边界使用 DataFrame
- UI 层避免直接操作 DataFrame

### 1.3 YAML 驱动的配置

**原则**：Excel 模板的区域布局和字段映射由 YAML 配置文件驱动，无需代码硬编码。

**实践**：
- 区域定义在 YAML `sections` 中
- 字段映射在 YAML 中定义 `filed`, `index`, `regex`
- 区域检测算法读取 YAML 配置，自动生成 dropdown
- 新模板只需提供 `.xlsx` 和 `.paste.yaml` 文件

**约束**：
- YAML 结构必须清晰简洁
- YAML 验证必须完善（格式、必填字段、值域）
- YAML 错误必须有友好的错误提示

### 1.4 LLM 辅助而非依赖

**原则**：Phi-4 模型用于辅助字段匹配，但系统不应完全依赖 LLM。

**实践**：
- Phi-4 失败时回退到简单规则匹配（YAML `filed` 精确匹配）
- 提供手动编辑机制
- LLM 仅用于模糊匹配场景（Sheet 列名与 YAML filed 不完全一致）

**约束**：
- LLM 推理时间不超过 5 秒
- LLM 匹配准确率 ≥90%（否则回退）
- LLM 模型不可用时系统仍可正常工作

### 1.5 用户友好的错误处理

**原则**：所有错误都应有清晰的提示和恢复建议。

**实践**：
- 使用 `gr.Info()` 提示成功操作
- 使用 `gr.Warning()` 提示可恢复错误
- 使用 `gr.Error()` 提示严重错误
- 错误提示包含原因和解决建议
- 记录详细日志便于调试

**约束**：
- 不向用户显示技术栈错误（如 Python traceback）
- 不使用模糊的错误提示（如 "操作失败"）
- 网络错误必须提示用户检查连接或重试

### 1.6 性能优先

**原则**：响应时间直接影响用户体验，优化性能优先级高。

**实践**：
- 使用 polars 处理大数据量
- 批量操作显示进度提示
- 区域检测算法优化（避免重复读取）
- Phi-4 推理使用合适的量化版本（Q4_K_M）

**约束**：
- 应用启动时间 < 10s
- 模板切换 < 2s
- ID 查询 < 3s
- 批量导入 100 行 < 30s

## 2. 代码约束

### 2.1 状态管理规则

**约束**：
- **禁止使用全局 Python 变量存储用户会话数据**
- **必须使用 `gr.State()` 管理会话状态**
- 状态必须显式传递给事件处理函数
- 避免在 State 中存储大对象（如完整 DataFrame）

**示例**：

```python
# ❌ 错误：使用全局变量
current_template = None  # 全局变量

def on_template_change(template_name):
    global current_template
    current_template = template_name  # 会话数据污染

# ✅ 正确：使用 gr.State()
def build_app():
    current_template = gr.State()  # 会话状态
    
    template_selector.change(
        fn=on_template_change,
        inputs=[template_selector, current_template],
        outputs=[current_template]
    )
```

### 2.2 Gradio 交互规则

**约束**：
- 数据获取操作必须使用 `.submit()` 或 `.change()` 事件
- 长时间操作必须设置 `interactive=False` 防止重复提交
- 操作结果必须使用 `gr.Info()` 或 `gr.Warning()` 反馈

**示例**：

```python
def handle_id_lookup(id_value, credentials):
    if not id_value:
        gr.Warning("请输入 ID")
        return gr.update()
    
    try:
        data = fetch_row_by_id(credentials, id_value)
        gr.Info(f"成功获取 ID {id_value} 的数据")
        return gr.update(value=data)
    except Exception as e:
        gr.Warning(f"查询失败：{str(e)}")
        return gr.update()

id_field.change(
    fn=handle_id_lookup,
    inputs=[id_field, credentials_state],
    outputs=[*form_fields]
)
```

### 2.3 动态布局管理

**约束**：
- 动态显示/隐藏组件使用 `gr.update(visible=True/False)`
- 动态更新组件内容使用 `gr.update(value=...)`
- 不在事件处理函数中创建新组件（Gradio 不支持）

### 2.4 文件路径规则

**约束**：
- **必须使用 `pathlib.Path` 处理所有文件路径**
- 禁止使用 `os.path`（用户规则要求）
- 路径拼接使用 `/` 运算符
- 文件存在性检查使用 `Path.exists()`, `Path.is_file()`, `Path.is_dir()`

**示例**：

```python
# ❌ 错误：使用 os.path
import os
config_path = os.path.join("templates", "config.json")

# ✅ 正确：使用 pathlib
from pathlib import Path
config_path = Path("templates") / "config.json"
if config_path.is_file():
    ...
```

### 2.5 错误处理规则

**约束**：
- 所有 I/O 操作必须 try-except
- 所有网络请求必须 try-except
- 所有 LLM 调用必须 try-except
- 错误必须记录日志
- 错误提示必须用户友好

**示例**：

```python
def fetch_row_by_id(worksheet, id_column, id_value):
    try:
        df = fetch_all_rows(worksheet)
        result = df.filter(pl.col(id_column) == id_value)
        
        if result.height == 0:
            logger.warning(f"未找到 ID {id_value}")
            return None
        
        return result.row(0, named=True)
    
    except Exception as e:
        logger.error(f"查询失败: {e}")
        raise GoogleSheetsError(f"无法查询 ID {id_value}，请检查网络连接和 Sheet 权限")
```

### 2.6 日志记录规则

**约束**：
- 使用 Python `logging` 模块
- 日志级别：
  - `DEBUG`: 详细调试信息（函数调用、参数）
  - `INFO`: 正常操作（模板加载、区域检测完成）
  - `WARNING`: 可恢复错误（Sheet 连接失败、ID 查询无结果）
  - `ERROR`: 严重错误（模型加载失败、OAuth 异常）
- 日志格式包含时间、级别、模块、消息

**示例**：

```python
import logging

logger = logging.getLogger(__name__)

def detect_multi_areas(workbook, sheet_name, section_config):
    logger.info(f"开始检测区域: {sheet_name}, 配置: {section_config}")
    
    try:
        areas = []
        # ... 检测逻辑 ...
        logger.info(f"检测到 {len(areas)} 个区域")
        return areas
    
    except Exception as e:
        logger.error(f"区域检测失败: {e}")
        raise
```

## 3. YAML 设计约束

### 3.1 YAML 结构清晰

**约束**：
- 顶层键明确：`sections`, `determiner`, `worksheet`, `order`, 字段名
- sections 配置简洁：`input_area`, `move_to`, `offset`
- 字段映射规则一致：`filed`, `index`, `regex`, `ID`

### 3.2 YAML 向后兼容

**约束**：
- 已有 `.paste.yaml` 文件（无 sections）仍可使用
- 默认单区域行为：整个工作表作为一个区域
- 渐进式迁移：用户可逐步添加 sections 配置

### 3.3 YAML 验证严格

**约束**：
- 加载时验证 YAML 格式
- 验证必填字段存在
- 验证字段值域合法
- 验证失败给出详细错误位置和原因

### 3.4 YAML 文档完整

**约束**：
- 必须提供完整的 YAML 配置指南
- 必须提供多种场景的示例文件
- 示例文件必须有详细注释
- 文档必须包含常见问题和故障排除

## 4. 用户体验约束

### 4.1 操作流程简洁

**约束**：
- 核心流程不超过 5 步
- 每步操作有明确反馈
- 错误可快速恢复
- 批量操作有进度提示

### 4.2 UI 布局合理

**约束**：
- 左侧模板列表，右侧工作区（Streamlit 布局保持）
- Tab 组织功能模块（数据录入、数据源）
- 表单网格布局（每行 11 个字段）
- 折叠面板隐藏高级功能（批量导入）

### 4.3 提示信息友好

**约束**：
- 成功提示简洁明确（`gr.Info("已导入 5 行数据")`）
- 警告提示说明原因和建议（`gr.Warning("未找到 ID 12345，请检查输入")`）
- 错误提示不显示技术细节（`gr.Error("连接 Sheet 失败，请检查网络连接和权限")`）

### 4.4 加载状态明确

**约束**：
- 长时间操作显示加载提示
- 批量操作显示进度
- 模型加载显示下载进度
- 避免界面卡死无响应

## 5. 测试和质量约束

### 5.1 质量检查机制

**约束**：
- 每个 Phase 结束后必须启动 sub-agent 质量检查
- 质量检查不通过不进入下一 Phase
- 质量检查覆盖：功能、性能、代码质量、文档

### 5.2 测试覆盖

**约束**：
- 核心算法必须有单元测试（区域检测、字段匹配）
- 数据处理必须有单元测试（polars 集成、pandas Excel）
- 集成测试覆盖主要流程（模板加载、OAuth、批量导入）
- 性能测试验证响应时间指标

### 5.3 代码质量

**约束**：
- 无重复代码（函数长度 < 50 行）
- 无过长函数（单函数 < 100 行）
- 无魔法数字（常量命名）
- 有类型注解（主要接口函数）
- 有文档字符串（公开 API）

### 5.4 文档完整性

**约束**：
- Speckit 文档齐全（plan, spec, tasks, constitution）
- YAML 配置指南详细准确
- 示例 YAML 可直接使用
- README 更新包含 Gradio 版本说明
- 批处理文件有注释

## 6. 技术选型约束

### 6.1 框架选择

**约束**：
- UI 框架：Gradio 4.x（最新稳定版）
- 数据处理：pandas 2.x（Excel），polars 0.20+（Sheets）
- LLM 加载：llama-cpp-python 0.2+
- OAuth：google-auth, google-auth-oauthlib（保持现有）

### 6.2 模型选择

**约束**：
- LLM 模型：`bartowski/microsoft_Phi-4-mini-instruct-GGUF`
- 量化版本：Q4_K_M（平衡性能和质量）
- 模型大小：2-3GB
- 推理速度：单次推理 < 5s（CPU）

### 6.3 依赖版本

**约束**：
- 所有依赖指定最低版本（`>=`）
- 核心依赖固定主版本（避免破坏性变更）
- 定期检查依赖更新和安全漏洞
- 避免依赖冲突

## 7. 部署和维护约束

### 7.1 一键安装

**约束**：
- `install.bat` 必须包含所有安装步骤
- 自动下载模型（无需手动操作）
- 安装失败给出明确错误和解决建议
- 安装完成后给出使用说明

### 7.2 环境隔离

**约束**：
- 使用虚拟环境（`.venv`）
- 不污染全局 Python 环境
- 依赖完全在 `requirements.txt` 中

### 7.3 数据安全

**约束**：
- OAuth token 不入库（`.gitignore`）
- 模型文件不入库（`.gitignore`）
- 用户 Excel 模板不入库（用户自行管理）
- 导出文件不入库（`.gitignore` exports/）

### 7.4 版本控制

**约束**：
- Git 分支：`gradio-ui`（独立分支）
- 不合并到 `main`（保持旧版本可用）
- Commit 消息清晰（遵循约定式提交）
- 里程碑打 tag（Phase 1-6 完成）

## 8. 文档和注释约束

### 8.1 代码注释

**约束**：
- 不写显而易见的注释（如 `# 定义函数`）
- 注释解释非显而易见的意图、权衡、约束
- 复杂算法必须有注释（如区域检测停止条件）
- 用户规则：不使用 emoji（除非用户明确要求）

### 8.2 文档字符串

**约束**：
- 公开 API 必须有文档字符串
- 文档字符串包含：功能描述、参数说明、返回值说明、示例
- 使用 Google 风格或 NumPy 风格文档字符串

### 8.3 README 和 QUICKSTART

**约束**：
- README 保持双语（中英）
- QUICKSTART 保持双语（中英）
- 包含 Gradio 版本运行说明
- 包含依赖安装和模型下载说明

## 9. 不允许的实践

以下实践在本项目中**严格禁止**：

1. **全局变量存储会话状态**（违反 Gradio 规则）
2. **使用 `os.path` 处理路径**（违反用户规则，必须用 `pathlib`）
3. **硬编码模板配置**（违反 YAML 驱动原则）
4. **忽略错误或静默失败**（违反用户友好原则）
5. **向用户显示技术栈错误**（违反用户体验约束）
6. **在事件处理函数中创建新组件**（Gradio 不支持）
7. **频繁在 pandas 和 polars 之间转换**（违反数据源分治原则）
8. **LLM 推理超过 5 秒不中断**（违反性能约束）
9. **写代码时添加 emoji**（除非用户明确要求，违反用户规则）
10. **在计划模式编辑非 markdown 文件**（违反模式约束）

## 10. 成功标准（重申）

项目成功的**不可妥协**标准：

1. **功能完整性**：所有 10 项功能标准达成
2. **性能指标**：所有 5 项性能指标达成
3. **代码质量**：通过所有 6 个 Phase 的质量检查
4. **文档完整性**：所有 5 项文档标准达成
5. **用户体验**：所有 5 项用户体验标准达成

任何一项不达标，项目不视为完成。