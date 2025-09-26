#!/usr/bin/env bash
# build-macos.sh — Build a macOS native single-file executable using PyInstaller
# Run this on macOS (real Mac hardware or macOS runner); PyInstaller must be run on the target OS to produce a native binary.
# Usage: ./build-macos.sh
set -euo pipefail

# Ensure script runs from repo root
ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT_DIR"

# Detect python: prefer python3, python
PY_CANDIDATES=(python3 python)
PY_CMD=""
for p in "${PY_CANDIDATES[@]}"; do
  if command -v "$p" >/dev/null 2>&1; then
    PY_CMD="$p"
    break
  fi
done
if [ -z "$PY_CMD" ]; then
  echo "Python 3 not found in PATH. Install Python 3 (Homebrew: brew install python) and retry." >&2
  exit 1
fi

echo "Using Python: $PY_CMD"

# Create venv
if [ ! -d .venv ]; then
  "$PY_CMD" -m venv .venv
fi

# Activate venv
# shellcheck source=/dev/null
. .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# Clean previous builds
rm -rf dist build kube-sec.spec || true

# macOS (and Linux) use ':' as add-data separator
SEP=:
ADD_DATA=(
  "src/web/templates${SEP}templates"
  "src/web/static${SEP}static"
  "public${SEP}public"
)

PY_ARGS=(--onefile --noconfirm --name kube-sec)
for d in "${ADD_DATA[@]}"; do
  PY_ARGS+=("--add-data=$d")
done
PY_ARGS+=(src/main.py)

# Run PyInstaller via the python module
"$PY_CMD" -m PyInstaller "${PY_ARGS[@]}"

if [ $? -ne 0 ]; then
  echo "PyInstaller failed" >&2
  exit 2
fi

echo "Build complete. Executable: dist/kube-sec"

echo "Run './dist/kube-sec' and visit http://127.0.0.1:8080/_debug/list-templates to verify templates/static."