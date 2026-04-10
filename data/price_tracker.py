"""
data/price_tracker.py — Stock price & volume fetcher for anomaly detection
Uses Google Finance (primary) and Yahoo Finance direct API (fallback).
"""
import re
import json
import logging
from typing import Dict, List, Optional
from datetime import datetime

from curl_cffi import requests

from config import WATCHLIST_TICKERS, TOP_ACTIVE_STOCKS

logger = logging.getLogger("idx_bot.price_tracker")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_stock_data(tickers: List[str] = None) -> Dict[str, dict]:
    """
    Fetch current price + volume for given tickers.
    Returns dict: {ticker: {close, open, high, low, volume, change_pct, ...}}
    """
    if tickers is None:
        tickers = WATCHLIST_TICKERS

    results = {}

    for ticker in tickers:
        try:
            data = _fetch_yahoo_ticker(ticker)
            if data:
                results[ticker] = data
                continue
        except Exception as e:
            logger.debug("Yahoo fetch failed for %s: %s", ticker, e)

        try:
            data = _fetch_google_ticker(ticker)
            if data:
                results[ticker] = data
        except Exception as e:
            logger.debug("Google fetch failed for %s: %s", ticker, e)

    logger.info("Fetched price data for %d/%d tickers", len(results), len(tickers))
    return results


def _fetch_yahoo_ticker(ticker: str) -> Optional[dict]:
    """Fetch single ticker from Yahoo Finance direct API."""
    # IDX tickers need .JK suffix for Yahoo
    yahoo_ticker = f"{ticker}.JK"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}"
    params = {
        "range": "1d",
        "interval": "1d",
        "includePrePost": "false",
    }

    resp = requests.get(
        url,
        params=params,
        headers={**HEADERS, "Accept": "application/json"},
        impersonate="chrome120",
        timeout=10,
    )

    if resp.status_code != 200:
        return None

    data = resp.json()
    chart = data.get("chart", {}).get("result", [])
    if not chart:
        return None

    result = chart[0]
    meta = result.get("meta", {})
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote", [{}])[0]

    close = meta.get("regularMarketPrice", 0)
    prev_close = meta.get("chartPreviousClose", meta.get("previousClose", 0))

    closes = [c for c in quotes.get("close", []) if c is not None]
    opens = [o for o in quotes.get("open", []) if o is not None]
    highs = [h for h in quotes.get("high", []) if h is not None]
    lows = [l for l in quotes.get("low", []) if l is not None]
    volumes = [v for v in quotes.get("volume", []) if v is not None]

    if not close and closes:
        close = closes[-1]

    change_pct = 0
    if prev_close and prev_close > 0:
        change_pct = ((close - prev_close) / prev_close) * 100

    return {
        "ticker": ticker,
        "close": close,
        "open": opens[-1] if opens else close,
        "high": highs[-1] if highs else close,
        "low": lows[-1] if lows else close,
        "volume": volumes[-1] if volumes else 0,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source": "Yahoo Finance",
    }


def _fetch_google_ticker(ticker: str) -> Optional[dict]:
    """Fetch single ticker from Google Finance."""
    url = f"https://www.google.com/finance/quote/{ticker}:IDX"

    resp = requests.get(
        url,
        headers=HEADERS,
        impersonate="chrome120",
        timeout=10,
    )

    if resp.status_code != 200:
        return None

    html = resp.text

    # Extract price
    price_match = re.search(r'data-last-price="([0-9.]+)"', html)
    if not price_match:
        return None

    close = float(price_match.group(1))

    # Extract change %
    pct_match = re.search(r'data-change-percent="([+-]?[0-9.]+)"', html)
    change_pct = float(pct_match.group(1)) if pct_match else 0

    # Extract previous close
    prev_match = re.search(r'data-previous-close="([0-9.]+)"', html)
    prev_close = float(prev_match.group(1)) if prev_match else close

    # Volume
    vol_match = re.search(
        r'(?:Volume|Vol)\s*</div>\s*<div[^>]*>\s*<div[^>]*>([0-9,.]+[KMB]?)',
        html, re.IGNORECASE | re.DOTALL,
    )
    volume = 0
    if vol_match:
        raw = vol_match.group(1).replace(",", "")
        if raw.endswith("B"):
            volume = int(float(raw[:-1]) * 1_000_000_000)
        elif raw.endswith("M"):
            volume = int(float(raw[:-1]) * 1_000_000)
        elif raw.endswith("K"):
            volume = int(float(raw[:-1]) * 1_000)
        else:
            try:
                volume = int(float(raw))
            except ValueError:
                pass

    return {
        "ticker": ticker,
        "close": close,
        "open": close,  # Google Finance doesn't always show open
        "high": close,
        "low": close,
        "volume": volume,
        "prev_close": prev_close,
        "change_pct": change_pct,
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "source": "Google Finance",
    }


def fetch_batch_yahoo(tickers: List[str]) -> Dict[str, dict]:
    """
    Batch fetch multiple tickers from Yahoo Finance.
    More efficient than individual calls.
    """
    if not tickers:
        return {}

    # Yahoo supports batch quotes
    symbols = ",".join(f"{t}.JK" for t in tickers[:50])  # Max 50 at once
    url = f"https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": symbols}

    try:
        resp = requests.get(
            url,
            params=params,
            headers={**HEADERS, "Accept": "application/json"},
            impersonate="chrome120",
            timeout=20,
        )

        if resp.status_code != 200:
            logger.warning("Yahoo batch quote returned HTTP %s", resp.status_code)
            return {}

        data = resp.json()
        quotes = data.get("quoteResponse", {}).get("result", [])

        results = {}
        for q in quotes:
            symbol = q.get("symbol", "").replace(".JK", "")
            if not symbol:
                continue

            prev = q.get("regularMarketPreviousClose", 0)
            close = q.get("regularMarketPrice", 0)
            change_pct = q.get("regularMarketChangePercent", 0)

            results[symbol] = {
                "ticker": symbol,
                "close": close,
                "open": q.get("regularMarketOpen", close),
                "high": q.get("regularMarketDayHigh", close),
                "low": q.get("regularMarketDayLow", close),
                "volume": q.get("regularMarketVolume", 0),
                "prev_close": prev,
                "change_pct": change_pct,
                "avg_volume_10d": q.get("averageDailyVolume10Day", 0),
                "avg_volume_3m": q.get("averageDailyVolume3Month", 0),
                "market_cap": q.get("marketCap", 0),
                "date": datetime.utcnow().strftime("%Y-%m-%d"),
                "source": "Yahoo Finance Batch",
            }

        logger.info("Yahoo batch: fetched %d/%d tickers", len(results), len(tickers))
        return results

    except Exception as e:
        logger.warning("Yahoo batch fetch failed: %s", e)
        return {}


def update_price_history(tickers: List[str], db) -> Dict[str, dict]:
    """
    Fetch and store daily OHLCV, compute 20-day average volume.
    Returns the current data dict.
    """
    # Try batch fetch first (more efficient)
    results = fetch_batch_yahoo(tickers)

    # Fallback to individual fetch for missing tickers
    missing = [t for t in tickers if t not in results]
    if missing:
        individual = fetch_stock_data(missing)
        results.update(individual)

    # Save to DB and compute avg volume
    for ticker, data in results.items():
        # Get existing 20-day avg from DB
        avg_vol = db.get_avg_volume(ticker, days=20)
        data["avg_volume_20d"] = avg_vol or data.get("avg_volume_10d", 0)

        db.save_price(ticker, data)

    return results
