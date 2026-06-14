# Batch LLM Field Matching - Technical Specification

## Overview

This document specifies the technical implementation of batch LLM field matching as designed in `docs/llm_matching_flow.md`.

**Core Principle**: ONE LLM call for ALL fields and ALL columns.

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Gradio UI Layer                         │
│              (app/components/gradio_config.py)              │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │          handle_llm_test()                           │  │
│  │  - Receive user input (template, test_cols)          │  │
│  │  - Call batch matching                               │  │
│  │  - Display results                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Batch Matching Engine                           │
│         (app/services/phi4_field_matcher.py)                │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │   batch_match_sheet_fields_to_yaml()                 │  │
│  │                                                       │  │
│  │   1. Prepare batch input                             │  │
│  │      └─> prepare_batch_input()                       │  │
│  │                                                       │  │
│  │   2. Build batch prompt                              │  │
│  │      └─> _build_batch_field_mapping_prompt()         │  │
│  │                                                       │  │
│  │   3. Single LLM call                                 │  │
│  │      └─> model.generate()                            │  │
│  │                                                       │  │
│  │   4. Parse batch response                            │  │
│  │      └─> _parse_batch_mapping_result()               │  │
│  │                                                       │  │
│  │   5. Return mappings                                 │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  Phi-4-mini LLM                             │
│            (4B GGUF, CPU inference)                         │
└─────────────────────────────────────────────────────────────┘
```

## Data Structures

### Input: Source Columns Data

```python
from typing import TypedDict

class SourceColumnData(TypedDict):
    index: int              # 0-based column index
    header: str             # Column header name
    data: list[str]         # Sample values (min 5 rows)

# Example:
source_columns_data: list[SourceColumnData] = [
    {
        "index": 0,
        "header": "PO",
        "data": ["10073", "10021", "10055", "10089", "10102"]
    },
    {
        "index": 1,
        "header": "Container#",
        "data": ["MSCU1234567", "ASDB123456", "TCLU9876543", "HLBU5551212", "CMAU4443332"]
    }
]
```

### Output: Phase 1 Batch Mapping Result

```python
class FieldMapping(TypedDict):
    field: str              # YAML field name
    filed: str | None       # Matched source column header (or null)
    index: int              # Source column index (-1 if no match)

class BatchMappingResult(TypedDict):
    mappings: list[FieldMapping]

# Example:
batch_result: BatchMappingResult = {
    "mappings": [
        {"field": "P.O. No.", "filed": "PO", "index": 0},
        {"field": "Container No.", "filed": "Container#", "index": 1},
        {"field": "Container Seal No.", "filed": None, "index": -1}
    ]
}
```

### Output: Phase 2 Batch Mapping with Confidence

```python
class FieldMappingWithConfidence(TypedDict):
    field: str              # YAML field name
    filed: str | None       # Matched source column header (or null)
    index: int              # Source column index (-1 if no match)
    confidence_reason: str  # Explanation of why this match was made

class BatchMappingResultV2(TypedDict):
    mappings: list[FieldMappingWithConfidence]

# Example:
batch_result_v2: BatchMappingResultV2 = {
    "mappings": [
        {
            "field": "P.O. No.",
            "filed": "PO",
            "index": 0,
            "confidence_reason": "Header 'PO' strongly matches field name, sample values are numeric IDs"
        },
        {
            "field": "Container No.",
            "filed": "Container#",
            "index": 1,
            "confidence_reason": "Header matches pattern, samples show container format (MSCU1234567)"
        },
        {
            "field": "Container Seal No.",
            "filed": None,
            "index": -1,
            "confidence_reason": "No source column contains seal number data"
        }
    ]
}
```

### Output: Phase 3 Transformation Instructions

```python
class TransformationRule(TypedDict):
    source_column: str           # Source column name
    target_field: str            # Target YAML field name
    extraction_method: str       # "regex", "split", "replace", etc.
    pattern: str                 # Regex pattern or transformation expression
    extract_group: int | None    # Regex capture group index (if applicable)
    explanation: str             # LLM's explanation of the transformation

class TransformationResult(TypedDict):
    transformations: list[TransformationRule]

