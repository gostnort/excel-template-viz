"""Download Gemma 4 E4B GGUF from Hugging Face (embed_gemma4.md §4.0)."""

from __future__ import annotations

import argparse
import sys

from llm_gemma4.hf_download import DownloadError, download_gguf, gguf_present, gguf_weight_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download Gemma 4 E4B GGUF Q4_0")
    parser.add_argument("--auto", action="store_true", help="Non-interactive")
    parser.add_argument("--force", action="store_true", help="Re-download if present")
    args = parser.parse_args(argv)
    if gguf_present() and not args.force:
        path = gguf_weight_path()
        print(f"GGUF already present: {path}")
        print(f"Size: {path.stat().st_size / (1024 ** 3):.2f} GB")
        if args.auto:
            return 0
        answer = input("Re-download? (y/N): ").strip().lower()
        if answer not in {"y", "yes"}:
            return 0
    try:
        path = download_gguf(force=args.force)
    except DownloadError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
