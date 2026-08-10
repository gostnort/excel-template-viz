#!/usr/bin/env bash
# Linux/macOS 安装入口（与 install.bat 等价，均调用 bootstrap_install.py）
set -euo pipefail
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 bootup/bootstrap_install.py "$@"
fi
if command -v python >/dev/null 2>&1; then
  exec python bootup/bootstrap_install.py "$@"
fi
echo "ERROR: python3 not found. Install Python 3.10/3.11, then re-run ./install.sh" >&2
exit 1
