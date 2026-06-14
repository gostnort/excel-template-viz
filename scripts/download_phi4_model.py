"""
Download Phi-4 GGUF model from Hugging Face Hub

Automatically selects the best GGUF quantization based on available system memory
and downloads from Vocabook/Phi-4-mini-instruct-GGUF on Hugging Face.

Usage:
    python download_phi4_model.py         # Interactive mode
    python download_phi4_model.py --auto  # Auto mode (no user input)
"""
from pathlib import Path
import sys
import argparse

# Allow importing app services when run as a script from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.phi4_field_matcher import (  # noqa: E402
    QUANT_SPECS,
    ModelDownloadError,
    ensure_model_downloaded,
    get_available_memory_gb,
    gguf_filename,
    select_quantization,
)


def interactive_select_quantization() -> tuple[str, float]:
    """Prompt user to confirm or override auto-selected quantization."""
    available_gb, total_gb = get_available_memory_gb()
    print(f"System Memory: {total_gb:.1f} GB total, {available_gb:.1f} GB available")
    print()

    quant_name, mem_req = select_quantization(auto_mode=True)
    usable_gb = available_gb - 2.0

    print(f"Selected quantization: {quant_name}")
    print(f"  Memory required: ~{mem_req:.1f} GB")
    print()
    print("Available options:")
    for i, (q_name, q_mem, q_desc) in enumerate(QUANT_SPECS, 1):
        marker = " (selected)" if q_name == quant_name else ""
        fit_marker = " [fits]" if q_mem <= usable_gb else " [may not fit]"
        print(f"  {i}. {q_name:8} - {q_mem:.1f}GB - {q_desc}{marker}{fit_marker}")
    print()

    user_input = input(
        f"Press Enter to use {quant_name}, or enter number to choose different version: "
    ).strip()
    if user_input and user_input.isdigit():
        idx = int(user_input) - 1
        if 0 <= idx < len(QUANT_SPECS):
            quant_name, mem_req, _ = QUANT_SPECS[idx]
            print(f"User selected: {quant_name}")
            print()

    return quant_name, mem_req


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Phi-4 GGUF model")
    parser.add_argument("--auto", action="store_true", help="Auto mode (no user input)")
    args = parser.parse_args()

    print("=" * 60)
    print("Phi-4 Model Download - Auto-Quantization Selection")
    print("=" * 60)
    print()

    try:
        if args.auto:
            quant_name, mem_req = select_quantization(auto_mode=True)
            print(f"Auto mode: Using {quant_name} (~{mem_req:.1f} GB)")
            print()
            model_path = ensure_model_downloaded(auto_mode=True, quant_name=quant_name)
        else:
            quant_name, mem_req = interactive_select_quantization()
            model_filename = gguf_filename(quant_name)
            from app.services.phi4_field_matcher import MODEL_DIR

            model_path = MODEL_DIR / model_filename
            if model_path.exists():
                print(f"Model already exists at: {model_path}")
                print(f"File size: {model_path.stat().st_size / (1024 ** 3):.2f} GB")
                print()
                user_input = input("Do you want to re-download? (y/N): ").strip().lower()
                if user_input not in ("y", "yes"):
                    print("Skipping download.")
                    print()
                    print(f"Model ready to use: {model_path}")
                    return
                print()
                model_path = ensure_model_downloaded(
                    auto_mode=False,
                    force_redownload=True,
                    quant_name=quant_name,
                )
            else:
                print("Starting download...")
                print(f"Estimated file size: ~{mem_req:.1f} GB (this may take a while)")
                print()
                model_path = ensure_model_downloaded(auto_mode=False, quant_name=quant_name)

        print()
        print("=" * 60)
        print("Download completed successfully!")
        print(f"Model saved to: {model_path}")
        print(f"File size: {model_path.stat().st_size / (1024 ** 3):.2f} GB")
        print("=" * 60)
        print()

    except ModelDownloadError as exc:
        print()
        print(f"ERROR: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
