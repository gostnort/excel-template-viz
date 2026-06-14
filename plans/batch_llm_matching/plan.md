# Batch LLM Field Matching Implementation Plan

## Executive Summary

This plan implements **batch LLM field matching** as specified in `docs/llm_matching_flow.md`. The core principle is: **ONE LLM call processes ALL fields and ALL columns simultaneously**, using 5+ sample rows for better accuracy.

**Key Change**: Replace incremental field-by-field matching with true batch matching.

## Current State Analysis

### What Exists
- `app/services/phi4_field_matcher.py` - Field matcher using Phi-4-mini 4B GGUF (CPU-only)
- `app/components/gradio_config.py` - UI handler for LLM testing
- Design document: `docs/llm_matching_flow.md` - Correct batch matching specification

### Critical Problems

#### Problem 1: Wrong Implementation Strategy
**Current behavior**: The existing code (or old plan) uses **incremental field-by-field matching**:
- Loop through each YAML field
- Call LLM N times (once per field)
- Total time: N × 3s = 36s for 12 fields

**Design document specifies**: **Batch matching**:
- Collect ALL YAML fields
- Collect ALL source columns with 5+ sample rows
- Call LLM ONCE
- Total time: ~5s

#### Problem 2: Insufficient Sample Data
**Current behavior**: Uses single row or empty row (`empty_row`)
**Design document requires**: At least 5 sample rows per column

#### Problem 3: No Batch Prompt Template
**Current behavior**: No implementation of batch prompt
**Design document specifies**: Detailed batch prompt format (section 3.4)

#### Problem 4: No Batch Response Parsing
**Current behavior**: No batch JSON parser
**Design document requires**: Parse `{"mappings": [{field, filed, index}, ...]}`

### Why the Old Plan Failed

The old plan (`plans/llm_field_matching_optimization/`) focused on:
1. Adding progress bars ✓ (useful but not core)
2. Refactoring output format ✓ (useful but not core)
3. Semantic similarity matching ✗ (not in design doc, adds complexity)
4. Regex auto-suggestion ✗ (not in design doc, out of scope)

**Root cause**: The old plan tried to **optimize** incremental matching instead of **replacing** it with batch matching.

## Implementation Phases

### Phase 1: Core Batch Matching (8-10 hours)

**Goal**: Implement basic batch matching: field → column mapping only.

**Tasks**:
- Implement batch data preparation (fetch 5+ sample rows)
- Implement `_build_batch_field_mapping_prompt()` function
- Implement single LLM call: `batch_match_all_fields()`
- Parse batch JSON response: `{"mappings": [{field, filed, index}, ...]}`
- Integrate with UI and display results
- Basic YAML update with mappings

**Success Criteria**:
- Single LLM call processes all fields
- Uses 5+ sample rows per column
- Parses batch JSON correctly
- Returns mapping dictionary: `{field: {filed, index}}`
- User can review mappings before applying
- Total time < 10s for 12 fields

---

### Phase 2: Add Confidence Reasoning (1-2 hours)

**Goal**: Add `confidence_reason` field to explain why each match was made.

**Tasks**:
- Update prompt to request confidence reasoning
- Update JSON schema: Add `confidence_reason` to each mapping
- Parse and store confidence_reason
- Display confidence_reason in UI (optional tooltip or detail view)
- Update YAML to optionally store confidence_reason as comment

**Updated JSON Schema**:
```json
{
  "mappings": [
    {
      "field": "P.O. No.",
      "filed": "PO",
      "index": 0,
      "confidence_reason": "Header 'PO' strongly matches field name, sample values are numeric IDs"
    }
  ]
}
```

**Success Criteria**:
- Each mapping includes confidence_reason
- Reasoning displayed to user
- Helps user understand matching decisions

---

### Phase 3: Format Mismatch Detection and Transformation (3-4 hours)

**Goal**: Detect format mismatches and use LLM to infer extraction patterns.

#### Problem Statement

After Phase 1 & 2, we have field-to-column mappings. But sometimes the matched column has format mismatches:

**Example**:
- YAML expects: `mm: "6"`, `dd: "2"`, `receiving_date: "6/2/2026"`
- Source column: `reci. date` with values: `["pick up 6/2", "pick up 6/5", "pick up 6/8"]`
- Problem: Content doesn't match expected format, but semantically correct

#### Solution: Two-Stage Approach

**Stage 1: Detect Format Mismatches**
- After Phase 1 completes, analyze matched pairs
- For each matched column, compare sample values vs expected format
- Criteria for "format mismatch":
  - Expected format: Based on field name hints (date → YYYY-MM-DD, number → digits only)
  - Actual format: Pattern in sample values
  - Threshold: If <50% samples match expected format, trigger Phase 3

**Stage 2: Send Second Prompt for Transformation Inference**
- Build second prompt with mismatch info
- Ask LLM to infer extraction patterns (regex or transformation logic)
- Parse transformation instructions
- Validate: Apply to samples, check success rate ≥50%
- Store in YAML for runtime execution

**Tasks**:
- Implement format mismatch detection logic
- Build second prompt template for transformation inference
- Parse LLM's transformation instructions
- Validate transformations on sample data
- Store transformation rules in YAML
- Add user review step before applying transformations

**Critical Constraint**: 
- ❌ DO NOT hardcode extraction logic in code
- ✅ USE LLM to infer extraction patterns from samples
- ✅ ALL patterns must come from LLM

