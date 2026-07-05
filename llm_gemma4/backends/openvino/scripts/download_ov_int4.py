"""Download OpenVINO INT4 Gemma 4 E4B from Hugging Face (embed_gemma4.md §4.0)."""

from __future__ import annotations

import argparse
import sys

from llm_gemma4.hf_download import (
    DownloadError,
    download_openvino_int4,
    openvino_present,
)
from llm_gemma4.models_catalog import OV_INT4_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Gemma 4 E4B OpenVINO INT4")
    parser.add_argument("--auto", action="store_true", help="Non-interactive")
    parser.add_argument("--force", action="store_true", help="Re-download if present")
    args = parser.parse_args(argv)
    if openvino_present() and not args.force:
        print(f"OpenVINO IR already present: {OV_INT4_DIR}")
        if args.auto:
            return 0
        answer = input("Re-download? (y/N): ").strip().lower()
        if answer not in {"y", "yes"}:
            return 0
    try:
        path = download_openvino_int4(force=args.force)
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
