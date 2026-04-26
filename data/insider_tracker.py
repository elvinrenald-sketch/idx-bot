"""
data/insider_tracker.py — IDX insider transaction & ownership change tracker
Monitors: KSEI substantial shareholder changes, IDX insider trading disclosures,
           and large block trade notifications.
Designed to catch whales entering/exiting BEFORE the news breaks.
"""
import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from curl_cffi import requests
from bs4 import BeautifulSoup
import pytz

from config import IDX_HEADERS, TIMEZONE, WATCHLIST_TICKERS

logger = logging.getLogger("idx_bot.insider")
WIB = pytz.timezone(TIMEZONE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.idx.co.id/",
    "Origin": "https://www.idx.co.id",
}

# ══════════════════════════════════════════════════════════════════
# INSIDER TRANSACTION TYPES (Indonesian Market)
# ══════════════════════════════════════════════════════════════════
INSIDER_TYPES = {
    "substantial_shareholder": {
        "label": "🐋 Pemegang Saham Substansial",
        "weight": 5,
        "description": "Perubahan kepemilikan > 5%",
    },
    "insider_buy": {
        "label": "🟢 Insider Buy",
        "weight": 4,
        "description": "Pembelian saham oleh direksi/komisaris",
    },
    "insider_sell": {
        "label": "🔴 Insider Sell",
        "weight": 3,
        "description": "Penjualan saham oleh direksi/komisaris",
    },
    "block_trade": {
        "label": "📦 Block Trade",
        "weight": 4,
        "description": "Transaksi blok > Rp 10 miliar",
    },
    "tender_offer": {
        "label": "🎯 Tender Offer",
        "weight": 5,
        "description": "Penawaran tender oleh pihak tertentu",
    },
    "new_controller": {
        "label": "👑 Pengendali Baru",
        "weight": 5,
        "description": "Perubahan pemegang saham pengendali",
    },
}


def scan_insider_activity() -> List[Dict]:
    """
    Comprehensive insider activity scan.
    Sources:
    1. IDX disclosure API — filtered for insider/ownership keywords
    2. KSEI ownership change page
    3. IDX company actions
    """
    all_activities = []

    # Source 1: IDX Disclosure API — filter for insider-related disclosures
    try:
        insider_disclosures = _fetch_insider_disclosures()
        all_activities.extend(insider_disclosures)
    except Exception as e:
        logger.warning("Insider disclosure scan failed: %s", e)

    # Source 2: IDX Company Actions API
    try:
        actions = _fetch_company_actions()
        all_activities.extend(actions)
    except Exception as e:
        logger.warning("Company actions scan failed: %s", e)

    # Source 3: IDX Substantial Shareholder Changes
    try:
        shareholders = _fetch_substantial_changes()
        all_activities.extend(shareholders)
    except Exception as e:
        logger.warning("Substantial shareholder scan failed: %s", e)

    # Sort by weight/urgency
    all_activities.sort(key=lambda x: x.get("weight", 0), reverse=True)

    logger.info("Insider scan: %d activities detected", len(all_activities))
    return all_activities


