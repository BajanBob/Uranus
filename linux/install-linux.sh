#!/usr/bin/env bash
# Uranus installer for any Linux with Python 3.11+ (uses a private virtual environment).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
$PY - <<'PYEOF' || { echo "Python 3.11 or newer is required"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PYEOF
$PY -m venv .venv
.venv/bin/pip install --upgrade pip numpy scipy sounddevice pyserial
.venv/bin/python -m unittest tests.test_uranus
cat <<MSG

Done. Run Uranus with:  .venv/bin/python -m uranus plan
Point-and-click window: .venv/bin/python uranus_app.py   (needs your distro's python3-tk / tkinter)
For rig control install Hamlib (rigctld); for FT8/WSPR install WSJT-X.
MSG
