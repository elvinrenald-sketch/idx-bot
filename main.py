"""
main.py — Entry point IDX Signal Bot
"""
import logging
import sys

from telegram.ext import Application, CommandHandler

from config import TELEGRAM_BOT_TOKEN, logger
from bot.handlers import (
    cmd_start,
    cmd_help,
    cmd_ihsg,
    cmd_disclosure,
    cmd_signals,
)
from bot.scheduler import register_jobs


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.critical(
            "TELEGRAM_BOT_TOKEN tidak ditemukan! "
            "Tambahkan ke .env atau environment variable Railway."
        )
        sys.exit(1)

    logger.info("Memulai IDX Signal Bot…")

    # ── Build Application ─────────────────────────────────────────
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # ── Register command handlers ─────────────────────────────────
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("ihsg",        cmd_ihsg))
    app.add_handler(CommandHandler("disclosure",  cmd_disclosure))
    app.add_handler(CommandHandler("signals",     cmd_signals))

    # ── Register scheduled jobs ───────────────────────────────────
    register_jobs(app)

    # ── Start polling ─────────────────────────────────────────────
    logger.info("Bot aktif — menunggu pesan (polling)…")
    app.run_polling(
        poll_interval=2,
        timeout=30,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
