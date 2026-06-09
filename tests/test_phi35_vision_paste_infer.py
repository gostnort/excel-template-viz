import pytest

from app.services.paste_parse_config import extract_yaml_text, validate_mapping_yaml
from app.services.phi35_vision_model import PHI35_VISION_MODEL_ID


def test_hardcoded_vision_model_id() -> None:
    assert PHI35_VISION_MODEL_ID == "OpenVINO/Phi-3.5-vision-instruct-int4-ov"


def test_extract_yaml_text_strips_fence() -> None:
    raw = "```yaml\ndeterminer: tab\nP.O. No.:\n  - filed: PO\n    index: 0\n```"
    assert "determiner: tab" in extract_yaml_text(raw)


def test_validate_mapping_yaml_rejects_unknown_target() -> None:
    yaml_text = """
determiner: tab
Not A Real Field:
  - filed: PO
    index: 0
"""
    with pytest.raises(ValueError, match="Unknown template field"):
        validate_mapping_yaml(yaml_text, ["P.O. No."])


def test_validate_mapping_yaml_accepts_date_rules() -> None:
    yaml_text = """
determiner: tab
MM:
  - filed: "recv. date"
    index: 12
    regex: "(\\\\d{1,2})(?=\\\\/\\\\d{1,2})"
DD:
  - filed: "recv. date"
    index: 12
    regex: "(?<=\\\\d{1,2}\\\\/)(\\\\d{1,2})"
Receiving Date:
  - filed: "recv. date"
    index: 12
    regex: "(\\\\d{1,2}\\\\/\\\\d{1,2})"
"""
    parsed = validate_mapping_yaml(yaml_text, ["MM", "DD", "Receiving Date"])
    assert parsed["determiner"] == "tab"
    assert "MM" in parsed
