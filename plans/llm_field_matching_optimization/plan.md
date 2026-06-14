# LLM 字段匹配优化计划

## 概述

优化 Phi-4 字段匹配流程，实现细粒度进度显示、语义相似度批量匹配、regex 自动建议，并统一测试与配置的输出格式。

**关键目标**：
- 添加模型加载和匹配的详细进度条（避免 command prompt 关闭导致进度不可见）
- 将测试输出改为 YAML 配置格式（而非当前的字段值映射）
- 实现基于语义相似度的批量匹配（替代逐字段 LLM 推理）
- 自动生成 regex 建议（当前 Phi-4 不生成 regex）
- 支持测试时选择特定列（反向匹配：列 → 字段）

## 当前问题诊断

### 与 spec.md 的偏差

现有 `plans/gradio_ui_migration/spec.md` 第 138-206 行定义的 Phi-4 字段匹配器期望：

```python
def match_sheet_fields_to_yaml(
    sheet_row: dict[str, str],
    yaml_config: dict
) -> dict[str, str]:
    """
    算法：
    1. 构建 prompt：列出所有 Sheet 列名和值 + YAML filed 参数
    2. 调用模型推理（单次）
    3. 解析 JSON 结果
    4. 应用 regex 规则
    5. 返回匹配结果
    """
```

**实际实现偏差**（`app/services/phi4_field_matcher.py`）：

| 维度 | spec 期望 | 实际实现 | 偏差原因 |
|------|----------|---------|---------|
| 后端 | llama-cpp-python | Transformers + GGUF | 技术选型变更 |
| 匹配策略 | 单次批量 prompt | 逐字段 N 次推理 | 实现简化 |
| 样本值使用 | 辅助匹配 | 自动配置不使用（传 empty_row） | 实现不完整 |
| regex 生成 | 隐含支持 | 不生成，只应用已有 regex | 功能缺失 |
| 进度显示 | < 5s 推理 | 静态文案，无百分比 | 未实现 |
| 测试输出 | 未明确 | 字段值映射，非 YAML 配置 | 未明确定义 |

### 用户需求分析

用户反馈的具体需求：

1. **进度可见性**：command prompt 会关闭，需要进度条显示各阶段（加载权重、转换权重、获取数据源、找寻匹配结果）
2. **测试输出格式**：应输出 YAML 配置片段（filed/index/regex），而非字段值
3. **匹配流程优化**：
   - 测试时选择特定列 → 使用该列找 YAML 字段的最高相似度 → 给出 regex 建议
   - 配置时也应显示进度
4. **真实使用场景**：数据源 field name 与 YAML fieldname 语义相似度匹配，登记 index（base 0）和 regex

## 分阶段实施

### Phase 1: 进度显示基础设施（2-3 小时）

**目标**：为模型加载和字段匹配建立统一进度接口。

**任务**：
1. 设计进度回调接口（ProgressStage, ProgressCallback）
2. 为 `ensure_model_downloaded` 添加下载进度（自定义 tqdm 类）
3. 为 `Phi4FieldMatcher.__init__` 添加加载阶段标记
4. 在 `gradio_config.py` 集成 `gr.Progress()` 组件
5. 修改匹配迭代器 yield 三元组：`(stage, current, total), result`

**成功标准**：
- UI 显示进度条和阶段描述
- 下载时显示速度和百分比
- 加载时显示当前阶段（检查版本、加载 tokenizer、加载模型）
- 匹配时显示当前字段和总字段数

**受影响文件**：
- `app/services/phi4_field_matcher.py`
- `app/components/gradio_config.py`

### Phase 2: 输出格式重构（2-3 小时）

**目标**：将测试输出改为可直接应用的 YAML 配置格式。

**任务**：
1. 重写 `_format_llm_test_json` 输出结构：
   ```json
   {
     "progress": {"stage": "match", "current": 12, "total": 12},
     "yaml_config": {
       "P.O. No.": [{
         "filed": "PO Number",
         "index": 3,
         "regex": "\\d{4,8}",
         "similarity": 0.92,
         "matched_value": "12345"
       }]
     }
   }
   ```
2. 添加"应用到 YAML"按钮
3. 实现应用逻辑：解析测试结果 → 更新 `.paste.yaml` 文件

**成功标准**：
- 测试输出可直接复制到 YAML 配置
- 保留 `matched_value` 用于验证
- 点击按钮后 YAML 文件自动更新

**受影响文件**：
- `app/components/gradio_config.py`（`_format_llm_test_json`, `handle_llm_test`）

### Phase 3: 语义相似度匹配（4-6 小时）

**目标**：从逐字段推理改为批量语义相似度匹配。

**任务**：
1. 在 `Phi4FieldMatcher` 添加 `compute_semantic_similarity` 方法
2. 实现方案选择：
   - **方案 A（推荐）**：Phi-4 生成 embeddings，计算余弦相似度
   - **方案 B**：单次 LLM prompt 输出完整映射（符合原 spec）
   - **方案 C**：轻量级 embedding 模型（sentence-transformers）
3. 重构 `_iter_llm_match_columns` 使用批量匹配
4. 修改自动配置流程读取样本行（不再传 empty_row）
5. 保留精确匹配优先级：精确 > 语义（≥0.7）> LLM 降级

**成功标准**：
- 匹配准确率 ≥90%
- 总推理时间从 N×3s 降至 < 5s
- 自动配置利用样本值辅助匹配

**受影响文件**：
- `app/services/phi4_field_matcher.py`（核心重构）
- `app/components/gradio_config.py`（调用方式调整）

### Phase 4: Regex 自动建议（3-4 小时）

**目标**：为匹配结果自动生成 regex 建议。

