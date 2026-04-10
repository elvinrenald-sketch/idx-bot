"""
signals/detector.py — Multi-layer intelligent signal detection
Combines keyword matching + Gemini AI + price anomalies + news correlation
for a 40-point scoring system.
"""
import re
import logging
from typing import List, Dict, Tuple

from config import (
    SIGNAL_KEYWORDS,
    WATCHLIST_KEYWORDS,
    WATCHLIST_TICKERS,
    ALERT_CRITICAL_THRESHOLD,
    ALERT_HIGH_THRESHOLD,
    ALERT_INFO_THRESHOLD,
    MAX_GEMINI_CALLS_PER_SCAN,
)

logger = logging.getLogger("idx_bot.detector")


def _normalize(text: str) -> str:
    """Lowercase + strip punctuation for matching."""
    return re.sub(r"[^\w\s]", " ", text.lower())


def _is_watchlist_text(text: str) -> bool:
    """Check if text contains watchlist sector keywords."""
    norm = _normalize(text)
    return any(kw in norm for kw in WATCHLIST_KEYWORDS)


def _is_watchlist_ticker(ticker: str) -> bool:
    """Check if ticker is in watchlist."""
    return ticker.upper() in WATCHLIST_TICKERS


# ── Layer 1: Keyword Matching ─────────────────────────────────────

def score_keywords(disclosure: dict) -> Tuple[int, List[str]]:
    """
    Score disclosure based on keyword matching.
    Max score: 10 points.
    Returns (score, list_of_matched_labels).
    """
    combined_text = _normalize(
        f"{disclosure.get('title', '')} {disclosure.get('category', '')} "
        f"{disclosure.get('emiten', '')}"
    )

    total_score = 0
    matched_labels = []

    for sig_key, sig_def in SIGNAL_KEYWORDS.items():
        for kw in sig_def["keywords"]:
            if kw in combined_text:
                total_score += sig_def["weight"]
                label = sig_def["label"]
                if label not in matched_labels:
                    matched_labels.append(label)
                break  # Only count once per category

    # Cap at 10
    return min(total_score, 10), matched_labels


# ── Layer 2: AI Analysis Score ────────────────────────────────────

def score_ai_analysis(analysis: dict) -> int:
    """
    Score based on Gemini AI analysis.
    Max score: 10 points.
    """
    if not analysis:
        return 0

    urgency = analysis.get("urgency", 0)  # 1-10
    confidence = analysis.get("confidence", 0)  # 0-1
    risk_type = analysis.get("risk_type", "normal")

    # High-risk types get bonus
    risk_bonus = {
        "backdoor_listing": 3,
        "acquisition": 2,
        "change_of_control": 2,
        "merger": 2,
        "rights_issue": 1,
        "material_transaction": 1,
        "divestiture": 1,
        "normal": 0,
    }.get(risk_type, 0)

    # Score = (urgency * confidence) scaled to 0-7, plus risk bonus
    base_score = int((urgency * confidence) * 0.7)
    total = min(base_score + risk_bonus, 10)

    return total


# ── Layer 3: Anomaly Correlation Score ────────────────────────────

def score_anomaly_correlation(ticker: str, anomalies: List[dict]) -> int:
    """
    Score based on price/volume anomaly correlation.
    Max score: 8 points.
    """
    if not anomalies:
        return 0

    ticker_anomalies = [a for a in anomalies if a.get("ticker", "").upper() == ticker.upper()]
    if not ticker_anomalies:
        return 0

    score = 0
    for anomaly in ticker_anomalies:
        atype = anomaly.get("type", "")
        magnitude = anomaly.get("magnitude", 0)

        if atype == "VOLUME_PRICE_SPIKE":
            score += 6  # Both volume + price = very suspicious
        elif atype == "VOLUME_SPIKE":
            score += 3 + min(int(magnitude / 2), 2)  # 3-5 based on magnitude
        elif atype == "PRICE_SPIKE":
            score += 2 + min(int(magnitude / 3), 2)  # 2-4 based on magnitude

        # Extra penalty if no disclosure exists
        if not anomaly.get("has_disclosure", True):
            score += 2

    return min(score, 8)


