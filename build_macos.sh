#!/bin/sh
set -eu

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR=".venv-macos"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r requirements.txt
"$VENV_DIR/bin/python" -m PyInstaller \
    --noconfirm \
    --clean \
    --windowed \
    --onedir \
    --name DataSheet \
    --collect-data tzdata \
    --distpath dist-macos \
    --workpath build-macos \
    --specpath build-macos \
    run_datasheet.py

printf '%s\n' "Build complete: $(pwd)/dist-macos/DataSheet.app"
