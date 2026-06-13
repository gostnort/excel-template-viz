# Gradio UI 迁移 - 技术规格

## 1. 架构设计

### 1.1 应用层次结构

```
gradio_app.py (入口)
  └── app/gradio_main.py (主应用构建)
      ├── 左侧栏：模板选择
      │   └── app/services/registry.py (模板扫描)
      │
      └── 右侧主区域
          ├── Tab: 数据录入
          │   ├── app/components/gradio_template_form.py
          │   ├── app/services/section_detector.py (区域检测)
          │   └── app/services/phi4_field_matcher.py (字段匹配)
          │
          └── Tab: 数据源
              ├── app/components/gradio_data_source_settings.py
              └── app/services/google_sheets.py (polars)
```

### 1.2 数据流架构

```
Excel模板 (.xlsx) → pandas DataFrame → 表单数据 (list[dict])
                                         ↓
                                    Gradio UI 显示
                                         ↓
Google Sheet → polars DataFrame → Phi-4匹配 → 填充表单
                                              ↓
                                          导出Excel
```

## 2. 核心模块规格

### 2.1 区域检测器 (`app/services/section_detector.py`)

**核心函数**：

```python
def parse_area_range(area_str: str) -> tuple[int, int, int, int]:
    """
    解析 Excel 区域字符串为坐标
    
    Args:
        area_str: "A1:M2" 格式的区域字符串
    
    Returns:
        (start_row, start_col, end_row, end_col) 元组
        行列索引从 1 开始（Excel 坐标系）
    
    示例:
        "A1:M2" → (1, 1, 2, 13)
        "B5:E10" → (5, 2, 10, 5)
    """

def calculate_next_area(
    input_area: str,
    move_to: str,
    offset: int
) -> str:
    """
    计算下一个区域坐标
    
    Args:
        input_area: 当前区域 "A1:M2"
        move_to: 移动方向 "down" | "up" | "left" | "right"
        offset: 偏移量（行数或列数）
    
    Returns:
        下一区域字符串
    
    示例:
        ("A1:M2", "down", 2) → "A3:M4"
        ("A1:M2", "right", 3) → "D1:P2"
    """

def is_cell_empty_content(cell) -> bool:
    """
    判断单元格是否为空内容
    
    规则：
    - cell.value 为 None → 空
    - cell.value 为空字符串 → 空
    - cell.data_type == 'f' (公式) → 空
    - border, fill, font 不算内容
    
    Args:
        cell: openpyxl Cell 对象
    
    Returns:
        True 表示空，False 表示有内容
    """

def detect_multi_areas(
    workbook,
    sheet_name: str,
    section_config: dict
) -> list[dict]:
    """
    检测多区域重复
    
    Args:
        workbook: openpyxl Workbook 对象
        sheet_name: 工作表名称
        section_config: sections 配置字典
            {
                "input_area": "A1:M2",
                "move_to": "down",
                "offset": 2
            }
    
    Returns:
        检测到的区域列表
        [
            {"index": 1, "area": "A1:M2", "has_data": True},
            {"index": 2, "area": "A3:M4", "has_data": False},
            ...
        ]
    
    算法：
    1. 解析第一区域坐标
    2. 读取第一区域内容作为参考格式
    3. 循环：
       a. 计算下一区域坐标
       b. 读取下一区域内容
       c. 比较内容一致性（排除公式单元格）
       d. 检查停止条件：
          - 内容格式不一致 → 停止
          - 完全为空（不含公式的内容） → 停止
       e. 添加到结果列表
    4. 返回所有检测到的区域
    """
```

### 2.2 Phi-4 字段匹配器 (`app/services/phi4_field_matcher.py`)

**类定义**：

