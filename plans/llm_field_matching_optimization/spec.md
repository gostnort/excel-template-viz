# LLM 字段匹配优化 - 技术规格

## 1. 进度显示规格

### 1.1 进度回调接口

```python
from typing import Literal, Callable

ProgressStage = Literal[
    "download",        # 模型下载
    "load_tokenizer",  # 加载 Tokenizer
    "load_model",      # 加载模型权重
    "warmup",          # 模型预热
    "match"            # 字段匹配
]

# 回调签名：(stage, current, total, message)
ProgressCallback = Callable[[ProgressStage, int, int, str], None]
```

### 1.2 下载进度实现

**修改 `ensure_model_downloaded`**：

```python
from huggingface_hub import hf_hub_download
from tqdm.auto import tqdm

class DownloadProgressTqdm(tqdm):
    """自定义 tqdm 类，转发进度到回调"""
    
    def __init__(self, on_progress: ProgressCallback | None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_progress = on_progress
    
    def update(self, n: int = 1):
        super().update(n)
        if self.on_progress:
            current = self.n
            total = self.total or 1
            speed = self.format_dict.get("rate", 0)
            msg = f"下载中... {current/1024/1024:.1f}MB / {total/1024/1024:.1f}MB ({speed/1024/1024:.1f}MB/s)"
            self.on_progress("download", current, total, msg)

def ensure_model_downloaded(
    auto_mode: bool = False,
    on_progress: ProgressCallback | None = None
) -> Path:
    """
    确保模型已下载，支持进度回调
    
    Args:
        auto_mode: 自动选择量化版本
        on_progress: 进度回调函数
    
    Returns:
        模型文件路径
    """
    # ... 选择量化版本 ...
    
    model_path = hf_hub_download(
        repo_id=MODEL_REPO,
        filename=filename,
        local_dir=MODEL_DIR,
        local_dir_use_symlinks=False,
        resume_download=True,
        tqdm_class=lambda *args, **kwargs: DownloadProgressTqdm(on_progress, *args, **kwargs)
    )
    
    return Path(model_path)
```

### 1.3 加载进度实现

**修改 `Phi4FieldMatcher.__init__`**：

```python
def __init__(
    self,
    model_path: str | Path | None = None,
    on_progress: ProgressCallback | None = None
):
    """
    初始化 Phi-4 字段匹配器，支持进度回调
    
    Args:
        model_path: 模型文件路径
        on_progress: 进度回调函数
    """
    # 阶段 1: 检查 GGUF 版本（10%）
    if on_progress:
        on_progress("load_model", 1, 10, "检查 GGUF 版本")
    _ensure_gguf_version()
    
    # 阶段 2: 定位模型文件（20%）
    if on_progress:
        on_progress("load_model", 2, 10, "定位模型文件")
    hub_filename, local_path = _resolve_gguf_source(model_path)
    
    # 阶段 3: 确认 Hub 缓存（30%）
    if on_progress:
        on_progress("load_model", 3, 10, "确认 Hub 缓存")
    _ensure_gguf_hub_accessible(hub_filename)
    
    # 阶段 4: 加载 Tokenizer（50%）
    if on_progress:
        on_progress("load_tokenizer", 5, 10, "加载 Tokenizer")
    
    load_kwargs = {
        "gguf_file": hub_filename,
        "device_map": "cpu",
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
    }
    self.tokenizer = AutoTokenizer.from_pretrained(MODEL_REPO, **load_kwargs)
    
    # 阶段 5: 加载模型权重（90%）
    if on_progress:
        on_progress("load_model", 9, 10, "加载模型权重")
    self.model = AutoModelForCausalLM.from_pretrained(MODEL_REPO, **load_kwargs)
    
    # 阶段 6: 模型就绪（100%）
    self.model.eval()
    if on_progress:
        on_progress("load_model", 10, 10, "模型就绪")
```

### 1.4 匹配进度实现

**修改迭代器返回格式**：

```python
def iter_match_sheet_fields_to_yaml(
    self,
    sheet_row: dict[str, str],
    yaml_dict: dict,
    on_progress: ProgressCallback | None = None
) -> Iterator[tuple[tuple[str, int, int], dict[str, str]]]:
    """
    迭代匹配 Sheet 字段到 YAML 配置
    
    Yields:
        ((stage, current, total), partial_result) 元组
    """
    yaml_fields = self._collect_yaml_fields(yaml_dict)
    total_fields = len(yaml_fields)
    matched: dict[str, str] = {}
    
    for idx, (template_field, hint, regex) in enumerate(yaml_fields, 1):
        # yield 进度信息
        stage = f"正在匹配 {template_field}"
        yield (("match", idx, total_fields), matched.copy())
        
        # ... 匹配逻辑 ...
        
        if on_progress:
            on_progress("match", idx, total_fields, stage)
    
    # 最终结果
    yield (("match", total_fields, total_fields), matched)
```

