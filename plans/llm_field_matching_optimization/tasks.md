# LLM 字段匹配优化 - 任务分解

本文档将优化计划分解为可执行的具体任务。

## Phase 1: 进度显示基础设施（2-3 小时）

### 1.1 设计进度回调接口
- [ ] 定义 `ProgressStage` 枚举类型
- [ ] 定义 `ProgressCallback` 类型签名
- [ ] 在 `phi4_field_matcher.py` 添加接口定义
- [ ] 添加使用说明文档字符串

### 1.2 实现下载进度
- [ ] 创建 `DownloadProgressTqdm` 自定义类
- [ ] 修改 `ensure_model_downloaded` 接受 `on_progress` 参数
- [ ] 集成 `tqdm_class` 到 `hf_hub_download`
- [ ] 格式化进度消息（速度、百分比）
- [ ] 测试下载进度回调

### 1.3 实现加载进度
- [ ] 修改 `Phi4FieldMatcher.__init__` 接受 `on_progress` 参数
- [ ] 添加 10 个加载阶段标记：
  - [ ] 检查 GGUF 版本（10%）
  - [ ] 定位模型文件（20%）
  - [ ] 确认 Hub 缓存（30%）
  - [ ] 加载 Tokenizer（50%）
  - [ ] 加载模型权重（90%）
  - [ ] 模型就绪（100%）
- [ ] 每个阶段调用 `on_progress` 回调
- [ ] 测试加载进度回调

### 1.4 实现匹配进度
- [ ] 修改 `iter_match_sheet_fields_to_yaml` 返回格式：
  - 改为 `((stage, current, total), result)` 元组
- [ ] 修改 `_iter_llm_match_columns` 返回格式
- [ ] 更新所有调用点适配新格式
- [ ] 测试匹配进度迭代

### 1.5 集成 Gradio Progress
- [ ] 修改 `handle_llm_test` 接受 `progress` 参数
- [ ] 实现 `download_progress` lambda 转发
- [ ] 实现 `load_progress` lambda 转发
- [ ] 在匹配循环中更新 `progress()`
- [ ] 修改 `handle_yaml_auto_config` 同样集成
- [ ] 测试 UI 进度条显示

### 1.6 Phase 1 质量检查
- [ ] 验证进度回调接口设计合理
- [ ] 验证下载进度显示正确
- [ ] 验证加载进度阶段清晰
- [ ] 验证匹配进度逐字段更新
- [ ] 验证 Gradio UI 进度条流畅
- [ ] 验证错误情况不影响进度

---

## Phase 2: 输出格式重构（2-3 小时）

### 2.1 定义数据结构
- [ ] 创建 `FieldMatchResult` dataclass
  - [ ] `filed: str`
  - [ ] `index: int`
  - [ ] `regex: str | None`
  - [ ] `similarity: float`
  - [ ] `matched_value: str`
  - [ ] `regex_suggested: bool`
  - [ ] `ID: bool`
- [ ] 创建 `TestOutput` dataclass（可选，用于类型注解）

### 2.2 重写格式化函数
- [ ] 备份旧版 `_format_llm_test_json`
- [ ] 重写函数签名接受新参数：
  - `progress_tuple: tuple[str, int, int]`
  - `yaml_config_dict: dict[str, list[FieldMatchResult]]`
  - `sheet_columns: list[str]`
  - `sample_row: dict[str, str] | None`
- [ ] 实现新的 JSON 结构：
  - [ ] `progress` 对象
  - [ ] `yaml_config` 对象（嵌套字段映射）
  - [ ] `sheet_meta` 对象
- [ ] 使用 `dataclasses.asdict` 序列化
- [ ] 测试输出格式正确性

### 2.3 更新匹配迭代器
- [ ] 修改 `iter_match_sheet_fields_to_yaml` 返回 `dict[str, list[FieldMatchResult]]`
- [ ] 构造 `FieldMatchResult` 对象：
  - [ ] 填充 `filed`, `index`, `regex`
  - [ ] 填充 `matched_value`
  - [ ] 初始设 `similarity=1.0`（Phase 3 再更新）
  - [ ] 初始设 `regex_suggested=False`（Phase 4 再更新）
- [ ] 更新调用点适配新返回类型

