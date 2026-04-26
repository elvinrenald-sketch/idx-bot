"""
data/rss_feeds.py — Real-time RSS feed aggregator for Indonesian financial news
Scans 10+ sources every cycle. Built for speed — no heavy XML libs, just regex + curl.
Zero external dependencies beyond what we already have.
"""
import re
import logging
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from xml.etree import ElementTree

from curl_cffi import requests
import pytz

from config import TIMEZONE, WATCHLIST_TICKERS

logger = logging.getLogger("idx_bot.rss")
WIB = pytz.timezone(TIMEZONE)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ══════════════════════════════════════════════════════════════════
# RSS FEED SOURCES — Indonesian Financial Media + Global
# ══════════════════════════════════════════════════════════════════
RSS_FEEDS = {
    # ── Indonesian Financial News ──────────────────────────────
    "cnbc_market": {
        "name": "CNBC Indonesia Market",
        "url": "https://www.cnbcindonesia.com/market/rss",
        "lang": "id",
        "priority": 1,
    },
    "cnbc_news": {
        "name": "CNBC Indonesia News",
        "url": "https://www.cnbcindonesia.com/news/rss",
        "lang": "id",
        "priority": 2,
    },
    "kontan_investasi": {
        "name": "Kontan Investasi",
        "url": "https://www.kontan.co.id/rss/investasi",
        "lang": "id",
        "priority": 1,
    },
    "kontan_saham": {
        "name": "Kontan Saham",
        "url": "https://www.kontan.co.id/rss/saham",
        "lang": "id",
        "priority": 1,
    },
    "bisnis_market": {
        "name": "Bisnis.com Market",
        "url": "https://www.bisnis.com/rss/market",
        "lang": "id",
        "priority": 1,
    },
    "bisnis_finansial": {
        "name": "Bisnis.com Finansial",
        "url": "https://www.bisnis.com/rss/finansial",
        "lang": "id",
        "priority": 2,
    },
    "detik_finance": {
        "name": "Detik Finance",
        "url": "https://rss.detik.com/index.php/finance",
        "lang": "id",
        "priority": 2,
    },
    "idnfinancials": {
        "name": "IDN Financials",
        "url": "https://www.idnfinancials.com/rss",
        "lang": "en",
        "priority": 1,
    },
    # ── Global News (for macro context) ────────────────────────
    "reuters_business": {
        "name": "Reuters Business",
        "url": "https://news.google.com/rss/search?q=Indonesia+stock+market&hl=en-ID&gl=ID&ceid=ID:en",
        "lang": "en",
        "priority": 2,
    },
    "bloomberg_asia": {
        "name": "Bloomberg Asia",
        "url": "https://news.google.com/rss/search?q=IHSG+OR+IDX+OR+%22Indonesia+stock%22&hl=id&gl=ID&ceid=ID:id",
        "lang": "id",
        "priority": 1,
    },
}

# Keywords that indicate HIGH-PRIORITY corporate actions
CRITICAL_KEYWORDS = [
    # Acquisition & Takeover
    "akuisisi", "acquisition", "mengakuisisi", "diakuisisi",
    "pengambilalihan", "takeover", "beli saham", "membeli saham",
    "pembelian saham", "share purchase",
    # Backdoor Listing & RTO
    "backdoor listing", "reverse takeover", "rto", "injeksi aset",
    "shell company", "perubahan kegiatan usaha",
    # Change of Control
    "perubahan pengendali", "change of control", "pengendali baru",
    "pemegang saham pengendali", "controlling shareholder",
    # Big Player Entry
    "masuk ke", "suntik dana", "suntik modal", "injeksi dana",
    "investasi strategis", "strategic investment",
    "investor strategis", "strategic investor",
    "private placement", "rights issue", "hmetd",
    # Merger
    "merger", "penggabungan", "konsolidasi",
    # Divestasi
    "divestasi", "jual saham", "lepas saham", "divestiture",
    # Tokoh/Konglomerat
    "konglomerat", "taipan", "bakrie", "salim", "hartono",
    "widjaja", "tanoto", "prajogo", "surya paloh",
    "chairul tanjung", "anthoni salim", "low tuck kwong",
    "garibaldi thohir", "erick thohir", "sandiaga",
    "aguan", "ciputra", "sinar mas", "lippo", "djarum",
    "astra", "jardine",
]

# Keywords for macro/economic events
MACRO_KEYWORDS = [
    "suku bunga", "interest rate", "bi rate", "bi 7-day",
    "inflasi", "inflation", "deflasi",
    "kurs", "rupiah", "usd/idr", "dollar",
    "the fed", "federal reserve", "fomc",
    "resesi", "recession",
    "gdp", "pdb", "pertumbuhan ekonomi",
    "neraca", "trade balance", "ekspor", "impor",
    "obligasi", "sbn", "bond", "yield",
    "commodity", "komoditas", "minyak", "crude oil",
    "batu bara", "coal", "nikel", "nickel", "emas", "gold",
    "cpo", "kelapa sawit", "palm oil",
]