# Example:
transformation_result: TransformationResult = {
    "transformations": [
        {
            "source_column": "reci. date",
            "target_field": "mm",
            "extraction_method": "regex",
            "pattern": r"^pick up (\d{1,2})/(\d{1,2})$",
            "extract_group": 1,
            "explanation": "Extract month from 'pick up M/D' pattern, first capture group"
        },
        {
            "source_column": "reci. date",
            "target_field": "dd",
            "extraction_method": "regex",
            "pattern": r"^pick up (\d{1,2})/(\d{1,2})$",
            "extract_group": 2,
            "explanation": "Extract day from 'pick up M/D' pattern, second capture group"
        }
    ]
}
```

### Internal: Mapping Dictionary

```python
# After parsing, convert to dictionary for YAML update
mapping_dict: dict[str, dict[str, Any]] = {
    "P.O. No.": {"filed": "PO", "index": 0},
    "Container No.": {"filed": "Container#", "index": 1},
    "Container Seal No.": {"filed": "?", "index": -1}
}
```

## API Specifications

### 1. Batch Data Preparation

```python
def prepare_batch_input(
    source_columns: list[str],
    sample_rows: list[dict[str, str]],
    min_rows: int = 5
) -> list[SourceColumnData]:
    """
    Prepare source columns with sample data for batch matching.
    
    Args:
        source_columns: List of source column headers
        sample_rows: Sample data rows (min 5 rows)
        min_rows: Minimum required sample rows (default: 5)
    
    Returns:
        List of SourceColumnData with index, header, and sample values
    
    Raises:
        ValueError: If sample_rows < min_rows
    
    Example:
        >>> columns = ["PO", "Container#"]
        >>> rows = [
        ...     {"PO": "10073", "Container#": "MSCU1234567"},
        ...     {"PO": "10021", "Container#": "ASDB123456"},
        ...     {"PO": "10055", "Container#": "TCLU9876543"},
        ...     {"PO": "10089", "Container#": "HLBU5551212"},
        ...     {"PO": "10102", "Container#": "CMAU4443332"}
        ... ]
        >>> prepare_batch_input(columns, rows)
        [
            {"index": 0, "header": "PO", "data": ["10073", "10021", "10055", "10089", "10102"]},
            {"index": 1, "header": "Container#", "data": ["MSCU1234567", "ASDB123456", ...]}
        ]
    """
    if len(sample_rows) < min_rows:
        raise ValueError(f"At least {min_rows} sample rows required, got {len(sample_rows)}")
    
    result: list[SourceColumnData] = []
    for idx, header in enumerate(source_columns):
        data = [str(row.get(header, "") or "") for row in sample_rows[:min_rows]]
        result.append({"index": idx, "header": header, "data": data})
    
    return result
```

### 2. Batch Prompt Building

```python
def _build_batch_field_mapping_prompt(
    source_columns_data: list[SourceColumnData],
    yaml_field_names: list[str]
) -> str:
    """
    Build batch matching prompt for LLM.
    
    Uses the prompt template from docs/llm_matching_flow.md section 3.4.
    
    Args:
        source_columns_data: Source columns with sample values
        yaml_field_names: All YAML template field names
    
    Returns:
        Complete prompt string for LLM
    
    Example:
        >>> source_data = [
        ...     {"index": 0, "header": "PO", "data": ["10073", "10021", ...]},
        ...     {"index": 1, "header": "Container#", "data": ["MSCU1234567", ...]}
        ... ]
        >>> yaml_fields = ["P.O. No.", "Container No.", "Supplier"]
        >>> prompt = _build_batch_field_mapping_prompt(source_data, yaml_fields)
    """
    import json
    
    # Serialize source columns
    source_json = json.dumps(source_columns_data, ensure_ascii=False, indent=2)
    
    # Serialize YAML fields
    fields_json = json.dumps(yaml_field_names, ensure_ascii=False, indent=2)
    
    # Use prompt template from design doc
    prompt = f"""You map Google Sheet source columns to template YAML fields for a paste/lookup config.

## Source columns (user-selected; header + sample rows)
Each column includes at least 5 sample values from the connected sheet.
{source_json}

## Template fields (YAML top-level keys)
{fields_json}

## Rules
1. For each template field, pick the best matching source "header" using BOTH header text and the "data" values.
2. "index" MUST be the source column's index from Source columns (0-based). Use -1 when filed is null.
3. One source column may map to multiple template fields only if they share the same cell (e.g. MM/DD/Receiving Date from one date column).
4. Do not invent column names. Do not map unrelated fields just to use every column.

Reply with JSON only (no markdown, no explanation):
{{
  "mappings": [
    {{"field": "P.O. No.", "filed": "PO", "index": 0}},
    {{"field": "Container No.", "filed": "Container#", "index": 1}},
    {{"field": "Container Seal No.", "filed": null, "index": -1}}
  ]
}}
JSON:"""
    
    return prompt
