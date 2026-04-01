#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="agape"
REMOTE_DIR="/opt/telegram-bot/pal-distributor-bot"
SERVICE_NAME="pal-distributor-bot"

echo "==> Syncing files to ${REMOTE_HOST}:${REMOTE_DIR}"
rsync -av --delete \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='data/' \
  --exclude='.env' \
  . "${REMOTE_HOST}:${REMOTE_DIR}/"

echo "==> Setting up venv and installing dependencies"
ssh "${REMOTE_HOST}" bash <<EOF
  set -euo pipefail
  cd "${REMOTE_DIR}"
  if [ ! -d venv ]; then
    python3 -m venv venv
  fi
  venv/bin/pip install --quiet --upgrade pip
  venv/bin/pip install --quiet -r requirements.txt
  mkdir -p data
EOF

echo "==> Installing systemd service"
ssh "${REMOTE_HOST}" bash <<EOF
  set -euo pipefail
  sudo cp "${REMOTE_DIR}/${SERVICE_NAME}.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now "${SERVICE_NAME}"
  sudo systemctl restart "${SERVICE_NAME}"
  echo "Service status:"
  sudo systemctl status "${SERVICE_NAME}" --no-pager
EOF

echo ""
echo "Done. To follow logs: ssh ${REMOTE_HOST} journalctl -u ${SERVICE_NAME} -f"
