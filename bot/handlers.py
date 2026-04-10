"""
bot/handlers.py — Telegram command handlers for IDX Intelligence Bot v2.0
Commands: /start, /help, /ihsg, /disclosure, /signals, /news, /anomaly, /watchlist, /status
"""
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from data.ihsg import fetch_ihsg
from data.disclosure import fetch_disclosures, filter_new_disclosures
from data.news import scan_all_news
from data.price_tracker import fetch_stock_data
from signals.detector import detect_signals
from signals.formatter import (
    fmt_ihsg,
    fmt_disclosures,
    fmt_signal_alert,
    fmt_anomaly_report,
    fmt_news_report,
    fmt_status,
    fmt_welcome,
    fmt_help,
    fmt_error,
    fmt_watchlist,
)
from config import WATCHLIST_TICKERS

logger = logging.getLogger("idx_bot.handlers")

# Max Telegram message length
MAX_MSG_LEN = 4096


async def _send_long(update_or_context, text: str, chat_id: int = None, **kwargs):
    """Send a potentially long message, splitting if needed."""
    if chat_id and hasattr(update_or_context, 'bot'):
        # Context-based send
        bot = update_or_context.bot
        for chunk in _split_message(text):
            await bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                **kwargs,
            )
    elif hasattr(update_or_context, 'message'):
        # Update-based reply
        for chunk in _split_message(text):
            await update_or_context.message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                **kwargs,
            )


def _split_message(text: str, max_len: int = MAX_MSG_LEN) -> list:
    """Split long message into chunks."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Find a good split point (newline or space)
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = text.rfind(" ", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    return chunks


# ══════════════════════════════════════════════════════════════════
# COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /start — register and welcome user."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Persist chat_id to both bot_data and database
    if "chat_ids" not in context.bot_data:
        context.bot_data["chat_ids"] = set()
    context.bot_data["chat_ids"].add(chat_id)

    # Save to database
    db = context.bot_data.get("db")
    if db:
        db.set_chat_id(chat_id)

    logger.info("User %s (%d) started bot", user.first_name, chat_id)

    await _send_long(update, fmt_welcome(user.first_name))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /help."""
    await _send_long(update, fmt_help())


async def cmd_ihsg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /ihsg — fetch IHSG data from multi-source."""
    await update.message.reply_text("⏳ Mengambil data IHSG (multi-sumber)…")

    data = fetch_ihsg()
    msg = fmt_ihsg(data)

    await _send_long(update, msg)


async def cmd_disclosure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /disclosure — latest disclosures."""
    await update.message.reply_text("⏳ Mengambil keterbukaan informasi IDX…")

    disclosures = fetch_disclosures(page_size=20)
    msg = fmt_disclosures(disclosures, max_items=10)

    await _send_long(update, msg)


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /signals — full AI-powered signal detection."""
    await update.message.reply_text(
        "⏳ Menjalankan deteksi sinyal AI…\n"
        "📊 Keyword + 🧠 Gemini AI + 📈 Anomali + 📰 Berita"
    )

    db = context.bot_data.get("db")
    engine = context.bot_data.get("engine")

    # 1. Fetch disclosures
    disclosures = fetch_disclosures(page_size=50)
    if not disclosures:
        await _send_long(
            update,
            fmt_error("Gagal mengambil data disclosure dari IDX. Coba beberapa saat lagi."),
        )
        return

    # 2. Fetch news
    news = []
    try:
        news = scan_all_news()
    except Exception as e:
        logger.warning("News scan failed in /signals: %s", e)

    # 3. Fetch anomalies
    anomalies = []
    try:
        price_data = fetch_stock_data(WATCHLIST_TICKERS[:20])
        if db:
            from intelligence.anomaly import AnomalyDetector
            detector = AnomalyDetector(db)
            anomalies = detector.scan(price_data)
    except Exception as e:
        logger.warning("Anomaly detection failed in /signals: %s", e)

    # 4. Run full detection
    signals = detect_signals(
        disclosures=disclosures,
        news_articles=news,
        anomalies=anomalies,
        engine=engine,
        db=db,
    )

    msg = fmt_signal_alert(signals)
    await _send_long(update, msg)


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /news — scan financial news."""
    await update.message.reply_text("⏳ Scanning berita CNBC/Kontan/Bisnis…")

    try:
        articles = scan_all_news()
        msg = fmt_news_report(articles, max_items=10)
    except Exception as e:
        logger.error("News scan failed: %s", e)
        msg = fmt_error(f"Gagal scan berita: {e}")

    await _send_long(update, msg)


async def cmd_anomaly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /anomaly — detect price/volume anomalies."""
    await update.message.reply_text("⏳ Scanning anomali harga & volume…")

    db = context.bot_data.get("db")

    try:
        price_data = fetch_stock_data(WATCHLIST_TICKERS)

        if db:
            from intelligence.anomaly import AnomalyDetector
            detector = AnomalyDetector(db)
            anomalies = detector.scan(price_data)
            msg = fmt_anomaly_report(anomalies)
        else:
            msg = fmt_error("Database belum siap. Coba lagi nanti.")

    except Exception as e:
        logger.error("Anomaly detection failed: %s", e)
        msg = fmt_error(f"Gagal deteksi anomali: {e}")

    await _send_long(update, msg)


async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /watchlist — show watchlist tickers."""
    msg = fmt_watchlist(WATCHLIST_TICKERS)
    await _send_long(update, msg)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /status — bot health dashboard."""
    db = context.bot_data.get("db")
    engine = context.bot_data.get("engine")

    stats = {}
    gemini_stats = None

    if db:
        stats = db.get_stats()

    if engine and hasattr(engine, 'gemini'):
        gemini_stats = engine.gemini.get_stats()

    msg = fmt_status(stats, gemini_stats)
    await _send_long(update, msg)