```

### 3. Batch LLM Call

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
    
    Example:
        >>> matcher = Phi4FieldMatcher()
        >>> source_data = [...]  # From prepare_batch_input()
        >>> yaml_fields = ["P.O. No.", "Container No.", "Supplier"]
        >>> mappings = matcher.batch_match_all_fields(source_data, yaml_fields)
        >>> mappings["P.O. No."]
        {"filed": "PO", "index": 0}
    """
    # Build prompt
    prompt = self._build_batch_field_mapping_prompt(
        source_columns_data,
        yaml_field_names
    )
    
    # Single LLM inference
    response = self._generate(
        prompt,
        max_new_tokens=1024,
        temperature=0.0
    )
    
    # Extract source column headers for validation
    source_columns = [col["header"] for col in source_columns_data]
    
    # Parse response
    mappings = self._parse_batch_mapping_result(
        response,
        source_columns,
        yaml_field_names
    )
    
    return mappings
```

### 4. Batch Response Parsing

```python
def _parse_batch_mapping_result(
    self,
    response_text: str,
    source_columns: list[str],
    expected_fields: list[str]
) -> dict[str, dict[str, Any]]:
    """
    Parse batch JSON response from LLM.
    
    Args:
        response_text: Raw LLM response
        source_columns: Valid source column headers
        expected_fields: Expected YAML field names
    
    Returns:
        Mapping dictionary: {field: {filed, index}}
    
    Behavior:
        - Extract JSON from response (handle markdown code blocks)
        - Validate "filed" values against source_columns
        - Handle null mappings (filed=null -> filed="?", index=-1)
        - Ensure all expected_fields present in output
    
    Example:
        >>> response = '{"mappings": [{"field": "P.O. No.", "filed": "PO", "index": 0}]}'
        >>> source_cols = ["PO", "Container#"]
        >>> expected = ["P.O. No.", "Container No."]
        >>> result = _parse_batch_mapping_result(response, source_cols, expected)
        >>> result
        {
            "P.O. No.": {"filed": "PO", "index": 0},
            "Container No.": {"filed": "?", "index": -1}  # Not in response
        }
    """
    import json
    import re
    
    # Extract JSON from response (may be wrapped in markdown)
    json_match = re.search(r'\{[\s\S]*"mappings"[\s\S]*\}', response_text)
    if not json_match:
        raise ValueError("No valid JSON found in LLM response")
    
    parsed = json.loads(json_match.group(0))
    mappings_list = parsed.get("mappings", [])
    
    # Create case-insensitive lookup for source columns
    header_by_norm = {h.strip().lower(): h for h in source_columns}
    
    # Build result dictionary
    result: dict[str, dict[str, Any]] = {}
    
    for item in mappings_list:
        field = str(item.get("field", "")).strip()
        if field not in expected_fields:
            continue  # Skip unexpected fields
        
        filed = item.get("filed")
        index = item.get("index", -1)
        
        # Handle null mappings
        if filed is None or str(filed).lower() in ("null", "none"):
            result[field] = {"filed": "?", "index": -1}
            continue
        
        # Validate filed against source columns (case-insensitive)
        filed_str = str(filed).strip()
        canonical = header_by_norm.get(filed_str.lower())
        
        if canonical is None:
            # Invalid column name, mark as unmapped
            result[field] = {"filed": "?", "index": -1}
            continue
        
        # Use canonical column name and validate index
        idx = source_columns.index(canonical)
        if isinstance(index, int) and 0 <= index < len(source_columns):
            # Trust LLM index if valid
            idx = index if source_columns[index] == canonical else idx
        
        result[field] = {"filed": canonical, "index": idx}
    
    # Ensure all expected fields present
    for field in expected_fields:
        result.setdefault(field, {"filed": "?", "index": -1})
    
    return result
```

### 5. YAML Update

