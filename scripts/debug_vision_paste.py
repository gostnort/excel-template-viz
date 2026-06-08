from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.phi35_vision_model import get_vision_model_status
from app.services.phi35_vision_paste_infer import (
    VisionInferenceError,
    infer_paste_mapping_from_image_debug,
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

EXPECTED_TARGETS = {
    "P.O. No.",
    "Supplier",
    "Container No.",
    "Product Description",
    "Receiving Date",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="调试截图推测 YAML 输出")
    parser.add_argument(
        "--image",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "logistics_screenshot.png",
        help="截图路径",
    )
    parser.add_argument("--headers", nargs="*", default=GINGER_HEADERS, help="模板字段列表")
    args = parser.parse_args()

    status = get_vision_model_status()
    print(f"model_dir: {status.model_dir}")
    print(f"complete: {status.complete}")
    if status.missing_files:
        print(f"missing_files: {', '.join(status.missing_files)}")
        print("请先运行: python -c \"from app.services.phi35_vision_model import download_vision_model; download_vision_model()\"")
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

    import yaml

    parsed = yaml.safe_load(result.yaml_text)
    targets: set[str] = set()
    for rule in parsed.get("fields", []):
        if isinstance(rule, dict) and rule.get("target"):
            targets.add(str(rule["target"]))
        derive = rule.get("derive") if isinstance(rule, dict) else None
        if isinstance(derive, dict) and derive.get("target"):
            targets.add(str(derive["target"]))
        for sub in rule.get("fields", []) if isinstance(rule, dict) else []:
            if isinstance(sub, dict) and sub.get("target"):
                targets.add(str(sub["target"]))

    missing = EXPECTED_TARGETS - targets
    if missing:
        print("MISSING TARGETS:", ", ".join(sorted(missing)))
        return 1
    print("OK: all expected targets present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
