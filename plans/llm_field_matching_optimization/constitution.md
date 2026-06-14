# LLM 字段匹配优化 - 设计原则和约束

本计划是 `plans/gradio_ui_migration/` 的补充优化计划，必须遵守主计划的所有设计原则和约束。

## 1. 继承主计划约束

本计划完全继承 `plans/gradio_ui_migration/constitution.md` 的所有约束，包括但不限于：

### 1.1 核心设计原则（主计划 1.x）
- 全新分支，零兼容负担
- 数据源分治（Excel 用 pandas，Sheets 用 polars）
- YAML 驱动的配置
- LLM 辅助而非依赖
- 用户友好的错误处理
- 性能优先

### 1.2 代码约束（主计划 2.x）
- **状态管理规则**：禁用全局变量，必须用 `gr.State()`
- **Gradio 交互规则**：长操作设 `interactive=False`，用 `gr.Info()` 反馈
- **动态布局管理**：使用 `gr.update()`
- **文件路径规则**：必须用 `pathlib.Path`，禁用 `os.path`
- **错误处理规则**：所有 I/O、网络、LLM 调用必须 try-except
- **日志记录规则**：使用 Python `logging` 模块

### 1.3 YAML 设计约束（主计划 3.x）
- YAML 结构清晰
- YAML 向后兼容
- YAML 验证严格
- YAML 文档完整

### 1.4 用户体验约束（主计划 4.x）
- 操作流程简洁
- UI 布局合理
- 提示信息友好
- 加载状态明确

### 1.5 测试和质量约束（主计划 5.x）
- 质量检查机制
- 测试覆盖
- 代码质量
- 文档完整性

### 1.6 技术选型约束（主计划 6.x）
- UI 框架：Gradio 4.x
- 数据处理：pandas 2.x（Excel），polars 0.20+（Sheets）
- LLM 加载：Transformers + GGUF（已变更，不再是 llama-cpp-python）
- OAuth：google-auth, google-auth-oauthlib

## 2. 本计划特定原则

### 2.1 进度显示原则

**原则**：进度信息必须清晰、及时、不阻塞 UI。

**实践**：
- 使用 Gradio `gr.Progress()` 组件
- 进度回调函数不做耗时操作
- 进度更新频率适中（避免过于频繁）
- 进度消息简洁明确

**约束**：
- 进度回调函数执行时间 < 10ms
- 进度更新间隔 > 100ms
- 进度消息长度 < 50 字符
- 进度百分比计算准确

**反例**：
```python
# ❌ 错误：在进度回调中做耗时操作
def progress_callback(stage, current, total, msg):
    time.sleep(1)  # 阻塞
    logger.info(msg)  # I/O 操作

# ❌ 错误：过于频繁更新
for i in range(1000):
    progress(i/1000)  # 每次循环都更新

# ✅ 正确：批量更新
for i in range(1000):
    if i % 10 == 0:  # 每 10 次更新一次
        progress(i/1000)
```

### 2.2 输出格式原则

**原则**：输出格式必须可直接应用，避免二次转换。

**实践**：
- 测试输出为 YAML 配置格式
- 保留必要的元数据（相似度、建议标记）
- JSON 结构清晰，易于解析
- 支持"应用到 YAML"一键操作

**约束**：
- 输出 JSON 必须合法（可被 `json.loads` 解析）
- `yaml_config` 字段可直接写入 `.paste.yaml` 文件
- 不包含冗余信息（如中间计算结果）
- 包含足够信息用于验证（如 `matched_value`）

**反例**：
```python
# ❌ 错误：输出字段值而非配置
output = {
    "results": {
        "P.O. No.": "12345"  # 只有值，无配置
    }
}

# ✅ 正确：输出完整配置
output = {
    "yaml_config": {
        "P.O. No.": [{
            "filed": "PO Number",
            "index": 3,
            "regex": "\\d{4,8}",
            "matched_value": "12345"
        }]
    }
}
```

### 2.3 语义相似度原则

**原则**：语义匹配必须准确、高效、可解释。

**实践**：
- 使用 embeddings 计算相似度（方案 A）
- 相似度阈值可配置（默认 0.7）
- 保留精确匹配优先级
- 相似度过低时 LLM 降级

**约束**：
- 相似度计算时间 < 3s（12 字段）
- 准确率 ≥90%（测试集验证）
- 相似度分数归一化到 [0, 1]
- 贪婪匹配不重复使用列