```python
class Phi4FieldMatcher:
    """使用 Phi-4 GGUF 模型匹配 Google Sheet 字段到 YAML 配置"""
    
    def __init__(self, model_path: str):
        """
        初始化模型
        
        Args:
            model_path: Phi-4 GGUF 模型文件路径
                       默认: models/phi4/Phi-4-mini-instruct-Q4_K_M.gguf
        """
        from llama_cpp import Llama
        
        self.model = Llama(
            model_path=model_path,
            n_ctx=4096,      # 上下文长度
            n_threads=4,     # CPU 线程数
            verbose=False
        )
    
    def match_sheet_fields_to_yaml(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict
    ) -> dict[str, str]:
        """
        匹配 Sheet 字段到 YAML 参数
        
        Args:
            sheet_row: Google Sheet 行数据
                      {"PO Number": "12345", "Container": "ABCD123", ...}
            
            yaml_config: YAML 配置字典
                        {
                            "P.O. No.": [{"filed": "PO Number", ...}],
                            "Container No.": [{"filed": "Container", ...}],
                            ...
                        }
        
        Returns:
            匹配后的表单字段值
            {"P.O. No.": "12345", "Container No.": "ABCD123", ...}
        
        算法：
        1. 构建 prompt：
           - 列出所有 Sheet 列名和值
           - 列出所有 YAML filed 参数
           - 要求模型输出 JSON 格式的匹配结果
        2. 调用模型推理
        3. 解析 JSON 结果
        4. 应用 regex 规则（如果 YAML 中定义）
        5. 返回匹配结果
        """
    
    def _build_matching_prompt(
        self,
        sheet_row: dict[str, str],
        yaml_config: dict
    ) -> str:
        """构建匹配 prompt"""
    
    def _parse_matching_result(self, response_text: str) -> dict[str, str]:
        """解析模型输出的 JSON 结果"""
```

**Prompt 模板**：

```
You are a data mapping assistant. Match Google Sheet columns to YAML field configurations.

Google Sheet Row Data:
- PO Number: "12345"
- Container: "ABCD123"
- Date: "2024-01-15"
...

YAML Field Configurations:
- P.O. No.: filed="PO Number", regex="^\\d+"
- Container No.: filed="Container"
- MM/DD: filed="Date"
...

Task: Output JSON mapping YAML fields to Sheet values:
{
  "P.O. No.": "12345",
  "Container No.": "ABCD123",
  "MM/DD": "2024-01-15"
}

Only output valid JSON, no explanations.
```

### 2.3 Google Sheets Polars 集成 (`app/services/google_sheets.py`)

**核心函数**：

```python
import polars as pl

def fetch_sheet_preview(
    worksheet,
    max_rows: int = 20
) -> pl.DataFrame:
    """
    预览 Sheet 数据（使用 polars）
    
    Args:
        worksheet: gspread Worksheet 对象
        max_rows: 最多预览行数
    
    Returns:
        polars DataFrame
    """
    values = worksheet.get_all_values()
    if not values:
        return pl.DataFrame()
    
    headers = values[0]
    data = values[1:max_rows+1]
    
    return pl.DataFrame(data, schema=headers, orient="row")

def fetch_all_rows(worksheet) -> pl.DataFrame:
    """
    获取所有 Sheet 数据（用于批量导入）
    
    Returns:
        polars DataFrame，所有行数据
    """
    values = worksheet.get_all_values()
    if not values:
        return pl.DataFrame()
    
    headers = values[0]
    data = values[1:]
    
    return pl.DataFrame(data, schema=headers, orient="row")

def fetch_row_by_id(
    worksheet,
    id_column: str,
    id_value: str
) -> dict[str, str] | None:
    """
    按 ID 查询单行
    
    Args:
        worksheet: gspread Worksheet 对象
        id_column: ID 列名
        id_value: 要查询的 ID 值
    
    Returns:
        查询到的行数据（dict）或 None
    """
    df = fetch_all_rows(worksheet)
    
    # polars 查询
    result = df.filter(pl.col(id_column) == id_value)
    
    if result.height == 0:
        return None
    
    # 转换为 dict
    return result.row(0, named=True)
```

### 2.4 YAML 配置解析扩展 (`app/services/paste_parse_config.py`)

**新增数据结构**：

