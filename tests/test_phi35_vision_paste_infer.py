import pytest

from app.services.paste_parse_config import extract_yaml_text, validate_mapping_yaml
from app.services.phi35_vision_model import PHI35_VISION_MODEL_ID


def test_hardcoded_vision_model_id() -> None:
    assert PHI35_VISION_MODEL_ID == "OpenVINO/Phi-3.5-vision-instruct-int4-ov"


def test_extract_yaml_text_strips_fence() -> None:
    raw = "```yaml\ndelimiter: tab\nindex_base: 1\n```"
    assert "delimiter: tab" in extract_yaml_text(raw)


def test_validate_mapping_yaml_rejects_unknown_target() -> None:
    yaml_text = """
delimiter: tab
index_base: 1
fields:
  - target: Not A Real Field
    index: 1
"""
    with pytest.raises(ValueError, match="未知模板字段"):
        validate_mapping_yaml(yaml_text, ["P.O. No."])


def test_validate_mapping_yaml_accepts_nested_date() -> None:
    yaml_text = """
delimiter: tab
index_base: 1
fields:
  - index: 13
    split: /
    fields:
      - target: MM
        index: 1
      - target: DD
        index: 2
    derive:
      target: Receiving Date
      from: [MM, DD]
"""
    parsed = validate_mapping_yaml(yaml_text, ["MM", "DD", "Receiving Date"])
    assert parsed["delimiter"] == "tab"
    assert len(parsed["fields"]) == 1
