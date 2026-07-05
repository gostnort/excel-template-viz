"""Smoke test: OpenVINO GPU profile (requires OV INT4 + openvino-genai)."""

from __future__ import annotations

import argparse
import sys

from llm_gemma4.hf_download import openvino_present
from llm_gemma4.backends.openvino.backend import smoke_generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Reply with one word: OK")
    args = parser.parse_args(argv)
    if not openvino_present():
        print("SKIP: OpenVINO IR missing. Run: python -m llm_gemma4 download --profile openvino")
        return 0
    try:
        smoke_generate(args.prompt)
    except ImportError as exc:
        print(f"SKIP: {exc}")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
