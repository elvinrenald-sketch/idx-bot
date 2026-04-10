"""
data/disclosure.py — IDX disclosure fetcher with retry + fallback + persistence
No more in-memory _seen_ids — everything persisted to SQLite.
"""
import logging
import time
import re
from datetime import datetime
from typing import List, Dict

from curl_cffi import requests
import pytz

from config import IDX_HEADERS, TIMEZONE

logger = logging.getLogger("idx_bot.disclosure")
WIB = pytz.timezone(TIMEZONE)


def fetch_disclosures(page_size: int = 30) -> List[Dict]:
    """
    Fetch IDX disclosures with 3-endpoint fallback + proxy routing + retry logic.
    Returns list of standardized dicts, or empty list on total failure.
    """
    endpoints = [
        # 1. Direct routes (Works on local residential IPs)
        f"https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        f"?indexFrom=0&pageSize={page_size}&lang=id",
        
        f"https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        f"?indexFrom=0&pageSize={page_size}",

        # 2. CORS Proxy routes (Bypasses Cloudflare Datacenter block on Railway)
        f"https://cors.eu.org/https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        f"?indexFrom=0&pageSize={page_size}&lang=id",
        
        # 3. Legacy endpoint
        f"https://www.idx.co.id/umbraco/Surface/ListedCompany/GetAnnouncement"
        f"?indexFrom=0&pageSize={page_size}&lang=id",
    ]

    for endpoint in endpoints:
        for attempt in range(3):  # 3 retries with exponential backoff
            try:
                resp = requests.get(
                    endpoint,
                    impersonate="chrome120",
                    timeout=20,
                    headers={
                        **IDX_HEADERS,
                        "Cache-Control": "no-cache",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    items = _parse_announcements(data)
                    if items:
                        logger.info(
                            "Fetched %d disclosures from %s (attempt %d)",
                            len(items), endpoint[:60], attempt + 1,
                        )
                        return items

                logger.warning(
                    "IDX endpoint HTTP %s: %s (attempt %d)",
                    resp.status_code, endpoint[:60], attempt + 1,
                )
            except Exception as e:
                logger.warning(
                    "IDX fetch error: %s | %s (attempt %d)",
                    endpoint[:60], e, attempt + 1,
                )

            # Exponential backoff: 2s, 4s, 8s
            delay = 2 ** (attempt + 1)
            time.sleep(delay)

    logger.error("All IDX endpoints failed after retries.")
    return []


def _parse_announcements(data) -> List[Dict]:
    """Parse JSON response from IDX into standardized list of dicts."""
    items = []

    rows = []
    if isinstance(data, dict):
        rows = data.get("Replies", data.get("Rows", data.get("data", data.get("rows", []))))
    elif isinstance(data, list):
        rows = data

    for row in rows:
        try:
            item = _parse_single_row(row)
            if item and (item.get("title") or item.get("emiten")):
                items.append(item)
        except Exception as e:
            logger.debug("Failed to parse row: %s | %s", row, e)

    return items


def _parse_single_row(row: dict) -> Dict:
    """Parse a single announcement row — handles both old and new IDX format."""
    # New format (Replies -> pengumuman)
    if "pengumuman" in row:
        p = row["pengumuman"]
        return {
            "id": str(p.get("Id2", p.get("Id", ""))),
            "emiten": (p.get("Kode_Emiten", "") or "").strip().upper(),
            "title": (p.get("JudulPengumuman", "") or "").strip(),
            "date": _format_date(p.get("TglPengumuman", "")),
            "category": (p.get("JenisPengumuman", "") or "").strip(),
            "url": _build_attachment_url(row),
            "raw_date": p.get("TglPengumuman", ""),
        }

    # Old format (flat dict)
    return {
        "id": str(row.get("Kode", row.get("code", row.get("No", "")))),
        "emiten": (
            row.get("KodeEmiten", row.get("stock_code", row.get("Emiten", ""))) or ""
        ).strip().upper(),
        "title": (
            row.get("Judul", row.get("title", row.get("Title", ""))) or ""
        ).strip(),
        "date": _format_date(
            row.get("Tanggal", row.get("date", row.get("Date", "")))
        ),
        "category": (
            row.get("Kategori", row.get("category", row.get("Category", ""))) or ""
        ).strip(),
        "url": _build_attachment_url(row),
        "raw_date": row.get("Tanggal", row.get("date", row.get("Date", ""))),
    }


def _format_date(raw: str) -> str:
    """Normalize date string to YYYY-MM-DD."""
    if not raw:
        return ""
    # Already YYYY-MM-DD
    if re.match(r"\d{4}-\d{2}-\d{2}", str(raw)):
        return str(raw)[:10]
    # Try common IDX date formats
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"]:
        try:
            return datetime.strptime(str(raw)[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return str(raw)[:10]


def _build_attachment_url(row: dict) -> str:
    """Build URL to the PDF/document attachment."""
    # New structure
    attachments = row.get("attachments", [])
    if attachments and isinstance(attachments, list) and len(attachments) > 0:
        attach = attachments[0].get("FullSavePath", "")
        if attach:
            return attach

    # Old structure
    attach = row.get("Attachment", row.get("attachment", row.get("File", "")))
    if attach and isinstance(attach, str) and attach.strip():
        if attach.startswith("http"):
            return attach
        return f"https://www.idx.co.id/{attach.lstrip('/')}"
    return ""


def filter_new_disclosures(disclosures: List[Dict], db) -> List[Dict]:
    """
    Filter only disclosures not yet seen — uses SQLite instead of in-memory set.
    Also saves new ones to the database.
    """
    new_items = []
    for disc in disclosures:
        if db.save_disclosure(disc):  # Returns True if new
            new_items.append(disc)

    if new_items:
        logger.info("Found %d new disclosures out of %d total.", len(new_items), len(disclosures))
    return new_items