### 1.5 Gradio Progress 集成

**修改 `gradio_config.py`**：

```python
def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: list | None,
    credentials: Any,
    progress: gr.Progress = gr.Progress()  # 新增参数
):
    """
    测试 LLM 字段匹配，显示进度条
    """
    if not template:
        yield "// 请先选择模板"
        return
    
    try:
        # ... 读取 Sheet 列 ...
        
        if not find_model_file():
            # 下载进度
            def download_progress(stage, current, total, msg):
                progress(current / total, desc=msg)
            
            progress(0, desc="正在下载 Phi-4 模型...")
            ensure_model_downloaded(auto_mode=True, on_progress=download_progress)
        
        # 加载进度
        def load_progress(stage, current, total, msg):
            progress(current / total, desc=msg)
        
        progress(0, desc="正在加载 Phi-4...")
        matcher = Phi4FieldMatcher(on_progress=load_progress)
        
        # 匹配进度
        for (stage_name, current, total), partial in matcher.iter_match_sheet_fields_to_yaml(
            sample_row, yaml_dict
        ):
            progress(current / total, desc=f"{stage_name} ({current}/{total})")
            yield _format_llm_test_json(stage_name, partial, ...)
    
    except Exception as exc:
        logger.error("LLM test failed: %s", exc)
        yield f"// 测试失败：{exc}"
```

## 2. 输出格式规格

### 2.1 测试输出数据结构

```python
@dataclass
class FieldMatchResult:
    """单字段匹配结果"""
    filed: str              # Sheet 列名
    index: int              # 列索引（base 0）
    regex: str | None       # 提取正则
    similarity: float       # 语义相似度分数
    matched_value: str      # 匹配到的单元格值
    regex_suggested: bool   # regex 是否为自动建议

@dataclass
class TestOutput:
    """测试输出完整结构"""
    progress: dict[str, any]                           # 进度信息
    yaml_config: dict[str, list[FieldMatchResult]]     # YAML 配置映射
    sheet_meta: dict[str, any]                         # Sheet 元数据
```

### 2.2 输出 JSON 格式

```json
{
  "progress": {
    "stage": "match",
    "current": 12,
    "total": 12,
    "message": "匹配完成"
  },
  "yaml_config": {
    "P.O. No.": [
      {
        "filed": "PO Number",
        "index": 3,
        "regex": "\\d{4,8}",
        "similarity": 0.92,
        "matched_value": "12345",
        "regex_suggested": true,
        "ID": false
      }
    ],
    "Container No.": [
      {
        "filed": "Container",
        "index": 5,
        "regex": "[A-Z]{4}\\d{7}",
        "similarity": 0.88,
        "matched_value": "ABCD1234567",
        "regex_suggested": true,
        "ID": false
      }
    ],
    "MM": [
      {
        "filed": "recv. date",
        "index": 8,
        "regex": "(\\d{1,2})(?=\\/\\d{1,2})",
        "similarity": 0.75,
        "matched_value": "01",
        "regex_suggested": false,
        "ID": false
      }
    ]
  },
  "sheet_meta": {
    "columns": ["Date", "Vendor", "Status", "PO Number", "Notes", "Container", ...],
    "sample_row": {
      "Date": "2024-01-15",
      "Vendor": "Acme Corp",
      "Status": "Shipped",
      "PO Number": "12345",
      "Notes": "Urgent",
      "Container": "ABCD1234567",
      ...
    }
  }
}
```

### 2.3 格式化函数

```python
def _format_llm_test_json(
    progress_tuple: tuple[str, int, int],
    yaml_config_dict: dict[str, list[FieldMatchResult]],
    sheet_columns: list[str],
    sample_row: dict[str, str] | None = None
) -> str:
    """
    格式化测试输出为 JSON
    
    Args:
        progress_tuple: (stage, current, total)
        yaml_config_dict: YAML 配置字段映射
        sheet_columns: Sheet 列名列表
        sample_row: 样本行数据（可选）
    
    Returns:
        JSON 字符串
    """
    stage, current, total = progress_tuple
    
    output = {
        "progress": {
            "stage": "match",
            "current": current,
            "total": total,
            "message": stage
        },
        "yaml_config": {
            field: [asdict(result) for result in results]
            for field, results in yaml_config_dict.items()
        },
        "sheet_meta": {
            "columns": sheet_columns,
            "sample_row": sample_row
        }
    }
    
    return json.dumps(output, ensure_ascii=False, indent=2)
```

