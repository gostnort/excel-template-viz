"""
Download Phi-4 GGUF model from Hugging Face Hub

This script automatically selects the best GGUF quantization based on available system memory
and downloads from bartowski's optimized GGUF repository.

Usage:
    python download_phi4_model.py         # Interactive mode
    python download_phi4_model.py --auto  # Auto mode (no user input)
"""
from pathlib import Path
import sys
import argparse

try:
    from huggingface_hub import hf_hub_download
    import psutil
except ImportError as e:
    print(f"ERROR: Required package not installed: {e}")
    print("Please run: pip install huggingface-hub psutil")
    sys.exit(1)

# Model configuration
MODEL_REPO = "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
MODEL_DIR = Path("models/phi4")

# Quantization versions with memory requirements (GB) and file sizes (approx)
QUANT_VERSIONS = [
    ("Q8_0", 6.5, "Best quality, highest memory"),      # Max quality
    ("Q6_K", 5.0, "Very good quality"),
    ("Q5_K_M", 4.0, "Good quality, balanced"),
    ("Q4_K_M", 3.5, "Balanced (recommended)"),          # Default recommended
    ("Q3_K_M", 3.0, "Lower quality, smaller"),
    ("Q2_K", 2.5, "Minimal quality, smallest"),
]

def get_available_memory_gb() -> float:
    """Get available system memory in GB"""
    mem = psutil.virtual_memory()
    available_gb = mem.available / (1024 ** 3)
    total_gb = mem.total / (1024 ** 3)
    return available_gb, total_gb

def select_quantization(auto_mode: bool = False) -> tuple[str, float]:
    """
    Select best quantization version based on available memory
    
    Args:
        auto_mode: If True, skip user input and use auto-selected version
    
    Returns:
        (quant_name, memory_required): e.g. ("Q4_K_M", 3.5)
    """
    available_gb, total_gb = get_available_memory_gb()
    
    print(f"System Memory: {total_gb:.1f} GB total, {available_gb:.1f} GB available")
    print()
    
    # Reserve 2GB for OS and other processes
    usable_gb = available_gb - 2.0
    
    if usable_gb < 2.0:
        print("WARNING: Very low memory available!")
        print("This may cause performance issues.")
        print()
    
    # Find best quantization that fits in available memory
    selected = None
    for quant_name, mem_req, desc in QUANT_VERSIONS:
        if mem_req <= usable_gb:
            selected = (quant_name, mem_req, desc)
            break
    
    # If nothing fits, use smallest version with warning
    if selected is None:
        selected = QUANT_VERSIONS[-1]
        print(f"WARNING: Limited memory. Using smallest quantization: {selected[0]}")
        print()
    
    quant_name, mem_req, desc = selected
    print(f"Selected quantization: {quant_name}")
    print(f"  Description: {desc}")
    print(f"  Memory required: ~{mem_req:.1f} GB")
    print()
    
    # In auto mode, skip user input
    if auto_mode:
        print(f"Auto mode: Using {quant_name}")
        print()
        return quant_name, mem_req
    
    # Ask user if they want to override
    print("Available options:")
    for i, (q_name, q_mem, q_desc) in enumerate(QUANT_VERSIONS, 1):
        marker = " (selected)" if q_name == quant_name else ""
        fit_marker = " [fits]" if q_mem <= usable_gb else " [may not fit]"
        print(f"  {i}. {q_name:8} - {q_mem:.1f}GB - {q_desc}{marker}{fit_marker}")
    print()
    
    user_input = input(f"Press Enter to use {quant_name}, or enter number to choose different version: ").strip()
    
    if user_input and user_input.isdigit():
        idx = int(user_input) - 1
        if 0 <= idx < len(QUANT_VERSIONS):
            selected = QUANT_VERSIONS[idx]
            print(f"User selected: {selected[0]}")
            print()
    
    return selected[0], selected[1]

def main():
    """Download the Phi-4 GGUF model with auto-selected quantization"""
    # Parse arguments
    parser = argparse.ArgumentParser(description="Download Phi-4 GGUF model")
    parser.add_argument("--auto", action="store_true", help="Auto mode (no user input)")
    args = parser.parse_args()
    
    print("="*60)
    print("Phi-4 Model Download - Auto-Quantization Selection")
    print("="*60)
    print()
    
    # Select quantization based on memory
    quant_name, mem_req = select_quantization(auto_mode=args.auto)
    
    model_filename = f"microsoft_Phi-4-mini-instruct-{quant_name}.gguf"
    
    print(f"Repository: {MODEL_REPO}")
    print(f"File: {model_filename}")
    print(f"Destination: {MODEL_DIR}")
    print()
    
    # Create model directory
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if model already exists
    model_path = MODEL_DIR / model_filename
    if model_path.exists():
        print(f"Model already exists at: {model_path}")
        print(f"File size: {model_path.stat().st_size / (1024**3):.2f} GB")
        print()
        
        if not args.auto:
            user_input = input("Do you want to re-download? (y/N): ").strip().lower()
            if user_input not in ('y', 'yes'):
                print("Skipping download.")
                print()
                print(f"Model ready to use: {model_path}")
                return
        else:
            print("Auto mode: Model already exists, skipping download.")
            return
        
        print()
    
    print("Starting download...")
    print(f"Estimated file size: ~{mem_req:.1f} GB (this may take a while)")
    print()
    
    try:
        downloaded_path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=model_filename,
            local_dir=MODEL_DIR,
            local_dir_use_symlinks=False,
            resume_download=True  # Allow resuming if interrupted
        )
        
        print()
        print("="*60)
        print("Download completed successfully!")
        print(f"Model saved to: {downloaded_path}")
        
        # Show file size
        file_size = Path(downloaded_path).stat().st_size / (1024**3)
        print(f"File size: {file_size:.2f} GB")
        print("="*60)
        print()
        
    except Exception as e:
        print()
        print(f"ERROR: Failed to download model: {e}")
        print()
        print("You can try:")
        print("1. Check your internet connection")
        print(f"2. Visit the model page: https://huggingface.co/{MODEL_REPO}")
        print(f"3. Download manually and place in: {MODEL_DIR}")
        sys.exit(1)

if __name__ == "__main__":
    main()
