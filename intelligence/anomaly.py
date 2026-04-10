"""
intelligence/anomaly.py — Stock price & volume anomaly detection engine
Detects unusual trading activity as early warning before disclosures are published.
"""
import logging
from typing import List, Dict
from statistics import mean

from config import VOLUME_SPIKE_RATIO, PRICE_SPIKE_PCT, ANOMALY_LOOKBACK_DAYS

logger = logging.getLogger("idx_bot.anomaly")


class AnomalyDetector:
    """
    Detects volume spikes and price anomalies in IDX stocks.
    Cross-references with disclosures to identify possible insider activity.
    """

    def __init__(self, db):
        self.db = db

    def scan(self, price_data: Dict[str, dict]) -> List[dict]:
        """
        Scan price data for anomalies.

        Args:
            price_data: Dict of {ticker: {close, volume, change_pct, ...}}

        Returns:
            List of detected anomalies, sorted by magnitude (most severe first).
        """
        anomalies = []

        for ticker, data in price_data.items():
            ticker_anomalies = self._check_ticker(ticker, data)
            anomalies.extend(ticker_anomalies)

        # Sort by magnitude (most extreme first)
        anomalies.sort(key=lambda x: x.get("magnitude", 0), reverse=True)

        if anomalies:
            logger.info(
                "Detected %d anomalies across %d tickers",
                len(anomalies), len(price_data),
            )

        return anomalies

    def _check_ticker(self, ticker: str, data: dict) -> List[dict]:
        """Check a single ticker for anomalies."""
        anomalies = []

        volume = data.get("volume", 0)
        change_pct = data.get("change_pct", 0)

        # Get historical data for comparison
        history = self.db.get_price_history(ticker, days=ANOMALY_LOOKBACK_DAYS)

        # Calculate average volume
        avg_volume = 0
        if history:
            hist_volumes = [h["volume"] for h in history if h.get("volume", 0) > 0]
            if hist_volumes:
                avg_volume = mean(hist_volumes)
        elif data.get("avg_volume_20d"):
            avg_volume = data["avg_volume_20d"]
        elif data.get("avg_volume_10d"):
            avg_volume = data["avg_volume_10d"]
        elif data.get("avg_volume_3m"):
            avg_volume = data["avg_volume_3m"]

        # ── Check Volume Spike ──────────────────────────────────
        volume_spike = False
        volume_ratio = 0

        if avg_volume > 0 and volume > 0:
            volume_ratio = volume / avg_volume
            if volume_ratio >= VOLUME_SPIKE_RATIO:
                volume_spike = True
                anomalies.append({
                    "ticker": ticker,
                    "type": "VOLUME_SPIKE",
                    "magnitude": round(volume_ratio, 1),
                    "current_volume": volume,
                    "avg_volume": int(avg_volume),
                    "change_pct": change_pct,
                    "description": (
                        f"Volume {ticker} melonjak {volume_ratio:.1f}x "
                        f"dari rata-rata 20 hari ({volume:,} vs avg {int(avg_volume):,})"
                    ),
                })

        # ── Check Price Spike ───────────────────────────────────
        price_spike = False

        if abs(change_pct) >= PRICE_SPIKE_PCT:
            price_spike = True
            direction = "naik" if change_pct > 0 else "turun"
            anomalies.append({
                "ticker": ticker,
                "type": "PRICE_SPIKE",
                "magnitude": abs(change_pct),
                "change_pct": change_pct,
                "direction": "UP" if change_pct > 0 else "DOWN",
                "close": data.get("close", 0),
                "prev_close": data.get("prev_close", 0),
                "description": (
                    f"Harga {ticker} {direction} {abs(change_pct):.1f}% "
                    f"({data.get('prev_close', 0):,.0f} → {data.get('close', 0):,.0f})"
                ),
            })

        # ── Check Combined Anomaly (both volume + price) ────────
        if volume_spike and price_spike:
            # This is the most suspicious — remove separate entries and add combined
            anomalies = [a for a in anomalies if a["ticker"] != ticker]
            combined_magnitude = volume_ratio + abs(change_pct)
            direction = "naik" if change_pct > 0 else "turun"

            anomalies.append({
                "ticker": ticker,
                "type": "VOLUME_PRICE_SPIKE",
                "magnitude": round(combined_magnitude, 1),
                "volume_ratio": round(volume_ratio, 1),
                "current_volume": volume,
                "avg_volume": int(avg_volume),
                "change_pct": change_pct,
                "direction": "UP" if change_pct > 0 else "DOWN",
                "close": data.get("close", 0),
                "prev_close": data.get("prev_close", 0),
                "suspicion": "VERY_HIGH",
                "description": (
                    f"🚨 {ticker}: Volume {volume_ratio:.1f}x rata-rata "
                    f"DAN harga {direction} {abs(change_pct):.1f}%! "
                    f"Kemungkinan aktivitas insider."
                ),
            })

        # ── Cross-reference with disclosures ────────────────────
        for anomaly in anomalies:
            has_disc = self.db.has_recent_disclosure(ticker, hours=48)
            anomaly["has_disclosure"] = has_disc

            if not has_disc and anomaly.get("type") in ("VOLUME_SPIKE", "VOLUME_PRICE_SPIKE"):
                anomaly["suspicion"] = "HIGH"
                anomaly["description"] += (
                    " ⚠️ Tidak ada disclosure resmi — kemungkinan kebocoran informasi."
                )
            elif has_disc:
                anomaly["suspicion"] = anomaly.get("suspicion", "MEDIUM")

            # Save to database
            self.db.save_anomaly(anomaly)

        return anomalies

    def get_summary(self) -> Dict:
        """Get anomaly detection summary for the last 24 hours."""
        recent = self.db.get_recent_anomalies(hours=24)

        volume_spikes = [a for a in recent if "VOLUME" in (a.get("anomaly_type", ""))]
        price_spikes = [a for a in recent if "PRICE" in (a.get("anomaly_type", ""))]
        combined = [a for a in recent if a.get("anomaly_type") == "VOLUME_PRICE_SPIKE"]

        suspicious = [
            a for a in recent
            if not a.get("has_disclosure") and "VOLUME" in (a.get("anomaly_type", ""))
        ]

        return {
            "total": len(recent),
            "volume_spikes": len(volume_spikes),
            "price_spikes": len(price_spikes),
            "combined": len(combined),
            "suspicious_no_disclosure": len(suspicious),
            "anomalies": recent[:20],  # Top 20
        }