```python
from dataclasses import dataclass

@dataclass
class SectionConfig:
    """区域配置"""
    input_area: str          # "A1:M2"
    move_to: str             # "down" | "up" | "left" | "right"
    offset: int              # 偏移量

@dataclass
class PasteParseConfig:
    """扩展后的 YAML 配置"""
    determiner: str = "tab"
    worksheet: str | None = None
    order: list[str] | None = None
    sections: list[SectionConfig] | None = None  # 新增
    field_mappings: dict = None  # 原有字段映射
```

**新增函数**：

```python
def parse_sections_config(yaml_dict: dict) -> list[SectionConfig]:
    """
    解析 sections 配置
    
    Args:
        yaml_dict: YAML 字典
    
    Returns:
        SectionConfig 列表
    
    验证：
    - input_area 格式正确（"A1:M2"）
    - move_to 值有效（"down", "up", "left", "right"）
    - offset 为正整数
    """

def validate_sections_config(sections: list[SectionConfig]) -> list[str]:
    """
    验证 sections 配置
    
    Returns:
        错误信息列表（空列表表示无错误）
    """
```

## 3. Gradio 组件规格

### 3.1 主应用布局 (`app/gradio_main.py`)

```python
def build_app() -> gr.Blocks:
    """
    构建 Gradio 应用
    
    Returns:
        gr.Blocks 对象
    """
    with gr.Blocks(title="Excel 模板可视化 - Gradio") as app:
        # 状态管理
        current_template = gr.State()
        credentials_state = gr.State()
        form_data = gr.State(value=[])
        detected_areas = gr.State()
        
        with gr.Row():
            # 左侧栏（scale=1）
            with gr.Column(scale=1):
                template_selector = gr.Radio(
                    label="选择模板",
                    choices=[],  # 动态加载
                    value=None
                )
                shutdown_btn = gr.Button("关闭应用", variant="secondary")
            
            # 右侧主区域（scale=4）
            with gr.Column(scale=4):
                with gr.Tabs():
                    # Tab 1: 数据录入
                    with gr.TabItem("数据录入"):
                        build_form_tab(
                            current_template,
                            credentials_state,
                            form_data,
                            detected_areas
                        )
                    
                    # Tab 2: 数据源
                    with gr.TabItem("数据源"):
                        build_datasource_tab(
                            current_template,
                            credentials_state
                        )
        
        # 事件绑定
        app.load(fn=load_templates, outputs=[template_selector])
        template_selector.change(
            fn=on_template_change,
            inputs=[template_selector],
            outputs=[current_template, detected_areas]
        )
        
        return app
```

### 3.2 数据录入 Tab (`app/components/gradio_template_form.py`)

```python
def build_form_tab(
    current_template: gr.State,
    credentials_state: gr.State,
    form_data: gr.State,
    detected_areas: gr.State
):
    """
    构建数据录入 Tab
    
    组件：
    - Sheet 选择器
    - 区域选择器（基于检测结果）
    - 动态表单（11 列网格）
    - ID 字段自动查询
    - 批量导入折叠面板
    - 导出和打印按钮
    """
    with gr.Column():
        # Sheet 选择器
        sheet_selector = gr.Dropdown(
            label="选择工作表",
            choices=[],
            interactive=True
        )
        
        # 区域选择器
        area_selector = gr.Dropdown(
            label="选择区域",
            choices=[],
            interactive=True
        )
        
        # 动态表单容器
        form_container = gr.Column(visible=False)
        
        with form_container:
            # 表单字段（动态生成）
            form_fields = []  # 存储所有字段组件
            
            # 网格布局（每行 11 个字段）
            # 动态创建 gr.Textbox()
        
        # 批量导入
        with gr.Accordion("批量导入", open=False):
            refresh_btn = gr.Button("🔄 从 Google Sheet 刷新数据")
            import_preview = gr.Dataframe(
                headers=["选择", "ID", "..."],
                interactive=True
            )
            import_btn = gr.Button("✅ 导入选中行")
        
        # 操作按钮
        with gr.Row():
            export_btn = gr.Button("导出 Excel", variant="primary")
            print_btn = gr.Button("打印预览")
    
    # 事件绑定
    area_selector.change(
        fn=load_area_data,
        inputs=[current_template, area_selector],
        outputs=[form_container, *form_fields]
    )
    
    # ID 字段自动查询（动态绑定）
    # id_field.change(
    #     fn=handle_id_lookup,
    #     inputs=[id_field, credentials_state, current_template],
    #     outputs=[*form_fields]
    # )
```

