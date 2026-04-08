"""
bot/handlers.py — Command handlers untuk Telegram bot
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from data.ihsg import fetch_ihsg
from data.disclosure import fetch_disclosures, get_new_disclosures
from signals.detector import detect_signals
from signals.formatter import (
    fmt_ihsg,
    fmt_disclosures,
    fmt_signal_alert,
    fmt_welcome,
    fmt_help,
    fmt_error,
)

logger = logging.getLogger("idx_bot.handlers")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /start — sapa user dan simpan chat_id."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Simpan chat_id ke bot_data supaya scheduler bisa pakai
    if "chat_ids" not in context.bot_data:
        context.bot_data["chat_ids"] = set()
    context.bot_data["chat_ids"].add(chat_id)

    logger.info("User %s (%d) menjalankan /start", user.first_name, chat_id)

    await update.message.reply_text(
        fmt_welcome(user.first_name),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /help."""
    await update.message.reply_text(
        fmt_help(),
        parse_mode=ParseMode.HTML,
    )


async def cmd_ihsg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /ihsg — fetch dan tampilkan data IHSG terkini."""
    await update.message.reply_text("⏳ Mengambil data IHSG…")

    data = fetch_ihsg()
    msg = fmt_ihsg(data)

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_disclosure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /disclosure — tampilkan 10 keterbukaan informasi terbaru."""
    await update.message.reply_text("⏳ Mengambil keterbukaan informasi IDX…")

    disclosures = fetch_disclosures(page_size=20)
    msg = fmt_disclosures(disclosures, max_items=10)

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler /signals — jalankan deteksi sinyal dan tampilkan hasilnya."""
    await update.message.reply_text("⏳ Menjalankan deteksi sinyal…")

    disclosures = fetch_disclosures(page_size=50)

    if not disclosures:
        await update.message.reply_text(
            fmt_error("Gagal mengambil data keterbukaan dari IDX. Coba beberapa saat lagi."),
            parse_mode=ParseMode.HTML,
        )
        return

    signals = detect_signals(disclosures)
    msg = fmt_signal_alert(signals)

    await update.message.reply_text(
        msg,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