**反例**：
```python
# ❌ 错误：无阈值判断
if field in matches:
    column = matches[field][0]
    # 即使相似度很低也使用

# ❌ 错误：允许重复匹配
matches["P.O. No."] = ("PO Number", 0.9, 3)
matches["Container No."] = ("PO Number", 0.8, 3)  # 重复

# ✅ 正确：阈值判断 + 独占列
if similarity >= 0.7 and col_idx not in used_columns:
    matches[field] = (column, similarity, col_idx)
    used_columns.add(col_idx)
```

### 2.4 Regex 建议原则

**原则**：Regex 建议必须经过验证，不能盲目应用。

**实践**：
- 优先使用内置模式库
- LLM 生成后在样本值上验证
- 验证匹配率 ≥50%
- 标记 `regex_suggested: true`

**约束**：
- 生成的 regex 必须合法（可被 `re.compile` 编译）
- 必须在至少 3 个样本值上测试
- 匹配率 < 50% 时不返回建议
- 不自动应用建议（需用户确认）

**反例**：
```python
# ❌ 错误：不验证 regex 语法
regex = llm_generate_regex(samples)
return regex  # 可能非法

# ❌ 错误：不测试样本值
regex = r"\d{4,8}"
return regex  # 未验证是否匹配样本

# ✅ 正确：验证后返回
try:
    re.compile(regex)
    match_count = sum(1 for val in samples if re.search(regex, val))
    if match_count / len(samples) >= 0.5:
        return regex
except re.error:
    return None
```

### 2.5 性能优化原则

**原则**：性能优化不能牺牲准确性和可维护性。

**实践**：
- 模型缓存单例（线程安全）
- 批量计算相似度（避免重复推理）
- 超时保护（不影响已匹配字段）
- 合理的超时阈值（单字段 10s，总体 60s）

**约束**：
- 缓存必须线程安全（使用锁）
- 超时后返回部分结果（不抛出异常）
- 批量处理不改变单行结果
- 性能优化不引入新的依赖

**反例**：
```python
# ❌ 错误：缓存不线程安全
_cached_matcher = None
def get_matcher():
    global _cached_matcher
    if _cached_matcher is None:
        _cached_matcher = load_model()  # 竞态条件
    return _cached_matcher

# ❌ 错误：超时后抛出异常
try:
    with timeout(10):
        result = match_field(field)
except TimeoutError:
    raise  # 中断整个流程

# ✅ 正确：线程安全 + 优雅降级
_cached_matcher = None
_matcher_lock = threading.Lock()

def get_matcher():
    global _cached_matcher
    if _cached_matcher is not None:
        return _cached_matcher
    
    with _matcher_lock:
        if _cached_matcher is None:
            _cached_matcher = load_model()
        return _cached_matcher

# ✅ 正确：超时后继续
try:
    with timeout(10):
        result = match_field(field)
except TimeoutError:
    logger.warning(f"字段 {field} 匹配超时")
    continue  # 跳过该字段，继续处理
```

## 3. 约束与权衡

### 3.1 Transformers 进度限制

**约束**：Transformers `from_pretrained` 无法获取连续进度，只能分阶段标记。

**权衡**：
- 接受阶段性进度（10%、20%、...、100%）
- 不追求连续进度条（如下载时的逐字节更新）
- 提供清晰的阶段描述弥补

### 3.2 Embedding 实现复杂度

**约束**：Phi-4 主要是生成模型，用于 embedding 需要额外处理。

**权衡**：
- 使用最后一层隐藏状态 + 平均池化
- 不追求最优 embedding（如专门训练的编码器）
- 可配置切换到 Sentence-Transformers（方案 C）

### 3.3 Regex 生成准确性

**约束**：LLM 生成的 regex 可能不准确或过于复杂。

**权衡**：
- 优先使用内置模式库（准确率高）
- LLM 生成后必须验证
- 允许用户手动编辑
- 不强制应用建议

### 3.4 向后兼容

**约束**：优化不能破坏现有功能（批量导入、手动匹配）。

**权衡**：
- 保留 `match_sheet_fields_to_yaml` 非迭代版本
- 进度回调为可选参数（默认 `None`）
- 语义相似度可降级到 LLM 单字段匹配
- Regex 建议可关闭（`suggest_regex=False`）

## 4. 不允许的实践

以下实践在本计划中**严格禁止**：