### 2.4 应用到 YAML 功能

```python
def handle_apply_test_result(
    template: TemplateConfig | None,
    test_result_json: str
) -> str:
    """
    将测试结果应用到 YAML 配置
    
    Args:
        template: 模板配置
        test_result_json: 测试输出 JSON
    
    Returns:
        更新后的 YAML 字符串
    """
    if not template:
        return "// 请先选择模板"
    
    try:
        test_output = json.loads(test_result_json)
        yaml_config = test_output["yaml_config"]
        
        # 读取现有 YAML
        yaml_path = TEMPLATES_PATH / template.id / f"{template.id}.paste.yaml"
        with open(yaml_path, encoding="utf-8") as f:
            yaml_dict = yaml.safe_load(f)
        
        # 更新字段映射
        for field, results in yaml_config.items():
            if field in yaml_dict:
                yaml_dict[field] = results
        
        # 写回文件
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_dict, f, allow_unicode=True, sort_keys=False)
        
        gr.Info(f"已更新 {len(yaml_config)} 个字段配置")
        return yaml.dump(yaml_dict, allow_unicode=True, sort_keys=False)
    
    except Exception as exc:
        logger.error("Apply test result failed: %s", exc)
        gr.Error(f"应用失败：{exc}")
        return test_result_json
```

## 3. 语义相似度匹配规格

### 3.1 方案 A：Phi-4 Embeddings（推荐）

```python
import torch
import torch.nn.functional as F

def compute_semantic_similarity(
    self,
    template_fields: list[tuple[str, str]],  # (field_name, hint)
    sheet_columns: list[str],
    sample_values: dict[str, str] | None = None
) -> dict[str, tuple[str, float, int]]:  # field -> (column, similarity, index)
    """
    使用 Phi-4 embeddings 计算语义相似度
    
    算法：
    1. 为每个模板字段构造查询文本
    2. 为每个 Sheet 列构造文本
    3. 使用 Phi-4 最后一层隐藏状态作为 embedding
    4. 计算余弦相似度矩阵
    5. 贪婪匹配：相似度最高且未占用的列
    
    Returns:
        {template_field: (sheet_column, similarity_score, column_index)}
    """
    # 构造查询文本
    field_queries = []
    for field_name, hint in template_fields:
        query = field_name
        if hint and hint != "?":
            query += f" (提示: {hint})"
        field_queries.append(query)
    
    # 构造列文本
    column_texts = []
    for col in sheet_columns:
        text = col
        if sample_values and col in sample_values:
            text += f" (样本值: {sample_values[col]})"
        column_texts.append(text)
    
    # 生成 embeddings
    field_embeddings = self._get_embeddings(field_queries)  # (N, D)
    column_embeddings = self._get_embeddings(column_texts)  # (M, D)
    
    # 计算相似度矩阵
    similarity_matrix = F.cosine_similarity(
        field_embeddings.unsqueeze(1),  # (N, 1, D)
        column_embeddings.unsqueeze(0),  # (1, M, D)
        dim=2
    )  # (N, M)
    
    # 贪婪匹配
    used_columns = set()
    matches = {}
    
    for field_idx, (field_name, _) in enumerate(template_fields):
        # 找相似度最高且未占用的列
        scores = similarity_matrix[field_idx].tolist()
        sorted_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )
        
        for col_idx in sorted_indices:
            if col_idx not in used_columns:
                matches[field_name] = (
                    sheet_columns[col_idx],
                    scores[col_idx],
                    col_idx
                )
                used_columns.add(col_idx)
                break
    
    return matches

def _get_embeddings(self, texts: list[str]) -> torch.Tensor:
    """
    获取文本的 embedding 向量
    
    Args:
        texts: 文本列表
    
    Returns:
        embeddings 张量 (N, D)
    """
    # Tokenize
    inputs = self.tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=128,
        return_tensors="pt"
    )
    
    # Forward pass
    with torch.no_grad():
        outputs = self.model(**inputs, output_hidden_states=True)
    
    # 使用最后一层的 [CLS] token 或平均池化
    last_hidden_state = outputs.hidden_states[-1]  # (B, L, D)
    
    # 平均池化（忽略 padding）
    attention_mask = inputs["attention_mask"].unsqueeze(-1)  # (B, L, 1)
    embeddings = (last_hidden_state * attention_mask).sum(dim=1) / attention_mask.sum(dim=1)  # (B, D)
    
    # L2 归一化
    embeddings = F.normalize(embeddings, p=2, dim=1)
    
    return embeddings
```

