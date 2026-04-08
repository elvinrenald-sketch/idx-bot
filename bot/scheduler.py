"""
bot/scheduler.py — Scheduled jobs: daily IHSG summary & disclosure scan
"""
import logging
from datetime import datetime, time as dtime

import pytz
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from data.ihsg import fetch_ihsg
from data.disclosure import fetch_disclosures, get_new_disclosures
from signals.detector import detect_signals
from signals.formatter import fmt_ihsg, fmt_signal_alert
from config import (
    TIMEZONE,
    DAILY_SUMMARY_HOUR,
    DAILY_SUMMARY_MINUTE,
    SCAN_INTERVAL_MINUTES,
    MARKET_OPEN_HOUR,
    MARKET_CLOSE_HOUR,
    MARKET_CLOSE_MINUTE,
)

logger = logging.getLogger("idx_bot.scheduler")
WIB = pytz.timezone(TIMEZONE)


def _get_registered_chats(context: ContextTypes.DEFAULT_TYPE) -> set:
    """Ambil set chat_id yang sudah /start."""
    return context.bot_data.get("chat_ids", set())


async def job_daily_ihsg(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Job harian: kirim ringkasan IHSG ke semua chat terdaftar.
    Dijadwalkan pukul 16:30 WIB setiap hari kerja.
    """
    chat_ids = _get_registered_chats(context)
    if not chat_ids:
        logger.info("Tidak ada chat terdaftar — skip daily IHSG job.")
        return

    logger.info("Menjalankan job_daily_ihsg untuk %d chat…", len(chat_ids))
    data = fetch_ihsg()
    msg = f"📅 <b>Ringkasan Harian IHSG</b>\n\n{fmt_ihsg(data)}"

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error("Gagal kirim daily IHSG ke %d: %s", chat_id, e)


async def job_scan_disclosures(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Job periodik: scan keterbukaan IDX, kirim alert sinyal jika ada yang baru.
    Berjalan setiap 30 menit selama jam bursa (09:00–16:30 WIB, Senin–Jumat).
    """
    now_wib = datetime.now(WIB)

    # Skip weekend
    if now_wib.weekday() >= 5:  # 5=Sabtu, 6=Minggu
        return

    # Skip di luar jam bursa
    market_open  = dtime(MARKET_OPEN_HOUR, 0)
    market_close = dtime(MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE)
    current_time = now_wib.time().replace(second=0, microsecond=0)

    if not (market_open <= current_time <= market_close):
        return

    chat_ids = _get_registered_chats(context)
    if not chat_ids:
        return

    logger.info("Menjalankan job_scan_disclosures pukul %s WIB…", now_wib.strftime("%H:%M"))

    disclosures = fetch_disclosures(page_size=30)
    if not disclosures:
        logger.warning("Tidak ada disclosure berhasil diambil.")
        return

    # Hanya proses disclosure yang baru (belum dikirim sebelumnya)
    new_disclosures = get_new_disclosures(disclosures)
    if not new_disclosures:
        logger.info("Tidak ada disclosure baru.")
        return

    logger.info("Ditemukan %d disclosure baru.", len(new_disclosures))

    signals = detect_signals(new_disclosures)
    if not signals:
        logger.info("Tidak ada sinyal terdeteksi dari disclosure baru.")
        return

    msg = (
        f"🔔 <b>Alert Otomatis — {now_wib.strftime('%H:%M WIB %d %b %Y')}</b>\n\n"
        + fmt_signal_alert(signals)
    )

    for chat_id in chat_ids:
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            logger.info("Alert sinyal terkirim ke chat %d.", chat_id)
        except Exception as e:
            logger.error("Gagal kirim alert ke %d: %s", chat_id, e)


def register_jobs(app) -> None:
    """
    Daftarkan semua scheduled jobs ke JobQueue Telegram.
    Dipanggil dari main.py setelah Application dibuat.
    """
    jq = app.job_queue

    # ── 1. Daily IHSG summary pukul 16:30 WIB ──────────────────────
    jq.run_daily(
        job_daily_ihsg,
        time=dtime(
            hour=DAILY_SUMMARY_HOUR,
            minute=DAILY_SUMMARY_MINUTE,
            tzinfo=WIB,
        ),
        days=(0, 1, 2, 3, 4),  # Senin–Jumat
        name="daily_ihsg",
    )
    logger.info(
        "Job daily_ihsg dijadwalkan pukul %02d:%02d WIB (Senin–Jumat).",
        DAILY_SUMMARY_HOUR,
        DAILY_SUMMARY_MINUTE,
    )

    # ── 2. Disclosure scan setiap 30 menit ─────────────────────────
    jq.run_repeating(
        job_scan_disclosures,
        interval=SCAN_INTERVAL_MINUTES * 60,
        first=60,  # Mulai 60 detik setelah bot aktif
        name="scan_disclosures",
    )
    logger.info(
        "Job scan_disclosures dijadwalkan setiap %d menit (aktif jam bursa).",
        SCAN_INTERVAL_MINUTES,
    )
