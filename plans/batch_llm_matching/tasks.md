# Batch LLM Field Matching - Task Breakdown

## Phase 1: Core Batch Matching

**Estimated Time**: 8-10 hours

### Task 1.1: Implement Batch Data Preparation
**Estimated**: 2 hours

- [ ] Implement `fetch_google_sheet_sample(min_rows=5)` function
- [ ] Implement `prepare_batch_input()` - format columns + 5 rows
- [ ] Add validation for minimum sample count
- [ ] Add warning UI for insufficient samples

**Success Criteria**:
- Can fetch at least 5 rows from Google Sheets
- Data formatted as `[{index, header, data: [5 values]}, ...]`
- Warning shown when samples < 5
- All source columns have sample data

---

### Task 1.2: Implement Batch Prompt Building
**Estimated**: 2 hours

- [ ] Implement `_build_batch_field_mapping_prompt()` function
- [ ] Use prompt template from spec.md (Phase 1 format)
- [ ] Serialize source columns to JSON
- [ ] Serialize YAML fields to JSON
- [ ] Format complete prompt string

**Success Criteria**:
- Prompt includes ALL source columns with 5 samples
- Prompt includes ALL YAML fields
- JSON formatting is correct
- Prompt matches design doc template

---

### Task 1.3: Implement Single LLM Call
**Estimated**: 1.5 hours

- [ ] Implement `batch_match_all_fields()` function
- [ ] Call `_build_batch_field_mapping_prompt()`
- [ ] Call `self.model.generate()` ONCE
- [ ] Set appropriate generation parameters
- [ ] Add error handling for generation failures

**Success Criteria**:
- Single LLM call made
- Response string returned
- Error handling in place
- Logging for debugging

---

### Task 1.4: Implement Batch Response Parsing
**Estimated**: 2 hours

- [ ] Implement JSON extraction from response
- [ ] Implement `_parse_batch_mapping_result()` function
- [ ] Validate `filed` values against source columns
- [ ] Handle `null` mappings (no match found)
- [ ] Ensure all expected fields present in output

**Success Criteria**:
- All mappings extracted from JSON
- `filed` values validated against source columns
- Unmapped fields have `filed: "?"` and `index: -1`
- Invalid mappings rejected with warnings

---

### Task 1.5: Integrate with UI
**Estimated**: 1.5 hours

- [ ] Update `handle_llm_test()` to use batch matching
- [ ] Display mapping results in UI
- [ ] Add "Apply to YAML" button
- [ ] Implement `apply_batch_mapping_to_yaml()` function

**Success Criteria**:
- UI calls new batch matching
- Results displayed correctly
- User can review before applying
- YAML file updated successfully

---

## Phase 2: Add Confidence Reasoning

**Estimated Time**: 1-2 hours

### Task 2.1: Update Prompt Template
**Estimated**: 30 minutes

- [ ] Modify `_build_batch_field_mapping_prompt()` to request confidence_reason
- [ ] Add rule #5: "For each mapping, provide 'confidence_reason'"
- [ ] Update example output in prompt to include confidence_reason

**Success Criteria**:
- Prompt requests confidence_reason
- Example shows correct format
- Prompt still follows design doc structure

---

### Task 2.2: Update Response Parsing
**Estimated**: 30 minutes

- [ ] Modify `_parse_batch_mapping_result()` to extract confidence_reason
- [ ] Update data structure to include confidence_reason field
- [ ] Handle missing confidence_reason (default to "No reason provided")

**Success Criteria**:
- Parser extracts confidence_reason
- Missing reasons handled gracefully
- Data structure updated

---

### Task 2.3: Display Confidence Reasoning in UI
**Estimated**: 30 minutes

- [ ] Add confidence_reason to mapping display
- [ ] Show as tooltip or expandable detail
- [ ] Format for readability

**Success Criteria**:
- User can view confidence_reason
- UI is not cluttered
- Reasoning helps user understand matches

---

### Task 2.4: Write Unit Tests
**Estimated**: 30 minutes

- [ ] Test parsing with confidence_reason
- [ ] Test parsing without confidence_reason
- [ ] Test display formatting

**Success Criteria**:
- All tests pass
- Edge cases covered

---

## Phase 3: Format Mismatch Detection and Transformation

**Estimated Time**: 3-4 hours

