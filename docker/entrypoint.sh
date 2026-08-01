#!/bin/sh
# Container entry: ensure runtime dirs; hint if model weights are missing.
set -eu

mkdir -p /app/temp /app/exports /app/models/gemma4 /app/paddle_ocr/models

if [ ! -f /app/models/gemma4/gemma-4-E4B-it.litertlm ]; then
  echo "NOTE: Gemma weight not found under /app/models/gemma4/"
  echo "  Mount ./models or download after start, e.g.:"
  echo "  uv run python -c \"from llm_gemma4.hf_download import download_litert; print(download_litert())\""
fi

if [ ! "$(ls -A /app/paddle_ocr/models 2>/dev/null | grep -v '^\.gitkeep$' || true)" ]; then
  echo "NOTE: PaddleOCR models dir looks empty (/app/paddle_ocr/models)."
  echo "  Mount ./paddle_ocr/models or run: uv run python paddle_ocr/main.py"
fi

echo "INSTALL_PROFILE=${INSTALL_PROFILE:-unknown}"
exec "$@"
