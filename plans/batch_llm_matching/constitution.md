# Batch LLM Field Matching - Design Constitution

## Core Design Principles

### 1. Single LLM Call for All Fields

**Principle**: Batch processing over incremental processing.

**Rationale**: 
- One LLM call is faster than N calls (5s vs 36s for 12 fields)
- Batch context allows LLM to make better decisions
- Consistent with design document specification

**Implementation Rule**:
```python
# ✅ CORRECT: Single batch call
mappings = batch_match_all_fields(source_data, yaml_fields)

# ❌ FORBIDDEN: Field-by-field loop
for field in yaml_fields:
    mapping = match_single_field(field, columns)  # NO!
```

**This rule is ABSOLUTE. No exceptions.**

---

### 2. Phase 3: Use LLM for Transformation Inference

**Principle**: LLM infers extraction patterns, not hardcoded rules.

**Rationale**:
- User requirements vary (different date formats, different container patterns)
- Hardcoded rules cannot cover all cases
- LLM can adapt to specific data patterns from samples
- More maintainable: no regex patterns scattered in code

**Implementation Rule**:
```python
# ✅ CORRECT: LLM infers the pattern
transformation_prompt = build_transformation_inference_prompt(
    source_column, sample_values, target_fields
)
transformation_rules = llm_infer_transformations(transformation_prompt)

# ❌ FORBIDDEN: Hardcoded regex patterns in code
if "pick up" in value:
    date_part = re.search(r'(\d+/\d+)', value).group(1)  # NO!
```

**This rule is ABSOLUTE for Phase 3. All transformation patterns must come from LLM.**

---

### 3. Use Multi-Row Sample Data

**Principle**: Multiple samples improve matching accuracy.

**Rationale**:
- Single row may have atypical values
- Multiple rows show data patterns
- Design document requires minimum 5 rows

**Implementation Rule**:
```python
# ✅ CORRECT: At least 5 rows
sample_rows = fetch_google_sheet_sample(sheet_id, sheet_range, min_rows=5)

# ❌ FORBIDDEN: Single row or empty row
sample_row = fetch_single_row()  # NO!
empty_row = {col: "" for col in columns}  # NO!
```

**Minimum: 5 rows. Warn if less, but continue with available rows.**

---

### 4. Trust the Design Document

**Principle**: Implement exactly what the design specifies.

**Rationale**:
- Design document is the source of truth
- Previous implementation deviated and failed
- No "clever" improvements without updating design doc first

**Implementation Rule**:
- Follow `docs/llm_matching_flow.md` section 3.4 for prompt template
- Follow section 3.5 for response parsing
- No modifications to prompt or response format without design doc update

**If you think the design is wrong, update the design doc first, then implement.**

---

## What NOT to Do

### 1. DO NOT Implement Incremental Matching

**Why the old plan failed**: It tried to optimize incremental matching instead of replacing it.

**Forbidden Patterns**:
```python
# ❌ NO: Field-by-field loop
for field in yaml_fields:
    column = llm_match_field(field)
    
# ❌ NO: Multiple LLM calls
for field in yaml_fields:
    prompt = build_single_field_prompt(field)
    response = model.generate(prompt)
    
# ❌ NO: Incremental processing
for field in yaml_fields:
    if exact_match(field):
        continue
    if semantic_match(field):
        continue
    llm_match(field)  # Still incremental!
```

**These patterns are BANNED. Delete them if you find them.**

---

### 2. DO NOT Add Features Not in Design Doc

**Forbidden additions**:
- ❌ Semantic similarity matching (not in design doc)
- ❌ Interactive correction UI beyond Phase 3 review (not required)

**Allowed additions (specified in this plan)**:
- ✅ Phase 2: Confidence reasoning (helps user understand matches)
- ✅ Phase 3: Transformation inference (solves format mismatch problem)

**Rationale**: Phase 2 and Phase 3 are natural extensions of the batch matching design. They solve real user problems without changing the core architecture.

**Rule**: If it's not in the plan or design doc, don't implement it.

---

### 3. DO NOT Use Single Row Samples

**Why**: Single rows don't show data patterns.

**Example of failure**:
```
Single row: {"Date": "N/A"}
→ LLM cannot determine this is a date field

Five rows: {"Date": ["6/1", "6/2", "6/3", "6/4", "6/5"]}
→ LLM clearly sees date pattern
```

**Rule**: Always fetch at least 5 rows. If less available, warn user but continue.

---

### 4. DO NOT Modify Prompt Without Design Doc

**Why**: Prompt is carefully designed to produce correct JSON format.

**Forbidden changes**:
- ❌ Changing JSON structure
- ❌ Adding extra fields
- ❌ Removing rules
- ❌ Changing output format

**Rule**: Prompt template from design doc section 3.4 is FINAL.

