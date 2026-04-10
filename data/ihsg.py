"""
data/ihsg.py — Multi-source IHSG fetcher with 3-level fallback
Never returns "data tidak tersedia" — tries Google Finance, Yahoo direct, then Investing.com.
"""
import re
import json
import logging
from datetime import datetime
from typing import Optional

from curl_cffi import requests
import pytz

from config import (
    IHSG_GOOGLE_URL, IHSG_YAHOO_URL, IHSG_INVESTING_URL,
    IDX_HEADERS, TIMEZONE,
)

logger = logging.getLogger("idx_bot.ihsg")
WIB = pytz.timezone(TIMEZONE)

# Browser headers for scraping
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}


def fetch_ihsg() -> dict:
    """
    Fetch IHSG data with 3-source fallback.
    Tries: Google Finance → Yahoo direct API → Investing.com
    Returns standardized dict, never None.
    """
    sources = [
        ("Google Finance", _fetch_google_finance),
        ("Yahoo Finance", _fetch_yahoo_direct),
        ("Investing.com", _fetch_investing_com),
    ]

    for name, fetch_fn in sources:
        try:
            data = fetch_fn()
            if data and not data.get("error"):
                data["source"] = name
                data["timestamp"] = datetime.now(WIB).strftime("%d %b %Y %H:%M WIB")
                logger.info("IHSG data fetched from %s: %.2f", name, data.get("close", 0))
                return data
        except Exception as e:
            logger.warning("IHSG source %s failed: %s", name, e)

    logger.error("All IHSG sources failed!")
    return {
        "error": "Semua sumber data IHSG gagal. Coba lagi nanti.",
        "timestamp": datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
    }


