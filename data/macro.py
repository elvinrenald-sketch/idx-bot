"""
data/macro.py — Global macro-economic data fetcher
Fetches: Global indices, commodities, forex (USD/IDR), bond yields, Fed decisions.
Bloomberg-terminal grade data coverage using free public sources.
"""
import re
import logging
from datetime import datetime
from typing import Dict, List, Optional

from curl_cffi import requests
import pytz

from config import TIMEZONE

logger = logging.getLogger("idx_bot.macro")
WIB = pytz.timezone(TIMEZONE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ══════════════════════════════════════════════════════════════════
# GLOBAL INDEX TICKERS (Yahoo Finance symbols)
# ══════════════════════════════════════════════════════════════════
GLOBAL_INDICES = {
    "^DJI": {"name": "Dow Jones (US)", "emoji": "🇺🇸"},
    "^GSPC": {"name": "S&P 500 (US)", "emoji": "🇺🇸"},
    "^IXIC": {"name": "NASDAQ (US)", "emoji": "🇺🇸"},
    "^N225": {"name": "Nikkei 225 (Japan)", "emoji": "🇯🇵"},
    "^HSI": {"name": "Hang Seng (HK)", "emoji": "🇭🇰"},
    "000001.SS": {"name": "Shanghai Comp (China)", "emoji": "🇨🇳"},
    "^STI": {"name": "Straits Times (SG)", "emoji": "🇸🇬"},
    "^KLSE": {"name": "KLCI (Malaysia)", "emoji": "🇲🇾"},
    "^SET.BK": {"name": "SET (Thailand)", "emoji": "🇹🇭"},
}

COMMODITY_TICKERS = {
    "GC=F": {"name": "Gold (XAU/USD)", "emoji": "🥇", "unit": "USD/oz"},
    "CL=F": {"name": "Crude Oil WTI", "emoji": "🛢️", "unit": "USD/bbl"},
    "BZ=F": {"name": "Brent Crude", "emoji": "🛢️", "unit": "USD/bbl"},
    "SI=F": {"name": "Silver", "emoji": "🥈", "unit": "USD/oz"},
    "HG=F": {"name": "Copper", "emoji": "🔶", "unit": "USD/lb"},
    "NG=F": {"name": "Natural Gas", "emoji": "🔥", "unit": "USD/MMBtu"},
}

FOREX_TICKERS = {
    "USDIDR=X": {"name": "USD/IDR", "emoji": "💱"},
    "DX-Y.NYB": {"name": "Dollar Index (DXY)", "emoji": "💵"},
    "EURUSD=X": {"name": "EUR/USD", "emoji": "🇪🇺"},
    "SGDIDR=X": {"name": "SGD/IDR", "emoji": "🇸🇬"},
}

BOND_TICKERS = {
    "^TNX": {"name": "US 10Y Treasury Yield", "emoji": "📊", "unit": "%"},
    "^TYX": {"name": "US 30Y Treasury Yield", "emoji": "📊", "unit": "%"},
    "^FVX": {"name": "US 5Y Treasury Yield", "emoji": "📊", "unit": "%"},
}


def fetch_macro_data() -> Dict:
    """
    Fetch comprehensive macro data: global indices, commodities, forex, bonds.
    Returns organized dict with all data.
    """
    result = {
        "timestamp": datetime.now(WIB).strftime("%d %b %Y %H:%M WIB"),
        "indices": {},
        "commodities": {},
        "forex": {},
        "bonds": {},
        "errors": [],
    }

    # Fetch all categories
    all_tickers = {}
    all_tickers.update(GLOBAL_INDICES)
    all_tickers.update(COMMODITY_TICKERS)
    all_tickers.update(FOREX_TICKERS)
    all_tickers.update(BOND_TICKERS)

    # Batch fetch via Yahoo
    symbols = list(all_tickers.keys())
    data = _batch_fetch_yahoo(symbols)

    # Categorize results
    for symbol, quote in data.items():
        meta = all_tickers.get(symbol, {})
        entry = {
            **quote,
            "name": meta.get("name", symbol),
            "emoji": meta.get("emoji", ""),
            "unit": meta.get("unit", ""),
        }

        if symbol in GLOBAL_INDICES:
            result["indices"][symbol] = entry
        elif symbol in COMMODITY_TICKERS:
            result["commodities"][symbol] = entry
        elif symbol in FOREX_TICKERS:
            result["forex"][symbol] = entry
        elif symbol in BOND_TICKERS:
            result["bonds"][symbol] = entry

    logger.info(
        "Macro data: %d indices, %d commodities, %d forex, %d bonds",
        len(result["indices"]),
        len(result["commodities"]),
        len(result["forex"]),
        len(result["bonds"]),
    )

    return result


def _batch_fetch_yahoo(symbols: List[str]) -> Dict[str, dict]:
    """Batch-fetch quotes from Yahoo Finance."""
    if not symbols:
        return {}

    results = {}

    # Yahoo supports batching up to ~50 symbols
    symbols_str = ",".join(symbols)
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    params = {"symbols": symbols_str}

    try:
        resp = requests.get(
            url,
            params=params,
            headers={**HEADERS, "Accept": "application/json"},
            impersonate="chrome120",
            timeout=15,
        )

        if resp.status_code != 200:
            logger.warning("Yahoo macro batch returned HTTP %s", resp.status_code)
            return _fallback_individual_fetch(symbols)

        data = resp.json()
        quotes = data.get("quoteResponse", {}).get("result", [])

        for q in quotes:
            symbol = q.get("symbol", "")
            if not symbol:
                continue

            price = q.get("regularMarketPrice", 0)
            prev_close = q.get("regularMarketPreviousClose", 0)
            change = q.get("regularMarketChange", 0)
            change_pct = q.get("regularMarketChangePercent", 0)

            results[symbol] = {
                "price": price,
                "prev_close": prev_close,
                "change": change,
                "change_pct": change_pct,
                "high": q.get("regularMarketDayHigh", price),
                "low": q.get("regularMarketDayLow", price),
                "volume": q.get("regularMarketVolume", 0),
                "market_state": q.get("marketState", ""),
            }

        logger.info("Yahoo macro batch: fetched %d/%d symbols", len(results), len(symbols))
        return results

    except Exception as e:
        logger.warning("Yahoo macro batch failed: %s", e)
        return _fallback_individual_fetch(symbols[:5])  # Only fetch critical ones


def _fallback_individual_fetch(symbols: List[str]) -> Dict[str, dict]:
    """Fallback: fetch symbols individually via Yahoo chart API."""
    results = {}
    for symbol in symbols[:8]:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
            resp = requests.get(
                url,
                params={"range": "1d", "interval": "1d"},
                headers={**HEADERS, "Accept": "application/json"},
                impersonate="chrome120",
                timeout=10,
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            chart = data.get("chart", {}).get("result", [])
            if not chart:
                continue

            meta = chart[0].get("meta", {})
            price = meta.get("regularMarketPrice", 0)
            prev = meta.get("chartPreviousClose", meta.get("previousClose", 0))
            change = price - prev if prev else 0
            change_pct = (change / prev * 100) if prev else 0

            results[symbol] = {
                "price": price,
                "prev_close": prev,
                "change": change,
                "change_pct": change_pct,
                "high": price,
                "low": price,
                "volume": 0,
                "market_state": "",
            }
        except Exception:
            continue

    return results


def fetch_bi_rate() -> Optional[Dict]:
    """Fetch latest BI Rate (Bank Indonesia interest rate) from public source."""
    try:
        resp = requests.get(
            "https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx",
            headers=HEADERS,
            impersonate="chrome120",
            timeout=10,
        )
        if resp.status_code != 200:
            return None

        html = resp.text
        rate_match = re.search(r'(\d+[.,]\d+)\s*%', html)
        if rate_match:
            rate = float(rate_match.group(1).replace(",", "."))
            return {"rate": rate, "source": "Bank Indonesia"}

    except Exception as e:
        logger.debug("BI Rate fetch failed: %s", e)

    return None


def format_macro_briefing(data: Dict) -> str:
    """Format macro data into a comprehensive Telegram briefing."""
    lines = [
        "🌍 <b>MACRO INTELLIGENCE BRIEFING</b>",
        f"🕐 <i>{data.get('timestamp', '')}</i>",
        "",
    ]

    # Global Indices
    indices = data.get("indices", {})
    if indices:
        lines.append("📊 <b>Global Indices</b>")
        for symbol, d in indices.items():
            pct = d.get("change_pct", 0)
            arrow = "▲" if pct >= 0 else "▼"
            sign = "+" if pct >= 0 else ""
            lines.append(
                f"  {d['emoji']} {d['name']}: "
                f"<b>{d['price']:,.2f}</b> {arrow} {sign}{pct:.2f}%"
            )
        lines.append("")

    # Commodities
    commodities = data.get("commodities", {})
    if commodities:
        lines.append("🏭 <b>Commodities</b>")
        for symbol, d in commodities.items():
            pct = d.get("change_pct", 0)
            arrow = "▲" if pct >= 0 else "▼"
            sign = "+" if pct >= 0 else ""
            unit = d.get("unit", "")
            lines.append(
                f"  {d['emoji']} {d['name']}: "
                f"<b>{d['price']:,.2f}</b> {unit} {arrow} {sign}{pct:.2f}%"
            )
        lines.append("")

    # Forex
    forex = data.get("forex", {})
    if forex:
        lines.append("💱 <b>Forex & Currency</b>")
        for symbol, d in forex.items():
            pct = d.get("change_pct", 0)
            arrow = "▲" if pct >= 0 else "▼"
            sign = "+" if pct >= 0 else ""
            price_fmt = f"{d['price']:,.2f}" if d['price'] < 1000 else f"{d['price']:,.0f}"
            lines.append(
                f"  {d['emoji']} {d['name']}: "
                f"<b>{price_fmt}</b> {arrow} {sign}{pct:.2f}%"
            )
        lines.append("")

    # Bonds
    bonds = data.get("bonds", {})
    if bonds:
        lines.append("🏦 <b>Bond Yields</b>")
        for symbol, d in bonds.items():
            pct = d.get("change_pct", 0)
            arrow = "▲" if pct >= 0 else "▼"
            sign = "+" if pct >= 0 else ""
            lines.append(
                f"  {d['emoji']} {d['name']}: "
                f"<b>{d['price']:.3f}%</b> {arrow} {sign}{pct:.2f}%"
            )
        lines.append("")

    # Market sentiment summary
    if indices:
        up = sum(1 for d in indices.values() if d.get("change_pct", 0) > 0)
        down = len(indices) - up
        if up > down:
            sentiment = "🟢 RISK-ON (Global bullish)"
        elif down > up:
            sentiment = "🔴 RISK-OFF (Global bearish)"
        else:
            sentiment = "🟡 MIXED (Wait & see)"
        lines.append(f"🧠 <b>Sentimen Global:</b> {sentiment}")

    return "\n".join(lines)