### Task 3.1: Implement Mismatch Detection
**Estimated**: 1 hour

- [ ] Implement `detect_format_mismatches()` function
- [ ] Implement `_infer_expected_format()` helper
- [ ] Implement `_matches_expected_format()` helper
- [ ] Group fields by source column
- [ ] Compare sample values vs expected format
- [ ] Calculate match percentage
- [ ] Identify mismatches (threshold: <50%)

**Success Criteria**:
- Correctly identifies format mismatches
- Groups fields by source column
- Returns dictionary of mismatches
- Threshold logic works correctly

---

### Task 3.2: Build Transformation Inference Prompt
**Estimated**: 1 hour

- [ ] Implement `_build_transformation_inference_prompt()` function
- [ ] Format source column name and samples
- [ ] Format target fields with expected formats
- [ ] Include extraction method guidelines
- [ ] Include regex syntax rules
- [ ] Format JSON output template

**Success Criteria**:
- Prompt clearly explains task
- Includes all necessary information
- Follows spec.md template
- JSON output format specified

---

### Task 3.3: Parse Transformation Instructions
**Estimated**: 30 minutes

- [ ] Implement `_parse_transformation_result()` function
- [ ] Extract JSON from LLM response
- [ ] Parse transformation rules
- [ ] Validate required fields (method, pattern, etc.)

**Success Criteria**:
- Successfully parses transformation JSON
- Validates required fields
- Handles malformed responses

---

### Task 3.4: Validate Transformation Patterns
**Estimated**: 1 hour

- [ ] Implement `validate_transformation()` function
- [ ] Apply regex patterns to sample values
- [ ] Calculate success rate
- [ ] Require ≥50% success rate
- [ ] Return extracted values for review

**Success Criteria**:
- Validation logic works correctly
- Success rate calculated accurately
- Invalid patterns rejected
- User can review extracted values

---

### Task 3.5: Store Transformations in YAML
**Estimated**: 30 minutes

- [ ] Update `apply_batch_mapping_to_yaml()` to include transformations
- [ ] Add transformation metadata to field config
- [ ] Include method, pattern, extract_group, explanation
- [ ] Format YAML correctly

**Success Criteria**:
- Transformations stored in YAML
- Format matches spec.md example
- YAML is valid and readable

---

### Task 3.6: Add User Review Step
**Estimated**: 30 minutes

- [ ] Display detected mismatches to user
- [ ] Show proposed transformations
- [ ] Show before/after sample values
- [ ] Add "Approve" / "Skip" buttons
- [ ] Only apply if user approves

**Success Criteria**:
- User can review all transformations
- Sample transformations shown
- User can approve or skip
- Clear UI workflow

---

### Task 3.7: Write Unit Tests
**Estimated**: 30 minutes

- [ ] Test mismatch detection logic
- [ ] Test transformation prompt building
- [ ] Test transformation parsing
- [ ] Test transformation validation
- [ ] Test YAML storage

**Success Criteria**:
- All tests pass
- Phase 3 logic validated
- Edge cases covered

---

## Phase 4: Remove Old Code

**Estimated Time**: 2-3 hours

### Task 4.1: Identify Incremental Matching Code
**Estimated**: 30 minutes

- [ ] Review `app/services/phi4_field_matcher.py`
- [ ] Identify field-by-field loop methods
- [ ] Document all methods to be removed
- [ ] Check dependencies

**Success Criteria**:
- Complete list of methods to remove
- No critical functionality depends on them

---

### Task 4.2: Mark Methods as Deprecated
**Estimated**: 30 minutes

- [ ] Add deprecation warnings to old methods
- [ ] Update docstrings
- [ ] Add log warnings

**Success Criteria**:
- All old methods deprecated
- Warnings logged

---

### Task 4.3: Remove or Archive Old Code
**Estimated**: 1 hour

- [ ] Remove deprecated methods (or move to archive)
- [ ] Update UI handlers
- [ ] Remove old tests

**Success Criteria**:
- No field-by-field loops remain
- Clean codebase
- Documentation updated

---

## Phase 5: Testing and Validation

**Estimated Time**: 3-4 hours

### Task 6.1: Complete Unit Test Suite
**Estimated**: 1 hour