### 3.2 方案 B：单次 LLM Prompt（符合原 spec）

```python
def compute_semantic_similarity_llm(
    self,
    template_fields: list[tuple[str, str]],
    sheet_columns: list[str],
    sample_values: dict[str, str] | None = None
) -> dict[str, tuple[str, float, int]]:
    """
    使用单次 LLM prompt 输出完整映射
    
    Prompt 格式：
    ```
    Match Google Sheet columns to YAML template fields. Output JSON only.
    
    Sheet columns with sample values:
    - PO Number: "12345"
    - Container: "ABCD123"
    - Date: "2024-01-15"
    ...
    
    Template fields to match:
    - P.O. No. (hint: PO Number)
    - Container No. (hint: Container)
    - MM (hint: recv. date)
    ...
    
    Output JSON mapping with confidence scores:
    {
      "P.O. No.": {"column": "PO Number", "confidence": 0.95},
      "Container No.": {"column": "Container", "confidence": 0.90},
      ...
    }
    ```
    """
    prompt = self._build_batch_matching_prompt(
        template_fields, sheet_columns, sample_values
    )
    
    response = self._generate(prompt, max_new_tokens=512)
    matches_json = self._parse_json_response(response)
    
    # 转换为统一格式
    matches = {}
    for field, result in matches_json.items():
        column = result["column"]
        confidence = result.get("confidence", 1.0)
        index = sheet_columns.index(column) if column in sheet_columns else -1
        matches[field] = (column, confidence, index)
    
    return matches
```

### 3.3 方案 C：Sentence-Transformers（备选）

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class SentenceTransformerMatcher:
    """使用轻量级 sentence-transformers 模型"""
    
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
    
    def compute_semantic_similarity(
        self,
        template_fields: list[tuple[str, str]],
        sheet_columns: list[str],
        sample_values: dict[str, str] | None = None
    ) -> dict[str, tuple[str, float, int]]:
        """使用预训练 sentence-transformers 模型"""
        # 构造文本
        field_texts = [f"{name} {hint}" for name, hint in template_fields]
        column_texts = [
            f"{col} {sample_values.get(col, '')}" if sample_values else col
            for col in sheet_columns
        ]
        
        # 生成 embeddings
        field_embeddings = self.model.encode(field_texts)
        column_embeddings = self.model.encode(column_texts)
        
        # 计算余弦相似度
        from sklearn.metrics.pairwise import cosine_similarity
        similarity_matrix = cosine_similarity(field_embeddings, column_embeddings)
        
        # 贪婪匹配（同方案 A）
        # ...
```

**方案选择建议**：
- **方案 A（推荐）**：无额外依赖，利用已加载的 Phi-4 模型
- **方案 B**：符合原 spec，但推理时间较长，prompt 工程复杂
- **方案 C**：需额外下载模型（~80MB），但速度快且准确

**默认采用方案 A**，在 `constitution.md` 中注明可配置切换。

### 3.4 集成到自动配置流程

```python
def _iter_llm_match_columns(
    matcher: Phi4FieldMatcher,
    unmatched_fields: list[tuple[str, str]],
    available_columns: list[str],
    sample_row: dict[str, str]  # 不再传 empty_row
) -> Iterator[tuple[str, dict[str, str]]]:
    """
    使用语义相似度批量匹配
    
    Args:
        matcher: Phi-4 匹配器
        unmatched_fields: 未匹配的字段列表
        available_columns: 可用的 Sheet 列
        sample_row: 样本行数据（用于辅助匹配）
    
    Yields:
        (stage, column_map) 元组
    """
    # 批量计算相似度（单次操作）
    yield "正在计算语义相似度...", {}
    
    matches = matcher.compute_semantic_similarity(
        unmatched_fields,
        available_columns,
        sample_row
    )
    
    # 逐个 yield 结果（UI 进度显示）
    column_map = {}
    for idx, (field_name, _) in enumerate(unmatched_fields, 1):
        if field_name in matches:
            column, similarity, index = matches[field_name]
            
            # 相似度阈值判断
            if similarity >= 0.7:
                column_map[field_name] = column
                stage = f"匹配字段 {field_name} → {column} (相似度: {similarity:.2f})"
            else:
                # 相似度过低，LLM 降级单字段匹配
                stage = f"相似度过低 ({similarity:.2f})，使用 LLM 重试 {field_name}"
                llm_result = matcher._llm_match_column(field_name, available_columns, sample_row)
                if llm_result:
                    column_map[field_name] = llm_result
        
        yield stage, column_map.copy()