def _fetch_insider_disclosures() -> List[Dict]:
    """Fetch IDX disclosures and filter for insider/ownership keywords."""
    endpoints = [
        "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        "?indexFrom=0&pageSize=50&lang=id",
        "https://cors.eu.org/https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        "?indexFrom=0&pageSize=50&lang=id",
    ]

    insider_keywords = [
        "pemegang saham", "shareholder", "kepemilikan", "ownership",
        "pengendali", "controller", "controlling",
        "akuisisi", "acquisition", "pengambilalihan", "takeover",
        "pembelian saham", "share purchase", "beli saham",
        "direksi", "komisaris", "director", "commissioner",
        "transaksi saham", "share transaction",
        "transaksi orang dalam", "insider transaction",
        "tender offer", "penawaran tender",
        "perubahan pengendali", "change of control",
        "substansial", "substantial",
        "hmetd", "rights issue", "private placement",
        "suntik", "injeksi", "investasi strategis",
        "merger", "penggabungan",
    ]

    for endpoint in endpoints:
        try:
            resp = requests.get(
                endpoint,
                headers=HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            rows = []
            if isinstance(data, dict):
                rows = data.get("Replies", data.get("Rows", data.get("data", [])))
            elif isinstance(data, list):
                rows = data

            results = []
            for row in rows:
                parsed = _parse_disclosure_for_insider(row)
                if not parsed:
                    continue

                combined = f"{parsed.get('title', '')} {parsed.get('category', '')}".lower()
                
                # Filter false positives: general meetings, dividends
                if any(ex in combined for ex in ["rups", "rapat umum", "general meeting", "dividen", "dividend"]):
                    continue

                if any(kw in combined for kw in insider_keywords):
                    # Classify the type
                    insider_type = _classify_insider_type(combined)
                    type_info = INSIDER_TYPES.get(insider_type, {})

                    results.append({
                        "source": "IDX Disclosure",
                        "ticker": parsed.get("emiten", ""),
                        "title": parsed.get("title", ""),
                        "date": parsed.get("date", ""),
                        "url": parsed.get("url", ""),
                        "insider_type": insider_type,
                        "type_label": type_info.get("label", "📋 Corporate Action"),
                        "weight": type_info.get("weight", 2),
                        "description": parsed.get("title", ""),
                        "is_watchlist": parsed.get("emiten", "").upper() in WATCHLIST_TICKERS,
                    })

            if results:
                return results

        except Exception as e:
            logger.debug("Insider disclosure endpoint failed: %s", e)

    return []


def _parse_disclosure_for_insider(row: dict) -> Optional[Dict]:
    """Parse a single announcement row for insider tracking."""
    if "pengumuman" in row:
        p = row["pengumuman"]
        attachments = row.get("attachments", [])
        url = ""
        if attachments and isinstance(attachments, list) and len(attachments) > 0:
            url = attachments[0].get("FullSavePath", "")

        return {
            "emiten": (p.get("Kode_Emiten", "") or "").strip().upper(),
            "title": (p.get("JudulPengumuman", "") or "").strip(),
            "date": str(p.get("TglPengumuman", ""))[:10],
            "category": (p.get("JenisPengumuman", "") or "").strip(),
            "url": url,
        }

    return {
        "emiten": (
            row.get("KodeEmiten", row.get("stock_code", row.get("Emiten", ""))) or ""
        ).strip().upper(),
        "title": (
            row.get("Judul", row.get("title", row.get("Title", ""))) or ""
        ).strip(),
        "date": str(row.get("Tanggal", row.get("date", "")))[:10],
        "category": (
            row.get("Kategori", row.get("category", "")) or ""
        ).strip(),
        "url": "",
    }


def _classify_insider_type(text: str) -> str:
    """Classify insider activity type from disclosure text."""
    text = text.lower()

    if any(kw in text for kw in ["tender offer", "penawaran tender"]):
        return "tender_offer"
    if any(kw in text for kw in ["pengendali baru", "perubahan pengendali", "change of control"]):
        return "new_controller"
    if any(kw in text for kw in ["substansial", "substantial", "kepemilikan > 5"]):
        return "substantial_shareholder"
    if any(kw in text for kw in [
        "pembelian saham", "beli saham", "akuisisi", "acquisition",
        "pengambilalihan", "suntik", "injeksi",
    ]):
        return "insider_buy"
    if any(kw in text for kw in ["penjualan saham", "jual saham", "divestasi"]):
        return "insider_sell"
    if any(kw in text for kw in ["transaksi blok", "block trade"]):
        return "block_trade"

    return "insider_buy"  # Default for ambiguous ownership changes


def _fetch_company_actions() -> List[Dict]:
    """Fetch corporate actions from IDX API."""
    endpoints = [
        "https://www.idx.co.id/primary/ListedCompany/GetCorporateAction"
        "?indexFrom=0&pageSize=20&lang=id",
        "https://cors.eu.org/https://www.idx.co.id/primary/ListedCompany/GetCorporateAction"
        "?indexFrom=0&pageSize=20&lang=id",
    ]

    for endpoint in endpoints:
        try:
            resp = requests.get(
                endpoint,
                headers=HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            rows = []
            if isinstance(data, dict):
                rows = data.get("Replies", data.get("Rows", data.get("data", [])))
            elif isinstance(data, list):
                rows = data

            results = []
            for row in rows:
                ticker = (row.get("KodeEmiten", row.get("Kode", "")) or "").strip().upper()
                action_type = (row.get("JenisAksiKorporasi", row.get("Type", "")) or "").strip()
                title = (row.get("Judul", row.get("Remark", "")) or "").strip()
                date = str(row.get("TanggalAksi", row.get("Date", "")))[:10]

                if ticker and (action_type or title):
                    results.append({
                        "source": "IDX Corporate Action",
                        "ticker": ticker,
                        "title": f"{action_type}: {title}" if action_type else title,
                        "date": date,
                        "url": "",
                        "insider_type": "insider_buy",
                        "type_label": "📋 Corporate Action",
                        "weight": 3,
                        "description": title,
                        "is_watchlist": ticker in WATCHLIST_TICKERS,
                    })

            if results:
                return results

        except Exception as e:
            logger.debug("Corporate action endpoint failed: %s", e)

    return []


def _fetch_substantial_changes() -> List[Dict]:
    """
    Fetch substantial shareholder changes from IDX.
    These are the most valuable — someone buying > 5% of a company.
    """
    endpoints = [
        "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        "?indexFrom=0&pageSize=30&lang=id&jenisPengumuman=Perubahan%20Pemegang%20Saham",
        "https://cors.eu.org/https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        "?indexFrom=0&pageSize=30&lang=id&jenisPengumuman=Perubahan%20Pemegang%20Saham",
    ]

    for endpoint in endpoints:
        try:
            resp = requests.get(
                endpoint,
                headers=HEADERS,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            data = resp.json()
            rows = []
            if isinstance(data, dict):
                rows = data.get("Replies", data.get("Rows", data.get("data", [])))

            results = []
            for row in rows:
                parsed = _parse_disclosure_for_insider(row)
                if parsed and parsed.get("emiten"):
                    results.append({
                        "source": "IDX Substantial Change",
                        "ticker": parsed["emiten"],
                        "title": parsed.get("title", ""),
                        "date": parsed.get("date", ""),
                        "url": parsed.get("url", ""),
                        "insider_type": "substantial_shareholder",
                        "type_label": "🐋 Pemegang Saham Substansial",
                        "weight": 5,
                        "description": parsed.get("title", ""),
                        "is_watchlist": parsed["emiten"] in WATCHLIST_TICKERS,
                    })

            if results:
                return results

        except Exception as e:
            logger.debug("Substantial shareholder endpoint failed: %s", e)

    return []


def format_insider_alert(activities: List[Dict]) -> str:
    """Format insider activities into a Telegram alert."""
    if not activities:
        return ""

    lines = [
        "🐋 <b>INSIDER / WHALE ACTIVITY DETECTED</b>",
        f"<i>{len(activities)} aktivitas terdeteksi</i>",
        "",
    ]

    for i, act in enumerate(activities[:10], 1):
        ticker = act.get("ticker", "—")
        title = act.get("title", "—")[:120]
        type_label = act.get("type_label", "")
        date = act.get("date", "")
        url = act.get("url", "")
        wl = "⭐ " if act.get("is_watchlist") else ""

        link_str = f' → <a href="{url}">📄 Buka</a>' if url else ""
        date_str = f" ({date})" if date else ""

        lines.append(
            f"{i}. {wl}{type_label}\n"
            f"   <b>[{ticker}]</b>{date_str}\n"
            f"   {title}{link_str}"
        )
        lines.append("")

    lines.append("⚠️ <i>Ini bukan rekomendasi investasi. DYOR.</i>")
    return "\n".join(lines)