### 3.3 数据源 Tab (`app/components/gradio_data_source_settings.py`)

```python
def build_datasource_tab(
    current_template: gr.State,
    credentials_state: gr.State
):
    """
    构建数据源 Tab
    
    组件：
    - OAuth 设置向导
    - 连接 Google 账号按钮
    - Sheet URL 输入
    - 连接 Sheet 按钮
    - 工作表选择器
    - ID 列选择器
    - 配置自动保存
    """
    with gr.Column():
        # OAuth 区域
        oauth_status = gr.Textbox(
            label="OAuth 状态",
            value="未连接",
            interactive=False
        )
        connect_oauth_btn = gr.Button("连接 Google 账号")
        disconnect_oauth_btn = gr.Button("断开连接", visible=False)
        
        # Sheet 连接
        sheet_url = gr.Textbox(
            label="Google Sheet URL",
            placeholder="https://docs.google.com/spreadsheets/d/..."
        )
        connect_sheet_btn = gr.Button("连接 Sheet")
        
        # 工作表和 ID 列选择
        worksheet_selector = gr.Dropdown(
            label="选择工作表",
            choices=[],
            interactive=True
        )
        id_column_selector = gr.Dropdown(
            label="ID 列",
            choices=[],
            interactive=True
        )
        
        # 预览
        preview_df = gr.Dataframe(
            label="数据预览",
            headers=[],
            interactive=False
        )
    
    # 事件绑定
    connect_oauth_btn.click(
        fn=handle_oauth_connect,
        outputs=[credentials_state, oauth_status, connect_oauth_btn, disconnect_oauth_btn]
    )
    
    connect_sheet_btn.click(
        fn=handle_sheet_connect,
        inputs=[sheet_url, credentials_state],
        outputs=[worksheet_selector, preview_df]
    )
```

## 4. 数据模型

### 4.1 表单数据结构

```python
# 表单行列表（UI 层）
FormRows = list[dict[str, str]]

# 示例
form_rows = [
    {
        "P.O. No.": "12345",
        "Container No.": "ABCD123",
        "MM": "01",
        "DD": "15",
        ...
    },
    {
        "P.O. No.": "12346",
        ...
    }
]
```

### 4.2 区域检测结果

```python
# 检测到的区域列表
DetectedAreas = list[dict[str, any]]

# 示例
detected_areas = [
    {
        "index": 1,
        "area": "A1:M2",
        "start_row": 1,
        "start_col": 1,
        "end_row": 2,
        "end_col": 13,
        "has_data": True
    },
    {
        "index": 2,
        "area": "A3:M4",
        "start_row": 3,
        "start_col": 1,
        "end_row": 4,
        "end_col": 13,
        "has_data": False
    }
]
```

## 5. 批处理文件规格

### 5.1 install.bat

```batch
@echo off
REM 创建虚拟环境
python -m venv .venv

REM 激活虚拟环境
call .venv\Scripts\activate.bat

REM 升级 pip
python -m pip install --upgrade pip

REM 安装依赖
pip install -r requirements.txt

REM 下载 Phi-4 模型
echo.
echo 正在下载 Phi-4 模型...
python scripts/download_phi4_model.py

echo.
echo 安装完成！运行 run_gradio.bat 启动应用
pause
```

### 5.2 run_gradio.bat

```batch
@echo off
call .venv\Scripts\activate.bat
python gradio_app.py
```

### 5.3 scripts/download_phi4_model.py

