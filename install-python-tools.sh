#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/python-tools/requirements.txt"

echo
echo "Portable Python tools installed in:"
echo "  $VENV_DIR"
echo
echo "Next steps:"
echo "  ./start-agent.sh"
echo "  ./usb-tools ask \"Summarize this drive\""
