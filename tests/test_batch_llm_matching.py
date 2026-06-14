import pytest

from app.services.gemma4_field_matcher import (
    MODEL_FILES,
    MODEL_WEIGHT_FILE,
    Gemma4FieldMatcher,
    build_batch_field_mapping_prompt,
    find_model_file,
    prepare_batch_input,
)


def test_model_files_include_weights():
    assert MODEL_WEIGHT_FILE in MODEL_FILES
    assert MODEL_WEIGHT_FILE == "gemma-4-E4B_q4_0-it.gguf"


def test_find_model_file_missing_when_not_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.gemma4_field_matcher.MODEL_DIR",
        tmp_path / "gemma4",
    )
    assert find_model_file() is None


def test_find_model_file_present_when_weights_exist(tmp_path, monkeypatch):
    model_dir = tmp_path / "gemma4"
    model_dir.mkdir(parents=True)
    (model_dir / MODEL_WEIGHT_FILE).write_bytes(b"fake")
    monkeypatch.setattr("app.services.gemma4_field_matcher.MODEL_DIR", model_dir)
    assert find_model_file() == model_dir.resolve()


def _matcher_without_model() -> Gemma4FieldMatcher:
    return Gemma4FieldMatcher.__new__(Gemma4FieldMatcher)


def test_prepare_batch_input_success():
    columns = ["PO", "Container#"]
    rows = [
        {"PO": "1001", "Container#": "MSCU1234567"},
        {"PO": "1002", "Container#": "MSCU1234568"},
        {"PO": "1003", "Container#": "MSCU1234569"},
        {"PO": "1004", "Container#": "MSCU1234570"},
        {"PO": "1005", "Container#": "MSCU1234571"},
    ]
    payload = prepare_batch_input(columns, rows, min_rows=5)
    assert payload[0]["header"] == "PO"
    assert payload[0]["index"] == 0
    assert payload[0]["data"] == ["1001", "1002", "1003", "1004", "1005"]


def test_prepare_batch_input_requires_min_rows():
    with pytest.raises(ValueError):
        prepare_batch_input(["PO"], [{"PO": "1001"}], min_rows=5)


def test_parse_batch_mapping_result_validates_and_fills_defaults():
    matcher = _matcher_without_model()
    response = """
    {
      "mappings": [
        {"field": "P.O. No.", "filed": "po", "index": 0, "confidence_reason": "header match"},
        {"field": "Container No.", "filed": "unknown_col", "index": 2, "confidence_reason": "guess"}
      ]
    }
    """
    result = matcher._parse_batch_mapping_result(
        response,
        ["PO", "Container#"],
        ["P.O. No.", "Container No.", "Supplier"],
    )
    assert result["P.O. No."]["filed"] == "PO"
    assert result["P.O. No."]["index"] == 0
    assert result["Container No."]["filed"] == "?"
    assert result["Supplier"]["index"] == -1


def test_detect_format_mismatches_finds_date_column():
    matcher = _matcher_without_model()
    mappings = {
        "mm": {"filed": "reci. date", "index": 2, "confidence_reason": "test"},
        "dd": {"filed": "reci. date", "index": 2, "confidence_reason": "test"},
    }
    sample_rows = [
        {"reci. date": "pick up 6/2"},
        {"reci. date": "pick up 6/5"},
        {"reci. date": "pick up 6/8"},
        {"reci. date": "pick up 6/12"},
        {"reci. date": "pick up 6/15"},
    ]
    mismatches = matcher.detect_format_mismatches(mappings, sample_rows)
    assert "reci. date" in mismatches
    assert any(name == "mm" for name, _ in mismatches["reci. date"])


def test_validate_transformation_regex():
    matcher = _matcher_without_model()
    rule = {
        "source_column": "reci. date",
        "target_field": "mm",
        "extraction_method": "regex",
        "pattern": r"^pick up (\d{1,2})/(\d{1,2})$",
        "extract_group": 1,
        "explanation": "extract month",
    }
    ok, rate, extracted = matcher.validate_transformation(
        rule,
        ["pick up 6/2", "pick up 6/5", "pick up 6/8"],
    )
    assert ok is True
    assert rate == 1.0
    assert extracted == ["6", "6", "6"]


def test_build_batch_field_mapping_prompt_includes_fields_and_columns():
    columns = ["PO", "Container#"]
    rows = [
        {"PO": "1001", "Container#": "MSCU1234567"},
        {"PO": "1002", "Container#": "MSCU1234568"},
        {"PO": "1003", "Container#": "MSCU1234569"},
        {"PO": "1004", "Container#": "MSCU1234570"},
        {"PO": "1005", "Container#": "MSCU1234571"},
    ]
    source_data = prepare_batch_input(columns, rows, min_rows=5)
    prompt = build_batch_field_mapping_prompt(source_data, ["P.O. No.", "Container No."])
    assert "P.O. No." in prompt
    assert "Container No." in prompt
    assert "PO" in prompt
    assert "mappings" in prompt


def test_prepare_llm_test_prompt_without_template():
    from app.components.gradio_config import prepare_llm_test_prompt

    prepared, prompt, response, result, elapsed = prepare_llm_test_prompt(
        None, None, None, 0.0
    )
    assert prepared is None
    assert prompt == ""
    assert "请先选择模板" in result


def test_extract_response_text_strips_thinking_block():
    matcher = _matcher_without_model()
    raw = (
        "<|channel>thought\ninternal reasoning\n<channel|>\n"
        '<|channel>final\n{"column": "PO"}\n'
    )
    assert matcher._extract_response_text(raw) == '{"column": "PO"}'
