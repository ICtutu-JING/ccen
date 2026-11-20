#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv/bin/python}"
NODE="${NODE:-$(command -v node)}"
export CCEN_NODE="$NODE"
export PATH="$(dirname "$NODE"):$PATH"
npm --prefix resources ci --ignore-scripts --no-audit --no-fund
"$PYTHON" make_icon.py
"$PYTHON" -m PyInstaller --noconfirm --distpath dist --workpath build CCEN.spec
cp README.md THIRD_PARTY_NOTICES.md dist/
ditto -c -k --sequesterRsrc --keepParent dist/ClaudeConnectionManager.app "dist/CCEN-macOS-$(uname -m).zip"
echo "已构建：dist/ClaudeConnectionManager.app"
