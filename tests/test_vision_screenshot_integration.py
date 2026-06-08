from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

from app.services.phi35_vision_model import get_vision_model_status

FIXTURE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "logistics_screenshot.png"

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

EXPECTED_TARGETS = {
    "P.O. No.",
    "Supplier",
    "Container No.",
    "Product Description",
    "Receiving Date",
}


def _has_optimum() -> bool:
    return importlib.util.find_spec("optimum.intel.openvino") is not None


def _collect_targets(parsed: dict) -> set[str]:
    targets: set[str] = set()
    for rule in parsed.get("fields", []):
        if not isinstance(rule, dict):
            continue
        if rule.get("target"):
            targets.add(str(rule["target"]))
        derive = rule.get("derive")
        if isinstance(derive, dict) and derive.get("target"):
            targets.add(str(derive["target"]))
        for sub in rule.get("fields", []):
            if isinstance(sub, dict) and sub.get("target"):
                targets.add(str(sub["target"]))
    return targets


@pytest.mark.slow
@pytest.mark.skipif(not FIXTURE_IMAGE.exists(), reason="fixture screenshot missing")
@pytest.mark.skipif(not _has_optimum(), reason="optimum-intel not installed")
@pytest.mark.skipif(not get_vision_model_status().complete, reason="vision model not fully downloaded")
def test_logistics_screenshot_produces_ginger_yaml() -> None:
    from app.services.phi35_vision_paste_infer import infer_paste_mapping_from_image

    yaml_text = infer_paste_mapping_from_image(FIXTURE_IMAGE.read_bytes(), GINGER_HEADERS)
    parsed = yaml.safe_load(yaml_text)
    assert parsed["delimiter"] == "tab"
    assert parsed["index_base"] == 1
    targets = _collect_targets(parsed)
    assert EXPECTED_TARGETS.issubset(targets)
    po_rule = next(item for item in parsed["fields"] if item.get("target") == "P.O. No.")
    assert po_rule["index"] == 1
    container_rule = next(item for item in parsed["fields"] if item.get("target") == "Container No.")
    assert container_rule["index"] == 5