### 2.4 实现"应用到 YAML"功能
- [ ] 在 `gradio_config.py` 添加按钮
- [ ] 实现 `handle_apply_test_result` 函数：
  - [ ] 解析测试输出 JSON
  - [ ] 读取现有 YAML 文件
  - [ ] 更新字段映射（保留 `ID`, 移除 `matched_value` 和 `regex_suggested`）
  - [ ] 写回 YAML 文件
  - [ ] 显示成功提示
- [ ] 绑定按钮点击事件
- [ ] 测试应用功能

### 2.5 更新 UI 交互
- [ ] 修改 `test_result` 组件显示格式
- [ ] 添加"应用到 YAML"按钮（初始隐藏）
- [ ] 测试成功后显示按钮
- [ ] 测试完整流程

### 2.6 Phase 2 质量检查
- [ ] 验证输出 JSON 格式正确
- [ ] 验证可直接复制到 YAML
- [ ] 验证应用功能更新配置正确
- [ ] 验证 UI 交互流畅
- [ ] 验证向后兼容（批量导入不受影响）

---

## Phase 3: 语义相似度匹配（4-6 小时）

### 3.1 选择实现方案
- [ ] 评估方案 A（Phi-4 Embeddings）可行性
- [ ] 评估方案 B（单次 LLM Prompt）可行性
- [ ] 评估方案 C（Sentence-Transformers）可行性
- [ ] 确定默认方案（推荐方案 A）

### 3.2 实现 Embeddings 生成（方案 A）
- [ ] 添加 `_get_embeddings` 方法：
  - [ ] Tokenize 文本列表
  - [ ] Forward pass 获取 `hidden_states`
  - [ ] 提取最后一层
  - [ ] 平均池化（忽略 padding）
  - [ ] L2 归一化
- [ ] 测试 embeddings 生成
- [ ] 验证 embeddings 维度正确

### 3.3 实现相似度计算
- [ ] 添加 `compute_semantic_similarity` 方法：
  - [ ] 构造模板字段查询文本
  - [ ] 构造 Sheet 列文本（含样本值）
  - [ ] 生成 embeddings
  - [ ] 计算余弦相似度矩阵
  - [ ] 实现贪婪匹配算法
  - [ ] 返回匹配结果（列名、相似度、索引）
- [ ] 测试相似度计算准确性
- [ ] 测试贪婪匹配不重复使用列

### 3.4 重构自动配置流程
- [ ] 修改 `handle_yaml_auto_config` 读取样本行：
  - [ ] 调用 `_fetch_sheet_columns_and_sample`
  - [ ] 传递样本行到 `_iter_llm_match_columns`
- [ ] 修改 `_iter_llm_match_columns` 使用语义相似度：
  - [ ] 调用 `compute_semantic_similarity`
  - [ ] 判断相似度阈值（≥0.7）
  - [ ] 相似度过低时 LLM 降级单字段匹配
  - [ ] 逐个 yield 结果
- [ ] 测试自动配置流程

### 3.5 保留精确匹配优先级
- [ ] 确认 `_exact_match_columns` 在语义匹配前执行
- [ ] 确认精确匹配结果不参与语义匹配
- [ ] 测试匹配优先级顺序

### 3.6 更新测试输出包含相似度
- [ ] 修改 `FieldMatchResult` 填充 `similarity` 字段
- [ ] 精确匹配设 `similarity=1.0`
- [ ] 语义匹配使用计算的相似度
- [ ] LLM 降级匹配设 `similarity=0.5`（估算值）

### 3.7 性能测试
- [ ] 测试 12 字段匹配时间（目标 < 5s）
- [ ] 对比逐字段 LLM 推理时间
- [ ] 验证准确率 ≥90%
- [ ] 测试内存占用

### 3.8 Phase 3 质量检查
- [ ] 验证语义相似度计算正确
- [ ] 验证匹配准确率达标
- [ ] 验证性能提升明显
- [ ] 验证自动配置利用样本值
- [ ] 验证精确匹配优先级保持
- [ ] 验证向后兼容

---

## Phase 4: Regex 自动建议（3-4 小时）