# ── Layer 4: News Correlation Score ───────────────────────────────

def score_news_correlation(ticker: str, news_articles: List[dict]) -> int:
    """
    Score based on news mentions.
    Max score: 5 points.
    """
    if not news_articles:
        return 0

    matching = []
    for article in news_articles:
        tickers = article.get("tickers", [])
        if ticker.upper() in [t.upper() for t in tickers]:
            matching.append(article)
        elif ticker.upper() in (article.get("title", "") + article.get("snippet", "")).upper():
            matching.append(article)

    if not matching:
        return 0

    # More mentions = higher score
    base_score = min(len(matching) * 2, 4)

    # AI relevance bonus
    for article in matching:
        ai = article.get("gemini_analysis", {})
        if isinstance(ai, dict) and ai.get("is_actionable"):
            base_score += 1
            break

    return min(base_score, 5)


# ── Layer 5: Watchlist Bonus ──────────────────────────────────────

def score_watchlist_bonus(disclosure: dict) -> int:
    """
    Bonus for watchlist tickers/sectors.
    Max score: 3 points.
    """
    ticker = disclosure.get("emiten", "").upper()
    text = f"{disclosure.get('title', '')} {disclosure.get('category', '')}"

    score = 0
    if _is_watchlist_ticker(ticker):
        score += 2
    if _is_watchlist_text(text):
        score += 1

    return min(score, 3)


# ── Layer 6: PDF Content Depth Score ──────────────────────────────

def score_pdf_content(analysis: dict) -> int:
    """
    Score based on depth of PDF analysis.
    Max score: 4 points.
    """
    if not analysis:
        return 0

    score = 0
    red_flags = analysis.get("red_flags", [])
    if red_flags:
        score += min(len(red_flags), 3)

    confidence = analysis.get("confidence", 0)
    if confidence >= 0.8:
        score += 1

    return min(score, 4)


# ══════════════════════════════════════════════════════════════════
# MAIN DETECTION ENGINE
# ══════════════════════════════════════════════════════════════════

