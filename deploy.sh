#!/usr/bin/env bash
set -e

CONTAINER="lanterna-bot"
BOT_DIR="/opt/telegram-bot/pal-distributor-bot"
REPO="git@github.com:freddbomba/pal-distributor-bot.git"
SERVICE="pal-distributor-bot"

# --- Verify we can reach the container ---
if ! incus exec "$CONTAINER" -- true 2>/dev/null; then
    echo "ERROR: Cannot reach container '$CONTAINER' via incus. Run this script on agape."
    exit 1
fi

run() {
    incus exec "$CONTAINER" -- bash -c "$1"
}

echo "=== PAL Distributor Bot Deploy ==="

if ! run "test -d $BOT_DIR"; then
    # -------------------------------------------------------
    echo "--- First-time setup ---"

    echo "[1/5] Cloning repository..."
    run "GIT_SSH_COMMAND='ssh -i /root/.ssh/id_ed25519_github -o StrictHostKeyChecking=no' \
         git clone $REPO $BOT_DIR"

    echo "[2/5] Creating Python venv and installing requirements..."
    run "cd $BOT_DIR && python3 -m venv venv && venv/bin/pip install -q -r requirements.txt"

    echo "[3/5] Creating data directory..."
    run "mkdir -p $BOT_DIR/data"

    echo "[4/5] Installing systemd service..."
    run "cp $BOT_DIR/$SERVICE.service /etc/systemd/system/"
    run "systemctl daemon-reload && systemctl enable $SERVICE"

    echo "[5/5] Done."
    echo ""
    echo "IMPORTANT: Create the .env file before starting the service:"
    echo "  incus exec $CONTAINER -- nano $BOT_DIR/.env"
    echo ""
    echo "Then start with:  incus exec $CONTAINER -- systemctl start $SERVICE"
else
    # -------------------------------------------------------
    echo "--- Update ---"

    echo "[1/3] Pulling latest code..."
    run "cd $BOT_DIR && GIT_SSH_COMMAND='ssh -i /root/.ssh/id_ed25519_github -o StrictHostKeyChecking=no' \
         git pull origin main"

    echo "[2/3] Reinstalling requirements..."
    run "cd $BOT_DIR && venv/bin/pip install -q -r requirements.txt"

    echo "[3/3] Updating service file and restarting..."
    run "cp $BOT_DIR/$SERVICE.service /etc/systemd/system/"
    run "systemctl daemon-reload && systemctl restart $SERVICE"
fi

echo ""
echo "=== Service status ==="
incus exec "$CONTAINER" -- systemctl status "$SERVICE" --no-pager || true