```

## 4. Regex 自动建议规格

### 4.1 内置模式库

复用 `app/services/paste_mapping_infer.py` 的规则：

```python
REGEX_PATTERNS = {
    "po_number": r"\d{4,8}",
    "container": r"[A-Z]{4}\d{7}",
    "date_mm": r"(\d{1,2})(?=\/\d{1,2})",
    "date_dd": r"(?:\d{1,2}/)(\d{1,2})",
    "date_full": r"(\d{1,2}\/\d{1,2})",
    "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    "phone": r"\d{3}-\d{3}-\d{4}",
    "zipcode": r"\d{5}(?:-\d{4})?",
}

def detect_pattern_type(sample_values: list[str]) -> str | None:
    """
    检测样本值的模式类型
    
    Args:
        sample_values: 样本值列表
    
    Returns:
        模式类型名称或 None
    """
    for pattern_name, regex in REGEX_PATTERNS.items():
        match_count = sum(
            1 for val in sample_values
            if re.search(regex, val)
        )
        
        # 至少 70% 样本匹配
        if match_count / len(sample_values) >= 0.7:
            return pattern_name
    
    return None
```

### 4.2 LLM 生成 Regex

```python
def suggest_regex_for_field(
    self,
    field_name: str,
    column_name: str,
    sample_values: list[str]
) -> str | None:
    """
    为字段建议 regex
    
    优先级：
    1. 内置模式检测
    2. LLM 生成
    3. None（无建议）
    
    Args:
        field_name: 模板字段名
        column_name: Sheet 列名
        sample_values: 样本值列表（至少 3 个）
    
    Returns:
        regex 字符串或 None
    """
    # 步骤 1: 内置模式检测
    pattern_type = detect_pattern_type(sample_values)
    if pattern_type:
        regex = REGEX_PATTERNS[pattern_type]
        logger.info(f"字段 {field_name} 匹配内置模式: {pattern_type}")
        return regex
    
    # 步骤 2: LLM 生成
    prompt = f"""Generate a regex pattern to extract relevant information from the following values:

Field: {field_name}
Column: {column_name}
Sample values:
{chr(10).join(f"- {val}" for val in sample_values[:5])}

Output only the regex pattern, no explanations. Example: \\d{{4,8}}
Regex:"""
    
    try:
        response = self._generate(prompt, max_new_tokens=64, temperature=0.0)
        regex = response.strip()
        
        # 验证 regex 语法
        re.compile(regex)
        
        # 测试在样本值上
        match_count = sum(1 for val in sample_values if re.search(regex, val))
        if match_count / len(sample_values) >= 0.5:
            logger.info(f"LLM 生成 regex for {field_name}: {regex}")
            return regex
        else:
            logger.warning(f"LLM 生成的 regex 匹配率过低: {match_count}/{len(sample_values)}")
            return None
    
    except Exception as exc:
        logger.error(f"Regex 生成失败: {exc}")
        return None
```

### 4.3 集成到匹配流程

```python
def iter_match_sheet_fields_to_yaml(
    self,
    sheet_row: dict[str, str],
    yaml_dict: dict,
    suggest_regex: bool = True  # 新增参数
) -> Iterator[tuple[tuple[str, int, int], dict[str, FieldMatchResult]]]:
    """
    迭代匹配，支持 regex 建议
    """
    # ... 收集字段 ...
    
    for idx, (template_field, hint, existing_regex) in enumerate(yaml_fields, 1):
        # ... 匹配列 ...
        
        # Regex 建议
        regex = existing_regex
        regex_suggested = False
        
        if suggest_regex and (not existing_regex or existing_regex == "None"):
            # 获取多个样本值（从 Sheet 读取）
            sample_values = self._fetch_column_samples(sheet_columns, matched_column, count=5)
            suggested_regex = self.suggest_regex_for_field(
                template_field, matched_column, sample_values
            )
            if suggested_regex:
                regex = suggested_regex
                regex_suggested = True
        
        # 构造结果
        result = FieldMatchResult(
            filed=matched_column,
            index=column_index,
            regex=regex,
            similarity=similarity_score,
            matched_value=sheet_row[matched_column],
            regex_suggested=regex_suggested
        )
        
        matched[template_field] = [result]
        yield (("match", idx, total_fields), matched.copy())