---

### 5. DO NOT Skip Response Validation

**Why**: LLM may return invalid column names, patterns, or malformed JSON.

**Required validations (Phase 1 & 2)**:
- ✅ Extract JSON from response (may be wrapped in markdown)
- ✅ Validate "filed" values against source columns
- ✅ Handle null mappings (filed=null)
- ✅ Ensure all expected fields present in output

**Required validations (Phase 3)**:
- ✅ Validate regex patterns are syntactically correct
- ✅ Test patterns against sample values
- ✅ Require ≥50% success rate on samples
- ✅ Reject patterns that don't work

**Rule**: Never trust LLM response without validation. Phase 3 transformations MUST be tested before applying.

---

### 6. DO NOT Hardcode Transformation Patterns (Phase 3)

**Why**: User data varies, hardcoded patterns break.

**Forbidden patterns**:
```python
# ❌ NO: Hardcoded date extraction
if "pick up" in value:
    month, day = value.split("pick up ")[1].split("/")
    
# ❌ NO: Hardcoded container extraction
if "Container:" in value:
    container_no = re.search(r'Container:\s*([A-Z]{4}\d{7})', value).group(1)
    
# ❌ NO: Any regex pattern in code
CONTAINER_PATTERN = r'([A-Z]{4}\d{7})'  # NO!
```

**Correct approach**:
```python
# ✅ YES: LLM infers pattern
transformation = llm_infer_transformation(
    source_column="Container Info",
    samples=["Container: MSCU1234567 (20ft)", "Container: ASDB123456 (40ft)"],
    target_field="Container No.",
    expected_format="container format (e.g., 'MSCU1234567')"
)
# transformation.pattern = r'Container:\s*([A-Z]{4}\d{7})'  (from LLM)
```

**This rule is CRITICAL for Phase 3. All patterns must come from LLM.**

---

### 7. DO NOT Apply Transformations Without User Review (Phase 3)

**Why**: Transformation patterns may be incorrect or unexpected.

**Required workflow**:
1. Detect format mismatches
2. Generate transformation patterns with LLM
3. Validate patterns on samples
4. **Show results to user** (before/after samples)
5. User approves or rejects
6. Apply only if approved

**Forbidden**:
```python
# ❌ NO: Auto-apply transformations
transformations = infer_transformations(mismatches)
apply_transformations_to_yaml(transformations)  # NO!

# ✅ YES: User review required
transformations = infer_transformations(mismatches)
if user_approves(transformations):
    apply_transformations_to_yaml(transformations)
```

**Rule**: Phase 3 is optional and requires user confirmation.

---

## Code Quality Requirements

### 1. Type Hints Required

**Rule**: All functions must have type hints.

```python
# ✅ CORRECT
def prepare_batch_input(
    source_columns: list[str],
    sample_rows: list[dict[str, str]],
    min_rows: int = 5
) -> list[SourceColumnData]:
    ...

# ❌ FORBIDDEN: No type hints
def prepare_batch_input(source_columns, sample_rows, min_rows=5):
    ...
```

---

### 2. Docstrings Required

**Rule**: All public functions must have docstrings.

**Format**: Google style docstrings.

```python
def batch_match_all_fields(
    self,
    source_columns_data: list[SourceColumnData],
    yaml_field_names: list[str]
) -> dict[str, dict[str, Any]]:
    """
    Perform batch matching with SINGLE LLM call.
    
    Args:
        source_columns_data: Source columns with sample values
        yaml_field_names: All YAML field names to match
    
    Returns:
        Mapping dictionary: {field_name: {filed, index}}
    
    Raises:
        ValueError: If source_columns_data is empty
    """
```

---

### 3. Error Handling Required

**Rule**: Handle all failure points.

**Required error handling**:
- Google Sheets API failures
- Insufficient sample data
- LLM generation failures
- JSON parsing errors
- File I/O errors

```python
# ✅ CORRECT
try:
    sample_rows = fetch_google_sheet_sample(sheet_id, sheet_range, min_rows=5)
except Exception as e:
    logger.error(f"Failed to fetch Google Sheets data: {e}")
    gr.Error("Failed to fetch data from Google Sheets. Please check connection.")
    return

# ❌ FORBIDDEN: No error handling
sample_rows = fetch_google_sheet_sample(sheet_id, sheet_range, min_rows=5)
```

---

### 4. Logging Required

**Rule**: Log all important operations and errors.

```python
import logging

logger = logging.getLogger(__name__)

# Log important operations
logger.info(f"Starting batch matching for {len(yaml_fields)} fields")
logger.info(f"Using {len(sample_rows)} sample rows")

# Log warnings
logger.warning(f"Only {len(sample_rows)} sample rows available (recommend 5+)")

# Log errors
logger.error(f"Failed to parse LLM response: {e}")
```

