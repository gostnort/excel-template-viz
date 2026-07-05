"""Smoke test: llama.cpp CUDA profile (requires GGUF + CUDA wheel)."""

from __future__ import annotations

import argparse
import sys

from llm_gemma4.hf_download import gguf_present
from llm_gemma4.backends.llamacpp.backend import smoke_generate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="Reply with one word: OK")
    args = parser.parse_args(argv)
    if not gguf_present():
        print("SKIP: GGUF missing. Run: python -m llm_gemma4 download --profile cuda")
        return 0
    try:
        stats = smoke_generate("cuda", args.prompt)
        if stats.get("tok_per_s", 0) < 1.0:
            print("WARN: tok/s very low; check CUDA wheel and n_gpu_layers")
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