```

## 5. 测试列过滤与反向匹配规格

### 5.1 UI 数据源过滤

```python
def handle_llm_test(
    template: TemplateConfig | None,
    test_cols: list | None,  # 用户选择的测试列
    credentials: Any,
    progress: gr.Progress = gr.Progress()
):
    """
    测试 LLM 字段匹配，支持列过滤
    """
    # ... 读取 Sheet 列 ...
    
    # 列过滤
    if test_cols:
        filtered_columns = [c for c in sheet_columns if c in test_cols]
        filtered_sample = {k: v for k, v in sample_row.items() if k in test_cols}
        gr.Info(f"已过滤测试列：{len(filtered_columns)} / {len(sheet_columns)}")
    else:
        filtered_columns = sheet_columns
        filtered_sample = sample_row
    
    # ... 匹配流程使用 filtered_columns 和 filtered_sample ...
```

### 5.2 反向匹配模式

```python
def match_columns_to_yaml_fields(
    self,
    sheet_columns: list[str],
    yaml_fields: list[tuple[str, str]],  # (field_name, hint)
    sample_values: dict[str, str]
) -> dict[str, tuple[str, float]]:  # column -> (field, similarity)
    """
    反向匹配：Sheet 列 → YAML 字段
    
    用于"选择测试列"场景，用户想知道某个 Sheet 列应该对应哪个模板字段
    
    Args:
        sheet_columns: 要测试的 Sheet 列
        yaml_fields: 所有 YAML 模板字段
        sample_values: 样本值
    
    Returns:
        {sheet_column: (best_matching_field, similarity)}
    """
    # 构造文本
    column_texts = [
        f"{col} (样本值: {sample_values.get(col, '')})"
        for col in sheet_columns
    ]
    field_texts = [
        f"{name} (提示: {hint})" if hint != "?" else name
        for name, hint in yaml_fields
    ]
    
    # 生成 embeddings
    column_embeddings = self._get_embeddings(column_texts)
    field_embeddings = self._get_embeddings(field_texts)
    
    # 计算相似度（列 × 字段）
    similarity_matrix = F.cosine_similarity(
        column_embeddings.unsqueeze(1),
        field_embeddings.unsqueeze(0),
        dim=2
    )
    
    # 对每列找最佳字段
    matches = {}
    for col_idx, col in enumerate(sheet_columns):
        scores = similarity_matrix[col_idx].tolist()
        best_field_idx = max(range(len(scores)), key=lambda i: scores[i])
        best_field = yaml_fields[best_field_idx][0]
        best_score = scores[best_field_idx]
        matches[col] = (best_field, best_score)
    
    return matches
```

### 5.3 反向匹配输出格式

```json
{
  "mode": "reverse_matching",
  "results": [
    {
      "sheet_column": "PO Number",
      "suggested_field": "P.O. No.",
      "similarity": 0.92,
      "sample_value": "12345",
      "suggested_regex": "\\d{4,8}"
    },
    {
      "sheet_column": "Container",
      "suggested_field": "Container No.",
      "similarity": 0.88,
      "sample_value": "ABCD1234567",
      "suggested_regex": "[A-Z]{4}\\d{7}"
    }
  ]
}
```

## 6. 性能优化规格

### 6.1 模型缓存单例

```python
_cached_matcher: Phi4FieldMatcher | None = None
_cached_matcher_lock = threading.Lock()

def get_or_create_field_matcher(
    on_progress: ProgressCallback | None = None
) -> Phi4FieldMatcher | None:
    """
    获取或创建字段匹配器（单例模式）
    
    线程安全，首次加载后复用
    """
    global _cached_matcher
    
    if _cached_matcher is not None:
        logger.info("复用已加载的 Phi-4 模型")
        return _cached_matcher
    
    with _cached_matcher_lock:
        # 双重检查
        if _cached_matcher is not None:
            return _cached_matcher
        
        logger.info("首次加载 Phi-4 模型")
        _cached_matcher = create_field_matcher(on_progress=on_progress)
        return _cached_matcher

def clear_matcher_cache():
    """清除缓存（测试或手动重载时使用）"""
    global _cached_matcher
    _cached_matcher = None
    logger.info("已清除 Phi-4 模型缓存")