```python
def apply_batch_mapping_to_yaml(
    yaml_config: dict,
    mappings: dict[str, dict[str, Any]]
) -> dict:
    """
    Apply batch mapping results to YAML configuration.
    
    Args:
        yaml_config: Current YAML configuration dictionary
        mappings: Mapping results from batch matching
    
    Returns:
        Updated YAML configuration
    
    Behavior:
        - Update "filed" and "index" for each matched field
        - Handle list-type fields (update all items)
        - Skip unmapped fields (filed="?")
        - Preserve other YAML properties (regex, ID, etc.)
    
    Example:
        >>> yaml_config = {
        ...     "P.O. No.": [{"filed": "?", "index": -1, "regex": "\\d+"}]
        ... }
        >>> mappings = {
        ...     "P.O. No.": {"filed": "PO", "index": 0}
        ... }
        >>> updated = apply_batch_mapping_to_yaml(yaml_config, mappings)
        >>> updated["P.O. No."][0]
        {"filed": "PO", "index": 0, "regex": "\\d+"}
    """
    for field, mapping_info in mappings.items():
        if field not in yaml_config:
            continue
        
        filed = mapping_info.get("filed", "?")
        index = mapping_info.get("index", -1)
        
        # Skip unmapped fields
        if filed == "?":
            continue
        
        # Update field configuration
        field_config = yaml_config[field]
        
        if isinstance(field_config, list):
            # List-type field (e.g., [{"filed": "...", "index": ...}])
            for item in field_config:
                if isinstance(item, dict):
                    item["filed"] = filed
                    item["index"] = index
        elif isinstance(field_config, dict):
            # Dict-type field
            field_config["filed"] = filed
            field_config["index"] = index
    
    return yaml_config
```

## Prompt Templates

### Phase 1: Complete Prompt Format (Field Matching)

See `_build_batch_field_mapping_prompt()` implementation above.

**Key Elements**:
1. **Source columns**: JSON array with index, header, data (5 values)
2. **Template fields**: JSON array of field names
3. **Rules**: 4 rules for matching logic
4. **Output format**: JSON with "mappings" array

### Phase 2: Prompt with Confidence Reasoning

**Modification**: Add instruction to include `confidence_reason` in each mapping.

```python
prompt = f"""You map Google Sheet source columns to template YAML fields for a paste/lookup config.

## Source columns (user-selected; header + sample rows)
Each column includes at least 5 sample values from the connected sheet.
{source_json}

## Template fields (YAML top-level keys)
{fields_json}

## Rules
1. For each template field, pick the best matching source "header" using BOTH header text and the "data" values.
2. "index" MUST be the source column's index from Source columns (0-based). Use -1 when filed is null.
3. One source column may map to multiple template fields only if they share the same cell (e.g. MM/DD/Receiving Date from one date column).
4. Do not invent column names. Do not map unrelated fields just to use every column.
5. For each mapping, provide "confidence_reason" explaining why this match was made.

Reply with JSON only (no markdown, no explanation):
{{
  "mappings": [
    {{
      "field": "P.O. No.",
      "filed": "PO",
      "index": 0,
      "confidence_reason": "Header 'PO' strongly matches field name, sample values are numeric IDs"
    }},
    {{
      "field": "Container No.",
      "filed": "Container#",
      "index": 1,
      "confidence_reason": "Header matches pattern, samples show container format (MSCU1234567)"
    }},
    {{
      "field": "Container Seal No.",
      "filed": null,
      "index": -1,
      "confidence_reason": "No source column contains seal number data"
    }}
  ]
}}
JSON:"""
```

### Phase 3: Transformation Inference Prompt

**When to use**: After Phase 1/2 completes, if format mismatches are detected.

**Prompt Template**:
```python
def _build_transformation_inference_prompt(
    source_column: str,
    sample_values: list[str],
    target_fields: list[tuple[str, str]]  # [(field_name, expected_format), ...]
) -> str:
    """
    Build prompt for LLM to infer extraction patterns.
    
    Args:
        source_column: Name of source column
        sample_values: At least 5 sample values from the column
        target_fields: List of (field_name, expected_format) tuples
    
    Returns:
        Prompt string for transformation inference
    """
    import json
    
    samples_json = json.dumps(sample_values, ensure_ascii=False, indent=2)
    fields_info = "\n".join([
        f'{i+1}. "{name}" - expects {fmt}'
        for i, (name, fmt) in enumerate(target_fields)
    ])
    
    prompt = f"""Given a source column with sample values, infer extraction patterns for target fields.

## Source Column
Name: "{source_column}"

Sample Values ({len(sample_values)} rows):
{samples_json}

## Target Fields
{fields_info}

## Task
Provide extraction instructions for each target field that can be derived from this source column.

For each extraction:
1. Identify the extraction method: "regex" (for pattern matching), "split" (for string splitting), "replace" (for simple replacements), or "constant" (for fixed values)
2. For regex: Provide the pattern with capture groups, and specify which group to extract
3. For split: Provide the delimiter and which part to take
4. For replace: Provide search/replace pairs
5. Explain your reasoning

## Rules
- Use standard Python regex syntax
- Test your pattern mentally against the sample values
- If a field cannot be extracted from this column, omit it from the result
- Prefer simple patterns over complex ones
- Escape special regex characters

Reply with JSON only (no markdown, no explanation):
{{
  "transformations": [
    {{
      "source_column": "{source_column}",
      "target_field": "field_name",
      "extraction_method": "regex",
      "pattern": "regex_pattern_here",
      "extract_group": 1,
      "explanation": "Your reasoning here"
    }}
  ]
}}
JSON:"""
    
    return prompt
```

