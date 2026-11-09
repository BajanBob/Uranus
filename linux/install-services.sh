#!/usr/bin/env bash
# Installs systemd services: uranus-beacon (transmit schedule) and uranus-listen (decode + report).
# They are installed DISABLED. Enable one with:  sudo systemctl enable --now uranus-listen
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="${SUDO_USER:-$USER}"
PY="python3"; [ -x "$DIR/.venv/bin/python" ] && PY="$DIR/.venv/bin/python"
for svc in beacon:run listen:listen; do
  name=${svc%%:*}; cmd=${svc##*:}
  cat > /etc/systemd/system/uranus-$name.service <<UNIT
[Unit]
Description=Uranus $name
After=network-online.target time-sync.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$PY -m uranus $cmd
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT
done
systemctl daemon-reload
echo "Installed uranus-beacon and uranus-listen (disabled). Run only one transmitter per rig."
