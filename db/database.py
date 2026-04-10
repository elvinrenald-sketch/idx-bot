"""
db/database.py — SQLite persistence layer for IDX Signal Bot v2.0
Handles: disclosures, news, price history, anomalies, alerts, bot state.
Survives Railway restarts — no more lost data.
"""
import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

from config import DB_PATH

logger = logging.getLogger("idx_bot.db")


class Database:
    """Thread-safe SQLite manager with connection pooling."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def _conn(self):
        """Context manager for safe connection handling."""
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")  # Better concurrent access
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_db(self):
        """Create all tables if they don't exist."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS seen_disclosures (
                    id TEXT PRIMARY KEY,
                    ticker TEXT,
                    title TEXT,
                    date TEXT,
                    category TEXT,
                    url TEXT,
                    signal_score INTEGER DEFAULT 0,
                    signal_level TEXT,
                    signal_types TEXT,
                    gemini_analysis TEXT,
                    gemini_risk_type TEXT,
                    gemini_urgency INTEGER DEFAULT 0,
                    gemini_confidence REAL DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS seen_news (
                    url TEXT PRIMARY KEY,
                    source TEXT,
                    title TEXT,
                    snippet TEXT,
                    mentioned_tickers TEXT,
                    relevance_score REAL DEFAULT 0,
                    gemini_analysis TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume INTEGER,
                    change_pct REAL,
                    avg_volume_20d REAL,
                    UNIQUE(ticker, date)
                );

                CREATE TABLE IF NOT EXISTS anomaly_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    anomaly_type TEXT,
                    magnitude REAL,
                    details TEXT,
                    has_disclosure INTEGER DEFAULT 0,
                    related_disclosure_id TEXT,
                    gemini_analysis TEXT,
                    alerted INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS alert_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at TEXT NOT NULL,
                    tier TEXT,
                    dedup_key TEXT UNIQUE,
                    message_preview TEXT,
                    source_type TEXT,
                    source_id TEXT
                );

                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_disc_ticker ON seen_disclosures(ticker);
                CREATE INDEX IF NOT EXISTS idx_disc_date ON seen_disclosures(date);
                CREATE INDEX IF NOT EXISTS idx_price_ticker ON price_history(ticker, date);
                CREATE INDEX IF NOT EXISTS idx_anomaly_ticker ON anomaly_log(ticker, detected_at);
                CREATE INDEX IF NOT EXISTS idx_alert_dedup ON alert_log(dedup_key);
            """)
        logger.info("Database initialized: %s", self.db_path)

    # ── Disclosure Management ─────────────────────────────────────

    def is_disclosure_seen(self, disc_id: str) -> bool:
        """Check if a disclosure has already been processed."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_disclosures WHERE id = ?", (disc_id,)
            ).fetchone()
            return row is not None

    def save_disclosure(self, disc: dict) -> bool:
        """Save a disclosure. Returns True if new (not seen before)."""
        disc_id = disc.get("id", "")
        if not disc_id:
            disc_id = f"{disc.get('emiten', '')}_{disc.get('title', '')}"

        if self.is_disclosure_seen(disc_id):
            return False

        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seen_disclosures
                   (id, ticker, title, date, category, url)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    disc_id,
                    disc.get("emiten", ""),
                    disc.get("title", ""),
                    disc.get("date", ""),
                    disc.get("category", ""),
                    disc.get("url", ""),
                ),
            )
        return True

    def update_disclosure_analysis(self, disc_id: str, analysis: dict):
        """Update a disclosure with Gemini AI analysis results."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE seen_disclosures SET
                   signal_score = ?,
                   signal_level = ?,
                   signal_types = ?,
                   gemini_analysis = ?,
                   gemini_risk_type = ?,
                   gemini_urgency = ?,
                   gemini_confidence = ?
                   WHERE id = ?""",
                (
                    analysis.get("signal_score", 0),
                    analysis.get("signal_level", ""),
                    json.dumps(analysis.get("signal_types", []), ensure_ascii=False),
                    json.dumps(analysis.get("gemini_analysis", {}), ensure_ascii=False),
                    analysis.get("gemini_risk_type", ""),
                    analysis.get("gemini_urgency", 0),
                    analysis.get("gemini_confidence", 0),
                    disc_id,
                ),
            )

    def has_recent_disclosure(self, ticker: str, hours: int = 48) -> bool:
        """Check if there's a recent disclosure for a given ticker."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_disclosures WHERE ticker = ? AND created_at > ?",
                (ticker.upper(), cutoff),
            ).fetchone()
            return row is not None

    def get_recent_disclosures(self, hours: int = 24) -> List[dict]:
        """Get disclosures from the last N hours."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM seen_disclosures
                   WHERE created_at > ?
                   ORDER BY created_at DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── News Management ───────────────────────────────────────────

    def is_news_seen(self, url: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_news WHERE url = ?", (url,)
            ).fetchone()
            return row is not None

    def save_news(self, article: dict) -> bool:
        """Save a news article. Returns True if new."""
        url = article.get("url", "")
        if not url or self.is_news_seen(url):
            return False

        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO seen_news
                   (url, source, title, snippet, mentioned_tickers)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    url,
                    article.get("source", ""),
                    article.get("title", ""),
                    article.get("snippet", ""),
                    json.dumps(article.get("tickers", []), ensure_ascii=False),
                ),
            )
        return True

    def update_news_analysis(self, url: str, analysis: dict):
        """Update news article with AI analysis."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE seen_news SET
                   relevance_score = ?,
                   gemini_analysis = ?
                   WHERE url = ?""",
                (
                    analysis.get("relevance_score", 0),
                    json.dumps(analysis, ensure_ascii=False),
                    url,
                ),
            )

    # ── Price History ─────────────────────────────────────────────

    def save_price(self, ticker: str, data: dict):
        """Save daily OHLCV data for a ticker."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO price_history
                   (ticker, date, open, high, low, close, volume, change_pct, avg_volume_20d)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker.upper(),
                    data.get("date", datetime.utcnow().strftime("%Y-%m-%d")),
                    data.get("open", 0),
                    data.get("high", 0),
                    data.get("low", 0),
                    data.get("close", 0),
                    data.get("volume", 0),
                    data.get("change_pct", 0),
                    data.get("avg_volume_20d", 0),
                ),
            )

    def get_price_history(self, ticker: str, days: int = 20) -> List[dict]:
        """Get recent price history for a ticker."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM price_history
                   WHERE ticker = ?
                   ORDER BY date DESC LIMIT ?""",
                (ticker.upper(), days),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_avg_volume(self, ticker: str, days: int = 20) -> float:
        """Calculate average volume over N days."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT AVG(volume) as avg_vol FROM price_history
                   WHERE ticker = ? AND volume > 0
                   ORDER BY date DESC LIMIT ?""",
                (ticker.upper(), days),
            ).fetchone()
            return float(row["avg_vol"]) if row and row["avg_vol"] else 0

    # ── Anomaly Log ───────────────────────────────────────────────

    def save_anomaly(self, anomaly: dict):
        """Log a detected anomaly."""
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO anomaly_log
                   (ticker, detected_at, anomaly_type, magnitude, details,
                    has_disclosure, related_disclosure_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    anomaly.get("ticker", ""),
                    datetime.utcnow().isoformat(),
                    anomaly.get("type", ""),
                    anomaly.get("magnitude", 0),
                    json.dumps(anomaly, ensure_ascii=False),
                    1 if anomaly.get("has_disclosure") else 0,
                    anomaly.get("related_disclosure_id", ""),
                ),
            )

    def get_recent_anomalies(self, hours: int = 24) -> List[dict]:
        """Get anomalies from the last N hours."""
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM anomaly_log
                   WHERE detected_at > ?
                   ORDER BY magnitude DESC""",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Alert Log ─────────────────────────────────────────────────

    def is_alert_sent(self, dedup_key: str) -> bool:
        """Check if an alert with this dedup key was already sent."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM alert_log WHERE dedup_key = ?", (dedup_key,)
            ).fetchone()
            return row is not None

    def save_alert(self, tier: str, dedup_key: str, preview: str,
                   source_type: str = "", source_id: str = ""):
        """Log a sent alert."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO alert_log
                   (sent_at, tier, dedup_key, message_preview, source_type, source_id)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.utcnow().isoformat(),
                    tier,
                    dedup_key,
                    preview[:200],
                    source_type,
                    source_id,
                ),
            )

    # ── Bot State ─────────────────────────────────────────────────

    def get_state(self, key: str, default: str = "") -> str:
        """Get a bot state value."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM bot_state WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_state(self, key: str, value: str):
        """Set a bot state value."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO bot_state (key, value, updated_at)
                   VALUES (?, ?, datetime('now'))""",
                (key, value),
            )

    def get_chat_id(self) -> Optional[int]:
        """Get persisted chat_id."""
        val = self.get_state("chat_id")
        return int(val) if val else None

    def set_chat_id(self, chat_id: int):
        """Persist chat_id across restarts."""
        self.set_state("chat_id", str(chat_id))

    # ── Statistics ────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get bot statistics dashboard."""
        with self._conn() as conn:
            disc_total = conn.execute("SELECT COUNT(*) FROM seen_disclosures").fetchone()[0]
            disc_today = conn.execute(
                "SELECT COUNT(*) FROM seen_disclosures WHERE created_at > date('now')"
            ).fetchone()[0]
            news_total = conn.execute("SELECT COUNT(*) FROM seen_news").fetchone()[0]
            anomalies_today = conn.execute(
                "SELECT COUNT(*) FROM anomaly_log WHERE detected_at > date('now')"
            ).fetchone()[0]
            alerts_today = conn.execute(
                "SELECT COUNT(*) FROM alert_log WHERE sent_at > date('now')"
            ).fetchone()[0]
            last_scan = self.get_state("last_scan_time", "Never")

            return {
                "disc_total": disc_total,
                "disc_today": disc_today,
                "news_total": news_total,
                "anomalies_today": anomalies_today,
                "alerts_today": alerts_today,
                "last_scan": last_scan,
                "db_path": self.db_path,
            }

    def cleanup_old_data(self, days: int = 90):
        """Remove data older than N days to keep DB small."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM seen_news WHERE created_at < ?", (cutoff,))
            conn.execute("DELETE FROM anomaly_log WHERE detected_at < ?", (cutoff,))
            conn.execute("DELETE FROM alert_log WHERE sent_at < ?", (cutoff,))
            conn.execute("DELETE FROM price_history WHERE date < ?", (cutoff[:10],))
        logger.info("Cleaned up data older than %d days", days)