```

### 6.2 超时保护

```python
import signal
from contextlib import contextmanager

class TimeoutError(Exception):
    """超时异常"""
    pass

@contextmanager
def timeout(seconds: int):
    """超时上下文管理器"""
    def timeout_handler(signum, frame):
        raise TimeoutError(f"操作超时（{seconds}s）")
    
    # 设置信号处理器
    old_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

def iter_match_sheet_fields_to_yaml(
    self,
    sheet_row: dict[str, str],
    yaml_dict: dict,
    single_field_timeout: int = 10,  # 单字段超时
    total_timeout: int = 60           # 总体超时
) -> Iterator[tuple[tuple[str, int, int], dict[str, FieldMatchResult]]]:
    """
    迭代匹配，支持超时保护
    """
    start_time = time.time()
    
    for idx, (template_field, hint, regex) in enumerate(yaml_fields, 1):
        # 检查总体超时
        if time.time() - start_time > total_timeout:
            logger.warning(f"总体超时，已匹配 {idx-1}/{len(yaml_fields)} 字段")
            yield (("match", idx, len(yaml_fields)), matched)
            break
        
        # 单字段匹配（带超时）
        try:
            with timeout(single_field_timeout):
                # ... 匹配逻辑 ...
                pass
        except TimeoutError:
            logger.warning(f"字段 {template_field} 匹配超时")
            continue
        
        yield (("match", idx, len(yaml_fields)), matched)
```

### 6.3 批处理优化

对于批量导入场景，使用批处理推理：

```python
def batch_match_rows(
    self,
    sheet_rows: list[dict[str, str]],
    yaml_dict: dict,
    batch_size: int = 10
) -> list[dict[str, str]]:
    """
    批量匹配多行数据
    
    性能优化：
    1. 复用语义相似度计算结果
    2. 批量推理（如使用 embedding）
    3. 并行处理（可选）
    """
    # 一次性计算语义相似度（所有行共享）
    yaml_fields = self._collect_yaml_fields(yaml_dict)
    sheet_columns = list(sheet_rows[0].keys())
    
    similarity_map = self.compute_semantic_similarity(
        yaml_fields,
        sheet_columns,
        sheet_rows[0]  # 使用第一行作为样本
    )
    
    # 批量处理
    results = []
    for row in sheet_rows:
        matched = {}
        for field_name in yaml_fields:
            if field_name in similarity_map:
                column, similarity, index = similarity_map[field_name]
                matched[field_name] = row[column]
        results.append(matched)
    
    return results
```

## 7. 单元测试规格

### 7.1 测试文件结构

```
tests/
├── test_phi4_matcher_optimized.py       # 优化后的匹配器测试
├── test_progress_callback.py            # 进度回调测试
├── test_semantic_similarity.py          # 语义相似度测试
├── test_regex_suggestion.py             # Regex 建议测试
└── fixtures/
    ├── test_sheet_data.json             # 测试数据
    └── test_yaml_config.yaml            # 测试配置
```

### 7.2 核心测试用例

```python
import pytest
from app.services.phi4_field_matcher import (
    Phi4FieldMatcher,
    get_or_create_field_matcher,
    ProgressCallback
)

class TestProgressCallback:
    """进度回调测试"""
    
    def test_download_progress(self):
        """测试下载进度回调"""
        progress_calls = []
        
        def callback(stage, current, total, msg):
            progress_calls.append((stage, current, total, msg))
        
        # ... 触发下载 ...
        
        assert len(progress_calls) > 0
        assert progress_calls[-1][0] == "download"
        assert progress_calls[-1][1] == progress_calls[-1][2]  # 完成
    
    def test_load_progress(self):
        """测试加载进度回调"""
        progress_calls = []
        
        matcher = Phi4FieldMatcher(on_progress=lambda *args: progress_calls.append(args))
        
        # 验证加载阶段
        stages = [call[0] for call in progress_calls]
        assert "load_tokenizer" in stages
        assert "load_model" in stages