### 4.1 复用内置模式库
- [ ] 从 `paste_mapping_infer.py` 提取 `REGEX_PATTERNS`
- [ ] 定义 `detect_pattern_type` 函数
- [ ] 测试模式检测准确性

### 4.2 实现 LLM Regex 生成
- [ ] 添加 `suggest_regex_for_field` 方法：
  - [ ] 优先内置模式检测
  - [ ] 构建 LLM prompt
  - [ ] 调用 `_generate` 生成 regex
  - [ ] 验证 regex 语法
  - [ ] 测试 regex 在样本值上
  - [ ] 匹配率 ≥50% 才返回
- [ ] 测试 LLM 生成 regex

### 4.3 实现样本值获取
- [ ] 添加 `_fetch_column_samples` 方法：
  - [ ] 从 Sheet 读取指定列的多行值
  - [ ] 过滤空值
  - [ ] 返回至少 3-5 个样本
- [ ] 测试样本值获取

### 4.4 集成到匹配流程
- [ ] 修改 `iter_match_sheet_fields_to_yaml` 添加 `suggest_regex` 参数
- [ ] 在匹配列后判断是否需要建议：
  - [ ] YAML 无 regex 或为 "None"
  - [ ] `suggest_regex=True`
- [ ] 调用 `suggest_regex_for_field`
- [ ] 设置 `regex_suggested=True`
- [ ] 测试集成流程

### 4.5 更新测试输出
- [ ] 确认 `FieldMatchResult` 包含 `regex_suggested` 标记
- [ ] 测试输出 JSON 包含建议标记
- [ ] 验证建议的 regex 可应用

### 4.6 处理边界情况
- [ ] 样本值不足时跳过建议
- [ ] LLM 生成失败时跳过建议
- [ ] regex 验证失败时跳过建议
- [ ] 记录日志便于调试

### 4.7 Phase 4 质量检查
- [ ] 验证内置模式覆盖常见场景
- [ ] 验证 LLM 生成 regex 语法正确
- [ ] 验证样本验证有效
- [ ] 验证集成流程不影响性能
- [ ] 验证错误情况优雅处理

---

## Phase 5: 测试列过滤与反向匹配（2-3 小时）

### 5.1 实现列过滤逻辑
- [ ] 修改 `handle_llm_test` 数据源逻辑：
  - [ ] 判断 `test_cols` 是否非空
  - [ ] 过滤 `sheet_columns`
  - [ ] 过滤 `sample_row`
  - [ ] 显示过滤提示
- [ ] 测试列过滤功能

### 5.2 实现反向匹配方法
- [ ] 添加 `match_columns_to_yaml_fields` 方法：
  - [ ] 构造列文本（含样本值）
  - [ ] 构造字段文本（含 hint）
  - [ ] 生成 embeddings
  - [ ] 计算相似度矩阵（列 × 字段）
  - [ ] 对每列找最佳字段
  - [ ] 返回匹配结果
- [ ] 测试反向匹配准确性

### 5.3 添加反向匹配模式 UI
- [ ] 在 `handle_llm_test` 判断是否反向匹配：
  - [ ] `test_cols` 非空 → 反向匹配模式
- [ ] 调用 `match_columns_to_yaml_fields`
- [ ] 格式化反向匹配输出 JSON
- [ ] 测试反向匹配 UI

### 5.4 集成 Regex 建议到反向匹配
- [ ] 反向匹配结果包含 regex 建议
- [ ] 调用 `suggest_regex_for_field`
- [ ] 输出包含 `suggested_regex` 字段

### 5.5 Phase 5 质量检查
- [ ] 验证列过滤正确
- [ ] 验证反向匹配合理
- [ ] 验证 UI 切换流畅
- [ ] 验证反向匹配包含 regex 建议

---

## Phase 6: 性能优化与收尾（2-3 小时）

### 6.1 实现模型缓存
- [ ] 添加全局变量 `_cached_matcher`
- [ ] 添加线程锁 `_cached_matcher_lock`
- [ ] 实现 `get_or_create_field_matcher` 函数
- [ ] 实现 `clear_matcher_cache` 函数
- [ ] 更新所有调用点使用缓存版本
- [ ] 测试缓存复用