1. **在进度回调中做耗时操作**（违反进度显示原则）
2. **输出格式不可直接应用**（违反输出格式原则）
3. **语义相似度无阈值判断**（违反语义相似度原则）
4. **Regex 建议不验证**（违反 Regex 建议原则）
5. **缓存不线程安全**（违反性能优化原则）
6. **超时后抛出异常**（违反性能优化原则）
7. **破坏向后兼容**（违反约束与权衡）
8. **忽略主计划约束**（违反继承原则）

违反以上任何一条，代码 review 不通过。

## 5. 质量检查清单

每个 Phase 完成后，必须通过以下检查：

### 5.1 功能完整性
- [ ] 功能按 spec 实现
- [ ] 边界情况处理
- [ ] 错误处理完善
- [ ] 日志记录清晰

### 5.2 性能指标
- [ ] 响应时间达标
- [ ] 内存占用合理
- [ ] CPU 占用正常
- [ ] 无明显性能退化

### 5.3 代码质量
- [ ] 符合主计划 constitution.md
- [ ] 符合本计划特定原则
- [ ] 无代码异味
- [ ] 有类型注解
- [ ] 有文档字符串

### 5.4 测试覆盖
- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 性能测试达标
- [ ] 边界情况测试

### 5.5 文档完整
- [ ] 代码注释清晰
- [ ] API 文档准确
- [ ] 用户文档更新
- [ ] 示例代码可用

### 5.6 用户体验
- [ ] UI 交互流畅
- [ ] 错误提示友好
- [ ] 加载状态明确
- [ ] 进度显示清晰

只有所有检查项通过，才能进入下一 Phase。

## 6. 与主计划的关系

### 6.1 依赖关系
- 依赖主计划 Phase 2（数据层和 LLM 集成）已完成
- 不修改主计划的其他功能（区域检测、UI 布局、批量导入）

### 6.2 增强内容
- 优化 `plans/gradio_ui_migration/spec.md` 第 138-206 行定义的 Phi-4 字段匹配器
- 补充主计划未明确的进度显示、输出格式、语义匹配、Regex 建议

### 6.3 可选性
- 主计划可先完成，本计划作为后续优化
- 本计划可分阶段实施（Phase 1-6 独立）
- 本计划不影响主计划的成功标准

## 7. 成功标准（重申）

本计划成功的**不可妥协**标准：

1. **功能完整性**：6 项功能标准全部达成
2. **性能指标**：4 项性能指标全部达标
3. **代码质量**：符合所有代码约束
4. **测试覆盖**：单元测试和集成测试通过
5. **文档完整**：文档更新完整准确
6. **用户体验**：UI 交互流畅，提示友好

任何一项不达标，计划不视为完成。

## 8. 设计决策记录

### 8.1 选择方案 A（Phi-4 Embeddings）而非方案 B（单次 LLM Prompt）

**原因**：
- 方案 A 性能更好（3s vs 10s+）
- 方案 A 无需复杂 prompt 工程
- 方案 A 可解释性更好（相似度分数）
- 方案 A 无额外依赖

**权衡**：
- 方案 A 需要实现 embedding 提取（额外开发量）
- 方案 A 不完全符合原 spec（spec 期望单次 prompt）

**决定**：默认使用方案 A，在代码中注释方案 B 实现，支持配置切换。

### 8.2 Regex 建议不自动应用

**原因**：
- LLM 生成的 regex 可能不准确
- 用户需要审核和确认
- 避免错误 regex 导致数据提取错误

**权衡**：
- 需要额外的"应用到 YAML"步骤
- 用户体验略有降低

**决定**：Regex 建议仅作为参考，需用户手动应用。在测试输出中标记 `regex_suggested: true`，提示用户审核。

### 8.3 超时保护返回部分结果而非失败

**原因**：
- 部分匹配结果仍有价值
- 用户可以手动完成剩余字段
- 避免全部重试浪费时间

**权衡**：
- 可能导致用户误以为匹配完成
- 需要清晰提示哪些字段超时

**决定**：超时后返回已匹配字段，在日志和 UI 提示中明确说明超时情况。

### 8.4 模型缓存单例而非每次加载

**原因**：
- 模型加载耗时（20-30s）
- 用户会话内多次使用（测试、配置、查询）
- 内存占用可接受（< 4GB）

**权衡**：
- 缓存占用内存
- 多用户场景需注意线程安全

**决定**：使用线程安全的单例缓存，提供 `clear_matcher_cache` 用于手动清理。

以上设计决策记录在案，便于未来回顾和调整。