**Success Criteria**:
- Mismatch detection works correctly
- Second prompt generates valid transformation patterns
- Validation: ≥50% samples successfully transformed
- User can review transformations before applying
- Transformation rules stored in YAML
- Clear explanations for each transformation

---

### Phase 4: Remove Old Code (2-3 hours)

**Goal**: Clean up existing incremental matching implementation.

**Tasks**:
- Identify and deprecate incremental matching methods
- Remove `_iter_llm_match_columns` or equivalent
- Remove field-by-field loop logic
- Keep only essential model loading code
- Update documentation

**Success Criteria**:
- Old matching code is removed or clearly marked as deprecated
- No field-by-field loops remain
- Model loading code is intact

---

### Phase 5: Testing and Validation (3-4 hours)

**Goal**: Comprehensive testing of batch matching system.

**Tasks**:
- Write unit tests for prompt building (Phase 1 & 3)
- Write unit tests for response parsing
- Write integration tests for end-to-end flow
- Test Phase 3: format mismatch detection and transformation
- Test edge cases (empty columns, insufficient samples)
- Performance testing (timing, memory)

**Success Criteria**:
- All unit tests pass
- Integration tests pass
- Phase 3 transformations validated on test cases
- Edge cases handled gracefully
- Performance meets targets (< 15s total including Phase 3)
- No regression in existing features

## Timeline Estimation

| Phase | Estimated Hours | Cumulative |
|-------|----------------|------------|
| Phase 1: Core batch matching | 8-10 | 8-10h |
| Phase 2: Confidence reasoning | 1-2 | 9-12h |
| Phase 3: Transformation inference | 3-4 | 12-16h |
| Phase 4: Remove old code | 2-3 | 14-19h |
| Phase 5: Testing | 3-4 | 17-23h |
| **Total** | **17-23 hours** | **~3 work days** |

**Phase 3 Breakdown**:
- Mismatch detection: 1h
- Second prompt design: 1h
- Parsing & validation: 1-2h

## Success Criteria

### Functional Requirements (Phase 1 & 2)
- ✅ Single LLM call processes all fields
- ✅ Uses 5+ sample rows per column
- ✅ Batch prompt includes all fields + columns
- ✅ Parses batch JSON response correctly
- ✅ Each mapping includes confidence_reason
- ✅ Updates YAML with all mappings at once
- ✅ Shows progress for single LLM call

### Phase 3 Requirements
- ✅ Format mismatch detection works correctly
- ✅ Second prompt generates transformation patterns
- ✅ Transformation patterns inferred by LLM (no hardcoded rules)
- ✅ Validation: ≥50% samples successfully transformed
- ✅ User review workflow before applying transformations
- ✅ Clear explanations for each transformation

### Performance Requirements
- ✅ Phase 1 & 2: Total time < 10s (12 fields)
- ✅ Phase 3 (optional): Additional 2-3s per column needing transformation
- ✅ LLM inference time < 5s per call
- ✅ Data preparation time < 2s
- ✅ YAML update time < 1s

### Quality Requirements
- ✅ Matching accuracy ≥ 90% (on test dataset)
- ✅ No field-by-field loops
- ✅ No hardcoded regex patterns in code
- ✅ Error handling for all edge cases

### User Experience Requirements
- ✅ Clear progress indication
- ✅ Helpful error messages
- ✅ Ability to review before applying
- ✅ Backup before YAML modification
- ✅ Phase 3 is optional (user confirmation required)

## Risk Assessment

### Technical Risks
1. **LLM output format consistency**: Phi-4 may not always return valid JSON
   - **Mitigation**: Robust JSON extraction with fallbacks
   
2. **Sample data availability**: Sheet may have < 5 rows
   - **Mitigation**: Warning message, use available rows

3. **Mapping conflicts**: Multiple fields may match same column
   - **Mitigation**: Design allows this (e.g., MM/DD/Date from same column)

### Schedule Risks
1. **Underestimated complexity**: Parsing may be harder than expected
   - **Mitigation**: Add buffer time, prioritize core functionality

2. **Testing overhead**: Edge cases may be numerous
   - **Mitigation**: Focus on critical paths first

## Dependencies

### Internal Dependencies
- Phi-4-mini GGUF model must be loaded
- Google Sheets API must be connected
- YAML configuration must be valid

### External Dependencies
- Transformers library with GGUF support
- Hugging Face Hub for model download
- Google Auth credentials

## Acceptance Criteria

This plan is considered **complete** when:

1. ✅ Old incremental matching code is removed
2. ✅ Batch matching is implemented per design doc
3. ✅ Single LLM call processes all fields
4. ✅ Uses 5+ sample rows
5. ✅ Parses batch JSON correctly
6. ✅ Updates YAML with all mappings
7. ✅ All tests pass
8. ✅ Performance targets met
9. ✅ Documentation updated
10. ✅ User can successfully test and apply mappings

## Next Steps

After completing this plan:
1. User testing with real Google Sheets data
2. Optional: Add regex auto-suggestion (separate plan)
3. Optional: Add progress details for debugging
4. Monitor and iterate based on user feedback

---

**Plan Version**: 1.0  
**Created**: 2026-06-13  
**Target Completion**: 2026-06-16  
**Based On**: `docs/llm_matching_flow.md` v1.2.0