---

## Performance Requirements

### 1. Total Time Budget

**Requirement**: Total matching time < 10 seconds.

**Breakdown**:
- Data fetching: < 2s
- Data preparation: < 1s
- LLM inference: < 5s
- Response parsing: < 1s
- YAML update: < 1s

**Rule**: If any step exceeds budget, optimize or warn user.

---

### 2. Single LLM Call Only

**Requirement**: Exactly ONE LLM call per batch matching operation.

**Validation**: Add assertion in code.

```python
llm_call_count = 0

def batch_match_all_fields(self, ...):
    global llm_call_count
    llm_call_count = 0
    
    # ... prepare prompt ...
    
    llm_call_count += 1
    response = self.model.generate(prompt)
    
    assert llm_call_count == 1, "Batch matching must use exactly ONE LLM call"
    
    # ... parse response ...
```

---

### 3. Memory Efficiency

**Requirement**: Don't load unnecessary data.

**Rules**:
- Only fetch columns user selected (test_cols)
- Only fetch 5 sample rows (not entire sheet)
- Don't store full LLM response in memory (parse immediately)

---

## Testing Requirements

### 1. Minimum Test Coverage

**Requirement**: ≥ 80% code coverage for new functions.

**Tools**: pytest with coverage plugin.

```bash
pytest --cov=app.services.phi4_field_matcher --cov-report=term-missing
```

---

### 2. Required Test Categories

**Unit tests**:
- Data preparation
- Prompt building
- Response parsing
- YAML update

**Integration tests**:
- End-to-end batch matching
- Google Sheets integration
- UI workflow

**Performance tests**:
- Timing benchmarks
- Memory usage

---

### 3. Edge Case Testing

**Required edge cases**:
- Empty source columns
- Insufficient sample rows (< 5)
- Invalid LLM response (malformed JSON)
- Invalid column names in response
- All null mappings

---

## Documentation Requirements

### 1. Code Comments

**Rule**: Complex logic must have comments explaining WHY, not WHAT.

```python
# ✅ GOOD: Explains reasoning
# Use case-insensitive matching because Google Sheets may change case
header_by_norm = {h.strip().lower(): h for h in source_columns}

# ❌ BAD: Obvious
# Create dictionary
header_by_norm = {h.strip().lower(): h for h in source_columns}
```

---

### 2. Update Design Document

**Rule**: If implementation deviates from design doc, update design doc first.

**Process**:
1. Identify deviation
2. Update `docs/llm_matching_flow.md`
3. Get approval (if collaborative project)
4. Implement updated design

---

## Security and Safety Requirements

### 1. No Arbitrary Code Execution

**Rule**: Don't use `eval()` or `exec()` on LLM responses.

**Why**: LLM response is untrusted input.

---

### 2. Validate All User Input

**Rule**: Validate test_cols, sheet_id, sheet_range.

```python
# ✅ CORRECT
if not test_cols or len(test_cols) == 0:
    raise ValueError("test_cols cannot be empty")

# ❌ FORBIDDEN: Assume user input is valid
columns = [c for c in all_columns if c in test_cols]
```

---

### 3. Create Backup Before Modifying YAML

**Rule**: Always backup before writing to YAML file.

```python
# ✅ CORRECT
yaml_path = Path(yaml_file)
backup_path = yaml_path.with_suffix('.yaml.bak')
shutil.copy(yaml_path, backup_path)

# Write to original file
with open(yaml_path, 'w') as f:
    yaml.dump(updated_config, f)
```

---

## User Experience Requirements

### 1. Clear Progress Indication

**Rule**: Show progress before and after LLM call.

```python
gr.Info("Fetching sample data from Google Sheets...")
sample_rows = fetch_google_sheet_sample(...)

gr.Info("Calling Phi-4-mini for batch matching...")
mappings = batch_match_all_fields(...)

gr.Info(f"Matching complete: {matched_count}/{total_count} fields matched")
```

---

### 2. Helpful Error Messages

**Rule**: Error messages must be actionable.

```python
# ✅ GOOD: Actionable
gr.Error("Failed to fetch Google Sheets data. "
         "Please check your internet connection and Sheet permissions.")

# ❌ BAD: Not actionable
gr.Error("Error: NoneType object has no attribute 'values'")
```

---

### 3. Allow Review Before Applying

**Rule**: Don't automatically modify YAML. Let user review first.

```python
# ✅ CORRECT: Show results, let user click "Apply"
yield _format_results(mappings)

# User clicks "Apply to YAML" button
def on_apply_click():
    apply_batch_mapping_to_yaml(yaml_config, mappings)
    gr.Info("YAML updated successfully")

# ❌ FORBIDDEN: Auto-apply without user review
mappings = batch_match_all_fields(...)
apply_batch_mapping_to_yaml(yaml_config, mappings)  # NO!
```

