#!/bin/bash
# ══════════════════════════════════════════════════════════════
# BYBIT ALPHA BOT — Stop Script (Nuclear Clean)
# ══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SESSION_NAME="bybit-bot"
LOCK_FILE="$SCRIPT_DIR/.bot.lock"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}⏳ Stopping Bybit Alpha Bot...${NC}"

# Kill screen session
if screen -list 2>/dev/null | grep -q "$SESSION_NAME"; then
    screen -S "$SESSION_NAME" -X quit 2>/dev/null || true
    echo -e "${GREEN}✓ Screen session '$SESSION_NAME' stopped${NC}"
else
    echo -e "${YELLOW}⚠ Screen session '$SESSION_NAME' tidak ditemukan${NC}"
fi

# Kill ALL related processes (prevent orphans)
pkill -9 -f "\.bot_runner\.sh" 2>/dev/null || true
pkill -9 -f "caffeinate.*main\.py" 2>/dev/null || true
pkill -9 -f "python.*main\.py" 2>/dev/null || true

echo -e "${GREEN}✓ All bot processes killed${NC}"

# Clean up dead screen sessions
screen -wipe 2>/dev/null || true

# Remove lockfile
rm -f "$LOCK_FILE"

# Kill any process on port 8081
lsof -ti :8081 2>/dev/null | xargs kill -9 2>/dev/null || true

echo ""
echo -e "${GREEN}✓ Bot sudah berhenti sepenuhnya.${NC}"
echo -e "  Untuk start lagi: ${GREEN}./start_bot.sh${NC}"
echo ""
