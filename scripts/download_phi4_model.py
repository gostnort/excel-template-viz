"""
Download Phi-4 GGUF model from Hugging Face Hub

This script downloads the Phi-4-mini-instruct GGUF model 
for field matching between Google Sheets and YAML configurations.
"""
from pathlib import Path
import sys

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print("ERROR: huggingface-hub is not installed")
    print("Please run: pip install huggingface-hub")
    sys.exit(1)

# Model configuration
MODEL_REPO = "bartowski/microsoft_Phi-4-mini-instruct-GGUF"
MODEL_FILE = "Phi-4-mini-instruct-Q4_K_M.gguf"
MODEL_DIR = Path("models/phi4")

def main():
    """Download the Phi-4 GGUF model"""
    print(f"Model: {MODEL_REPO}/{MODEL_FILE}")
    print(f"Destination: {MODEL_DIR}")
    print()
    
    # Create model directory
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    
    # Check if model already exists
    model_path = MODEL_DIR / MODEL_FILE
    if model_path.exists():
        print(f"Model already exists at: {model_path}")
        print(f"File size: {model_path.stat().st_size / (1024**3):.2f} GB")
        print()
        
        user_input = input("Do you want to re-download? (y/N): ").strip().lower()
        if user_input not in ('y', 'yes'):
            print("Skipping download.")
            return
        
        print()
    
    print("Starting download...")
    print("Model size: ~2-3 GB (this may take a while)")
    print()
    
    try:
        downloaded_path = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            local_dir=MODEL_DIR,
            local_dir_use_symlinks=False
        )
        
        print()
        print("="*50)
        print("Download completed successfully!")
        print(f"Model saved to: {downloaded_path}")
        
        # Show file size
        file_size = Path(downloaded_path).stat().st_size / (1024**3)
        print(f"File size: {file_size:.2f} GB")
        print("="*50)
        
    except Exception as e:
        print()
        print(f"ERROR: Failed to download model: {e}")
        print()
        print("You can try:")
        print("1. Check your internet connection")
        print("2. Visit the model page: https://huggingface.co/" + MODEL_REPO)
        print("3. Download manually and place in: " + str(MODEL_DIR))
        sys.exit(1)

if __name__ == "__main__":
    main()
