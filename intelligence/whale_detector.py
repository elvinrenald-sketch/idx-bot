"""
intelligence/whale_detector.py — Cross-reference engine for detecting whale/insider entry
Combines: disclosure + news + price anomaly + insider data → unified whale signal
This is the brain that connects the dots and generates the "someone big is entering" alert.
"""
import logging
from datetime import datetime
from typing import List, Dict, Optional

import pytz

from config import TIMEZONE, WATCHLIST_TICKERS

logger = logging.getLogger("idx_bot.whale")
WIB = pytz.timezone(TIMEZONE)


class WhaleDetector:
    """
    Cross-references multiple data sources to detect whale/big-player activity.
    
    Signal strength is scored 0-100:
    - 80-100: 🔴 CONFIRMED whale activity (multiple sources confirm)
    - 60-79:  🟠 STRONG signal (2+ corroborating sources)
    - 40-59:  🟡 MODERATE signal (single source but high quality)
    - 20-39:  🔵 EARLY signal (rumor or weak indicator)
    """

    def __init__(self, engine=None):
        self.engine = engine  # GeminiClient for AI analysis

    def detect(
        self,
        insider_activities: List[Dict] = None,
        news_articles: List[Dict] = None,
        anomalies: List[Dict] = None,
        disclosures: List[Dict] = None,
    ) -> List[Dict]:
        """
        Run full whale detection across all sources.
        Returns list of whale signals, sorted by strength.
        """
        insider_activities = insider_activities or []
        news_articles = news_articles or []
        anomalies = anomalies or []
        disclosures = disclosures or []

        whale_signals = []

        # Build ticker-centric view of all data
        ticker_data = self._build_ticker_map(
            insider_activities, news_articles, anomalies, disclosures
        )

        for ticker, data in ticker_data.items():
            signal = self._analyze_ticker(ticker, data)
            if signal and signal.get("total_score", 0) >= 20:
                whale_signals.append(signal)

        # Also check for cross-ticker patterns (sector rotation, etc.)
        sector_signals = self._detect_sector_rotation(ticker_data)
        whale_signals.extend(sector_signals)

        # Sort by score
        whale_signals.sort(key=lambda x: x.get("total_score", 0), reverse=True)

        logger.info(
            "Whale detection: %d signals (%d tickers analyzed)",
            len(whale_signals), len(ticker_data),
        )

        return whale_signals

    def _build_ticker_map(
        self,
        insiders: List[Dict],
        news: List[Dict],
        anomalies: List[Dict],
        disclosures: List[Dict],
    ) -> Dict[str, Dict]:
        """Group all data by ticker for cross-referencing."""
        ticker_map = {}

        # Insider activities
        for act in insiders:
            ticker = act.get("ticker", "").upper()
            if not ticker:
                continue
            if ticker not in ticker_map:
                ticker_map[ticker] = {"insiders": [], "news": [], "anomalies": [], "disclosures": []}
            ticker_map[ticker]["insiders"].append(act)

        # News articles
        for article in news:
            tickers = article.get("tickers", [])
            for ticker in tickers:
                ticker = ticker.upper()
                if ticker not in ticker_map:
                    ticker_map[ticker] = {"insiders": [], "news": [], "anomalies": [], "disclosures": []}
                ticker_map[ticker]["news"].append(article)

        # Price anomalies
        for anomaly in anomalies:
            ticker = anomaly.get("ticker", "").upper()
            if not ticker:
                continue
            if ticker not in ticker_map:
                ticker_map[ticker] = {"insiders": [], "news": [], "anomalies": [], "disclosures": []}
            ticker_map[ticker]["anomalies"].append(anomaly)

        # Disclosures
        for disc in disclosures:
            ticker = disc.get("emiten", "").upper()
            if not ticker:
                continue
            if ticker not in ticker_map:
                ticker_map[ticker] = {"insiders": [], "news": [], "anomalies": [], "disclosures": []}
            ticker_map[ticker]["disclosures"].append(disc)

        return ticker_map

    def _analyze_ticker(self, ticker: str, data: Dict) -> Optional[Dict]:
        """Analyze a single ticker for whale activity patterns."""
        insiders = data.get("insiders", [])
        news = data.get("news", [])
        anomalies = data.get("anomalies", [])
        disclosures = data.get("disclosures", [])

        if not any([insiders, news, anomalies, disclosures]):
            return None

        # Score each source
        insider_score = self._score_insiders(insiders)
        news_score = self._score_news(news)
        anomaly_score = self._score_anomalies(anomalies)
        disclosure_score = self._score_disclosures(disclosures)

        # Cross-reference bonus: multiple sources = much more credible
        sources_count = sum(1 for s in [insider_score, news_score, anomaly_score, disclosure_score] if s > 0)
        cross_ref_bonus = 0
        if sources_count >= 3:
            cross_ref_bonus = 25  # 3+ sources = very strong
        elif sources_count >= 2:
            cross_ref_bonus = 15  # 2 sources = strong

        # Watchlist bonus
        watchlist_bonus = 5 if ticker in WATCHLIST_TICKERS else 0

        total_score = min(
            insider_score + news_score + anomaly_score + disclosure_score + cross_ref_bonus + watchlist_bonus,
            100,
        )

        if total_score < 20:
            return None

        # Determine signal level
        if total_score >= 80:
            level = "🔴 CONFIRMED"
            tier = "CRITICAL"
        elif total_score >= 60:
            level = "🟠 STRONG"
            tier = "HIGH"
        elif total_score >= 40:
            level = "🟡 MODERATE"
            tier = "MEDIUM"
        else:
            level = "🔵 EARLY"
            tier = "LOW"

        # Determine activity type
        activity_type = self._determine_activity_type(insiders, news, disclosures)

        # Build evidence list
        evidence = []
        if insiders:
            for ins in insiders[:3]:
                evidence.append(f"📋 {ins.get('type_label', '')}: {ins.get('title', '')[:80]}")
        if news:
            for n in news[:3]:
                if n.get("is_critical"):
                    evidence.append(f"📰 {n.get('source', '')}: {n.get('title', '')[:80]}")
        if anomalies:
            for a in anomalies[:2]:
                evidence.append(f"📈 {a.get('type', '')}: {a.get('description', '')[:80]}")
        if disclosures:
            for d in disclosures[:2]:
                evidence.append(f"📄 Disclosure: {d.get('title', '')[:80]}")

        # Generate AI summary if engine available
        ai_summary = None
        if self.engine and total_score >= 40:
            ai_summary = self._generate_ai_summary(ticker, data, total_score)

        return {
            "ticker": ticker,
            "total_score": total_score,
            "level": level,
            "tier": tier,
            "activity_type": activity_type,
            "score_breakdown": {
                "insider": insider_score,
                "news": news_score,
                "anomaly": anomaly_score,
                "disclosure": disclosure_score,
                "cross_ref": cross_ref_bonus,
                "watchlist": watchlist_bonus,
            },
            "sources_count": sources_count,
            "evidence": evidence,
            "ai_summary": ai_summary,
            "is_watchlist": ticker in WATCHLIST_TICKERS,
            "detected_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
        }

    def _score_insiders(self, insiders: List[Dict]) -> int:
        """Score insider activities. Max 30."""
        if not insiders:
            return 0

        score = 0
        for ins in insiders:
            weight = ins.get("weight", 2)
            score += weight * 5  # Each insider activity = 10-25 points

            # Extra points for specific types
            itype = ins.get("insider_type", "")
            if itype in ("substantial_shareholder", "new_controller", "tender_offer"):
                score += 10

        return min(score, 30)

    def _score_news(self, articles: List[Dict]) -> int:
        """Score news articles. Max 25."""
        if not articles:
            return 0

        score = 0
        for article in articles:
            if article.get("is_critical"):
                score += 10
            elif article.get("urgency", 0) >= 5:
                score += 5
            else:
                score += 2

        return min(score, 25)

    def _score_anomalies(self, anomalies: List[Dict]) -> int:
        """Score price/volume anomalies. Max 20."""
        if not anomalies:
            return 0

        score = 0
        for anomaly in anomalies:
            atype = anomaly.get("type", "")
            if "VOLUME_PRICE_SPIKE" in atype:
                score += 15
            elif "VOLUME_SPIKE" in atype:
                score += 10
            elif "PRICE_SPIKE" in atype:
                score += 5

            # No disclosure = more suspicious
            if not anomaly.get("has_disclosure", True):
                score += 5

        return min(score, 20)

    def _score_disclosures(self, disclosures: List[Dict]) -> int:
        """Score formal disclosures. Max 25."""
        if not disclosures:
            return 0

        score = 0
        for disc in disclosures:
            signal_score = disc.get("signal_score", 0)
            score += min(signal_score, 15)

            # High AI urgency bonus
            if disc.get("gemini_urgency", 0) >= 7:
                score += 5

        return min(score, 25)

    def _determine_activity_type(
        self, insiders: List[Dict], news: List[Dict], disclosures: List[Dict]
    ) -> str:
        """Determine the most likely activity type."""
        all_text = ""
        for ins in insiders:
            all_text += f" {ins.get('title', '')} {ins.get('insider_type', '')}"
        for n in news:
            all_text += f" {n.get('title', '')}"
        for d in disclosures:
            all_text += f" {d.get('title', '')}"

        all_text = all_text.lower()

        if any(kw in all_text for kw in ["akuisisi", "acquisition", "pengambilalihan"]):
            return "🏢 AKUISISI"
        if any(kw in all_text for kw in ["backdoor", "reverse takeover", "rto"]):
            return "🚪 BACKDOOR LISTING"
        if any(kw in all_text for kw in ["tender offer", "penawaran tender"]):
            return "🎯 TENDER OFFER"
        if any(kw in all_text for kw in ["pengendali baru", "change of control"]):
            return "👑 CHANGE OF CONTROL"
        if any(kw in all_text for kw in ["merger", "penggabungan"]):
            return "🔀 MERGER"
        if any(kw in all_text for kw in ["rights issue", "hmetd", "private placement"]):
            return "📈 CAPITAL INJECTION"
        if any(kw in all_text for kw in ["suntik", "injeksi", "investasi strategis"]):
            return "💰 STRATEGIC INVESTMENT"

        return "🐋 WHALE ENTRY"

    def _detect_sector_rotation(self, ticker_data: Dict) -> List[Dict]:
        """Detect sector-wide whale movement (e.g., money flowing into energy sector)."""
        # Group by sector (simple heuristic based on known tickers)
        sectors = {
            "Energy": ["BUMI", "ADRO", "PTBA", "MEDC", "ESSA", "PGAS"],
            "Mining": ["MDKA", "ANTM", "INCO"],
            "Tech": ["GOTO", "BUKA", "EMTK", "DCII"],
            "Property": ["BSDE", "CTRA", "SMRA"],
            "Banking": ["BBCA", "BBRI", "BMRI", "BBNI"],
            "Conglomerate": ["BRPT", "DSSA"],
        }

        sector_signals = []
        for sector, tickers in sectors.items():
            active_count = sum(1 for t in tickers if t in ticker_data)
            if active_count >= 2:
                # Multiple tickers in same sector showing activity
                sector_signals.append({
                    "ticker": f"SEKTOR:{sector.upper()}",
                    "total_score": active_count * 15,
                    "level": "🟡 MODERATE" if active_count < 3 else "🟠 STRONG",
                    "tier": "MEDIUM" if active_count < 3 else "HIGH",
                    "activity_type": "🔄 SECTOR ROTATION",
                    "score_breakdown": {"sector_activity": active_count},
                    "sources_count": active_count,
                    "evidence": [
                        f"📊 {active_count} saham di sektor {sector} menunjukkan aktivitas whale"
                    ],
                    "ai_summary": None,
                    "is_watchlist": True,
                    "detected_at": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
                })

        return sector_signals

    def _generate_ai_summary(self, ticker: str, data: Dict, score: int) -> Optional[str]:
        """Generate AI summary of whale activity."""
        if not self.engine:
            return None

        insiders = data.get("insiders", [])
        news = data.get("news", [])

        insider_text = "\n".join([
            f"- {ins.get('type_label', '')}: {ins.get('title', '')[:100]}"
            for ins in insiders[:5]
        ]) or "Tidak ada data insider."

        news_text = "\n".join([
            f"- [{n.get('source', '')}] {n.get('title', '')[:100]}"
            for n in news[:5]
        ]) or "Tidak ada berita terkait."

        prompt = f"""Kamu adalah analis pasar modal Indonesia yang sangat berpengalaman.
Analisis aktivitas whale/insider berikut dan berikan ringkasan 2-3 kalimat dalam BAHASA INDONESIA.

Saham: {ticker}
Skor Deteksi: {score}/100

Data Insider:
{insider_text}

Berita Terkait:
{news_text}

Berikan analisis singkat: Apa yang MUNGKIN terjadi? Siapa yang kemungkinan terlibat?
Apakah ini sinyal BELI atau JUAL? Seberapa besar dampaknya?
Jawab langsung tanpa format JSON — hanya teks narasi 2-3 kalimat."""

        try:
            return self.engine.gemini.analyze_text(prompt, temperature=0.3)
        except Exception as e:
            logger.debug("AI summary failed: %s", e)
            return None