class TestSemanticSimilarity:
    """语义相似度测试"""
    
    def test_exact_match_high_similarity(self):
        """测试完全匹配的相似度"""
        matcher = get_or_create_field_matcher()
        
        fields = [("P.O. No.", "PO Number")]
        columns = ["PO Number", "Container", "Date"]
        
        matches = matcher.compute_semantic_similarity(fields, columns)
        
        assert "P.O. No." in matches
        column, similarity, index = matches["P.O. No."]
        assert column == "PO Number"
        assert similarity > 0.9
        assert index == 0
    
    def test_fuzzy_match(self):
        """测试模糊匹配"""
        matcher = get_or_create_field_matcher()
        
        fields = [("Container No.", "Container")]
        columns = ["Container ID", "Cnt Number", "Date"]
        
        matches = matcher.compute_semantic_similarity(fields, columns)
        
        assert "Container No." in matches
        column, similarity, _ = matches["Container No."]
        assert column in ["Container ID", "Cnt Number"]
        assert similarity > 0.6

class TestRegexSuggestion:
    """Regex 建议测试"""
    
    def test_builtin_pattern_detection(self):
        """测试内置模式检测"""
        from app.services.phi4_field_matcher import detect_pattern_type
        
        samples = ["12345", "67890", "11223"]
        pattern = detect_pattern_type(samples)
        assert pattern == "po_number"
    
    def test_llm_regex_generation(self):
        """测试 LLM 生成 regex"""
        matcher = get_or_create_field_matcher()
        
        samples = ["ABCD1234567", "EFGH9876543", "IJKL5555555"]
        regex = matcher.suggest_regex_for_field(
            "Container No.", "Container", samples
        )
        
        assert regex is not None
        # 验证 regex 在样本上有效
        import re
        assert all(re.search(regex, s) for s in samples)

class TestReverseMatching:
    """反向匹配测试"""
    
    def test_reverse_match(self):
        """测试反向匹配"""
        matcher = get_or_create_field_matcher()
        
        columns = ["PO Number", "Container"]
        fields = [
            ("P.O. No.", "PO Number"),
            ("Container No.", "Container"),
            ("Date", "recv. date")
        ]
        sample_values = {"PO Number": "12345", "Container": "ABCD123"}
        
        matches = matcher.match_columns_to_yaml_fields(
            columns, fields, sample_values
        )
        
        assert "PO Number" in matches
        field, similarity = matches["PO Number"]
        assert field == "P.O. No."
        assert similarity > 0.8
```

## 8. 文档更新规格

### 8.1 YAML 配置指南更新

在 `docs/yaml_config_guide.md` 添加 Regex 建议部分：

```markdown
## Regex 自动建议

从 v2.0 开始，Phi-4 字段匹配器支持自动生成 regex 建议。

### 触发条件

当字段配置中 `regex` 为空或 `"None"` 时，系统会自动尝试生成建议。

### 建议来源

1. **内置模式库**：常见模式（PO号、容器号、日期）优先匹配
2. **LLM 生成**：基于样本值，Phi-4 生成定制 regex
3. **样本验证**：生成的 regex 在样本值上验证，匹配率 ≥50%

### 测试输出

测试结果中包含 `regex_suggested: true` 标记：

\`\`\`json
{
  "P.O. No.": [{
    "filed": "PO Number",
    "regex": "\\d{4,8}",
    "regex_suggested": true,
    "matched_value": "12345"
  }]
}
\`\`\`

### 应用建议

测试完成后，点击"应用到 YAML"按钮，自动更新配置文件。
```

### 8.2 README 更新

添加优化说明：

```markdown
## v2.0 优化

### 进度显示
- 模型加载显示详细阶段（检查版本、加载 Tokenizer、加载模型）
- 字段匹配显示逐字段进度（3/12）
- 下载模型显示速度和百分比

### 语义相似度匹配
- 从逐字段推理改为批量语义相似度计算
- 匹配速度提升 10 倍（12 字段从 36s → 3s）
- 自动配置利用样本值辅助匹配

### Regex 自动建议
- 内置常见模式库（PO号、容器号、日期、邮箱、电话）
- LLM 生成定制 regex
- 样本验证确保准确性

### 测试输出改进
- 输出 YAML 配置格式（而非字段值）
- 可直接应用到配置文件
- 支持测试列过滤和反向匹配
```

## 9. 部署检查清单

完成所有 Phase 后，执行以下检查：

- [ ] 进度条在所有场景下正常显示
- [ ] 测试输出为 YAML 格式且可应用
- [ ] 语义相似度匹配准确率 ≥90%
- [ ] Regex 建议覆盖常见模式
- [ ] 测试列过滤功能正常
- [ ] 反向匹配给出合理建议
- [ ] 模型缓存复用正常
- [ ] 超时保护不影响已匹配字段
- [ ] 单元测试全部通过
- [ ] 文档更新完整
- [ ] 符合 constitution.md 所有约束