def fetch_all_feeds(max_age_hours: int = 6) -> List[Dict]:
    """
    Fetch and parse ALL RSS feeds, returning deduplicated articles.
    Sorted by: priority first, then recency.
    """
    all_articles = []

    for feed_key, feed_cfg in RSS_FEEDS.items():
        try:
            articles = _fetch_single_feed(feed_key, feed_cfg, max_age_hours)
            all_articles.extend(articles)
        except Exception as e:
            logger.debug("RSS feed %s failed: %s", feed_key, str(e)[:100])

    # Deduplicate by URL hash
    seen = set()
    unique = []
    for article in all_articles:
        key = hashlib.md5(article.get("url", "").encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(article)

    # Sort: critical keywords first, then by priority, then recency
    unique.sort(key=lambda x: (
        -x.get("is_critical", 0),
        x.get("priority", 99),
        x.get("published", "0"),
    ), reverse=False)

    # Re-sort: critical first, then rest by recency
    critical = [a for a in unique if a.get("is_critical")]
    normal = [a for a in unique if not a.get("is_critical")]
    result = critical + normal

    logger.info(
        "RSS: %d unique articles (%d critical) from %d feeds",
        len(result), len(critical), len(RSS_FEEDS),
    )
    return result


def _fetch_single_feed(feed_key: str, cfg: dict, max_age_hours: int) -> List[Dict]:
    """Fetch a single RSS feed and parse items."""
    try:
        resp = requests.get(
            cfg["url"],
            headers=HEADERS,
            impersonate="chrome120",
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        return _parse_rss_xml(resp.text, cfg, max_age_hours)

    except Exception as e:
        logger.debug("RSS %s error: %s", feed_key, e)
        return []


def _parse_rss_xml(xml_text: str, cfg: dict, max_age_hours: int) -> List[Dict]:
    """Parse RSS XML into article dicts."""
    articles = []

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        # Fallback: try to clean broken XML
        xml_text = re.sub(r'&(?!amp;|lt;|gt;|apos;|quot;)', '&amp;', xml_text)
        try:
            root = ElementTree.fromstring(xml_text)
        except Exception:
            return []

    # Handle both RSS 2.0 and Atom formats
    items = root.findall(".//item")
    if not items:
        # Try Atom format
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//atom:entry", ns)

    for item in items[:20]:  # Max 20 per feed
        try:
            article = _parse_rss_item(item, cfg)
            if article:
                articles.append(article)
        except Exception:
            continue

    return articles


def _parse_rss_item(item, cfg: dict) -> Optional[Dict]:
    """Parse a single RSS item into a standardized dict."""
    # Extract fields — handle both RSS 2.0 and Atom
    title = _get_text(item, "title") or ""
    link = _get_text(item, "link") or ""
    description = _get_text(item, "description") or _get_text(item, "summary") or ""
    pub_date = _get_text(item, "pubDate") or _get_text(item, "published") or ""

    if not title or not link:
        return None

    # Clean HTML from description
    description = re.sub(r'<[^>]+>', '', description).strip()[:500]

    # Detect critical keywords
    combined_text = f"{title} {description}".lower()
    is_critical = any(kw in combined_text for kw in CRITICAL_KEYWORDS)
    is_macro = any(kw in combined_text for kw in MACRO_KEYWORDS)

    # Extract tickers
    tickers = _extract_tickers_from_text(f"{title} {description}")

    # Classify article type
    article_type = "general"
    if is_critical:
        article_type = "corporate_action"
    elif is_macro:
        article_type = "macro"

    # Calculate urgency score
    urgency = 0
    matched_keywords = []
    for kw in CRITICAL_KEYWORDS:
        if kw in combined_text:
            urgency += 3
            matched_keywords.append(kw)
    for kw in MACRO_KEYWORDS:
        if kw in combined_text:
            urgency += 1
            matched_keywords.append(kw)
    urgency = min(urgency, 10)

    return {
        "source": cfg["name"],
        "title": title[:300],
        "url": link,
        "snippet": description[:500],
        "published": pub_date,
        "lang": cfg.get("lang", "id"),
        "priority": cfg.get("priority", 5),
        "is_critical": is_critical,
        "is_macro": is_macro,
        "article_type": article_type,
        "tickers": tickers,
        "urgency": urgency,
        "matched_keywords": matched_keywords[:5],
    }


def _get_text(element, tag: str) -> Optional[str]:
    """Safely get text from an XML element."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    # Try with namespace
    for ns_prefix in ["", "{http://www.w3.org/2005/Atom}"]:
        child = element.find(f"{ns_prefix}{tag}")
        if child is not None:
            if child.text:
                return child.text.strip()
            # Atom link uses href attribute
            if tag == "link" and child.get("href"):
                return child.get("href")
    return None


def _extract_tickers_from_text(text: str) -> List[str]:
    """Extract stock ticker codes from text."""
    if not text:
        return []

    found = set()
    upper_text = text.upper()

    # Pattern: explicit mentions like (BBCA), [GOTO]
    explicit = re.findall(r'[(\[]\s*([A-Z]{4})\s*[)\]]', upper_text)
    found.update(explicit)

    # Pattern: "saham XXXX" or "emiten XXXX"
    contextual = re.findall(
        r'(?:saham|emiten|kode|ticker|PT)\s+([A-Z]{4})\b', upper_text
    )
    found.update(contextual)

    # Match known tickers
    for ticker in WATCHLIST_TICKERS:
        if ticker in upper_text:
            found.add(ticker)

    return list(found)


def filter_new_rss_articles(articles: List[Dict], db) -> List[Dict]:
    """Filter only articles not yet seen — uses SQLite."""
    new_items = []
    for article in articles:
        url = article.get("url", "")
        if url and not db.is_news_seen(url):
            if db.save_news(article):
                new_items.append(article)
    return new_items