def format_whale_alert(signals: List[Dict]) -> str:
    """Format whale signals into a premium Telegram alert."""
    if not signals:
        return ""

    lines = [
        "🐋 <b>WHALE INTELLIGENCE ALERT</b>",
        f"🕐 <i>{datetime.now(WIB).strftime('%H:%M WIB — %d %b %Y')}</i>",
        f"<i>{len(signals)} sinyal whale terdeteksi</i>",
        "",
    ]

    for i, sig in enumerate(signals[:8], 1):
        ticker = sig.get("ticker", "—")
        level = sig.get("level", "")
        score = sig.get("total_score", 0)
        activity = sig.get("activity_type", "")
        evidence = sig.get("evidence", [])
        ai_summary = sig.get("ai_summary", "")
        wl = "⭐ " if sig.get("is_watchlist") else ""
        sources = sig.get("sources_count", 0)

        # Score breakdown
        breakdown = sig.get("score_breakdown", {})
        bd_parts = []
        for k, v in breakdown.items():
            if v > 0:
                bd_parts.append(f"{k}:{v}")
        bd_str = " | ".join(bd_parts)

        lines.append("─" * 32)
        lines.append(f"{wl}{level} <b>[{ticker}]</b>")
        lines.append(f"   💪 Kekuatan: <b>{score}/100</b> ({sources} sumber)")
        lines.append(f"   🏷 Tipe: {activity}")
        lines.append(f"   📊 Detail: <code>{bd_str}</code>")

        # Evidence
        if evidence:
            lines.append("   📋 <b>Bukti:</b>")
            for ev in evidence[:3]:
                lines.append(f"      • {ev}")

        # AI Summary
        if ai_summary:
            lines.append(f"\n   🤖 <b>Analisis AI:</b>")
            lines.append(f"   {ai_summary[:300]}")

        lines.append("")

    lines.append("⚠️ <i>Ini bukan rekomendasi investasi. Selalu lakukan riset mandiri (DYOR).</i>")
    return "\n".join(lines)
