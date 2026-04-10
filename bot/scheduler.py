"""
bot/scheduler.py — Robust scheduled jobs for IDX Intelligence Bot v2.0
Persistent chat_id, auto-recovery, market-hours awareness, full scan pipeline.
"""
import logging
from datetime import datetime, time as dtime

import pytz
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from data.ihsg import fetch_ihsg
from data.disclosure import fetch_disclosures, filter_new_disclosures
from data.news import scan_all_news, filter_new_news
from data.price_tracker import update_price_history
from intelligence.anomaly import AnomalyDetector
from signals.detector import detect_signals
from signals.formatter import (
    fmt_ihsg, fmt_signal_alert, fmt_anomaly_report,
    fmt_market_open, fmt_bot_restart,
)
from config import (
    TIMEZONE,
    DAILY_SUMMARY_HOUR,
    DAILY_SUMMARY_MINUTE,
    DAILY_DIGEST_HOUR,
    DAILY_DIGEST_MINUTE,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    SCAN_INTERVAL_MINUTES,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
    PRICE_UPDATE_HOUR,
    PRICE_UPDATE_MINUTE,
    WATCHLIST_TICKERS,
    ALERT_HIGH_THRESHOLD,
)

logger = logging.getLogger("idx_bot.scheduler")
WIB = pytz.timezone(TIMEZONE)

MAX_MSG_LEN = 4096


def _get_chat_ids(context: ContextTypes.DEFAULT_TYPE) -> set:
    """Get chat IDs from bot_data + database fallback."""
    chat_ids = context.bot_data.get("chat_ids", set())

    # Fallback: load from database
    if not chat_ids:
        db = context.bot_data.get("db")
        if db:
            saved_id = db.get_chat_id()
            if saved_id:
                chat_ids = {saved_id}
                context.bot_data["chat_ids"] = chat_ids

    return chat_ids