---

## Design Constraints (Inherited from Main Project)

This plan inherits all constraints from `plans/gradio_ui_migration/constitution.md`:

### From Main Project Constitution

1. **No Global Variables for State**: Use `gr.State()` instead
2. **Long Operations Set interactive=False**: Prevent double-submission
3. **Use pathlib.Path**: Not `os.path`
4. **All I/O Must Have try-except**: Network, LLM, file operations
5. **Use Python logging**: Not print statements
6. **CPU-Only Phi-4 GGUF Model**: No GPU code

**Rule**: All these constraints apply to this plan as well.

---

## Success Definition

This plan is considered **successful** if and only if:

### Phase 1 & 2 Criteria
1. ✅ **Zero field-by-field loops** in final code
2. ✅ **Exactly one LLM call** per batch matching operation (Phase 1)
3. ✅ **Uses 5+ sample rows** (or warns if less)
4. ✅ **Parses batch JSON correctly** with validation
5. ✅ **Confidence reasoning included** in each mapping (Phase 2)
6. ✅ **Total time < 10s** for 12 fields (Phase 1 & 2)

### Phase 3 Criteria
7. ✅ **Format mismatch detection** works correctly
8. ✅ **Transformation patterns inferred by LLM** (no hardcoded regex)
9. ✅ **Transformation validation**: ≥50% success rate on samples
10. ✅ **User review required** before applying transformations
11. ✅ **Transformation rules stored in YAML** with explanations
12. ✅ **Phase 3 time budget**: +2-3s per mismatched column

### General Criteria
13. ✅ **Test coverage ≥ 80%** for new code
14. ✅ **Matching accuracy ≥ 90%** on test dataset
15. ✅ **No regression** in existing features
16. ✅ **User can review before applying** changes
17. ✅ **Follows all design principles** above

**If any of these criteria is not met, the plan is NOT complete.**

---

## Violation Consequences

### Critical Violations (Plan Fails)

These violations mean the plan has failed:
- ❌ Field-by-field loops in final code
- ❌ Multiple LLM calls per batch operation
- ❌ Using single row samples
- ❌ Not following design document

**Action**: Revert changes, re-implement correctly.

### Major Violations (Must Fix Before Completion)

These must be fixed before plan is complete:
- ⚠️ Missing type hints
- ⚠️ Missing error handling
- ⚠️ Test coverage < 80%
- ⚠️ Performance requirements not met

**Action**: Fix before proceeding to next phase.

### Minor Violations (Improvement Needed)

These should be fixed but don't block completion:
- ⚠️ Missing docstrings
- ⚠️ Suboptimal error messages
- ⚠️ Insufficient logging

**Action**: Fix when time permits, or document as technical debt.

---

## Design Decision Record

### Decision 1: Single LLM Call vs. Incremental

**Options Considered**:
1. Field-by-field with semantic similarity (old plan)
2. Single batch LLM call (design doc)

**Decision**: Option 2 (single batch call)

**Rationale**:
- Design document specifies batch matching
- 7× faster (5s vs 36s)
- Simpler implementation
- Better LLM context

**This decision is FINAL.**

---

### Decision 2: Minimum Sample Row Count

**Options Considered**:
1. Require exactly 5 rows (strict)
2. Recommend 5 rows, allow less (lenient)
3. Require 10+ rows (stricter)

**Decision**: Option 2 (recommend 5, allow less)

**Rationale**:
- Some sheets may have < 5 rows
- Better UX to warn and continue
- Design doc says "at least 5 rows"

**Implementation**: Warn if < 5 rows, continue with available rows.

---

### Decision 3: Response Format

**Options Considered**:
1. Custom format (not in design doc)
2. Design doc format: `{"mappings": [...]}`

**Decision**: Option 2 (design doc format)

**Rationale**:
- Design doc is source of truth
- No reason to deviate
- Format is already well-designed

**Rule**: Use exact format from design doc section 3.4.

---

## Lessons Learned from Old Plan

### What Went Wrong

1. **Misunderstood the goal**: Old plan tried to optimize incremental matching
2. **Scope creep**: Added semantic similarity, regex suggestion
3. **Ignored design doc**: Didn't implement batch matching
4. **Over-engineered**: Too many features, too complex

### What We'll Do Differently

1. **Follow design doc exactly**: No deviations
2. **Focus on core**: Batch matching only
3. **Simple implementation**: No fancy features
4. **Test early**: Validate batch approach works

---

**Constitution Version**: 1.0  
**Last Updated**: 2026-06-13  
**Authority**: This document overrides any conflicting guidance.  
**Enforcement**: All code reviews must check compliance with this constitution.