**Example Phase 3 Prompt**:

```
Given a source column with sample values, infer extraction patterns for target fields.

## Source Column
Name: "reci. date"

Sample Values (5 rows):
[
  "pick up 6/2",
  "pick up 6/5",
  "pick up 6/8",
  "pick up 6/12",
  "pick up 6/15"
]

## Target Fields
1. "mm" - expects month as integer (e.g., 6)
2. "dd" - expects day as integer (e.g., 2)
3. "receiving_date" - expects full date string (e.g., "6/2/2026")

## Task
Provide extraction instructions for each target field that can be derived from this source column.

For each extraction:
1. Identify the extraction method: "regex" (for pattern matching), "split" (for string splitting), "replace" (for simple replacements), or "constant" (for fixed values)
2. For regex: Provide the pattern with capture groups, and specify which group to extract
3. For split: Provide the delimiter and which part to take
4. For replace: Provide search/replace pairs
5. Explain your reasoning

## Rules
- Use standard Python regex syntax
- Test your pattern mentally against the sample values
- If a field cannot be extracted from this column, omit it from the result
- Prefer simple patterns over complex ones
- Escape special regex characters

Reply with JSON only (no markdown, no explanation):
{
  "transformations": [
    {
      "source_column": "reci. date",
      "target_field": "field_name",
      "extraction_method": "regex",
      "pattern": "regex_pattern_here",
      "extract_group": 1,
      "explanation": "Your reasoning here"
    }
  ]
}
JSON:
```

**Expected Response**:
```json
{
  "transformations": [
    {
      "source_column": "reci. date",
      "target_field": "mm",
      "extraction_method": "regex",
      "pattern": "^pick up (\\d{1,2})/(\\d{1,2})$",
      "extract_group": 1,
      "explanation": "Extract month from 'pick up M/D' pattern, first capture group"
    },
    {
      "source_column": "reci. date",
      "target_field": "dd",
      "extraction_method": "regex",
      "pattern": "^pick up (\\d{1,2})/(\\d{1,2})$",
      "extract_group": 2,
      "explanation": "Extract day from 'pick up M/D' pattern, second capture group"
    },
    {
      "source_column": "reci. date",
      "target_field": "receiving_date",
      "extraction_method": "regex",
      "pattern": "^pick up ((\\d{1,2})/(\\d{1,2}))$",
      "extract_group": 1,
      "explanation": "Extract date portion 'M/D' from the string, can append year later"
    }
  ]
}
```

### Expected LLM Response Formats

**Phase 1 Response**:
```json
{
  "mappings": [
    {"field": "P.O. No.", "filed": "PO", "index": 0},
    {"field": "Container No.", "filed": "Container#", "index": 1},
    {"field": "Receiving Date", "filed": "recv. date", "index": 2},
    {"field": "MM", "filed": "recv. date", "index": 2},
    {"field": "DD", "filed": "recv. date", "index": 2},
    {"field": "Supplier", "filed": "Supplier", "index": 3},
    {"field": "Container Seal No.", "filed": null, "index": -1}
  ]
}
```

**Phase 2 Response**:
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

**Phase 3 Response**: See example above.

**Rules**:
- `field`: Must match YAML field name exactly
- `filed`: Must be source column header or null
- `index`: 0-based column index, -1 for null
- `confidence_reason`: Clear explanation of matching decision (Phase 2+)
- `pattern`: Valid Python regex (Phase 3)
- `extract_group`: Capture group index, 0 for full match (Phase 3)