### 6.2 实现超时保护
- [ ] 创建 `TimeoutError` 异常类
- [ ] 实现 `timeout` 上下文管理器
- [ ] 修改 `iter_match_sheet_fields_to_yaml` 添加超时参数
- [ ] 在匹配循环中检查总体超时
- [ ] 在单字段匹配中使用 `timeout` 上下文
- [ ] 测试超时保护

### 6.3 实现批处理优化
- [ ] 添加 `batch_match_rows` 方法
- [ ] 复用语义相似度计算结果
- [ ] 批量处理多行数据
- [ ] 测试批量性能

### 6.4 编写单元测试
- [ ] 创建 `tests/test_phi4_matcher_optimized.py`
- [ ] 编写进度回调测试：
  - [ ] 测试下载进度
  - [ ] 测试加载进度
  - [ ] 测试匹配进度
- [ ] 编写语义相似度测试：
  - [ ] 测试精确匹配高相似度
  - [ ] 测试模糊匹配
  - [ ] 测试贪婪匹配不重复
- [ ] 编写 Regex 建议测试：
  - [ ] 测试内置模式检测
  - [ ] 测试 LLM 生成
  - [ ] 测试样本验证
- [ ] 编写反向匹配测试：
  - [ ] 测试列到字段匹配
  - [ ] 测试相似度分数
- [ ] 编写性能测试：
  - [ ] 测试匹配时间
  - [ ] 测试内存占用
  - [ ] 测试缓存复用
  - [ ] 测试批量处理
- [ ] 运行所有测试确保通过

### 6.5 更新文档
- [ ] 更新 `docs/yaml_config_guide.md`：
  - [ ] 添加 Regex 自动建议部分
  - [ ] 添加触发条件说明
  - [ ] 添加建议来源说明
  - [ ] 添加应用建议说明
- [ ] 更新 `README.md`：
  - [ ] 添加 v2.0 优化说明
  - [ ] 添加进度显示说明
  - [ ] 添加语义相似度匹配说明
  - [ ] 添加 Regex 自动建议说明
  - [ ] 添加性能对比数据

### 6.6 代码质量检查
- [ ] 代码格式化（black 或 ruff）
- [ ] 类型注解检查（mypy）
- [ ] 删除调试代码和注释
- [ ] 优化导入语句
- [ ] 补充文档字符串
- [ ] 检查日志记录

### 6.7 集成测试
- [ ] 测试完整流程：
  - [ ] 模板加载 → 区域检测
  - [ ] OAuth → Sheet 连接
  - [ ] LLM 测试（带进度）
  - [ ] 应用到 YAML
  - [ ] 自动配置（带进度）
  - [ ] ID 查询 → 字段匹配
  - [ ] 批量导入
- [ ] 测试错误场景：
  - [ ] 模型加载失败
  - [ ] Sheet 连接失败
  - [ ] 匹配超时
  - [ ] Regex 建议失败
- [ ] 测试性能指标：
  - [ ] 模型加载 < 30s
  - [ ] 字段匹配 < 5s（12 字段）
  - [ ] 准确率 ≥90%

### 6.8 Phase 6 质量检查
- [ ] 验证模型缓存有效
- [ ] 验证超时保护不影响已匹配字段
- [ ] 验证批量处理性能提升
- [ ] 验证单元测试覆盖核心功能
- [ ] 验证文档更新完整准确
- [ ] 验证代码质量符合 constitution.md
- [ ] 验证集成测试全部通过
- [ ] 验证性能指标达标

---

## 任务优先级

### P0（必须完成）
- Phase 1-6 的所有核心任务
- 每个 Phase 的质量检查
- 单元测试
- 文档更新

### P1（重要）
- 性能优化（缓存、批处理）
- 错误处理完善
- 边界情况处理

### P2（可选）
- 方案 B、C 的实现（备选方案）
- 高级 UI 优化
- 扩展文档

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

## 依赖关系

```
Phase 1（进度显示）
    ├── Phase 2（输出格式）【并行】
    └── Phase 3（语义相似度）
            ├── Phase 4（Regex 建议）
            └── Phase 5（列过滤）
                    └── Phase 6（性能优化）
```

Phase 1 和 Phase 2 可以并行开发，Phase 3 是核心重构，Phase 4-6 依次递进。
