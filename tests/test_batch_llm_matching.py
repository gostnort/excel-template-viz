import pytest

from app.services.phi4_field_matcher import (
    Phi4FieldMatcher,
    QUANT_VERSIONS,
    gguf_filename,
    prepare_batch_input,
)


def test_gguf_filename_vocabook_naming():
    assert gguf_filename("Q8_0") == "Phi-4-mini-instruct-Q8_0.gguf"
    assert gguf_filename("Q4_K_M") == "Phi-4-mini-instruct-Q4_K_M.gguf"


def test_quant_versions_match_vocabook_repo():
    assert QUANT_VERSIONS == ["Q8_0", "Q6_K", "Q4_K_M", "Q3_K_L"]


def _matcher_without_model() -> Phi4FieldMatcher:
    return Phi4FieldMatcher.__new__(Phi4FieldMatcher)


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
