#!/bin/bash
# ══════════════════════════════════════════════════════════════
# BYBIT ALPHA BOT — Local Launcher (macOS)
# Runs bot in screen with caffeinate to prevent sleep
# ══════════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_NAME="bybit-bot"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_FILE="$SCRIPT_DIR/.env"
DATA_DIR="$SCRIPT_DIR/data"
LOCK_FILE="$SCRIPT_DIR/.bot.lock"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════╗"
echo "║     BYBIT ALPHA BOT — Local Launcher        ║"
echo "╚══════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Kill ALL existing instances first ─────────────────────
# This prevents the "7 duplicate bots" problem
pkill -9 -f "\.bot_runner\.sh" 2>/dev/null || true
pkill -9 -f "caffeinate.*main\.py" 2>/dev/null || true
sleep 1

# Kill any orphan python main.py processes
pkill -9 -f "python.*main\.py" 2>/dev/null || true
sleep 0.5

# Clean up dead screen sessions
screen -wipe 2>/dev/null || true

# Kill active screen session if exists
if screen -list 2>/dev/null | grep -q "$SESSION_NAME"; then
    screen -S "$SESSION_NAME" -X quit 2>/dev/null || true
    sleep 1
fi

# Remove stale lockfile
rm -f "$LOCK_FILE"

# ── Check .env exists ────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}✗ File .env tidak ditemukan!${NC}"
    exit 1
fi

# ── Check required env vars ──────────────────────────────
source "$ENV_FILE"
if [ "$BYBIT_API_KEY" = "PASTE_YOUR_BYBIT_API_KEY_HERE" ] || [ -z "$BYBIT_API_KEY" ]; then
    echo -e "${RED}✗ BYBIT_API_KEY belum diisi di .env!${NC}"
    exit 1
fi
if [ "$TELEGRAM_CHAT_ID" = "PASTE_YOUR_TELEGRAM_CHAT_ID_HERE" ] || [ -z "$TELEGRAM_CHAT_ID" ]; then
    echo -e "${RED}✗ TELEGRAM_CHAT_ID belum diisi di .env!${NC}"
    exit 1
fi

# ── Create data directory ────────────────────────────────
mkdir -p "$DATA_DIR"
echo -e "${GREEN}✓ Data directory: $DATA_DIR${NC}"

# ── Setup Python virtual environment ─────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⏳ Membuat virtual environment...${NC}"
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓ Virtual environment dibuat${NC}"
fi

echo -e "${YELLOW}⏳ Menginstall dependencies...${NC}"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo -e "${GREEN}✓ Dependencies terinstall${NC}"

# ── Create wrapper script for screen ─────────────────────
WRAPPER="$SCRIPT_DIR/.bot_runner.sh"
cat > "$WRAPPER" << 'RUNNER_EOF'
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
RUNNER_EOF
chmod +x "$WRAPPER"

# ── Launch bot in screen ──────────────────────────────────
echo -e "${YELLOW}⏳ Memulai bot...${NC}"
screen -dmS "$SESSION_NAME" bash "$WRAPPER"

# Wait for screen to start
sleep 2

# Verify
if screen -list 2>/dev/null | grep -q "$SESSION_NAME"; then
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║  ✓ BOT BERHASIL DIJALANKAN!                 ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}Lihat log real-time:${NC}  screen -r $SESSION_NAME"
    echo -e "  ${CYAN}Detach (bot jalan):${NC}   Ctrl+A, lalu D"
    echo -e "  ${CYAN}Stop bot:${NC}             ./stop_bot.sh"
    echo -e "  ${CYAN}Dashboard:${NC}            http://localhost:${PORT:-8081}"
    echo ""
    echo -e "  ${YELLOW}Kamu bisa tutup lid MacBook sekarang.${NC}"
    echo -e "  ${YELLOW}Bot akan tetap berjalan selama charger tersambung.${NC}"
    echo ""
else
    echo -e "${RED}✗ Gagal memulai bot! Cek error di atas.${NC}"
    exit 1
fi