- [ ] Review all unit tests from previous phases
- [ ] Add missing test cases
- [ ] Ensure test coverage ≥ 80%
- [ ] Fix any failing tests

**Success Criteria**:
- All unit tests pass
- Test coverage ≥ 80%
- No skipped tests (except deprecated methods)

---

### Task 6.2: Run Integration Tests
**Estimated**: 1 hour

- [ ] Test with real Google Sheets data
- [ ] Test with various template configurations
- [ ] Test edge cases (empty sheets, insufficient data)
- [ ] Verify accuracy with known dataset

**Success Criteria**:
- Integration tests pass
- Accuracy ≥ 90% on test dataset
- Edge cases handled gracefully

---

### Task 6.3: Performance Testing
**Estimated**: 1 hour

- [ ] Measure total time (data fetch + LLM + parsing)
- [ ] Measure LLM inference time
- [ ] Measure memory usage
- [ ] Compare with old implementation

**Success Criteria**:
- Total time < 10s
- LLM time < 5s
- Memory usage reasonable
- Faster than old implementation

---

### Task 6.4: User Acceptance Testing
**Estimated**: 1 hour

- [ ] Test UI workflow end-to-end
- [ ] Verify error messages are clear
- [ ] Verify progress indicators work
- [ ] Get feedback from user

**Success Criteria**:
- UI workflow smooth
- Error messages helpful
- User satisfied with results

---

## Summary Checklist

### Phase 1 Completion Criteria
- [ ] Batch data preparation implemented
- [ ] Batch prompt building implemented
- [ ] Single LLM call implemented
- [ ] Response parsing implemented
- [ ] UI integration complete
- [ ] Unit tests pass

### Phase 2 Completion Criteria
- [ ] Prompt updated to request confidence_reason
- [ ] Parser extracts confidence_reason
- [ ] UI displays confidence reasoning
- [ ] Unit tests pass

### Phase 3 Completion Criteria
- [ ] Format mismatch detection implemented
- [ ] Transformation inference prompt implemented
- [ ] Transformation parsing implemented
- [ ] Transformation validation implemented
- [ ] YAML storage includes transformations
- [ ] User review workflow implemented
- [ ] Unit tests pass

### Phase 4 Completion Criteria
- [ ] Old incremental code identified
- [ ] Methods marked as deprecated or removed
- [ ] UI handlers updated
- [ ] Tests cleaned up

### Phase 5 Completion Criteria
- [ ] All unit tests pass (≥80% coverage)
- [ ] Integration tests pass (≥90% accuracy)
- [ ] Phase 3 transformations validated
- [ ] Performance tests pass (< 15s total with Phase 3)
- [ ] User acceptance testing complete

---

## Dependencies Between Tasks

```
Phase 1: Core batch matching
    └─> Phase 2: Add confidence reasoning (depends on Phase 1)
            └─> Phase 3: Transformation inference (depends on Phase 1 & 2)
                    ├─> Phase 4: Remove old code (can be parallel with Phase 3)
                    └─> Phase 5: Testing (depends on all phases)
```

**Critical Path**: 1 → 2 → 3 → 5

**Parallel Tasks**:
- Phase 4 (remove old code) can be done in parallel with Phase 3
- Unit tests can be written in parallel with implementation

---

## Risk Mitigation

### If Phase Takes Longer Than Expected

1. **Focus on Core Functionality First**:
   - Skip progress indicators (Phase 3.3)
   - Skip validation logging (Phase 4.3)
   - Simplify error messages

2. **Reduce Test Coverage**:
   - Focus on critical path tests
   - Defer edge case tests to later

3. **Defer Optional Features**:
   - Backup YAML file (Phase 5.3)
   - "Apply to YAML" button (do manual update first)

### If Accuracy Is Low

1. **Improve Prompt**:
   - Add more examples
   - Clarify rules
   - Add constraints

2. **Add Post-Processing**:
   - Manual correction UI
   - Confidence scores
   - Review step before applying

### If LLM Response Is Invalid

1. **Improve JSON Extraction**:
   - Try multiple regex patterns
   - Add fallback parsers

2. **Retry Logic**:
   - Retry with different temperature
   - Retry with simplified prompt

---

**Task Breakdown Version**: 1.0  
**Last Updated**: 2026-06-13  
**Total Estimated Hours**: 17-23 hours
