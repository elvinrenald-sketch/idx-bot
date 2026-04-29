"""
Bybit Crypto Algo Bot — Configuration
All parameters in one place. No magic numbers anywhere else.
"""
import os

# ══════════════════════════════════════════════════════════════
# BYBIT API
# ══════════════════════════════════════════════════════════════
BYBIT_API_KEY    = os.environ.get('BYBIT_API_KEY', '')
BYBIT_API_SECRET = os.environ.get('BYBIT_API_SECRET', '')
BYBIT_TESTNET    = os.environ.get('BYBIT_TESTNET', 'false').lower() == 'true'

# ══════════════════════════════════════════════════════════════
# TELEGRAM (reuse dari Polymarket bot)
# ══════════════════════════════════════════════════════════════
TG_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TG_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ══════════════════════════════════════════════════════════════
# STRATEGY — Price Action Parameters
# ══════════════════════════════════════════════════════════════
TIMEFRAMES          = ['1h', '4h']                # Scan pada H1 dan H4 saja (tidak M15)
PRIMARY_TIMEFRAME   = '1h'                        # Timeframe utama untuk entry
CANDLE_LOOKBACK     = 150                         # Jumlah candle yang diambil


# Pivot detection
PIVOT_LEFT     = 5     # Candle ke kiri untuk mendeteksi pivot
PIVOT_RIGHT    = 3     # [Tuned] Turunkan ke 3 agar entry lebih cepat tanpa mengorbankan akurasi

# Higher Low
MIN_HL_TOUCHES    = 2   # Minimal 2 higher low touches pada trendline
MAX_HL_TOUCHES    = 4   # Maksimal 4 touches (lebih dari ini = stale pattern)
MIN_HL_CANDLE_GAP = 3   # [Tuned] Jarak minimal antar HL agar bisa menangkap tren agresif
MAX_HL_CANDLE_GAP = 40  # [NEW] Jarak MAKSIMAL antar HL berurutan (candle). >40 = HL terlalu jauh, bukan tren kohesif
MAX_HL_PRICE_JUMP_PCT = 15.0  # [FIX] Crypto altcoins swing 10-15% between lows normally
MIN_ASCENDING_RANGE_PCT = 1.0  # [NEW] Minimum jarak total HL pertama ke terakhir (%). <1% = bukan ascending, cuma noise
MAX_RESISTANCE_RETEST = 4  # Maksimal 4x retest resistance untuk boleh entry

# Accumulation Zone
ACCUM_MIN_CANDLES   = 6      # Minimal 6 candle dalam zona akumulasi
ACCUM_MAX_RANGE_PCT = 7.2    # Range zona max 7.2% (kotak ungu)

# Volume Confirmation
VOLUME_BREAKOUT_MULT = 1.5   # Volume harus ≥ 1.5x rata-rata 20 candle
BREAKOUT_CLOSE_ABOVE = True  # Candle harus CLOSE di atas resistance


# Trendline / Pullback Entry
TRENDLINE_TOLERANCE_PCT = 1.2  # [FIX] Harga harus dalam 1.2% dari trendline HL (ketat)
DEMAND_TOLERANCE_PCT    = 1.5  # Harga harus dalam 1.5% dari demand zone

# Pucuk Protector (H4/D1) — [FIX v3] Lebih ketat
PUCUK_SMA_DISTANCE_PCT  = 4.0  # [FIX] Turunkan dari 8% ke 4% — ZEC pump 7% TIDAK tertangkap di 8%

# Pump Candle Detector (BARU)
PUMP_CANDLE_BODY_MULT   = 2.5  # Jika body candle > 2.5x ATR-14 = pump candle, TOLAK
PUMP_RISE_PCT           = 5.0  # Jika harga naik > 5% dalam 5 candle = momentum exhaustion, TOLAK
PUMP_LOOKBACK           = 5    # Cek 5 candle terakhir untuk deteksi pump

# Candle Structure Validator
MIN_H4_CANDLES_FOR_STRUCTURE = 4   # Pola HL/HH di M15/H1 wajib >= 4 candle di H4
MIN_D1_CANDLES_FOR_STRUCTURE = 2   # Pola HL/HH di H1 wajib >= 2 candle di D1

# ══════════════════════════════════════════════════════════════
# ALPHA DETECTION (KALIMASADA-style)
# ══════════════════════════════════════════════════════════════
ALPHA_THRESHOLD_PCT = 3.0    # Koin harus outperform BTC minimal 3% (True Alpha only)
ALPHA_LOOKBACK_H    = 4      # Bandingkan performa 4 jam terakhir
ALPHA_CANDIDATE_LIMIT = 50   # Jumlah koin yang di-investigasi lewat deep scan

