"""
Download Gemma 4 E4B Q4_0 GGUF model from Hugging Face Hub.

Downloads gemma-4-E4B_q4_0-it.gguf into models/gemma4/.
Inference requires llama-cpp-python; on Windows CPUs without AVX512 use
0.3.28 from the CPU wheel index (see QUICKSTART.md compatibility table).

Usage:
    python app/download_gemma4_model.py         # Interactive mode
    python app/download_gemma4_model.py --auto  # Auto mode (no user input)
"""
import argparse
import sys

from services.gemma4_field_matcher import (
    MODEL_DIR,
    MODEL_REPO,
    MODEL_WEIGHT_FILE,
    ModelDownloadError,
    ensure_model_downloaded,
    find_model_file,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Gemma 4 E4B Q4_0 GGUF model")
    parser.add_argument("--auto", action="store_true", help="Auto mode (no user input)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if model files already exist",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Gemma 4 E4B Q4_0 GGUF Model Download")
    print(f"Repository: {MODEL_REPO}")
    print("=" * 60)
    print()

    existing = find_model_file()
    if existing and not args.force:
        weight = existing / MODEL_WEIGHT_FILE
        print(f"Model already exists at: {existing}")
        print(f"GGUF file size: {weight.stat().st_size / (1024 ** 3):.2f} GB")
        print()
        if args.auto:
            print("Auto mode: skipping download.")
            return
        user_input = input("Do you want to re-download? (y/N): ").strip().lower()
        if user_input not in ("y", "yes"):
            print("Skipping download.")
            print()
            print(f"Model ready to use: {existing}")
            return
        print()

    try:
        print(f"Downloading into: {MODEL_DIR.resolve()}")
        print("Estimated GGUF size: ~4.8 GB (this may take a while)")
        print()
        model_dir = ensure_model_downloaded(
            force_redownload=args.force or (existing is not None and not args.auto),
        )
        weight = model_dir / MODEL_WEIGHT_FILE
        print()
        print("=" * 60)
        print("Download completed successfully!")
        print(f"Model saved to: {model_dir}")
        print(f"GGUF size: {weight.stat().st_size / (1024 ** 3):.2f} GB")
        print("=" * 60)
        print()
    except ModelDownloadError as exc:
        print()
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
