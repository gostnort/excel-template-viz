import yaml

from app.services.paste_mapping_infer import infer_paste_mapping, infer_paste_mapping_yaml
from app.services.paste_parse_config import (
    PasteParseConfig,
    parse_line_with_config,
    parse_text_with_config,
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


def test_infer_finds_po_container_and_date() -> None:
    config = infer_paste_mapping(EXAMPLE_LINE, GINGER_HEADERS)
    targets = {item.get("target") for item in config["fields"] if "target" in item}
    assert "P.O. No." in targets
    assert "Container No." in targets
    nested = next(item for item in config["fields"] if "split" in item)
    assert nested["field_index"] == 13


def test_infer_yaml_roundtrip() -> None:
    yaml_text = infer_paste_mapping_yaml(EXAMPLE_LINE, GINGER_HEADERS)
    loaded = yaml.safe_load(yaml_text)
    assert loaded["delimiter"] == "tab"
    assert loaded["index_base"] == 1


def test_parse_with_manual_yaml_config() -> None:
    raw = """
delimiter: tab
index_base: 1
fields:
  - target: P.O. No.
    field_index: 1
  - target: Container No.
    field_index: 5
  - field_index: 13
    split: /
    fields:
      - target: MM
        local_index: 1
        pad: 2
      - target: DD
        local_index: 2
        pad: 2
    derive:
      target: Receiving Date
      from: [MM, DD]
      format: MM/DD/YY
"""
    config = PasteParseConfig(**yaml.safe_load(raw))
    parsed = parse_line_with_config(EXAMPLE_LINE, config, order=1, reference_year=2026)
    assert parsed["P.O. No."] == "10073"
    assert parsed["Container No."] == "EMCU5484116"
    assert parsed["MM"] == "06"
    assert parsed["DD"] == "01"
    assert parsed["Receiving Date"] == "06/01/26"


def test_parse_text_multiple_lines() -> None:
    raw = """
delimiter: tab
index_base: 1
fields:
  - target: P.O. No.
    field_index: 1
"""
    config = PasteParseConfig(**yaml.safe_load(raw))
    rows = parse_text_with_config(f"{EXAMPLE_LINE}\n{EXAMPLE_LINE}", config)
    assert len(rows) == 2
