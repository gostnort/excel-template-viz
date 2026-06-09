from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.paste_parse_config import config_from_dict, parse_line_with_config
from app.services.phi35_vision_model import get_vision_model_status
from app.services.phi35_vision_paste_infer import (
    VisionInferenceError,
    infer_paste_mapping_from_image_debug,
)

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug screenshot → YAML mapping inference")
    parser.add_argument(
        "--image",
        type=Path,
        default=ROOT / "tests" / "test_image.png",
        help="Screenshot path",
    )
    parser.add_argument("--headers", nargs="*", default=GINGER_HEADERS, help="Template field list")
    args = parser.parse_args()

    status = get_vision_model_status()
    print(f"model_dir: {status.model_dir}")
    print(f"complete: {status.complete}")
    if status.missing_files:
        print(f"missing_files: {', '.join(status.missing_files)}")
        print(
            'Download first: python -c "from app.services.phi35_vision_model import '
            'download_vision_model; download_vision_model()"'
        )
        return 2

    image_bytes = args.image.read_bytes()
    print(f"image: {args.image} ({len(image_bytes)} bytes)")
    try:
        result = infer_paste_mapping_from_image_debug(image_bytes, list(args.headers))
    except VisionInferenceError as exc:
        print("INFERENCE FAILED:", exc)
        if exc.raw_response:
            print("--- raw response ---")
            print(exc.raw_response)
        return 1

    print("--- yaml ---")
    print(result.yaml_text)
    print("--- raw response ---")
    print(result.raw_response)

    parsed = yaml.safe_load(result.yaml_text)
    if parsed.get("determiner") != "tab":
        print("INVALID: determiner must be tab")
        return 1

    config = config_from_dict(parsed)
    if config is None:
        print("INVALID: no field mappings")
        return 1

    split = parse_line_with_config(FIXTURE_TSV, config, order=1)
    print("--- split fixture TSV ---")
    for field, expected in EXPECTED_SPLIT.items():
        actual = split.get(field)
        print(f"{field}: {actual!r} (expected {expected!r})")
        if actual != expected:
            print("SPLIT MISMATCH")
            return 1

    print("OK: YAML valid and fixture TSV splits match spec")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