## Phase 3: Format Mismatch Detection and Transformation

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│           Phase 1 & 2: Field Matching Complete              │
│              Result: {field: {filed, index}}                 │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│          Step 1: Detect Format Mismatches                   │
│   - For each matched pair (field, source_column)            │
│   - Compare sample values vs expected format                │
│   - Threshold: <50% samples match → mismatch detected       │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼ (if mismatches found)
┌─────────────────────────────────────────────────────────────┐
│       Step 2: Build Transformation Inference Prompt         │
│   - Group fields by source column                           │
│   - For each mismatched column:                             │
│     * Include source column name                            │
│     * Include 5+ sample values                              │
│     * Include target fields expecting data from this column │
│     * Include expected format hints                         │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│            Step 3: Call LLM for Transformation              │
│   - Send second prompt to LLM                               │
│   - LLM infers extraction patterns (regex, split, etc.)     │
│   - Parse transformation instructions                       │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│       Step 4: Validate Transformation Patterns              │
│   - Apply patterns to sample values                         │
│   - Calculate success rate                                  │
│   - Require ≥50% success rate                               │
│   - Reject patterns with low success rate                   │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│         Step 5: User Review and Confirmation                │
│   - Display detected transformations                        │
│   - Show sample transformations (before/after)              │
│   - User approves or rejects                                │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼ (if approved)
┌─────────────────────────────────────────────────────────────┐
│       Step 6: Store Transformation Rules in YAML            │
│   - Add transformation metadata to field config             │
│   - Include pattern, method, extract_group, explanation     │
└─────────────────────────────────────────────────────────────┘
```

### Mismatch Detection Logic

```python
def detect_format_mismatches(
    mappings: dict[str, dict[str, Any]],
    sample_rows: list[dict[str, str]]
) -> dict[str, list[tuple[str, str]]]:
    """
    Detect format mismatches between expected and actual values.
    
    Args:
        mappings: Field mappings from Phase 1/2
        sample_rows: Sample data rows
    
    Returns:
        Dictionary: {source_column: [(field_name, expected_format), ...]}
    
    Example:
        >>> mappings = {
        ...     "mm": {"filed": "reci. date", "index": 2},
        ...     "dd": {"filed": "reci. date", "index": 2},
        ...     "receiving_date": {"filed": "reci. date", "index": 2}
        ... }
        >>> sample_rows = [
        ...     {"reci. date": "pick up 6/2"},
        ...     {"reci. date": "pick up 6/5"}
        ... ]
        >>> detect_format_mismatches(mappings, sample_rows)
        {
            "reci. date": [
                ("mm", "month as integer (e.g., 6)"),
                ("dd", "day as integer (e.g., 2)"),
                ("receiving_date", "full date string (e.g., '6/2/2026')")
            ]
        }
    """
    mismatches: dict[str, list[tuple[str, str]]] = {}
    
    # Group fields by source column
    fields_by_column: dict[str, list[str]] = {}
    for field, mapping in mappings.items():
        filed = mapping.get("filed", "?")
        if filed == "?":
            continue
        fields_by_column.setdefault(filed, []).append(field)
    
    # Check each source column
    for source_column, fields in fields_by_column.items():
        # Extract sample values
        sample_values = [
            str(row.get(source_column, ""))
            for row in sample_rows[:5]
        ]
        
        # Check each field expecting data from this column
        for field in fields:
            expected_format = _infer_expected_format(field)
            match_count = sum(
                1 for val in sample_values
                if _matches_expected_format(val, expected_format)
            )
            
            # If <50% samples match expected format, it's a mismatch
            if match_count < len(sample_values) * 0.5:
                mismatches.setdefault(source_column, []).append(
                    (field, expected_format)
                )
    
    return mismatches


def _infer_expected_format(field_name: str) -> str:
    """
    Infer expected format from field name.
    
    Examples:
        - "mm" or "month" → "month as integer (e.g., 6)"
        - "dd" or "day" → "day as integer (e.g., 2)"
        - "yyyy" or "year" → "year as integer (e.g., 2026)"
        - "date" → "date string (e.g., '6/2/2026' or '2026-06-02')"
        - "P.O. No." → "alphanumeric ID"
        - "Container No." → "container format (e.g., 'MSCU1234567')"
    """
    field_lower = field_name.lower()
    
    if field_lower in ("mm", "month"):
        return "month as integer (e.g., 6)"
    elif field_lower in ("dd", "day"):
        return "day as integer (e.g., 2)"
    elif field_lower in ("yyyy", "year"):
        return "year as integer (e.g., 2026)"
    elif "date" in field_lower:
        return "date string (e.g., '6/2/2026' or '2026-06-02')"
    elif "no" in field_lower or "number" in field_lower or "id" in field_lower:
        return "alphanumeric ID"
    else:
        return "text value"


