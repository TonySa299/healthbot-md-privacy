#!/bin/bash
# ===========================================================================
#  Station Manager — double-click launcher for macOS
#  Just double-click this file. On first run it sets itself up (one minute),
#  after that it starts instantly and opens in your web browser.
# ===========================================================================
cd "$(dirname "$0")" || exit 1

echo "Starting Station Manager..."

# Pick a Python 3 interpreter.
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo
  echo "  Python 3 is not installed on this Mac."
  echo "  Please install it from https://www.python.org/downloads/ and try again."
  echo
  read -r -p "Press Return to close." _
  exit 1
fi

# Create a private environment and install the two libraries the first time.
if [ ! -d ".venv" ]; then
  echo "First-time setup (this happens only once)..."
  "$PY" -m venv .venv || { echo "Setup failed."; read -r _; exit 1; }
  ./.venv/bin/python -m pip install --quiet --upgrade pip
  ./.venv/bin/python -m pip install --quiet -r requirements.txt
fi

# Launch. app.py opens your browser automatically.
./.venv/bin/python app.py
