"""
data/ihsg.py — Fetch IHSG (^JKSE) data via yfinance
"""
import logging
from datetime import datetime
import yfinance as yf
import pytz

from config import IHSG_TICKER, TIMEZONE

logger = logging.getLogger("idx_bot.ihsg")
WIB = pytz.timezone(TIMEZONE)


def fetch_ihsg() -> dict:
    """
    Ambil data IHSG terkini dari Yahoo Finance.
    Returns dict dengan semua field yang dibutuhkan formatter.
    """
    try:
        ticker = yf.Ticker(IHSG_TICKER)

        # Fast info (realtime-ish)
        info = ticker.fast_info

        # Historical: ambil 5 hari terakhir untuk trend
        hist = ticker.history(period="5d", interval="1d", auto_adjust=True)

        if hist.empty:
            return {"error": "Data IHSG tidak tersedia saat ini."}

        latest = hist.iloc[-1]
        prev   = hist.iloc[-2] if len(hist) >= 2 else None

        close   = float(latest["Close"])
        open_   = float(latest["Open"])
        high    = float(latest["High"])
        low     = float(latest["Low"])
        volume  = int(latest["Volume"])

        change_pct = 0.0
        change_abs = 0.0
        if prev is not None:
            prev_close = float(prev["Close"])
            change_abs = close - prev_close
            change_pct = (change_abs / prev_close) * 100

        # 52-week high/low dari fast_info jika tersedia
        try:
            high_52w = float(info.year_high)
            low_52w  = float(info.year_low)
        except Exception:
            high_52w = low_52w = None

        # Trend 5 hari
        week_start = float(hist.iloc[0]["Close"])
        week_change_pct = ((close - week_start) / week_start) * 100

        now_wib = datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")

        return {
            "close":           close,
            "open":            open_,
            "high":            high,
            "low":             low,
            "volume":          volume,
            "change_abs":      change_abs,
            "change_pct":      change_pct,
            "week_change_pct": week_change_pct,
            "high_52w":        high_52w,
            "low_52w":         low_52w,
            "timestamp":       now_wib,
            "error":           None,
        }

    except Exception as e:
        logger.error("Gagal fetch IHSG: %s", e)
        return {"error": f"Gagal mengambil data IHSG: {e}"}
