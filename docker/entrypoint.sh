#!/bin/sh
# Container entry: ensure runtime dirs; hint if OCR weights are missing.
set -eu

mkdir -p /app/temp /app/exports /app/paddle_ocr/models

if [ ! "$(ls -A /app/paddle_ocr/models 2>/dev/null | grep -v '^\.gitkeep$' || true)" ]; then
  echo "NOTE: PaddleOCR models dir looks empty (/app/paddle_ocr/models)."
  echo "  Mount ./paddle_ocr/models or run: uv run --project bootup python paddle_ocr/main.py"
fi

echo "INSTALL_PROFILE=${INSTALL_PROFILE:-unknown}"
echo "LLM: use a host LM Studio and llm_lmstudio/user.toml (api_url)."
exec "$@"
