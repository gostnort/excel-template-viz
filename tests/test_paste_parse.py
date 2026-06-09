import pytest
import yaml

from app.services.paste_mapping_infer import infer_paste_mapping, infer_paste_mapping_yaml
from app.services.paste_parse_config import (
    config_from_dict,
    parse_line_with_config,
    parse_text_with_config,
    validate_mapping_yaml,
)

EXAMPLE_LINE = (
    "10073\tGIN\tShandong Santao\tS26167FG\tEMCU5484116\t140601104991\t"
    "5/9\t5/30\t$2,612\trel\teverport\t6/2\t6/1\t"
    "600000 Fresh Ginger, China. (F7)\t1780\t57294"
)

GINGER_HEADERS = [
    "order",
    "YY",
    "MM",
    "DD",
    "P.O. No.",
    "Container No.",
    "Container Seal No.",
    "Lot No.",
    "Receiving Date",
    "Product Description",
    "Supplier",
    "Truck Line",
]

GINGER_FIXTURE_YAML = """
determiner: "tab"
P.O. No.:
  - filed: "PO"
    index: 0
Supplier:
  - filed: "Supplier"
    index: 2
Container No.:
  - filed: "Container#"
    index: 4
Lot No.:
  - filed: "Com. Inv #"
    index: 3
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
Product Description:
  - filed: "Product"
    index: 13
"""


def _ginger_config():
    return config_from_dict(yaml.safe_load(GINGER_FIXTURE_YAML))


def test_infer_uses_zero_based_index() -> None:
    config = infer_paste_mapping(EXAMPLE_LINE, GINGER_HEADERS)
    assert config["determiner"] == "tab"
    po_rules = config["P.O. No."]
    assert po_rules[0]["index"] == 0


def test_infer_yaml_roundtrip() -> None:
    yaml_text = infer_paste_mapping_yaml(EXAMPLE_LINE, GINGER_HEADERS)
    loaded = yaml.safe_load(yaml_text)
    assert loaded["determiner"] == "tab"
    assert "fields" not in loaded


def test_split_fixture_tsv_matches_spec() -> None:
    config = _ginger_config()
    parsed = parse_line_with_config(EXAMPLE_LINE, config, order=1)
    assert parsed["P.O. No."] == "10073"
    assert parsed["Supplier"] == "Shandong Santao"
    assert parsed["Container No."] == "EMCU5484116"
    assert parsed["Lot No."] == "S26167FG"
    assert parsed["MM"] == "06"
    assert parsed["DD"] == "01"
    assert parsed["Receiving Date"] == "06/01"
    assert parsed["Product Description"] == "600000 Fresh Ginger, China. (F7)"


def test_regex_extracts_date_from_noisy_cell() -> None:
    raw = """
determiner: tab
Receiving Date:
  - filed: "recv. date"
    index: 0
    regex: "(\\\\d{1,2}\\\\/\\\\d{1,2})"
"""
    config = config_from_dict(yaml.safe_load(raw))
    parsed = parse_line_with_config("pickup 5/28, tdi 5/29", config, order=1)
    assert parsed["Receiving Date"] == "05/28"


def test_unknown_filed_still_splits_by_index() -> None:
    raw = """
determiner: tab
P.O. No.:
  - filed: "?"
    index: 0
"""
    config = config_from_dict(yaml.safe_load(raw))
    parsed = parse_line_with_config(EXAMPLE_LINE, config, order=1)
    assert parsed["P.O. No."] == "10073"


def test_comma_determiner() -> None:
    raw = """
determiner: ","
P.O. No.:
  - filed: "PO"
    index: 0
"""
    config = config_from_dict(yaml.safe_load(raw))
    parsed = parse_line_with_config("10073,GIN", config, order=1)
    assert parsed["P.O. No."] == "10073"


def test_failed_extraction_omits_field() -> None:
    raw = """
determiner: tab
Receiving Date:
  - filed: "recv. date"
    index: 99
    regex: "(\\\\d{1,2}\\\\/\\\\d{1,2})"
"""
    config = config_from_dict(yaml.safe_load(raw))
    parsed = parse_line_with_config(EXAMPLE_LINE, config, order=1)
    assert "Receiving Date" not in parsed


def test_validate_rejects_unknown_template_field() -> None:
    yaml_text = """
determiner: tab
Not A Real Field:
  - filed: "PO"
    index: 0
"""
    with pytest.raises(ValueError, match="Unknown template field"):
        validate_mapping_yaml(yaml_text, ["P.O. No."])


def test_id_flag_from_config() -> None:
    from app.services.paste_parse_config import id_target_field_from_config

    raw = """
determiner: tab
P.O. No.:
  - ID: true
    filed: PO
    index: 0
"""
    config = config_from_dict(yaml.safe_load(raw))
    assert id_target_field_from_config(config) == "P.O. No."


def test_parse_text_multiple_lines() -> None:
    config = _ginger_config()
    rows = parse_text_with_config(f"{EXAMPLE_LINE}\n{EXAMPLE_LINE}", config)
    assert len(rows) == 2
    assert rows[0]["P.O. No."] == "10073"