"""
data/news.py — Indonesian financial news scraper
Scans CNBC Indonesia, Kontan, and Bisnis.com for acquisition/backdoor listing mentions.
"""
import re
import logging
from typing import List, Dict
from datetime import datetime

from curl_cffi import requests
from bs4 import BeautifulSoup

from config import NEWS_SOURCES, NEWS_SEARCH_QUERIES, WATCHLIST_TICKERS

logger = logging.getLogger("idx_bot.news")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
}


def scan_all_news() -> List[Dict]:
    """
    Scan all configured news sources for corporate action / acquisition / backdoor listing news.
    Returns deduplicated list of articles.
    """
    all_articles = []

    for query in NEWS_SEARCH_QUERIES[:3]:  # Limit queries to conserve resources
        for source_key, source_cfg in NEWS_SOURCES.items():
            try:
                articles = _scan_source(source_key, source_cfg, query)
                all_articles.extend(articles)
            except Exception as e:
                logger.warning("News scan failed for %s (%s): %s", source_key, query, e)

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for article in all_articles:
        url = article.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(article)

    logger.info("Scraped %d unique news articles from %d total.", len(unique), len(all_articles))
    return unique


def _scan_source(source_key: str, source_cfg: dict, query: str) -> List[Dict]:
    """Scan a single news source for a given query."""
    search_url = source_cfg["search_url"].format(query=query.replace(" ", "+"))

    resp = requests.get(
        search_url,
        headers=HEADERS,
        impersonate="chrome120",
        timeout=15,
    )

    if resp.status_code != 200:
        logger.warning("News source %s returned HTTP %s", source_key, resp.status_code)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    if source_key == "cnbc":
        return _parse_cnbc(soup, source_cfg)
    elif source_key == "kontan":
        return _parse_kontan(soup, source_cfg)
    elif source_key == "bisnis":
        return _parse_bisnis(soup, source_cfg)

    return []


def _parse_cnbc(soup: BeautifulSoup, cfg: dict) -> List[Dict]:
    """Parse CNBC Indonesia search results."""
    articles = []
    # CNBC search results are in article/list items
    for item in soup.select("article, .list-news li, .media__title a, .box_list li")[:10]:
        try:
            link = item if item.name == "a" else item.find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href:
                continue

            # Make absolute URL
            if not href.startswith("http"):
                href = cfg["base_url"] + href

            # Extract snippet
            snippet_el = item.find("p") or item.find("span", class_=re.compile("desc|excerpt|summary"))
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            # Extract date
            date_el = item.find("span", class_=re.compile("date|time|ago"))
            date = date_el.get_text(strip=True) if date_el else ""

            articles.append({
                "source": "CNBC Indonesia",
                "title": title[:200],
                "url": href,
                "snippet": snippet[:300],
                "date": date,
                "tickers": _extract_tickers(f"{title} {snippet}"),
            })
        except Exception as e:
            logger.debug("CNBC parse error: %s", e)

    return articles


def _parse_kontan(soup: BeautifulSoup, cfg: dict) -> List[Dict]:
    """Parse Kontan search results."""
    articles = []
    for item in soup.select(".list-berita li, .news-list li, article")[:10]:
        try:
            link = item.find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href:
                continue

            if not href.startswith("http"):
                href = cfg["base_url"] + href

            snippet_el = item.find("p") or item.find("span", class_=re.compile("desc|synopsis"))
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            date_el = item.find("span", class_=re.compile("date|time"))
            date = date_el.get_text(strip=True) if date_el else ""

            articles.append({
                "source": "Kontan",
                "title": title[:200],
                "url": href,
                "snippet": snippet[:300],
                "date": date,
                "tickers": _extract_tickers(f"{title} {snippet}"),
            })
        except Exception as e:
            logger.debug("Kontan parse error: %s", e)

    return articles


def _parse_bisnis(soup: BeautifulSoup, cfg: dict) -> List[Dict]:
    """Parse Bisnis.com search results."""
    articles = []
    for item in soup.select(".col-sm-7, .list-news li, article")[:10]:
        try:
            link = item.find("a")
            if not link:
                continue

            title = link.get_text(strip=True)
            href = link.get("href", "")
            if not title or not href:
                continue

            if not href.startswith("http"):
                href = cfg["base_url"] + href

            snippet_el = item.find("p") or item.find("div", class_=re.compile("desc|synopsis"))
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""

            date_el = item.find("span", class_=re.compile("date|time"))
            date = date_el.get_text(strip=True) if date_el else ""

            articles.append({
                "source": "Bisnis.com",
                "title": title[:200],
                "url": href,
                "snippet": snippet[:300],
                "date": date,
                "tickers": _extract_tickers(f"{title} {snippet}"),
            })
        except Exception as e:
            logger.debug("Bisnis parse error: %s", e)

    return articles


def _extract_tickers(text: str) -> List[str]:
    """
    Extract stock ticker codes from text.
    Looks for 4-letter uppercase codes that match known tickers,
    or patterns like (BBCA), [GOTO], saham BUMI.
    """
    if not text:
        return []

    found = []

    # Pattern: explicit ticker mentions like (BBCA), [GOTO], KODE: BUMI
    explicit = re.findall(r'[(\[]\s*([A-Z]{4})\s*[)\]]', text.upper())
    found.extend(explicit)

    # Pattern: "saham XXXX" or "emiten XXXX" or "PT XXXX"
    contextual = re.findall(
        r'(?:saham|emiten|kode|ticker|PT)\s+([A-Z]{4})\b', text.upper()
    )
    found.extend(contextual)

    # Match against known watchlist tickers
    for ticker in WATCHLIST_TICKERS:
        if ticker in text.upper():
            found.append(ticker)

    # Deduplicate
    return list(set(found))


def filter_new_news(articles: List[Dict], db) -> List[Dict]:
    """Filter only articles not yet seen — uses SQLite."""
    new_items = []
    for article in articles:
        if db.save_news(article):
            new_items.append(article)
    return new_items
