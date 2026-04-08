"""
config.py — Central configuration for IDX Signal Bot
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── IDX API ───────────────────────────────────────────────
IDX_BASE_URL = "https://www.idx.co.id"
IDX_ANNOUNCEMENT_URL = (
    f"{IDX_BASE_URL}/primary/ListedCompany/GetAnnouncement"
    "?indexFrom=0&pageSize=20&lang=id"
)
IDX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
    "Origin": "https://www.idx.co.id",
    "Connection": "keep-alive",
}

# ── IHSG ──────────────────────────────────────────────────
IHSG_TICKER = "^JKSE"

# ── Timezone ──────────────────────────────────────────────
TIMEZONE = "Asia/Jakarta"

# ── Schedule (WIB = UTC+7) ────────────────────────────────
# Daily IHSG summary: 16:30 WIB
DAILY_SUMMARY_HOUR = 16
DAILY_SUMMARY_MINUTE = 30

# Disclosure scan: every 30 minutes, market hours 09:00–16:30 Mon–Fri
SCAN_INTERVAL_MINUTES = 30
MARKET_OPEN_HOUR = 9
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 30

# ── Watchlist sectors ─────────────────────────────────────
WATCHLIST_KEYWORDS = [
    # Energy
    "energi", "energy", "listrik", "electricity", "pln", "gas", "lng",
    "petroleum", "minyak", "pertamina",
    # Property
    "properti", "property", "real estate", "realestate", "kawasan industri",
    "perumahan", "apartemen", "gedung",
    # Komoditas / Batu bara
    "komoditas", "commodity", "batu bara", "batubara", "coal", "tambang",
    "pertambangan", "mining", "nikel", "nickel", "tembaga", "copper",
    "emas", "gold", "bauksit", "bauxite", "timah", "tin",
]

# ── Signal detection thresholds ───────────────────────────
SIGNAL_HIGH_THRESHOLD = 3     # score >= 3 → 🔴 TINGGI
SIGNAL_MEDIUM_THRESHOLD = 1   # score >= 1 → 🟡 MENENGAH

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("idx_bot")
