#!/usr/bin/env bash
# Linux/macOS 启动入口（与 run.ps1 等价）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
BOOTUP="$ROOT/bootup"
VENV_PY="$BOOTUP/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" -m nicegui_ui.app
fi
if command -v uv >/dev/null 2>&1; then
  unset VIRTUAL_ENV 2>/dev/null || true
  exec uv run --project "$BOOTUP" python -m nicegui_ui.app
fi
echo "ERROR: bootup/.venv missing and uv not on PATH. Run ./install.sh first." >&2
exit 1