async def _broadcast(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Send a message to all registered chats, splitting if needed."""
    chat_ids = _get_chat_ids(context)
    if not chat_ids:
        logger.info("No registered chats — skipping broadcast.")
        return

    chunks = [text] if len(text) <= MAX_MSG_LEN else _split_msg(text)

    for chat_id in chat_ids:
        for chunk in chunks:
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                logger.error("Failed to send to %d: %s", chat_id, e)


def _split_msg(text: str) -> list:
    """Split long text into max-length chunks."""
    chunks = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, MAX_MSG_LEN)
        if split_at < MAX_MSG_LEN // 2:
            split_at = MAX_MSG_LEN
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    return chunks


# ══════════════════════════════════════════════════════════════════
# SCHEDULED JOBS
# ══════════════════════════════════════════════════════════════════

async def job_market_open(context: ContextTypes.DEFAULT_TYPE) -> None:
    """09:00 WIB — Market open notification."""
    now_wib = datetime.now(WIB)
    if now_wib.weekday() >= 5:
        return

    logger.info("Job: market_open at %s", now_wib.strftime("%H:%M WIB"))

    ihsg_data = fetch_ihsg()
    msg = fmt_market_open(ihsg_data)
    await _broadcast(context, msg)


async def job_daily_ihsg(context: ContextTypes.DEFAULT_TYPE) -> None:
    """16:30 WIB — Daily IHSG summary."""
    now_wib = datetime.now(WIB)
    if now_wib.weekday() >= 5:
        return

    logger.info("Job: daily_ihsg at %s", now_wib.strftime("%H:%M WIB"))

    data = fetch_ihsg()
    msg = f"📅 <b>Ringkasan Harian IHSG</b>\n\n{fmt_ihsg(data)}"
    await _broadcast(context, msg)


async def job_full_scan(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Every 30 min (09:30–16:00 WIB, Mon–Fri)
    Full scan: disclosures + news + anomalies → signals → alerts
    """
    now_wib = datetime.now(WIB)

    # Skip weekend
    if now_wib.weekday() >= 5:
        return

    # Skip outside market hours
    market_open = dtime(MARKET_OPEN_HOUR, 0)
    market_close = dtime(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    current_time = now_wib.time().replace(second=0, microsecond=0)

    if not (market_open <= current_time <= market_close):
        return

    logger.info("═" * 50)
    logger.info("Job: full_scan at %s WIB", now_wib.strftime("%H:%M"))

    db = context.bot_data.get("db")
    engine = context.bot_data.get("engine")

    # ── Step 1: Fetch disclosures ──────────────────────────────
    logger.info("[1/5] Fetching disclosures…")
    all_disclosures = fetch_disclosures(page_size=30)
    new_disclosures = []
    if all_disclosures and db:
        new_disclosures = filter_new_disclosures(all_disclosures, db)
    elif all_disclosures:
        new_disclosures = all_disclosures

    logger.info("  → %d total, %d new disclosures", len(all_disclosures), len(new_disclosures))

    # ── Step 2: Fetch news ─────────────────────────────────────
    logger.info("[2/5] Scanning news…")
    new_news = []
    try:
        all_news = scan_all_news()
        if all_news and db:
            new_news = filter_new_news(all_news, db)
        elif all_news:
            new_news = all_news
        logger.info("  → %d total, %d new articles", len(all_news), len(new_news))
    except Exception as e:
        logger.warning("  → News scan failed: %s", e)

    # ── Step 3: Fetch stock prices ─────────────────────────────
    logger.info("[3/5] Fetching stock prices…")
    price_data = {}
    try:
        price_data = update_price_history(WATCHLIST_TICKERS, db) if db else {}
        logger.info("  → Got price data for %d tickers", len(price_data))
    except Exception as e:
        logger.warning("  → Price fetch failed: %s", e)

    # ── Step 4: Detect anomalies ───────────────────────────────
    logger.info("[4/5] Detecting anomalies…")
    anomalies = []
    if price_data and db:
        try:
            detector = AnomalyDetector(db)
            anomalies = detector.scan(price_data)
            logger.info("  → %d anomalies detected", len(anomalies))
        except Exception as e:
            logger.warning("  → Anomaly detection failed: %s", e)

    # ── Step 5: Run signal detection ───────────────────────────
    logger.info("[5/5] Running signal detection…")
    signals = []
    if new_disclosures:
        try:
            signals = detect_signals(
                disclosures=new_disclosures,
                news_articles=new_news,
                anomalies=anomalies,
                engine=engine,
                db=db,
            )
            logger.info("  → %d signals detected", len(signals))
        except Exception as e:
            logger.warning("  → Signal detection failed: %s", e)

    # ── Send alerts ────────────────────────────────────────────

    # Critical + High → immediate alert
    urgent_signals = [s for s in signals if s.get("signal_tier") in ("CRITICAL", "HIGH")]
    if urgent_signals:
        alert_msg = (
            f"🔔 <b>Alert Otomatis — {now_wib.strftime('%H:%M WIB %d %b %Y')}</b>\n\n"
            + fmt_signal_alert(urgent_signals)
        )

        # Dedup: don't send same alert twice
        if db:
            unsent = []
            for sig in urgent_signals:
                dedup_key = f"{sig.get('id', '')}_{sig.get('emiten', '')}_{sig.get('date', '')}"
                if not db.is_alert_sent(dedup_key):
                    unsent.append(sig)
                    db.save_alert(
                        tier=sig.get("signal_tier", "HIGH"),
                        dedup_key=dedup_key,
                        preview=sig.get("title", "")[:200],
                        source_type="disclosure",
                        source_id=sig.get("id", ""),
                    )

            if unsent:
                alert_msg = (
                    f"🔔 <b>Alert Otomatis — {now_wib.strftime('%H:%M WIB %d %b %Y')}</b>\n\n"
                    + fmt_signal_alert(unsent)
                )
                await _broadcast(context, alert_msg)
        else:
            await _broadcast(context, alert_msg)

    # Anomaly alerts (high suspicion only)
    suspicious_anomalies = [a for a in anomalies if a.get("suspicion") in ("HIGH", "VERY_HIGH")]
    if suspicious_anomalies:
        anomaly_msg = (
            f"⚠️ <b>Anomali Mencurigakan — {now_wib.strftime('%H:%M WIB')}</b>\n\n"
            + fmt_anomaly_report(suspicious_anomalies)
        )

        # Dedup anomaly alerts
        if db:
            unsent_anomalies = []
            for a in suspicious_anomalies:
                dedup_key = f"anomaly_{a.get('ticker', '')}_{now_wib.strftime('%Y-%m-%d')}"
                if not db.is_alert_sent(dedup_key):
                    unsent_anomalies.append(a)
                    db.save_alert(
                        tier="HIGH",
                        dedup_key=dedup_key,
                        preview=a.get("description", "")[:200],
                        source_type="anomaly",
                    )

            if unsent_anomalies:
                anomaly_msg = (
                    f"⚠️ <b>Anomali Mencurigakan — {now_wib.strftime('%H:%M WIB')}</b>\n\n"
                    + fmt_anomaly_report(unsent_anomalies)
                )
                await _broadcast(context, anomaly_msg)
        else:
            await _broadcast(context, anomaly_msg)

    # Update last scan time
    if db:
        db.set_state("last_scan_time", now_wib.strftime("%Y-%m-%d %H:%M WIB"))

    logger.info(
        "Scan complete: %d disclosures, %d news, %d anomalies, %d signals",
        len(new_disclosures), len(new_news), len(anomalies), len(signals),
    )
    logger.info("═" * 50)


async def job_daily_digest(context: ContextTypes.DEFAULT_TYPE) -> None:
    """16:35 WIB — Daily digest with all INFO signals + anomaly summary."""
    now_wib = datetime.now(WIB)
    if now_wib.weekday() >= 5:
        return

    logger.info("Job: daily_digest at %s", now_wib.strftime("%H:%M WIB"))

    db = context.bot_data.get("db")
    engine = context.bot_data.get("engine")

    # Gather day's data
    day_data = {"ihsg": fetch_ihsg()}

    if db:
        day_data["disclosures"] = db.get_recent_disclosures(hours=10)
        day_data["anomalies"] = db.get_recent_anomalies(hours=10)

    # Generate AI digest
    digest = None
    if engine:
        try:
            digest = engine.generate_daily_digest(day_data)
        except Exception as e:
            logger.warning("Daily digest generation failed: %s", e)

    if digest:
        msg = f"📋 <b>Ringkasan Harian — {now_wib.strftime('%d %b %Y')}</b>\n\n{digest}"
    else:
        msg = f"📋 <b>Ringkasan Harian — {now_wib.strftime('%d %b %Y')}</b>\n\nTidak ada data signifikan hari ini."

    await _broadcast(context, msg)


async def job_update_prices(context: ContextTypes.DEFAULT_TYPE) -> None:
    """17:00 WIB — Update 20-day price history for watchlist tickers."""
    now_wib = datetime.now(WIB)
    if now_wib.weekday() >= 5:
        return

    logger.info("Job: update_prices at %s", now_wib.strftime("%H:%M WIB"))

    db = context.bot_data.get("db")
    if db:
        try:
            update_price_history(WATCHLIST_TICKERS, db)
            logger.info("Price history updated for %d tickers", len(WATCHLIST_TICKERS))
        except Exception as e:
            logger.warning("Price update failed: %s", e)


async def job_cleanup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Weekly cleanup of old data."""
    db = context.bot_data.get("db")
    if db:
        db.cleanup_old_data(days=90)
        logger.info("Database cleanup completed")


# ══════════════════════════════════════════════════════════════════
# REGISTRATION
# ══════════════════════════════════════════════════════════════════

def register_jobs(app) -> None:
    """Register all scheduled jobs."""
    jq = app.job_queue

    # ── 1. Market open: 09:00 WIB ──────────────────────────────
    jq.run_daily(
        job_market_open,
        time=dtime(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, tzinfo=WIB),
        days=(0, 1, 2, 3, 4),
        name="market_open",
    )
    logger.info("Job market_open: %02d:%02d WIB (Mon-Fri)", MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE)

    # ── 2. Full scan: every 30 min ─────────────────────────────
    jq.run_repeating(
        job_full_scan,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=60,  # Start 60s after boot
        name="full_scan",
    )
    logger.info("Job full_scan: every %d min (active during market hours)", SCAN_INTERVAL_MINUTES)

    # ── 3. Daily IHSG summary: 16:30 WIB ──────────────────────
    jq.run_daily(
        job_daily_ihsg,
        time=dtime(hour=DAILY_SUMMARY_HOUR, minute=DAILY_SUMMARY_MINUTE, tzinfo=WIB),
        days=(0, 1, 2, 3, 4),
        name="daily_ihsg",
    )
    logger.info("Job daily_ihsg: %02d:%02d WIB (Mon-Fri)", DAILY_SUMMARY_HOUR, DAILY_SUMMARY_MINUTE)

    # ── 4. Daily digest: 16:35 WIB ────────────────────────────
    jq.run_daily(
        job_daily_digest,
        time=dtime(hour=DAILY_DIGEST_HOUR, minute=DAILY_DIGEST_MINUTE, tzinfo=WIB),
        days=(0, 1, 2, 3, 4),
        name="daily_digest",
    )
    logger.info("Job daily_digest: %02d:%02d WIB (Mon-Fri)", DAILY_DIGEST_HOUR, DAILY_DIGEST_MINUTE)

    # ── 5. Price history update: 17:00 WIB ─────────────────────
    jq.run_daily(
        job_update_prices,
        time=dtime(hour=PRICE_UPDATE_HOUR, minute=PRICE_UPDATE_MINUTE, tzinfo=WIB),
        days=(0, 1, 2, 3, 4),
        name="update_prices",
    )
    logger.info("Job update_prices: %02d:%02d WIB (Mon-Fri)", PRICE_UPDATE_HOUR, PRICE_UPDATE_MINUTE)

    # ── 6. Weekly cleanup: Sunday 03:00 WIB ────────────────────
    jq.run_daily(
        job_cleanup,
        time=dtime(hour=3, minute=0, tzinfo=WIB),
        days=(6,),  # Sunday only
        name="weekly_cleanup",
    )
    logger.info("Job weekly_cleanup: Sunday 03:00 WIB")