def _matches_expected_format(value: str, expected_format: str) -> bool:
    """
    Check if value matches expected format.
    
    Simple heuristic check:
    - For integer: Check if value is digits only
    - For date: Check if value contains "/" or "-"
    - For ID: Check if value is alphanumeric
    """
    import re
    
    if "integer" in expected_format:
        return bool(re.match(r'^\d+$', value.strip()))
    elif "date" in expected_format:
        return bool(re.search(r'\d+[/-]\d+', value))
    elif "id" in expected_format.lower():
        return bool(re.match(r'^[A-Za-z0-9]+$', value.strip()))
    else:
        return True  # Default: assume match for text values
```

### Transformation Validation

```python
def validate_transformation(
    transformation: TransformationRule,
    sample_values: list[str]
) -> tuple[bool, float, list[str]]:
    """
    Validate transformation pattern against sample values.
    
    Args:
        transformation: Transformation rule to validate
        sample_values: Sample values to test against
    
    Returns:
        (is_valid, success_rate, extracted_values)
    
    Example:
        >>> rule = {
        ...     "extraction_method": "regex",
        ...     "pattern": r"^pick up (\d{1,2})/(\d{1,2})$",
        ...     "extract_group": 1
        ... }
        >>> samples = ["pick up 6/2", "pick up 6/5", "pick up 6/8"]
        >>> validate_transformation(rule, samples)
        (True, 1.0, ["6", "6", "6"])
    """
    import re
    
    method = transformation["extraction_method"]
    extracted = []
    success_count = 0
    
    if method == "regex":
        pattern = transformation["pattern"]
        extract_group = transformation.get("extract_group", 0)
        
        try:
            compiled = re.compile(pattern)
        except re.error:
            return (False, 0.0, [])
        
        for value in sample_values:
            match = compiled.match(value)
            if match:
                try:
                    extracted_value = match.group(extract_group)
                    extracted.append(extracted_value)
                    success_count += 1
                except IndexError:
                    extracted.append("")
            else:
                extracted.append("")
    
    elif method == "split":
        delimiter = transformation.get("delimiter", ",")
        part_index = transformation.get("part_index", 0)
        
        for value in sample_values:
            parts = value.split(delimiter)
            if 0 <= part_index < len(parts):
                extracted.append(parts[part_index].strip())
                success_count += 1
            else:
                extracted.append("")
    
    else:
        # Unsupported method
        return (False, 0.0, [])
    
    success_rate = success_count / len(sample_values) if sample_values else 0.0
    is_valid = success_rate >= 0.5  # Require ≥50% success rate
    
    return (is_valid, success_rate, extracted)
```

### YAML Storage Format

After Phase 3, transformation rules are stored in YAML:

```yaml
# Example: Date field with transformation
receiving_date:
  - filed: "reci. date"
    index: 2
    transformation:
      method: regex
      pattern: '^pick up ((\d{1,2})/(\d{1,2}))$'
      extract_group: 1
      llm_explanation: "Extract date portion 'M/D' from the string"

# Example: Month field with transformation
mm:
  - filed: "reci. date"
    index: 2
    transformation:
      method: regex
      pattern: '^pick up (\d{1,2})/(\d{1,2})$'
      extract_group: 1
      llm_explanation: "Extract month from 'pick up M/D' pattern, first capture group"

# Example: Day field with transformation
dd:
  - filed: "reci. date"
    index: 2
    transformation:
      method: regex
      pattern: '^pick up (\d{1,2})/(\d{1,2})$'
      extract_group: 2
      llm_explanation: "Extract day from 'pick up M/D' pattern, second capture group"

# Example: Container number with transformation
Container No.:
  - filed: "Container Info"
    index: 5
    transformation:
      method: regex
      pattern: 'Container:\s*([A-Z]{4}\d{7})'
      extract_group: 1
      llm_explanation: "Extract container number from 'Container: MSCU1234567 (20ft)' format"
```

### Performance Considerations

**Phase 3 is Optional**:
- Only triggered if format mismatches detected
- Requires user confirmation before execution
- User can skip Phase 3 and manually edit YAML

**Estimated Time**:
- Mismatch detection: ~0.5s
- Per-column transformation inference: ~2-3s
- Validation: ~0.5s per column
- Total: 2-3s per mismatched column

**Example**: If 2 columns have format mismatches, Phase 3 adds ~4-6 seconds.

## Error Handling

### 1. Insufficient Sample Data

```python
if len(sample_rows) < 5:
    # Option A: Raise error (strict)
    raise ValueError("At least 5 sample rows required for batch matching")
    
    # Option B: Warn and continue (lenient)
    gr.Warning(f"Only {len(sample_rows)} sample rows available. "
               f"Recommend at least 5 for better accuracy.")
    # Use available rows
