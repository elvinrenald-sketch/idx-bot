"""
data/disclosure.py — Scrape IDX keterbukaan informasi
"""
import logging
import time
from datetime import datetime
from typing import List, Dict, Set

import httpx
import pytz

from config import IDX_ANNOUNCEMENT_URL, IDX_HEADERS, TIMEZONE

logger = logging.getLogger("idx_bot.disclosure")
WIB = pytz.timezone(TIMEZONE)

# In-memory cache: set of seen disclosure IDs to prevent duplicate alerts
_seen_ids: Set[str] = set()
_MAX_CACHE = 500  # reset kalau terlalu besar


def fetch_disclosures(page_size: int = 20) -> List[Dict]:
    """
    Ambil daftar keterbukaan informasi terbaru dari IDX.
    Returns list of dicts, atau list kosong jika gagal.
    """
    url = (
        f"https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
        f"?indexFrom=0&pageSize={page_size}&lang=id"
    )

    # Coba beberapa endpoint IDX (situs sering berubah path)
    endpoints = [
        url,
        f"https://www.idx.co.id/primary/ListedCompany/GetAnnouncement?indexFrom=0&pageSize={page_size}",
        (
            f"https://www.idx.co.id/umbraco/Surface/ListedCompany/GetAnnouncement"
            f"?indexFrom=0&pageSize={page_size}&lang=id"
        ),
    ]

    for endpoint in endpoints:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(endpoint, headers=IDX_HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    return _parse_announcements(data)
                logger.warning("IDX endpoint %s → HTTP %s", endpoint, resp.status_code)
                time.sleep(1)
        except Exception as e:
            logger.error("Error fetch disclosure dari %s: %s", endpoint, e)
            time.sleep(1)

    logger.error("Semua endpoint IDX gagal.")
    return []


def _parse_announcements(data) -> List[Dict]:
    """Parse JSON response dari IDX ke list dict terstandar."""
    items = []

    # IDX API biasanya punya struktur: {"Rows": [...]} atau {"data": [...]}
    rows = []
    if isinstance(data, dict):
        rows = data.get("Rows", data.get("data", data.get("rows", [])))
    elif isinstance(data, list):
        rows = data

    for row in rows:
        try:
            item = {
                "id":       str(row.get("Kode", row.get("code", row.get("No", "")))),
                "emiten":   row.get("KodeEmiten", row.get("stock_code", row.get("Emiten", ""))),
                "title":    row.get("Judul", row.get("title", row.get("Title", ""))),
                "date":     row.get("Tanggal", row.get("date", row.get("Date", ""))),
                "category": row.get("Kategori", row.get("category", row.get("Category", ""))),
                "url":      _build_attachment_url(row),
            }
            if item["title"] or item["emiten"]:
                items.append(item)
        except Exception as e:
            logger.debug("Gagal parse row: %s | %s", row, e)

    return items


def _build_attachment_url(row: dict) -> str:
    """Bangun URL lampiran PDF/dokumen dari field attachment."""
    attach = row.get("Attachment", row.get("attachment", row.get("File", "")))
    if attach and isinstance(attach, str) and attach.strip():
        if attach.startswith("http"):
            return attach
        return f"https://www.idx.co.id/{attach.lstrip('/')}"
    return ""


def get_new_disclosures(disclosures: List[Dict]) -> List[Dict]:
    """
    Filter hanya disclosure yang belum pernah dilihat sebelumnya.
    Update cache _seen_ids.
    """
    global _seen_ids

    # Reset cache kalau terlalu besar
    if len(_seen_ids) > _MAX_CACHE:
        _seen_ids.clear()

    new_items = []
    for item in disclosures:
        uid = item.get("id") or f"{item.get('emiten')}_{item.get('title')}"
        if uid and uid not in _seen_ids:
            _seen_ids.add(uid)
            new_items.append(item)

    return new_items
