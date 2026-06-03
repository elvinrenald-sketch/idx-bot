#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCK_FILE="$SCRIPT_DIR/.bot.lock"

# Load environment variables
set -a
source "$SCRIPT_DIR/.env"
set +a
export DATA_DIR="$SCRIPT_DIR/data"

echo '══════════════════════════════════════════════'
echo '  BYBIT ALPHA BOT — RUNNING LOCALLY'
echo '  Ctrl+A lalu D untuk detach (bot tetap jalan)'
echo '  ./stop_bot.sh untuk berhenti'
echo '══════════════════════════════════════════════'
echo ''

# Lockfile to prevent duplicate instances
if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p $PID > /dev/null 2>&1; then
        echo "❌ ERROR: Bot is already running (PID: $PID)!"
        echo "Please run ./stop_bot.sh first."
        sleep 5
        exit 1
    fi
fi
echo $$ > "$LOCK_FILE"

# Cleanup lockfile on exit
trap "rm -f $LOCK_FILE" EXIT

# Auto-restart loop with caffeinate
while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting bot..."
    caffeinate -s "$SCRIPT_DIR/.venv/bin/python" -u "$SCRIPT_DIR/main.py"
    EXIT_CODE=$?
    echo ""
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Bot exited with code $EXIT_CODE"
    echo "Restarting in 10 seconds... (Ctrl+C to stop)"
    sleep 10
done
