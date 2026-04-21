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
TIMEFRAMES          = ['15m', '1h', '4h']        # Scan pada M15, H1, H4
PRIMARY_TIMEFRAME   = '1h'                        # Timeframe utama untuk entry
CANDLE_LOOKBACK     = 150                         # Jumlah candle yang diambil

# Stochastic Oscillator (5, 3, 3)
STOCH_K        = 5
STOCH_SMOOTH_K = 3
STOCH_D        = 3

# Pivot detection
PIVOT_LEFT     = 5     # Candle ke kiri untuk mendeteksi pivot
PIVOT_RIGHT    = 3     # Candle ke kanan (lebih kecil = deteksi lebih cepat)

# Higher Low
MIN_HL_TOUCHES = 2     # Minimal 2 higher low touches pada trendline
MAX_HL_TOUCHES = 3     # Maksimal 3 touches (hindari trend yang sudah jenuh/terlalu lama)

# Accumulation Zone
ACCUM_MIN_CANDLES   = 8      # Minimal 8 candle dalam zona akumulasi
ACCUM_MAX_RANGE_PCT = 6.0    # Range zona max 6% (kotak ungu)

# Breakout Confirmation
VOLUME_BREAKOUT_MULT = 1.5   # Volume harus ≥ 1.5x rata-rata 20 candle
BREAKOUT_CLOSE_ABOVE = True  # Candle harus CLOSE di atas resistance

# Stochastic Filter
STOCH_ENTRY_MIN     = 20     # Sweet spot mulai dari 20
STOCH_ENTRY_MAX     = 42     # Batas maksimal entry di 42 (sweet spot 20-42)

# ══════════════════════════════════════════════════════════════
# ALPHA DETECTION (KALIMASADA-style)
# ══════════════════════════════════════════════════════════════
ALPHA_THRESHOLD_PCT = 2.0    # Koin harus outperform BTC minimal 2%
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
MIN_LEVERAGE       = 3       # Leverage minimum
MAX_LEVERAGE       = 10      # Leverage maksimum
DEFAULT_RR_RATIO   = 2.0     # Risk:Reward = 1:2 (TP = 2x jarak SL)
TRAILING_BREAKEVEN = True    # Geser SL ke breakeven setelah profit >= 1R

# SL Buffer
SL_BUFFER_PCT      = 0.3     # Tambahan 0.3% di bawah support zone untuk SL

# ══════════════════════════════════════════════════════════════
# MARKET FILTERS
# ══════════════════════════════════════════════════════════════
MIN_VOLUME_24H     = 2_000_000  # Volume 24h minimal $2M (lebih liquid)
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