# Volume Alpha & Decoupling
VOLUME_ALPHA_THRESHOLD = 1.5   # Volume koin must be 1.5x avg
BTC_VOLUME_MAX_RATIO   = 1.0   # BTC volume must be stagnant/low
DECOUPLING_THRESHOLD   = 0.3   # Max correlation with BTC (Pearson)
DECOUPLING_WINDOW_H    = 24    # 24h correlation window

# New Listing Filtering
NEW_LISTING_DAYS       = 14    # M15 hanya discan untuk koin < 14 hari

# Multi-Timeframe Sync
TRIPLE_SCREEN_ENABLED  = True  # Align M15 with H1 & H4 trends

# ══════════════════════════════════════════════════════════════
# RISK MANAGEMENT
# ══════════════════════════════════════════════════════════════
RISK_PER_TRADE_PCT = 3.0     # Risiko 3% equity per trade
MAX_OPEN_POSITIONS = 3       # Maksimal 3 posisi terbuka
MIN_EQUITY_FOR_TRADE = 5.5   # [NEW] Minimum equity $5.5 USDT untuk boleh trade. Jika di bawah = SKIP scan
FAILED_SYMBOL_COOLDOWN = 10  # [NEW] Cooldown: skip simbol yang gagal selama 10 scan (~10 menit)
MIN_LEVERAGE       = 3       # Leverage minimum
MAX_LEVERAGE       = 10      # Leverage maksimum
DEFAULT_RR_RATIO   = 1.3     # Risk:Reward = 1:1.3 (TP realistis untuk M15 crypto)
PARTIAL_TP_RATIO   = 0.8     # Close 50% posisi di profit 0.8R
PARTIAL_TP_PCT     = 50      # Persentase size yang diclose saat partial TP
TRAILING_BREAKEVEN = True    # Geser SL otomatis

# SL Buffer
SL_BUFFER_PCT      = 0.3     # Tambahan 0.3% di bawah support zone untuk SL

# ATR Multiplier per Timeframe
# RR tetap 1:2 di semua TF, hanya ukuran absolut SL/TP yang menyesuaikan "napas" TF
ATR_SL_MULT = {
    '15m': 1.5,   # M15: napas pendek, SL tipis tapi wajar
    '1h':  2.0,   # H1:  napas lebih panjang, SL lebih lebar
    '4h':  2.5,   # H4:  swing trade, butuh ruang gerak lebih besar
    '1d':  3.0,   # D1:  position trade, SL sangat lebar
}
ATR_SL_MULT_DEFAULT = 1.5  # Fallback jika TF tidak dikenali

# ══════════════════════════════════════════════════════════════
# MARKET FILTERS
# ══════════════════════════════════════════════════════════════
MIN_VOLUME_24H     = 10_000_000   # Volume 24h minimal $10M (likuid, bukan micro cap)
MAX_VOLUME_24H     = 250_000_000  # Volume 24h max $250M (skip mega cap BTC/ETH/SOL)
MAX_SPREAD_PCT     = 0.15      # Spread max 0.15%
MIN_PRICE          = 0.0001    # Harga minimum (filter dust coins)
MIN_NOTIONAL_USDT  = 5.5       # Bybit minimum order $5 USDT (tambah buffer 10%)
BLACKLIST_SYMBOLS  = [         # Koin yang di-skip (stablecoins, delisted)
    'USDC/USDT:USDT', 'DAI/USDT:USDT', 'TUSD/USDT:USDT',
    'BUSD/USDT:USDT', 'FDUSD/USDT:USDT',
]

# ══════════════════════════════════════════════════════════════
# SCAN & TIMING
# ══════════════════════════════════════════════════════════════
SCAN_INTERVAL_SEC     = 60     # Scan setiap 1 menit (Real-time momentum)
POSITION_CHECK_SEC    = 60     # Cek posisi setiap 1 menit
MAX_ALPHA_COINS       = 30     # Max koin alpha yang di-deep scan
RATE_LIMIT_DELAY      = 0.15   # Delay antar API call (150ms) untuk hindari rate limit

# Market Cap Filter (CoinGecko)
MARKETCAP_TOP_N       = 100    # Hanya exclude top 100 (scan koin rank 101+)
MARKETCAP_CACHE_SEC   = 3600   # Cache CoinGecko data selama 1 jam

# ══════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════
DATA_DIR = os.environ.get('DATA_DIR', '/data/bybit-bot')
DB_PATH  = os.path.join(DATA_DIR, 'trades.db')
LOG_PATH = os.path.join(DATA_DIR, 'bot.log')

# ══════════════════════════════════════════════════════════════
# WEB DASHBOARD
# ══════════════════════════════════════════════════════════════
WEB_PORT = int(os.environ.get('PORT', 8080))
