#!/usr/bin/env bash
# Thin wrapper around update_and_run.py.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/update_and_run.py"

if [ ! -f "$SCRIPT" ]; then
    echo "ERROR: update_and_run.py not found next to this script." >&2
    echo "  Expected: $SCRIPT" >&2
    echo "  Download from: https://raw.githubusercontent.com/z3nabi/app-blocker/main/update_and_run.py" >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT" "$@"
elif command -v python >/dev/null 2>&1; then
    exec python "$SCRIPT" "$@"
else
    echo "ERROR: python3/python not found on PATH" >&2
    exit 1
fi
