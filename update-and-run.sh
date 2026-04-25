#!/usr/bin/env bash
# run.sh — download latest app-blocker from GitHub and run it (macOS / Linux).
# Save anywhere, chmod +x, double-click or `./run.sh` to launch.

set -euo pipefail

INSTALL_DIR="$HOME/app-blocker"
ZIP_PATH="/tmp/app-blocker.zip"
EXTRACT_TMP="/tmp/app-blocker-extract"
ZIP_URL="https://github.com/z3nabi/app-blocker/archive/refs/heads/main.zip"

echo "=== app-blocker launcher ==="

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "ERROR: python3/python not found on PATH" >&2
    exit 1
fi
echo "Using: $PY"

echo "Downloading latest..."
curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"

echo "Extracting to $INSTALL_DIR..."
rm -rf "$EXTRACT_TMP" "$INSTALL_DIR"
mkdir -p "$EXTRACT_TMP"
unzip -q "$ZIP_PATH" -d "$EXTRACT_TMP"
mv "$EXTRACT_TMP/app-blocker-main" "$INSTALL_DIR"
rm -rf "$EXTRACT_TMP" "$ZIP_PATH"

echo "Starting app-blocker..."
cd "$INSTALL_DIR"
exec "$PY" main.py
