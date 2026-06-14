import pytest

from app.services.gemma4_field_matcher import (
    MODEL_FILES,
    MODEL_WEIGHT_FILE,
    Gemma4FieldMatcher,
    _collect_yaml_fields,
    batch_mapping_max_tokens,
    build_batch_field_mapping_prompt,
    find_model_file,
    prepare_batch_input,
    propagate_date_component_mappings,
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


def test_parse_batch_mapping_result_salvages_truncated_json():
    matcher = _matcher_without_model()
    response = """
    {
      "mappings": [
        {"field": "P.O. No.", "filed": "PO", "index": 0, "confidence_reason": "header match"},
        {"field": "Container No.", "filed": "Container#", "index": 1, "confidence_reason": "container ids"},
        {"field": "Truck
    """
    result = matcher._parse_batch_mapping_result(
        response,
        ["PO", "Container#"],
        ["P.O. No.", "Container No.", "Supplier"],
    )
    assert result["P.O. No."]["filed"] == "PO"
    assert result["Container No."]["filed"] == "Container#"
    assert result["Supplier"]["filed"] == "?"


def test_collect_yaml_fields_skips_reserved_keys():
    config = {
        "determiner": "tab",
        "fields_per_row": 7,
        "order": [{"filed": "?", "index": -1}],
        "sections": [{"input_area": "B2:F10", "move_to": "down", "offset": 1}],
        "P.O. No.": [{"filed": "?", "index": -1}],
    }
    fields = _collect_yaml_fields(config)
    assert [name for name, _, _ in fields] == ["P.O. No."]


def test_batch_mapping_max_tokens_scales_with_field_count():
    assert batch_mapping_max_tokens(0) == 1024
    assert batch_mapping_max_tokens(5) == 1024
    assert batch_mapping_max_tokens(20) == 1856
    assert batch_mapping_max_tokens(100) == 8256
    assert batch_mapping_max_tokens(125) == 10000


def test_detect_format_mismatches_uses_confidence_reason_keywords():
    matcher = _matcher_without_model()
    mappings = {
        "Receiving Date": {
            "filed": "reci. date",
            "index": 2,
            "confidence_reason": "Date not isolated; complex formatting with prefix text",
        },
    }
    sample_rows = [
        {"reci. date": "pick up 6/2/2026"},
        {"reci. date": "pick up 6/5/2026"},
        {"reci. date": "pick up 6/8/2026"},
        {"reci. date": "pick up 6/12/2026"},
        {"reci. date": "pick up 6/15/2026"},
    ]
    mismatches = matcher.detect_format_mismatches(mappings, sample_rows)
    assert "reci. date" in mismatches
    assert any(name == "Receiving Date" for name, _ in mismatches["reci. date"])


def test_enrich_mappings_with_transformations_attaches_regex(monkeypatch):
    matcher = _matcher_without_model()
    mappings = {
        "Receiving Date": {
            "filed": "reci. date",
            "index": 2,
            "confidence_reason": "complex formatting",
        },
    }
    sample_rows = [
        {"reci. date": "pick up 6/2/2026"},
        {"reci. date": "pick up 6/5/2026"},
        {"reci. date": "pick up 6/8/2026"},
        {"reci. date": "pick up 6/12/2026"},
        {"reci. date": "pick up 6/15/2026"},
    ]
    llm_response = """
    {
      "transformations": [
        {
          "source_column": "reci. date",
          "target_field": "Receiving Date",
          "extraction_method": "regex",
          "pattern": "^pick up (\\\\d{1,2}/\\\\d{1,2}/\\\\d{4})$",
          "extract_group": 1,
          "explanation": "strip pick up prefix"
        }
      ]
    }
    """
    monkeypatch.setattr(matcher, "_generate", lambda *args, **kwargs: llm_response)
    transformations, enriched = matcher.enrich_mappings_with_transformations(mappings, sample_rows)
    assert "reci. date" in transformations
    assert enriched["Receiving Date"]["regex"] == r"^pick up (\d{1,2}/\d{1,2}/\d{4})$"


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


def test_propagate_date_component_mappings_copies_from_receiving_date():
    mappings = {
        "P.O. No.": {"filed": "PO", "index": 0, "confidence_reason": "header match"},
        "Receiving Date": {
            "filed": "recv. date",
            "index": 1,
            "confidence_reason": "date column",
        },
        "mm": {
            "filed": "?",
            "index": -1,
            "confidence_reason": "No mapping returned by model",
        },
        "dd": {
            "filed": "?",
            "index": -1,
            "confidence_reason": "No mapping returned by model",
        },
        "yy": {
            "filed": "?",
            "index": -1,
            "confidence_reason": "No mapping returned by model",
        },
    }
    expected_fields = ["P.O. No.", "Receiving Date", "mm", "dd", "yy"]
    propagated = propagate_date_component_mappings(mappings, expected_fields)
    assert propagated["mm"]["filed"] == "recv. date"
    assert propagated["mm"]["index"] == 1
    assert propagated["dd"]["filed"] == "recv. date"
    assert propagated["yy"]["filed"] == "recv. date"
    assert propagated["P.O. No."]["filed"] == "PO"


def test_propagate_date_component_mappings_preserves_existing():
    mappings = {
        "Receiving Date": {"filed": "recv. date", "index": 1, "confidence_reason": "date"},
        "mm": {"filed": "Month", "index": 2, "confidence_reason": "already mapped"},
    }
    propagated = propagate_date_component_mappings(
        mappings,
        ["Receiving Date", "mm"],
    )
    assert propagated["mm"]["filed"] == "Month"


def test_enrich_mappings_after_date_propagation_infers_mm_dd_regex(monkeypatch):
    matcher = _matcher_without_model()
    mappings = propagate_date_component_mappings(
        {
            "Receiving Date": {
                "filed": "recv. date",
                "index": 1,
                "confidence_reason": "date column",
            },
            "mm": {
                "filed": "?",
                "index": -1,
                "confidence_reason": "No mapping returned by model",
            },
            "dd": {
                "filed": "?",
                "index": -1,
                "confidence_reason": "No mapping returned by model",
            },
        },
        ["Receiving Date", "mm", "dd"],
    )
    sample_rows = [
        {"recv. date": "6/2/2026"},
        {"recv. date": "6/5/2026"},
        {"recv. date": "6/8/2026"},
        {"recv. date": "6/12/2026"},
        {"recv. date": "6/15/2026"},
    ]
    llm_response = """
    {
      "transformations": [
        {
          "source_column": "recv. date",
          "target_field": "mm",
          "extraction_method": "regex",
          "pattern": "^(\\\\d{1,2})/(\\\\d{1,2})/\\\\d{4}$",
          "extract_group": 1,
          "explanation": "month from M/D/YYYY"
        },
        {
          "source_column": "recv. date",
          "target_field": "dd",
          "extraction_method": "regex",
          "pattern": "^(\\\\d{1,2})/(\\\\d{1,2})/\\\\d{4}$",
          "extract_group": 2,
          "explanation": "day from M/D/YYYY"
        }
      ]
    }
    """
    monkeypatch.setattr(matcher, "_generate", lambda *args, **kwargs: llm_response)
    transformations, enriched = matcher.enrich_mappings_with_transformations(mappings, sample_rows)
    assert "recv. date" in transformations
    assert enriched["mm"]["regex"] == r"^(\d{1,2})/(\d{1,2})/\d{4}$"
    assert enriched["dd"]["regex"] == r"^(\d{1,2})/(\d{1,2})/\d{4}$"


def test_build_llm_test_yaml_includes_propagated_date_components():
    import yaml

    from app.components.gradio_config import _build_llm_test_yaml_from_mappings
    from app.services.paste_parse_config import PasteParseConfig, PasteParseRule, config_from_dict
    from app.services.gemma4_field_matcher import propagate_date_component_mappings

    paste_config = PasteParseConfig(
        determiner="tab",
        field_rules={
            "P.O. No.": [PasteParseRule(filed="?", index=-1)],
            "Receiving Date": [PasteParseRule(filed="?", index=-1)],
            "mm": [PasteParseRule(filed="?", index=-1)],
            "dd": [PasteParseRule(filed="?", index=-1)],
        },
        order=[{"filed": "?", "index": -1}],
        worksheet="List",
    )
    column_map = propagate_date_component_mappings(
        {
            "P.O. No.": {"filed": "PO", "index": 0, "confidence_reason": "match"},
            "Receiving Date": {
                "filed": "recv. date",
                "index": 1,
                "confidence_reason": "match",
            },
            "mm": {
                "filed": "?",
                "index": -1,
                "confidence_reason": "No mapping returned by model",
            },
            "dd": {
                "filed": "?",
                "index": -1,
                "confidence_reason": "No mapping returned by model",
            },
        },
        ["P.O. No.", "Receiving Date", "mm", "dd"],
    )
    column_map["mm"]["regex"] = r"^(\d{1,2})/"
    column_map["dd"]["regex"] = r"/(\d{1,2})/"
    yaml_text = _build_llm_test_yaml_from_mappings(
        paste_config,
        column_map,
        ["PO", "recv. date"],
        None,
    )
    parsed = config_from_dict(yaml.safe_load(yaml_text))
    assert parsed is not None
    assert "mm" in parsed.field_rules
    assert "dd" in parsed.field_rules
    assert parsed.field_rules["mm"][0].filed == "recv. date"
    assert parsed.worksheet == "List"


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


def test_apply_column_mapping_includes_inferred_regex():
    from app.components.gradio_config import _apply_column_mapping_to_config
    from app.services.paste_parse_config import PasteParseConfig, PasteParseRule

    paste_config = PasteParseConfig(
        determiner="tab",
        field_rules={
            "Receiving Date": [
                PasteParseRule(filed="?", index=-1, regex=None),
            ],
        },
        order=[{"filed": "?", "index": -1}],
    )
    column_map = {
        "Receiving Date": {
            "filed": "reci. date",
            "index": 2,
            "regex": r"^pick up (\d{1,2}/\d{1,2}/\d{4})$",
        },
    }
    updated = _apply_column_mapping_to_config(
        paste_config,
        column_map,
        ["PO", "Container#", "reci. date"],
        None,
    )
    assert updated.field_rules["Receiving Date"][0].regex == r"^pick up (\d{1,2}/\d{1,2}/\d{4})$"


def test_build_llm_test_yaml_omits_unmapped_fields_and_order_placeholders():
    import yaml

    from app.components.gradio_config import _build_llm_test_yaml_from_mappings
    from app.services.paste_parse_config import PasteParseConfig, PasteParseRule, config_from_dict

    paste_config = PasteParseConfig(
        determiner="tab",
        field_rules={
            "P.O. No.": [PasteParseRule(filed="?", index=-1)],
            "Container No.": [PasteParseRule(filed="?", index=-1)],
            "Receiving Date": [PasteParseRule(filed="?", index=-1)],
        },
        order=[{"filed": "?", "index": -1}],
        worksheet="List",
        sections=[{"input_area": "A2:L2", "move_to": "down", "offset": 1}],
        fields_per_row=7,
    )
    column_map = {
        "P.O. No.": {"filed": "PO", "index": 0},
        "Container No.": {"filed": "?", "index": -1},
        "Receiving Date": {"filed": "recv. date", "index": 1},
    }
    yaml_text = _build_llm_test_yaml_from_mappings(
        paste_config,
        column_map,
        ["PO", "recv. date", "Status"],
        None,
    )
    parsed = config_from_dict(yaml.safe_load(yaml_text))
    assert parsed is not None
    assert set(parsed.field_rules) == {"P.O. No.", "Receiving Date"}
    assert parsed.field_rules["P.O. No."][0].filed == "PO"
    assert parsed.field_rules["Receiving Date"][0].filed == "recv. date"
    assert parsed.worksheet == "List"
    assert parsed.sections == paste_config.sections
    assert "?" not in yaml_text
    assert "Container No." not in yaml_text
    assert yaml_text.index("sections:") < yaml_text.index("P.O. No.:")


def test_apply_column_mapping_order_lists_only_matched_columns():
    from app.components.gradio_config import _apply_column_mapping_to_config
    from app.services.paste_parse_config import PasteParseConfig, PasteParseRule

    paste_config = PasteParseConfig(
        determiner="tab",
        field_rules={
            "P.O. No.": [PasteParseRule(filed="?", index=-1)],
            "Receiving Date": [PasteParseRule(filed="?", index=-1, id_flag=True)],
            "Container No.": [PasteParseRule(filed="?", index=-1)],
        },
    )
    column_map = {
        "P.O. No.": {"filed": "PO", "index": 0},
        "Receiving Date": {"filed": "recv. date", "index": 1},
        "Container No.": {"filed": "?", "index": -1},
    }
    updated = _apply_column_mapping_to_config(
        paste_config,
        column_map,
        ["PO", "recv. date"],
        None,
    )
    assert len(updated.order) == 2
    assert updated.order[0]["filed"] == "PO"
    assert updated.order[1]["filed"] == "recv. date"


def test_prepare_llm_test_prompt_without_template():
    from app.components.gradio_config import prepare_llm_test_prompt

    prepared, prompt, response, elapsed = prepare_llm_test_prompt(
        None, None, None, None, 0.0
    )
    assert prepared is None
    assert prompt == ""
    assert "请先选择模板" in response
