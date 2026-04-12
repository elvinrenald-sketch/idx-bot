"""
main.py — Entry point for IDX Intelligence Bot v2.0
Initializes database, Gemini AI, and Telegram bot with full intelligence stack.
"""
import sys
import logging
from datetime import datetime

import pytz
from telegram.ext import Application, CommandHandler

from config import TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, TIMEZONE, logger
from db.database import Database
from intelligence.gemini import GeminiClient
from intelligence.analyzer import IntelligenceEngine
from bot.handlers import (
    cmd_start,
    cmd_help,
    cmd_ihsg,
    cmd_disclosure,
    cmd_signals,
    cmd_news,
    cmd_watchlist,
    cmd_swing,
    cmd_status,
)
from bot.scheduler import register_jobs
from signals.formatter import fmt_bot_restart

WIB = pytz.timezone(TIMEZONE)


async def post_init(app: Application) -> None:
    """
    Called after bot initialization.
    - Load persisted chat_id
    - Send restart notification
    """
    db = app.bot_data.get("db")
    if db:
        # Restore chat_ids from database
        saved_chat_id = db.get_chat_id()
        if saved_chat_id:
            if "chat_ids" not in app.bot_data:
                app.bot_data["chat_ids"] = set()
            app.bot_data["chat_ids"].add(saved_chat_id)
            logger.info("Restored chat_id from database: %d", saved_chat_id)

            # Send restart notification
            try:
                await app.bot.send_message(
                    chat_id=saved_chat_id,
                    text=fmt_bot_restart(),
                    parse_mode="HTML",
                )
                logger.info("Restart notification sent to %d", saved_chat_id)
            except Exception as e:
                logger.warning("Could not send restart notification: %s", e)


def main() -> None:
    # ── Validate config ───────────────────────────────────────────
    if not TELEGRAM_BOT_TOKEN:
        logger.critical(
            "TELEGRAM_BOT_TOKEN not found! "
            "Add it to .env or Railway environment variables."
        )
        sys.exit(1)

    now_wib = datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S WIB")
    logger.info("=" * 60)
    logger.info("IDX Intelligence Bot v2.0 — Starting")
    logger.info("Time: %s", now_wib)
    logger.info("=" * 60)

    # ── Initialize Database ───────────────────────────────────────
    logger.info("[INIT] Database…")
    db = Database()
    db.set_state("last_boot", now_wib)

    # ── Initialize Gemini AI ──────────────────────────────────────
    logger.info("[INIT] Gemini AI…")
    gemini = GeminiClient(api_key=GEMINI_API_KEY)
    engine = IntelligenceEngine(gemini)

    if gemini.is_configured:
        logger.info("✅ Gemini AI configured (model: %s)", gemini.model)
    else:
        logger.warning(
            "⚠️ Gemini API key not found — AI analysis disabled. "
            "Set GEMINI_API_KEY in environment."
        )

    # ── Build Telegram Application ────────────────────────────────
    logger.info("[INIT] Telegram bot…")
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Store shared instances in bot_data
    app.bot_data["db"] = db
    app.bot_data["engine"] = engine
    app.bot_data["gemini"] = gemini

    # ── Register command handlers ─────────────────────────────────
    commands = [
        ("start", cmd_start),
        ("help", cmd_help),
        ("ihsg", cmd_ihsg),
        ("disclosure", cmd_disclosure),
        ("signals", cmd_signals),
        ("swing", cmd_swing),
        ("news", cmd_news),
        ("anomaly", cmd_anomaly),
        ("watchlist", cmd_watchlist),
        ("status", cmd_status),
    ]

    for name, handler in commands:
        app.add_handler(CommandHandler(name, handler))
    logger.info("✅ %d command handlers registered", len(commands))

    # ── Register scheduled jobs ───────────────────────────────────
    register_jobs(app)
    logger.info("✅ Scheduled jobs registered")

    # ── Start polling ─────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Bot ACTIVE — waiting for messages (polling)…")
    logger.info("=" * 60)

    app.run_polling(
        poll_interval=2,
        timeout=30,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
