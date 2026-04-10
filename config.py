"""
config.py — Central configuration for IDX Signal Bot v2.0
Intelligence Engine with Gemini AI, multi-source data, anomaly detection.
"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ══════════════════════════════════════════════════════════════════
# GEMINI AI
# ══════════════════════════════════════════════════════════════════
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
MAX_GEMINI_CALLS_PER_SCAN = 10   # Stay within 15 RPM free tier
GEMINI_TIMEOUT = 30               # seconds

# ══════════════════════════════════════════════════════════════════
# DATABASE — Railway Volume aware
# ══════════════════════════════════════════════════════════════════
def _resolve_data_dir() -> str:
    """Detect best data directory: Railway Volume → local fallback."""
    env_dir = os.environ.get("DATA_DIR")
    if env_dir:
        Path(env_dir).mkdir(parents=True, exist_ok=True)
        return env_dir
    if os.path.isdir("/data"):
        p = "/data/idx_bot"
        Path(p).mkdir(parents=True, exist_ok=True)
        return p
    local = os.path.join(os.path.dirname(__file__), "local_data")
    Path(local).mkdir(parents=True, exist_ok=True)
    return local

DATA_DIR = _resolve_data_dir()
DB_PATH = os.path.join(DATA_DIR, "idx_bot.db")
LOG_PATH = os.path.join(DATA_DIR, "bot.log")

# ══════════════════════════════════════════════════════════════════
# IDX API
# ══════════════════════════════════════════════════════════════════
IDX_BASE_URL = "https://www.idx.co.id"
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

# ══════════════════════════════════════════════════════════════════
# IHSG
# ══════════════════════════════════════════════════════════════════
IHSG_TICKER = "^JKSE"
IHSG_GOOGLE_URL = "https://www.google.com/finance/quote/COMPOSITE:IDX"
IHSG_YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EJKSE"
IHSG_INVESTING_URL = "https://id.investing.com/indices/idx-composite"

# ══════════════════════════════════════════════════════════════════
# NEWS SOURCES
# ══════════════════════════════════════════════════════════════════
NEWS_SOURCES = {
    "cnbc": {
        "name": "CNBC Indonesia",
        "search_url": "https://www.cnbcindonesia.com/search?query={query}&kanal=market",
        "base_url": "https://www.cnbcindonesia.com",
    },
    "kontan": {
        "name": "Kontan",
        "search_url": "https://www.kontan.co.id/search/?search={query}",
        "base_url": "https://www.kontan.co.id",
    },
    "bisnis": {
        "name": "Bisnis.com",
        "search_url": "https://www.bisnis.com/index?q={query}&per_page=10",
        "base_url": "https://www.bisnis.com",
    },
}

NEWS_SEARCH_QUERIES = [
    "akuisisi saham",
    "backdoor listing",
    "reverse takeover",
    "rights issue",
    "aksi korporasi",
    "perubahan pengendali",
]

# ══════════════════════════════════════════════════════════════════
# TIMEZONE & SCHEDULE
# ══════════════════════════════════════════════════════════════════
TIMEZONE = "Asia/Jakarta"

# Daily IHSG summary
DAILY_SUMMARY_HOUR = 16
DAILY_SUMMARY_MINUTE = 30

# Daily digest
DAILY_DIGEST_HOUR = 16
DAILY_DIGEST_MINUTE = 35

# Market open notification
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 0

# Scan interval
SCAN_INTERVAL_MINUTES = 30
MARKET_CLOSE_HOUR = 16
MARKET_CLOSE_MINUTE = 30

# Price history update
PRICE_UPDATE_HOUR = 17
PRICE_UPDATE_MINUTE = 0

# ══════════════════════════════════════════════════════════════════
# WATCHLIST — Sectors & Tickers
# ══════════════════════════════════════════════════════════════════
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
    # Teknologi
    "teknologi", "technology", "digital", "fintech", "data center",
]

WATCHLIST_TICKERS = [
    # Energy & Mining
    "BUMI", "ADRO", "MDKA", "ANTM", "INCO", "PTBA", "MEDC", "ESSA",
    # Tech & Digital
    "GOTO", "BUKA", "EMTK", "DCII",
    # Property
    "BSDE", "CTRA", "SMRA",
    # Conglomerate
    "BRPT", "DSSA", "PGAS",
    # Banks (for M&A activity)
    "BBCA", "BBRI", "BMRI", "BBNI",
]

# ══════════════════════════════════════════════════════════════════
# ANOMALY DETECTION
# ══════════════════════════════════════════════════════════════════
VOLUME_SPIKE_RATIO = 3.0      # Volume > 3x average → anomaly
PRICE_SPIKE_PCT = 5.0          # Price change > 5% → anomaly
ANOMALY_LOOKBACK_DAYS = 20     # Compare against 20-day average
TOP_ACTIVE_STOCKS = 50         # Scan top 50 most active stocks

# ══════════════════════════════════════════════════════════════════
# SIGNAL SCORING
# ══════════════════════════════════════════════════════════════════
# Keyword detection weights (improved from v1)
SIGNAL_KEYWORDS = {
    "backdoor_listing": {
        "label": "🚪 Backdoor Listing",
        "weight": 5,
        "keywords": [
            "backdoor listing", "reverse takeover", "reverse merger",
            "rto", "injeksi aset", "injection of assets",
            "penerbitan saham baru kepada pihak tertentu",
            "perubahan kegiatan usaha utama", "change of core business",
            "change of main business", "transaksi material",
        ],
    },
    "akuisisi": {
        "label": "🏢 Akuisisi",
        "weight": 4,
        "keywords": [
            "akuisisi", "acquisition", "pengambilalihan", "takeover",
            "pembelian saham", "share purchase", "pembelian kepemilikan",
            "beli saham", "pengambilalihan saham",
        ],
    },
    "perubahan_kendali": {
        "label": "🔄 Perubahan Kendali",
        "weight": 4,
        "keywords": [
            "perubahan pengendalian", "change of control",
            "pengendali baru", "new controlling shareholder",
            "pemegang saham pengendali baru", "pergantian pengendali",
            "perubahan pemegang saham utama",
        ],
    },
    "merger": {
        "label": "🔀 Merger",
        "weight": 4,
        "keywords": [
            "merger", "penggabungan usaha", "peleburan usaha",
            "konsolidasi", "consolidation", "amalgamation",
        ],
    },
    "penambahan_modal": {
        "label": "📈 Penambahan Modal",
        "weight": 3,
        "keywords": [
            "hmetd", "rights issue", "private placement",
            "penambahan modal tanpa hak memesan", "pmthmetd",
            "penambahan modal dengan hak memesan", "pmhmetd",
            "penerbitan saham baru", "capital increase",
            "obligasi konversi", "convertible bond",
        ],
    },
    "transaksi_material": {
        "label": "💰 Transaksi Material",
        "weight": 3,
        "keywords": [
            "transaksi material", "material transaction",
            "transaksi benturan kepentingan", "conflict of interest",
            "transaksi afiliasi", "affiliated transaction",
        ],
    },
    "divestasi": {
        "label": "📤 Divestasi",
        "weight": 2,
        "keywords": [
            "divestasi", "divestiture", "penjualan aset", "asset sale",
            "pelepasan saham", "disposal of shares",
        ],
    },
}

# Alert tier thresholds (out of 40 max score)
ALERT_CRITICAL_THRESHOLD = 25   # 🔴 Immediate alert
ALERT_HIGH_THRESHOLD = 15       # 🟡 Alert within scan cycle
ALERT_INFO_THRESHOLD = 8        # 🟢 Included in daily digest

# ══════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
    ],
)

# Add file handler if path available
try:
    _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(_fh)
except Exception:
    pass

logger = logging.getLogger("idx_bot")
