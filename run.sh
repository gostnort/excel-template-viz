#!/usr/bin/env bash
# Linux/macOS 启动入口（与 run.ps1 等价）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
BOOTUP="$ROOT/bootup"
VENV_PY="$BOOTUP/.venv/bin/python"
PROFILE_HELPER="$BOOTUP/uv_profile.py"

uv_extra_args() {
  local py=""
  if [[ -x "$VENV_PY" ]]; then
    py="$VENV_PY"
  elif command -v python3 >/dev/null 2>&1; then
    py="python3"
  elif command -v python >/dev/null 2>&1; then
    py="python"
  else
    return 0
  fi
  if [[ ! -f "$PROFILE_HELPER" ]]; then
    return 0
  fi
  "$py" "$PROFILE_HELPER" --flags || true
}

if [[ -x "$VENV_PY" ]]; then
  exec "$VENV_PY" -m nicegui_ui.app
fi
if command -v uv >/dev/null 2>&1; then
  unset VIRTUAL_ENV 2>/dev/null || true
  extra="$(uv_extra_args)"
  if [[ -n "${extra}" ]]; then
    # shellcheck disable=SC2086
    exec uv run --project "$BOOTUP" ${extra} python -m nicegui_ui.app
  fi
  exec uv run --project "$BOOTUP" python -m nicegui_ui.app
fi
echo "ERROR: bootup/.venv missing and uv not on PATH. Run ./install.sh first." >&2
exit 1
