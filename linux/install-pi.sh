#!/usr/bin/env bash
# Uranus installer for Raspberry Pi OS (Bookworm or newer) and Debian/Ubuntu.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== Installing system packages (needs sudo) =="
sudo apt-get update
sudo apt-get install -y python3 python3-numpy python3-scipy python3-tk python3-serial \
    alsa-utils libhamlib-utils
echo "== Optional: WSJT-X (FT8/WSPR encoders) =="
sudo apt-get install -y wsjtx || echo "wsjtx not installed - FT8/WSPR slots will be skipped"
python3 - <<'PY' || { echo "Python 3.11 or newer is required"; exit 1; }
import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)
PY
sudo usermod -aG dialout,audio "$USER" || true
echo "== Self-tests =="
python3 -m unittest tests.test_uranus
cat <<MSG

Done. Next:
  1. nano config/uranus.toml        (callsign, grid, lat/lon, power, audio devices)
  2. python3 -m uranus plan         (see the timeline)
  3. python3 -m uranus map --demo --open
  4. ./linux/uranus-window.sh       (point-and-click window)
Optional services:  sudo ./linux/install-services.sh
Log out and back in once so the dialout/audio groups take effect.
MSG
