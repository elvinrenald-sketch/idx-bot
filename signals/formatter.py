"""
signals/formatter.py — Tiered Telegram message formatting (HTML)
Supports: CRITICAL/HIGH/INFO alerts, IHSG summary, daily digest, anomaly reports.
"""
import json
from typing import List, Dict, Optional
from datetime import datetime


# ══════════════════════════════════════════════════════════════════
# IHSG FORMATTING
# ══════════════════════════════════════════════════════════════════

def fmt_ihsg(data: dict) -> str:
    """Format IHSG data with source indicator."""
    if data.get("error"):
        return f"❌ <b>IHSG</b>\n{data['error']}"

    pct = data.get("change_pct", 0)
    abs_ = data.get("change_abs", 0)
    arrow = "📈" if pct >= 0 else "📉"
    sign = "+" if pct >= 0 else ""
    source = data.get("source", "Unknown")

    week_pct = data.get("week_change_pct", 0)
    week_arrow = "↗️" if week_pct >= 0 else "↘️"
    week_sign = "+" if week_pct >= 0 else ""

    lines = [
        f"{arrow} <b>IHSG — Jakarta Composite Index</b>",
        f"🕐 <i>{data.get('timestamp', '')}</i>",
        f"📡 <i>Sumber: {source}</i>",
        "",
        f"💹 <b>Harga Terakhir:</b> {data['close']:,.2f}",
        f"📊 <b>Perubahan:</b> {sign}{abs_:,.2f} ({sign}{pct:.2f}%)",
        "",
        f"🔺 <b>Tertinggi:</b>  {data.get('high', 0):,.2f}",
        f"🔻 <b>Terendah:</b>   {data.get('low', 0):,.2f}",
        f"🏁 <b>Pembukaan:</b>  {data.get('open', 0):,.2f}",
        f"📦 <b>Volume:</b>     {data.get('volume', 0):,}",
    ]

    if data.get("high_52w") and data.get("low_52w"):
        lines += [
            "",
            f"📅 <b>52W High:</b> {data['high_52w']:,.2f}",
            f"📅 <b>52W Low:</b>  {data['low_52w']:,.2f}",
        ]

    if week_pct != 0:
        lines += [
            "",
            f"{week_arrow} <b>Tren 5 Hari:</b> {week_sign}{week_pct:.2f}%",
        ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# DISCLOSURE FORMATTING
# ══════════════════════════════════════════════════════════════════

def fmt_disclosures(disclosures: List[Dict], max_items: int = 10) -> str:
    """Format disclosure list."""
    if not disclosures:
        return "📭 Tidak ada keterbukaan informasi terbaru."

    lines = [
        "📋 <b>Keterbukaan Informasi IDX Terbaru</b>",
        f"<i>Menampilkan {min(len(disclosures), max_items)} dari {len(disclosures)}</i>",
        "",
    ]

    for i, item in enumerate(disclosures[:max_items], 1):
        emiten = item.get("emiten", "—")
        title = item.get("title", "—") or "—"
        date = item.get("date", "") or ""
        url = item.get("url", "")

        if len(title) > 80:
            title = title[:77] + "..."

        link_part = f' → <a href="{url}">📄 Buka</a>' if url else ""
        date_part = f" <i>({date[:10]})</i>" if date else ""

        lines.append(
            f"{i}. <b>[{emiten}]</b>{date_part}\n"
            f"   {title}{link_part}"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# SIGNAL ALERT FORMATTING (Tiered)
# ══════════════════════════════════════════════════════════════════

def fmt_signal_alert(signals: List[Dict]) -> str:
    """Format signal alerts with tiered urgency and AI analysis."""
    if not signals:
        return "✅ Tidak ada sinyal akuisisi / backdoor listing terdeteksi saat ini."

    critical = [s for s in signals if s.get("signal_tier") == "CRITICAL"]
    high = [s for s in signals if s.get("signal_tier") == "HIGH"]
    info = [s for s in signals if s.get("signal_tier") == "INFO"]

    lines = [
        "🚨 <b>SINYAL TERDETEKSI — IDX Intelligence Bot</b>",
        f"<i>Ditemukan {len(signals)} sinyal ({len(critical)} critical, {len(high)} high, {len(info)} info)</i>",
        "",
    ]

    # Critical signals first
    for sig in critical:
        lines.append(_fmt_single_signal(sig, "🔴"))
        lines.append("")

    # Then high
    for sig in high:
        lines.append(_fmt_single_signal(sig, "🟡"))
        lines.append("")

    # Then info (abbreviated)
    if info:
        lines.append("─" * 30)
        lines.append(f"<b>ℹ️ {len(info)} sinyal INFO lainnya:</b>")
        for sig in info[:5]:
            emiten = sig.get("emiten", "—")
            title = sig.get("title", "—")[:50]
            score = sig.get("signal_score", 0)
            lines.append(f"  • <b>[{emiten}]</b> {title} (skor: {score}/40)")

    lines.append("")
    lines.append("⚠️ <i>Ini bukan rekomendasi investasi. Lakukan riset mandiri.</i>")
    return "\n".join(lines)


def _fmt_single_signal(sig: dict, tier_emoji: str) -> str:
    """Format a single signal entry with full detail."""
    emiten = sig.get("emiten", "—")
    title = sig.get("title", "—") or "—"
    date = sig.get("date", "") or ""
    url = sig.get("url", "")
    score = sig.get("signal_score", 0)
    level = sig.get("signal_level", "")
    types = sig.get("signal_types", [])
    wl = "⭐ " if sig.get("is_watchlist") else ""
    breakdown = sig.get("score_breakdown", {})

    if len(title) > 100:
        title = title[:97] + "..."

    date_str = f" ({date[:10]})" if date else ""
    type_str = " · ".join(types) if types else "—"
    link_str = f'\n   📄 <a href="{url}">Lihat Dokumen</a>' if url else ""

    # Score breakdown
    bd_parts = []
    if breakdown.get("keyword"):
        bd_parts.append(f"KW:{breakdown['keyword']}")
    if breakdown.get("ai"):
        bd_parts.append(f"AI:{breakdown['ai']}")
    if breakdown.get("anomaly"):
        bd_parts.append(f"AN:{breakdown['anomaly']}")
    if breakdown.get("news"):
        bd_parts.append(f"NW:{breakdown['news']}")
    if breakdown.get("watchlist"):
        bd_parts.append(f"WL:{breakdown['watchlist']}")
    if breakdown.get("pdf"):
        bd_parts.append(f"PDF:{breakdown['pdf']}")
    bd_str = " | ".join(bd_parts)

    parts = [
        "─" * 30,
        f"{wl}{tier_emoji} <b>[{emiten}]</b>{date_str}",
        f"   📌 {title}",
        f"   ⚡ Level: <b>{level}</b> — Skor: <b>{score}/40</b>",
        f"   🏷 Tipe: {type_str}",
        f"   📊 Breakdown: <code>{bd_str}</code>",
    ]

    # Add AI analysis summary if available
    ai = sig.get("gemini_analysis")
    if ai and isinstance(ai, dict):
        summary = ai.get("summary", "")
        if summary:
            parts.append(f"\n   🤖 <b>Analisis AI:</b>")
            parts.append(f"   {summary}")

        red_flags = ai.get("red_flags", [])
        if red_flags:
            parts.append(f"   🚩 Red flags: {', '.join(red_flags[:3])}")

        recommendation = ai.get("recommendation", "")
        if recommendation:
            parts.append(f"   💡 {recommendation}")

    parts.append(link_str)
    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════
# ANOMALY FORMATTING
# ══════════════════════════════════════════════════════════════════

def fmt_anomaly_report(anomalies: List[dict]) -> str:
    """Format anomaly detection report."""
    if not anomalies:
        return "✅ Tidak ada anomali harga/volume terdeteksi saat ini."

    lines = [
        "📊 <b>ANOMALI TERDETEKSI — IDX Intelligence Bot</b>",
        f"<i>Ditemukan {len(anomalies)} anomali</i>",
        "",
    ]

    for i, a in enumerate(anomalies[:15], 1):
        ticker = a.get("ticker", "—")
        atype = a.get("type", a.get("anomaly_type", "—"))
        magnitude = a.get("magnitude", 0)
        desc = a.get("description", "")
        has_disc = a.get("has_disclosure", True)
        suspicion = a.get("suspicion", "LOW")

        # Type emoji
        if "VOLUME_PRICE" in atype:
            emoji = "🔴"
        elif "VOLUME" in atype:
            emoji = "🟡"
        elif "PRICE" in atype:
            emoji = "📈" if a.get("direction") == "UP" else "📉"
        else:
            emoji = "⚪"

        # Suspicion indicator
        sus_str = ""
        if suspicion == "VERY_HIGH":
            sus_str = " 🚨 SANGAT MENCURIGAKAN"
        elif suspicion == "HIGH":
            sus_str = " ⚠️ Mencurigakan"

        disc_str = "✅ Ada disclosure" if has_disc else "❌ Tanpa disclosure"

        lines.append(
            f"{i}. {emoji} <b>{ticker}</b> — {atype} ({magnitude:.1f}x){sus_str}\n"
            f"   {desc}\n"
            f"   📋 {disc_str}"
        )
        lines.append("")

    lines.append("⚠️ <i>Ini bukan rekomendasi investasi.</i>")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# NEWS FORMATTING
# ══════════════════════════════════════════════════════════════════

def fmt_news_report(articles: List[dict], max_items: int = 10) -> str:
    """Format news articles report."""
    if not articles:
        return "📰 Tidak ada berita aksi korporasi terbaru."

    lines = [
        "📰 <b>Berita Aksi Korporasi Terbaru</b>",
        f"<i>{min(len(articles), max_items)} artikel dari berbagai sumber</i>",
        "",
    ]

    for i, art in enumerate(articles[:max_items], 1):
        source = art.get("source", "—")
        title = art.get("title", "—")[:80]
        url = art.get("url", "")
        tickers = art.get("tickers", [])
        date = art.get("date", "")

        ticker_str = f" [{', '.join(tickers)}]" if tickers else ""
        link_str = f' → <a href="{url}">Baca</a>' if url else ""
        date_str = f" ({date})" if date else ""

        lines.append(
            f"{i}. <b>{source}</b>{date_str}\n"
            f"   {title}{ticker_str}{link_str}"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# STATUS & UTILITY MESSAGES
# ══════════════════════════════════════════════════════════════════

def fmt_status(stats: dict, gemini_stats: dict = None) -> str:
    """Format bot status dashboard."""
    lines = [
        "🤖 <b>IDX Intelligence Bot — Status</b>",
        "",
        f"📊 <b>Data:</b>",
        f"   • Disclosure dilihat: {stats.get('disc_total', 0)} total ({stats.get('disc_today', 0)} hari ini)",
        f"   • Berita tersimpan: {stats.get('news_total', 0)}",
        f"   • Anomali hari ini: {stats.get('anomalies_today', 0)}",
        f"   • Alert terkirim: {stats.get('alerts_today', 0)} hari ini",
        "",
        f"🕐 Scan terakhir: {stats.get('last_scan', 'Belum ada')}",
        f"💾 Database: {stats.get('db_path', 'N/A')}",
    ]

    if gemini_stats:
        lines += [
            "",
            f"🧠 <b>Gemini AI:</b>",
            f"   • Status: {'✅ Aktif' if gemini_stats.get('configured') else '❌ Tidak dikonfigurasi'}",
            f"   • Model: {gemini_stats.get('model', 'N/A')}",
            f"   • Total calls: {gemini_stats.get('total_calls', 0)}",
            f"   • Errors: {gemini_stats.get('errors', 0)}",
            f"   • Calls (menit ini): {gemini_stats.get('calls_last_minute', 0)}/15",
        ]

    return "\n".join(lines)


def fmt_welcome(first_name: str) -> str:
    """Welcome message with feature list."""
    return (
        f"👋 Halo, <b>{first_name}</b>!\n\n"
        "Selamat datang di <b>IDX Intelligence Bot</b> 🇮🇩🧠\n\n"
        "Bot cerdas yang memantau pasar modal Indonesia:\n"
        "📊 Data IHSG real-time (multi-sumber, anti-gagal)\n"
        "📋 Keterbukaan informasi IDX\n"
        "🚨 Deteksi akuisisi & backdoor listing dengan <b>AI</b>\n"
        "📰 Monitor berita CNBC/Kontan/Bisnis.com\n"
        "📈 Deteksi anomali harga & volume\n"
        "📄 Analisis dokumen PDF otomatis\n\n"
        "<b>Sektor prioritas:</b>\n"
        "⚡ Energi | 🏗 Properti | ⛏ Komoditas | 💻 Teknologi\n\n"
        "Ketik /help untuk melihat semua perintah."
    )


def fmt_help() -> str:
    """Help message with all commands."""
    return (
        "📖 <b>Daftar Perintah IDX Intelligence Bot</b>\n\n"
        "<b>📊 Data Pasar:</b>\n"
        "/ihsg — Data IHSG terkini (multi-sumber)\n"
        "/disclosure — 10 keterbukaan informasi terbaru\n\n"
        "<b>🚨 Intelligence:</b>\n"
        "/signals — Deteksi sinyal dengan AI (40-point scoring)\n"
        "/news — Berita aksi korporasi terbaru\n"
        "/anomaly — Anomali harga & volume saham\n\n"
        "<b>⚙️ Pengaturan:</b>\n"
        "/watchlist — Lihat daftar saham prioritas\n"
        "/status — Status bot & kesehatan sistem\n"
        "/help — Tampilkan pesan ini\n\n"
        "🔔 <b>Alert Otomatis:</b>\n"
        "• 🔴 CRITICAL — Alert segera (backdoor listing + anomali)\n"
        "• 🟡 HIGH — Alert per siklus scan (akuisisi terdeteksi)\n"
        "• 🟢 INFO — Ringkasan harian\n"
        "• 📊 DAILY — IHSG summary pukul 16:30 WIB\n\n"
        "⚙️ Scan otomatis setiap 30 menit (09:00–16:30 WIB)\n\n"
        "⚠️ <i>Bukan rekomendasi investasi.</i>"
    )


def fmt_error(msg: str) -> str:
    return f"❌ <b>Terjadi kesalahan:</b>\n<code>{msg}</code>"


def fmt_market_open(ihsg_data: dict) -> str:
    """Market open notification."""
    if ihsg_data and not ihsg_data.get("error"):
        return (
            f"🔔 <b>Pasar Dibuka!</b>\n\n"
            f"📊 IHSG terakhir: {ihsg_data['close']:,.2f}\n"
            f"📈 Bot monitoring aktif.\n"
            f"Scan disclosure & anomali dimulai."
        )
    return (
        "🔔 <b>Pasar Dibuka!</b>\n\n"
        "📈 Bot monitoring aktif.\n"
        "Scan disclosure & anomali dimulai."
    )


def fmt_bot_restart() -> str:
    """Bot restart notification."""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"🔄 <b>Bot Restarted</b>\n"
        f"<i>{now}</i>\n\n"
        "Semua sistem aktif. Melanjutkan monitoring."
    )


def fmt_watchlist(tickers: List[str]) -> str:
    """Format watchlist display."""
    if not tickers:
        return "📋 Watchlist kosong."

    lines = [
        "📋 <b>Watchlist Saham Prioritas</b>",
        "",
    ]

    for i, ticker in enumerate(tickers, 1):
        lines.append(f"  {i}. <code>{ticker}</code>")

    lines.append(f"\n<i>Total: {len(tickers)} saham</i>")
    lines.append("Saham di watchlist mendapat skor bonus +2 pada deteksi sinyal.")
    return "\n".join(lines)