```

### 2. Invalid JSON Response

```python
try:
    json_match = re.search(r'\{[\s\S]*"mappings"[\s\S]*\}', response_text)
    if not json_match:
        raise ValueError("No JSON found")
    parsed = json.loads(json_match.group(0))
except (ValueError, json.JSONDecodeError) as e:
    logger.error(f"Failed to parse LLM response: {e}")
    # Return empty mappings
    return {field: {"filed": "?", "index": -1} for field in expected_fields}
```

### 3. Invalid Column Names

```python
# During parsing, validate filed against source_columns
canonical = header_by_norm.get(filed_str.lower())
if canonical is None:
    logger.warning(f"LLM returned invalid column name: {filed_str}")
    result[field] = {"filed": "?", "index": -1}
    continue
```

### 4. LLM Timeout

```python
import signal

def timeout_handler(signum, frame):
    raise TimeoutError("LLM inference timeout")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(30)  # 30 second timeout

try:
    response = self.model.generate(prompt)
finally:
    signal.alarm(0)
```

## Testing Strategy

### Unit Tests

1. **test_prepare_batch_input**
   - Valid input (5+ rows)
   - Insufficient rows (< 5)
   - Empty columns
   - Missing values in rows

2. **test_build_batch_prompt**
   - Prompt format correctness
   - JSON serialization
   - Special characters handling

3. **test_parse_batch_response**
   - Valid JSON response
   - Markdown-wrapped JSON
   - Invalid column names
   - Null mappings
   - Missing fields

4. **test_apply_mapping_to_yaml**
   - List-type fields
   - Dict-type fields
   - Unmapped fields
   - Preserve existing properties

### Integration Tests

1. **test_end_to_end_batch_matching**
   - Fetch sample data from Google Sheets
   - Build prompt
   - Call LLM
   - Parse response
   - Update YAML
   - Verify results

2. **test_matching_accuracy**
   - Test with known dataset
   - Verify matching accuracy ≥ 90%

### Performance Tests

1. **test_timing**
   - Total time < 10s
   - LLM call time < 5s

2. **test_memory**
   - No memory leaks
   - Reasonable memory usage

## Migration Guide

### From Old Incremental Matching

**Old code** (field-by-field loop):
```python
for field in yaml_fields:
    matched_column = llm_match_single_field(field, columns)
    mappings[field] = matched_column
```

**New code** (batch matching):
```python
# ONE call for ALL fields
mappings = batch_match_all_fields(source_columns_data, yaml_fields)
```

### UI Handler Update

**Old `handle_llm_test()`**:
```python
for idx, (stage, partial) in enumerate(matcher.iter_match_sheet_fields_to_yaml(
    sample_row, yaml_dict
)):
    yield _format_result(stage, partial)
```

**New `handle_llm_test()`**:
```python
# Fetch at least 5 rows
sample_rows = fetch_google_sheet_sample(g_sheet_id, g_sheet_range, min_rows=5)

# Prepare batch input
source_data = prepare_batch_input(filtered_columns, sample_rows)

# Single batch call
mappings = matcher.batch_match_all_fields(source_data, yaml_field_names)

# Apply to YAML
updated_yaml = apply_batch_mapping_to_yaml(yaml_dict, mappings)

yield _format_result(mappings, updated_yaml)
```

## Configuration

### Model Parameters

```python
MODEL_CONFIG = {
    "max_new_tokens": 1024,  # Enough for batch JSON response
    "temperature": 0.0,       # Deterministic output
    "top_p": 0.95,
    "top_k": 50
}
```

### Validation Parameters

```python
VALIDATION_CONFIG = {
    "min_sample_rows": 5,        # Minimum sample rows required
    "min_similarity": 0.0,        # No similarity threshold (trust LLM)
    "allow_null_mappings": True,  # Allow fields with no match
    "strict_column_names": True   # Validate filed against source columns
}
```

---

**Specification Version**: 1.0  
**Last Updated**: 2026-06-13  
**Based On**: `docs/llm_matching_flow.md` v1.2.0