```python
from pathlib import Path
from huggingface_hub import hf_hub_download

MODEL_REPO = "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
MODEL_FILE = "Phi-4-mini-instruct-Q4_K_M.gguf"
MODEL_DIR = Path("models/phi4")

def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"下载 Phi-4 模型：{MODEL_REPO}/{MODEL_FILE}")
    print("模型大小约 2-3GB，请耐心等待...")
    
    model_path = hf_hub_download(
        repo_id=MODEL_REPO,
        filename=MODEL_FILE,
        local_dir=MODEL_DIR,
        local_dir_use_symlinks=False
    )
    
    print(f"模型已下载到：{model_path}")
    print("下载完成！")

if __name__ == "__main__":
    main()
```

## 6. 性能要求

### 6.1 响应时间

| 操作 | 目标时间 | 最大可接受时间 |
|------|---------|---------------|
| 应用启动 | < 5s | < 10s |
| 模板切换 | < 1s | < 2s |
| 区域检测 | < 2s | < 5s |
| ID 查询（Sheet） | < 2s | < 3s |
| Phi-4 字段匹配 | < 3s | < 5s |
| 批量导入 100 行 | < 20s | < 30s |
| Excel 导出 | < 3s | < 5s |

### 6.2 资源消耗

| 资源 | 限制 |
|------|-----|
| 内存 | < 1GB（不含模型） |
| 模型内存 | < 4GB（Phi-4 Q4_K_M） |
| 磁盘空间 | < 3GB（模型） |
| CPU 占用 | < 50%（平均） |

## 7. 错误处理

### 7.1 错误类型和处理策略

| 错误类型 | 处理策略 |
|---------|---------|
| 模板文件不存在 | `gr.Warning()` 提示用户，返回空列表 |
| Excel 文件损坏 | `gr.Error()` 提示用户，记录日志 |
| Sheet 连接失败 | `gr.Warning()` 提示重试，提供诊断信息 |
| OAuth 认证失败 | `gr.Error()` 提示用户重新认证 |
| Phi-4 模型加载失败 | `gr.Error()` 提示检查模型文件，回退到无 LLM 模式 |
| 区域检测异常 | 记录日志，使用默认单区域 |
| 批量导入超时 | 分批处理，显示进度 |

### 7.2 日志级别

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# INFO: 正常操作（模板加载、区域检测完成）
# WARNING: 可恢复错误（Sheet 连接失败、ID 查询无结果）
# ERROR: 严重错误（模型加载失败、OAuth 异常）
```

## 8. 测试策略

### 8.1 单元测试

- `test_section_detector.py`：区域检测算法
- `test_phi4_matcher.py`：Phi-4 字段匹配
- `test_google_sheets_polars.py`：polars 数据处理

### 8.2 集成测试

- 模板加载 → 区域检测 → 表单渲染
- OAuth → Sheet 连接 → 数据获取
- ID 查询 → Phi-4 匹配 → 表单填充
- 批量导入 → 数据验证 → Excel 导出

### 8.3 性能测试

- 区域检测性能（不同区域数量）
- 批量导入性能（不同行数）
- Phi-4 推理性能（不同字段数量）

## 9. 部署和发布

### 9.1 依赖打包

```
requirements.txt:
- gradio>=4.0
- polars>=0.20
- llama-cpp-python>=0.2.0
- pandas>=2.0
- openpyxl>=3.1
- gspread>=6.0
- google-auth>=2.0
- google-auth-oauthlib>=1.2
- PyYAML>=6.0
- Pillow>=10.0
- huggingface-hub>=0.23.0
```

### 9.2 首次运行流程

1. 运行 `install.bat`
2. 等待依赖安装和模型下载
3. 运行 `run_gradio.bat`
4. 浏览器自动打开应用

### 9.3 版本控制

- Git 分支：`gradio-ui`
- 不合并到 `main`（全新分支）
- `.gitignore` 排除：
  - `.venv/`
  - `models/phi4/`
  - `app/oauth/authorized_user.json`
  - `exports/`