def detect_signals(
    disclosures: List[Dict],
    news_articles: List[Dict] = None,
    anomalies: List[Dict] = None,
    engine=None,
    db=None,
) -> List[Dict]:
    """
    Full multi-layer signal detection.

    Scoring breakdown (max 40):
    - Keyword matching:         max 10
    - Gemini AI analysis:       max 10
    - Anomaly correlation:      max 8
    - News correlation:         max 5
    - Watchlist bonus:          max 3
    - PDF content depth:        max 4

    Args:
        disclosures: List of disclosure dicts
        news_articles: List of news article dicts (optional)
        anomalies: List of anomaly dicts (optional)
        engine: IntelligenceEngine instance (optional — for AI analysis)
        db: Database instance (optional — for persistence)

    Returns:
        List of signal dicts, sorted by score (highest first).
    """
    if not disclosures:
        return []

    news_articles = news_articles or []
    anomalies = anomalies or []
    results = []
    gemini_calls = 0

    for disc in disclosures:
        ticker = disc.get("emiten", "").upper()

        # ── Layer 1: Keywords ───────────────────────────────
        kw_score, matched_labels = score_keywords(disc)

        # ── Layer 5: Watchlist ──────────────────────────────
        wl_score = score_watchlist_bonus(disc)

        # Preliminary score (without AI) — used to prioritize Gemini calls
        prelim_score = kw_score + wl_score

        # ── Layer 2: AI Analysis (if available and budget permits)
        ai_score = 0
        ai_analysis = None

        if engine and gemini_calls < MAX_GEMINI_CALLS_PER_SCAN:
            # Only call Gemini for potentially interesting disclosures
            if prelim_score >= 2 or _is_watchlist_ticker(ticker):
                ai_analysis = engine.analyze_disclosure_with_pdf(disc)
                gemini_calls += 1

                if ai_analysis:
                    ai_score = score_ai_analysis(ai_analysis)

                    # Update labels with AI risk type
                    risk_label = _risk_type_to_label(ai_analysis.get("risk_type", ""))
                    if risk_label and risk_label not in matched_labels:
                        matched_labels.append(risk_label)

                    # Save analysis to DB
                    if db:
                        disc_id = disc.get("id", f"{ticker}_{disc.get('title','')}")
                        db.update_disclosure_analysis(disc_id, {
                            "signal_score": kw_score + ai_score,
                            "signal_level": "",
                            "signal_types": matched_labels,
                            "gemini_analysis": ai_analysis,
                            "gemini_risk_type": ai_analysis.get("risk_type", ""),
                            "gemini_urgency": ai_analysis.get("urgency", 0),
                            "gemini_confidence": ai_analysis.get("confidence", 0),
                        })

        # ── Layer 3: Anomaly Correlation ────────────────────
        anomaly_score = score_anomaly_correlation(ticker, anomalies)

        # ── Layer 4: News Correlation ───────────────────────
        news_score = score_news_correlation(ticker, news_articles)

        # ── Layer 6: PDF Content Depth ──────────────────────
        pdf_score = score_pdf_content(ai_analysis)

        # ── TOTAL SCORE ─────────────────────────────────────
        total_score = kw_score + ai_score + anomaly_score + news_score + wl_score + pdf_score

        # Skip if below minimum threshold
        if total_score < ALERT_INFO_THRESHOLD:
            continue

        # Classify alert tier
        if total_score >= ALERT_CRITICAL_THRESHOLD:
            signal_level = "🔴 CRITICAL"
            tier = "CRITICAL"
        elif total_score >= ALERT_HIGH_THRESHOLD:
            signal_level = "🟡 HIGH"
            tier = "HIGH"
        else:
            signal_level = "🟢 INFO"
            tier = "INFO"

        results.append({
            **disc,
            "signal_score": total_score,
            "signal_level": signal_level,
            "signal_tier": tier,
            "signal_types": matched_labels,
            "is_watchlist": _is_watchlist_ticker(ticker) or _is_watchlist_text(
                f"{disc.get('title', '')} {disc.get('emiten', '')}"
            ),
            "score_breakdown": {
                "keyword": kw_score,
                "ai": ai_score,
                "anomaly": anomaly_score,
                "news": news_score,
                "watchlist": wl_score,
                "pdf": pdf_score,
            },
            "gemini_analysis": ai_analysis,
            "related_anomalies": [
                a for a in anomalies if a.get("ticker", "").upper() == ticker
            ],
        })

    # Sort: watchlist first, then by score descending
    results.sort(key=lambda x: (x["is_watchlist"], x["signal_score"]), reverse=True)

    logger.info(
        "Signal detection: %d signals from %d disclosures "
        "(CRITICAL=%d, HIGH=%d, INFO=%d, Gemini calls=%d)",
        len(results),
        len(disclosures),
        sum(1 for r in results if r["signal_tier"] == "CRITICAL"),
        sum(1 for r in results if r["signal_tier"] == "HIGH"),
        sum(1 for r in results if r["signal_tier"] == "INFO"),
        gemini_calls,
    )

    return results


def _risk_type_to_label(risk_type: str) -> str:
    """Convert AI risk type to emoji label."""
    mapping = {
        "backdoor_listing": "🚪 Backdoor Listing",
        "acquisition": "🏢 Akuisisi",
        "change_of_control": "🔄 Perubahan Kendali",
        "merger": "🔀 Merger",
        "rights_issue": "📈 Rights Issue",
        "material_transaction": "💰 Transaksi Material",
        "divestiture": "📤 Divestasi",
    }
    return mapping.get(risk_type, "")


def classify_signal(score: int) -> str:
    """Classify signal level based on total score."""
    if score >= ALERT_CRITICAL_THRESHOLD:
        return "🔴 CRITICAL"
    elif score >= ALERT_HIGH_THRESHOLD:
        return "🟡 HIGH"
    elif score >= ALERT_INFO_THRESHOLD:
        return "🟢 INFO"
    return ""
