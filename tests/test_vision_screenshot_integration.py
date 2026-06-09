from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.services.paste_parse_config import config_from_dict, parse_line_with_config
from app.services.phi35_vision_model import get_vision_model_status

FIXTURE_IMAGE = Path(__file__).resolve().parent / "test_image.png"
FIXTURE_TSV = (
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

EXPECTED_SPLIT = {
    "P.O. No.": "10073",
    "Supplier": "Shandong Santao",
    "Container No.": "EMCU5484116",
    "MM": "06",
    "DD": "01",
    "Receiving Date": "06/01",
    "Product Description": "600000 Fresh Ginger, China. (F7)",
}


def _has_optimum() -> bool:
    if importlib.util.find_spec("optimum") is None:
        return False
    return importlib.util.find_spec("optimum.intel.openvino") is not None


def _collect_mapped_fields(parsed: dict) -> set[str]:
    return {key for key in parsed if key not in {"determiner", "order"}}


@pytest.mark.slow
@pytest.mark.skipif(not FIXTURE_IMAGE.exists(), reason="fixture screenshot missing")
@pytest.mark.skipif(not _has_optimum(), reason="optimum-intel not installed")
@pytest.mark.skipif(not get_vision_model_status().complete, reason="vision model not fully downloaded")
def test_screenshot_yaml_splits_fixture_tsv() -> None:
    from app.services.phi35_vision_paste_infer import infer_paste_mapping_from_image

    yaml_text = infer_paste_mapping_from_image(FIXTURE_IMAGE.read_bytes(), GINGER_HEADERS)
    parsed = yaml.safe_load(yaml_text)
    assert parsed["determiner"] == "tab"
    mapped = _collect_mapped_fields(parsed)
    assert {"P.O. No.", "Container No.", "Product Description"}.issubset(mapped)

    config = config_from_dict(parsed)
    assert config is not None
    split = parse_line_with_config(FIXTURE_TSV, config, order=1)
    for field, expected in EXPECTED_SPLIT.items():
        assert split.get(field) == expected, f"{field}: got {split.get(field)!r}, want {expected!r}"

    po_rules = parsed["P.O. No."]
    assert po_rules[0]["index"] == 0