**任务**：
1. 添加 `suggest_regex_for_field` 方法
2. 实现推断策略：
   - 模式检测（复用 `paste_mapping_infer.py` 规则）
   - LLM 生成（Phi-4 prompt）
   - 样本验证
3. 集成到匹配流程：YAML 无 regex 或为 "None" 时触发
4. 在测试输出中标记 `regex_suggested: true`

**成功标准**：
- 常见模式（PO号、日期、容器号）自动识别
- LLM 生成的 regex 在样本值上验证通过
- 测试输出包含 regex 建议

**受影响文件**：
- `app/services/phi4_field_matcher.py`（新增方法）
- `app/services/paste_mapping_infer.py`（复用规则）

### Phase 5: 测试列过滤与反向匹配（2-3 小时）

**目标**：支持"只测试选定列"功能，实现反向匹配。

**任务**：
1. 修改 `handle_llm_test` 数据源逻辑：
   - `test_cols` 非空时过滤 Sheet 列
2. 实现反向匹配模式：
   - 对每个选定的 Sheet 列
   - 在 YAML 所有字段中找最高相似度
   - 输出："列 {col} → 字段 {field}（相似度 {score}）"
3. 添加 `match_columns_to_yaml_fields` 方法

**成功标准**：
- 测试时可选择部分列
- 反向匹配给出合理建议
- 相似度阈值可配置

**受影响文件**：
- `app/components/gradio_config.py`（UI 逻辑）
- `app/services/phi4_field_matcher.py`（反向匹配方法）

### Phase 6: 性能优化与收尾（2-3 小时）

**目标**：优化性能和用户体验。

**任务**：
1. 实现模型缓存单例（`get_or_create_field_matcher`）
2. 添加超时保护（单字段 10s、总体 60s）
3. 编写单元测试（`tests/test_phi4_matcher_optimized.py`）
4. 更新文档（`docs/yaml_config_guide.md` 添加 regex 建议说明）

**成功标准**：
- 首次加载后模型复用
- 超时不影响已匹配字段
- 测试覆盖核心功能

**受影响文件**：
- `app/services/phi4_field_matcher.py`（缓存、超时）
- `tests/test_phi4_matcher.py`（新增测试）
- `docs/yaml_config_guide.md`（文档更新）

## 风险与约束

### 技术风险

1. **Transformers 进度限制**：`from_pretrained` 无法获取连续进度，只能分阶段标记
2. **Embedding 实现复杂度**：Phi-4 主要是生成模型，用于 embedding 需要额外处理
3. **向后兼容**：保留非迭代版本供批量导入使用

### 设计约束

必须遵守 `plans/gradio_ui_migration/constitution.md` 的约束：

- **状态管理规则**（2.1）：禁用全局变量，必须用 `gr.State()`
- **Gradio 交互规则**（2.2）：长操作设 `interactive=False`，用 `gr.Info()` 反馈
- **文件路径规则**（2.4）：必须用 `pathlib.Path`，禁用 `os.path`
- **错误处理规则**（2.5）：所有 I/O、网络、LLM 调用必须 try-except
- **性能约束**（1.6）：ID 查询 < 3s，Phi-4 推理 < 5s

### 用户体验约束

- 进度条不应阻塞 UI
- 错误提示友好（不显示 traceback）
- 测试结果可快速应用
- 支持手动编辑回退

## 成功标准

### 功能完整性
- [x] 模型加载显示详细进度（阶段 + 百分比）
- [x] 字段匹配显示逐字段进度
- [x] 测试输出为 YAML 配置格式
- [x] 语义相似度批量匹配（< 5s）
- [x] 自动生成 regex 建议
- [x] 支持测试列过滤和反向匹配

### 性能指标
- Phi-4 加载时间 < 30s
- 字段匹配总时间 < 5s（12 字段）
- 匹配准确率 ≥90%
- 内存占用无明显增加

### 代码质量
- 符合 constitution.md 所有约束
- 单元测试覆盖核心功能
- 日志记录清晰
- 错误处理完善

### 文档完整性
- YAML 配置指南更新
- 示例 YAML 包含 regex 建议
- README 添加优化说明

## 估算工时

| Phase | 预估时间 | 备注 |
|-------|---------|------|
| Phase 1 | 2-3 小时 | 进度显示基础设施 |
| Phase 2 | 2-3 小时 | 输出格式重构 |
| Phase 3 | 4-6 小时 | 语义相似度匹配（核心） |
| Phase 4 | 3-4 小时 | Regex 自动建议 |
| Phase 5 | 2-3 小时 | 测试列过滤 |
| Phase 6 | 2-3 小时 | 性能优化与收尾 |
| **总计** | **15-22 小时** | 约 2-3 个工作日 |

## 与主计划的关系

本计划是 `plans/gradio_ui_migration/` 的补充优化计划：

- **依赖关系**：依赖 Phase 2（数据层和 LLM 集成）已完成
- **增强内容**：优化 spec.md 第 138-206 行定义的 Phi-4 字段匹配器
- **不冲突**：不修改区域检测、UI 布局、批量导入等其他功能
- **可选性**：主计划可先完成，本计划作为后续优化

## 实施顺序建议

按依赖关系和优先级：

1. **Phase 1（进度条）** - 独立实现，改善用户体验
2. **Phase 2（输出格式）** - 与 Phase 3 并行，不冲突
3. **Phase 3（语义匹配）** - 核心重构，较大改动
4. **Phase 4（Regex 建议）** - 依赖 Phase 3 的匹配结果
5. **Phase 5（列过滤）** - 功能增强，依赖 Phase 3
6. **Phase 6（性能优化）** - 最后集成优化

每个 Phase 完成后应进行质量检查，确保符合 constitution.md 约束。