def _fetch_google_finance() -> Optional[dict]:
    """Scrape IHSG from Google Finance — most reliable, no blocking."""
    resp = requests.get(
        IHSG_GOOGLE_URL,
        headers=BROWSER_HEADERS,
        impersonate="chrome120",
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    # Extract price from Google Finance HTML
    # Pattern: data-last-price="6543.21"
    price_match = re.search(r'data-last-price="([0-9.]+)"', html)
    if not price_match:
        # Alternative pattern
        price_match = re.search(r'class="YMlKec fxKbKc"[^>]*>([0-9,.]+)', html)
        if not price_match:
            return None

    close = float(price_match.group(1).replace(",", ""))

    # Extract change
    change_match = re.search(r'data-currency-code="IDR"[^>]*>.*?([+-]?[0-9,.]+)\s*\(([+-]?[0-9,.]+)%\)', html, re.DOTALL)
    change_abs = 0.0
    change_pct = 0.0
    if change_match:
        change_abs = float(change_match.group(1).replace(",", ""))
        change_pct = float(change_match.group(2).replace(",", ""))
    else:
        # Try alternative change pattern
        chg_match = re.search(r'data-last-price="[^"]*"[^>]*>.*?<span[^>]*>([+-]?[0-9,.]+)\s', html, re.DOTALL)
        pct_match = re.search(r'\(([+-]?[0-9,.]+)%\)', html)
        if chg_match:
            change_abs = float(chg_match.group(1).replace(",", ""))
        if pct_match:
            change_pct = float(pct_match.group(1).replace(",", ""))

    # Extract open/high/low from the details section
    open_ = _extract_gf_value(html, "Open|Buka")
    high = _extract_gf_value(html, "High|Tertinggi")
    low = _extract_gf_value(html, "Low|Terendah")
    volume = _extract_gf_volume(html)

    # 52-week
    high_52w = _extract_gf_value(html, "52-wk high|52 mgg tertinggi")
    low_52w = _extract_gf_value(html, "52-wk low|52 mgg terendah")

    return {
        "close": close,
        "open": open_ or close,
        "high": high or close,
        "low": low or close,
        "volume": volume or 0,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "week_change_pct": 0,  # Google Finance doesn't provide this easily
        "error": None,
    }


def _extract_gf_value(html: str, label_pattern: str) -> Optional[float]:
    """Extract a numeric value from Google Finance HTML by label."""
    pattern = rf'(?:{label_pattern})\s*</div>\s*<div[^>]*>\s*<div[^>]*>([0-9,.]+)'
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _extract_gf_volume(html: str) -> Optional[int]:
    """Extract volume from Google Finance HTML."""
    pattern = r'(?:Volume|Vol)\s*</div>\s*<div[^>]*>\s*<div[^>]*>([0-9,.]+[KMB]?)'
    match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
    if match:
        raw = match.group(1).replace(",", "")
        try:
            if raw.endswith("B"):
                return int(float(raw[:-1]) * 1_000_000_000)
            elif raw.endswith("M"):
                return int(float(raw[:-1]) * 1_000_000)
            elif raw.endswith("K"):
                return int(float(raw[:-1]) * 1_000)
            return int(float(raw))
        except ValueError:
            pass
    return None


def _fetch_yahoo_direct() -> Optional[dict]:
    """Fetch IHSG from Yahoo Finance direct API (not yfinance library)."""
    params = {
        "range": "5d",
        "interval": "1d",
        "includePrePost": "false",
    }

    resp = requests.get(
        IHSG_YAHOO_URL,
        params=params,
        headers={
            **BROWSER_HEADERS,
            "Accept": "application/json",
        },
        impersonate="chrome120",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    chart = data.get("chart", {}).get("result", [])
    if not chart:
        return None

    result = chart[0]
    meta = result.get("meta", {})
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote", [{}])[0]
    timestamps = result.get("timestamp", [])

    if not timestamps or not quotes.get("close"):
        return None

    closes = [c for c in quotes["close"] if c is not None]
    opens = [o for o in quotes.get("open", []) if o is not None]
    highs = [h for h in quotes.get("high", []) if h is not None]
    lows = [l for l in quotes.get("low", []) if l is not None]
    volumes = [v for v in quotes.get("volume", []) if v is not None]

    if not closes:
        return None

    close = closes[-1]
    prev_close = closes[-2] if len(closes) >= 2 else close
    change_abs = close - prev_close
    change_pct = (change_abs / prev_close * 100) if prev_close else 0

    week_start = closes[0] if closes else close
    week_change_pct = ((close - week_start) / week_start * 100) if week_start else 0

    return {
        "close": close,
        "open": opens[-1] if opens else close,
        "high": highs[-1] if highs else close,
        "low": lows[-1] if lows else close,
        "volume": volumes[-1] if volumes else 0,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "high_52w": meta.get("fiftyTwoWeekHigh"),
        "low_52w": meta.get("fiftyTwoWeekLow"),
        "week_change_pct": week_change_pct,
        "error": None,
    }


def _fetch_investing_com() -> Optional[dict]:
    """Scrape IHSG from Investing.com Indonesia — last resort fallback."""
    resp = requests.get(
        IHSG_INVESTING_URL,
        headers={
            **BROWSER_HEADERS,
            "Accept-Language": "id-ID,id;q=0.9",
        },
        impersonate="chrome120",
        timeout=15,
    )
    resp.raise_for_status()
    html = resp.text

    # Extract last price
    price_match = re.search(
        r'data-test="instrument-price-last"[^>]*>([0-9.,]+)', html
    )
    if not price_match:
        price_match = re.search(r'"last_numeric"\s*:\s*([0-9.]+)', html)
        if not price_match:
            return None

    close = float(price_match.group(1).replace(".", "").replace(",", "."))

    # Extract change
    chg_match = re.search(
        r'data-test="instrument-price-change"[^>]*>([+-]?[0-9.,]+)', html
    )
    pct_match = re.search(
        r'data-test="instrument-price-change-percent"[^>]*>\(?([+-]?[0-9.,]+)%', html
    )

    change_abs = 0.0
    change_pct = 0.0
    if chg_match:
        change_abs = float(chg_match.group(1).replace(".", "").replace(",", "."))
    if pct_match:
        change_pct = float(pct_match.group(1).replace(",", "."))

    # Extract OHLCV from page
    open_ = _extract_inv_value(html, "Buka|Open")
    high = _extract_inv_value(html, "Tertinggi|High")
    low = _extract_inv_value(html, "Terendah|Low")
    volume = _extract_inv_volume(html)

    return {
        "close": close,
        "open": open_ or close,
        "high": high or close,
        "low": low or close,
        "volume": volume or 0,
        "change_abs": change_abs,
        "change_pct": change_pct,
        "high_52w": None,
        "low_52w": None,
        "week_change_pct": 0,
        "error": None,
    }


def _extract_inv_value(html: str, label_pattern: str) -> Optional[float]:
    """Extract a numeric value from Investing.com HTML."""
    pattern = rf'(?:{label_pattern})\s*</span>\s*<span[^>]*>([0-9.,]+)'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        try:
            raw = match.group(1).replace(".", "").replace(",", ".")
            return float(raw)
        except ValueError:
            pass
    return None


def _extract_inv_volume(html: str) -> Optional[int]:
    """Extract volume from Investing.com HTML."""
    pattern = r'(?:Volume|Vol)\s*</span>\s*<span[^>]*>([0-9.,]+)'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        try:
            raw = match.group(1).replace(".", "").replace(",", "")
            return int(float(raw))
        except ValueError:
            pass
    return None
