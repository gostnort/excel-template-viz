"""Hugging Face repos and local model paths (embed_gemma4.md §4.0)."""

from pathlib import Path


def repo_root() -> Path:
    """Project root (parent of llm_gemma4/)."""
    return Path(__file__).resolve().parent.parent


GGUF_REPO = "google/gemma-4-E4B-it-qat-q4_0-gguf"
GGUF_FILENAME = "gemma-4-E4B_q4_0-it.gguf"
GGUF_DIR = repo_root() / "models" / "gemma4"

OV_INT4_REPO = "OpenVINO/gemma-4-E4B-it-int4-ov"
OV_INT4_DIR = repo_root() / "models" / "gemma4-openvino-int4"
OV_MARKER_FILES = ("openvino_model.xml", "openvino_model.bin")
