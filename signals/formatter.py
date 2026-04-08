"""
signals/formatter.py — Format data menjadi pesan Telegram siap kirim (HTML)
"""
from typing import List, Dict, Optional


def fmt_ihsg(data: dict) -> str:
    """Format data IHSG menjadi pesan ringkas Telegram."""
    if data.get("error"):
        return f"❌ <b>IHSG</b>\n{data['error']}"

    pct = data["change_pct"]
    abs_ = data["change_abs"]
    arrow = "📈" if pct >= 0 else "📉"
    sign = "+" if pct >= 0 else ""

    week_pct = data.get("week_change_pct", 0)
    week_arrow = "↗️" if week_pct >= 0 else "↘️"
    week_sign = "+" if week_pct >= 0 else ""

    lines = [
        f"{arrow} <b>IHSG — Jakarta Composite Index</b>",
        f"🕐 <i>{data['timestamp']}</i>",
        "",
        f"💹 <b>Harga Terakhir:</b> {data['close']:,.2f}",
        f"📊 <b>Perubahan:</b> {sign}{abs_:,.2f} ({sign}{pct:.2f}%)",
        "",
        f"🔺 <b>Tertinggi:</b> {data['high']:,.2f}",
        f"🔻 <b>Terendah:</b>  {data['low']:,.2f}",
        f"🏁 <b>Pembukaan:</b> {data['open']:,.2f}",
        f"📦 <b>Volume:</b>    {data['volume']:,}",
    ]

    if data.get("high_52w") and data.get("low_52w"):
        lines += [
            "",
            f"📅 <b>52W High:</b> {data['high_52w']:,.2f}",
            f"📅 <b>52W Low:</b>  {data['low_52w']:,.2f}",
        ]

    lines += [
        "",
        f"{week_arrow} <b>Tren 5 Hari:</b> {week_sign}{week_pct:.2f}%",
    ]

    return "\n".join(lines)


def fmt_disclosures(disclosures: List[Dict], max_items: int = 10) -> str:
    """Format daftar keterbukaan informasi menjadi pesan Telegram."""
    if not disclosures:
        return "📭 Tidak ada keterbukaan informasi terbaru."

    lines = [
        "📋 <b>Keterbukaan Informasi IDX Terbaru</b>",
        f"<i>Menampilkan {min(len(disclosures), max_items)} dari {len(disclosures)}</i>",
        "",
    ]

    for i, item in enumerate(disclosures[:max_items], 1):
        emiten = item.get("emiten", "—")
        title  = item.get("title", "—") or "—"
        date   = item.get("date", "") or ""
        url    = item.get("url", "")

        # Potong judul panjang
        if len(title) > 80:
            title = title[:77] + "..."

        link_part = f' → <a href="{url}">📄 Buka</a>' if url else ""
        date_part = f" <i>({date[:10]})</i>" if date else ""

        lines.append(
            f"{i}. <b>[{emiten}]</b>{date_part}\n"
            f"   {title}{link_part}"
        )

    return "\n".join(lines)


def fmt_signal_alert(signals: List[Dict]) -> str:
    """Format sinyal akuisisi/backdoor listing menjadi alert Telegram."""
    if not signals:
        return "✅ Tidak ada sinyal akuisisi / backdoor listing terdeteksi saat ini."

    lines = [
        "🚨 <b>SINYAL TERDETEKSI — IDX Signal Bot</b>",
        f"<i>Ditemukan {len(signals)} sinyal mencurigakan</i>",
        "",
    ]

    for i, sig in enumerate(signals, 1):
        emiten  = sig.get("emiten", "—")
        title   = sig.get("title", "—") or "—"
        date    = sig.get("date", "") or ""
        url     = sig.get("url", "")
        level   = sig.get("signal_level", "🟡 MENENGAH")
        types   = sig.get("signal_types", [])
        wl      = "⭐ " if sig.get("is_watchlist") else ""

        if len(title) > 90:
            title = title[:87] + "..."

        date_str = f" ({date[:10]})" if date else ""
        type_str = " · ".join(types) if types else "—"
        link_str = f'\n   📄 <a href="{url}">Lihat Dokumen</a>' if url else ""

        lines += [
            f"{'─'*30}",
            f"{wl}<b>#{i} [{emiten}]</b>{date_str}",
            f"   📌 {title}",
            f"   ⚡ Level: <b>{level}</b>",
            f"   🏷 Tipe: {type_str}" + link_str,
            "",
        ]

    lines.append(
        "⚠️ <i>Ini bukan rekomendasi investasi. Lakukan riset mandiri.</i>"
    )
    return "\n".join(lines)


def fmt_no_signal() -> str:
    return "✅ <b>Tidak ada sinyal</b> akuisisi / backdoor listing terdeteksi saat ini."


def fmt_error(msg: str) -> str:
    return f"❌ <b>Terjadi kesalahan:</b>\n<code>{msg}</code>"


def fmt_welcome(first_name: str) -> str:
    return (
        f"👋 Halo, <b>{first_name}</b>!\n\n"
        "Selamat datang di <b>IDX Signal Bot</b> 🇮🇩\n\n"
        "Bot ini memantau:\n"
        "📊 Data harian IHSG\n"
        "📋 Keterbukaan informasi IDX\n"
        "🚨 Sinyal akuisisi & backdoor listing\n\n"
        "<b>Sektor prioritas:</b> ⚡ Energi | 🏗 Properti | ⛏ Komoditas & Batu Bara\n\n"
        "Ketik /help untuk melihat semua perintah."
    )


def fmt_help() -> str:
    return (
        "📖 <b>Daftar Perintah IDX Signal Bot</b>\n\n"
        "/start — Mulai & lihat informasi bot\n"
        "/ihsg — Lihat data IHSG terkini\n"
        "/disclosure — Lihat 10 keterbukaan informasi terbaru\n"
        "/signals — Cek sinyal akuisisi & backdoor listing\n"
        "/help — Tampilkan pesan ini\n\n"
        "🔔 Bot juga mengirim:\n"
        "• Ringkasan IHSG otomatis pukul 16:30 WIB\n"
        "• Alert sinyal setiap 30 menit jam bursa (09:00–16:30 WIB)\n\n"
        "⚠️ <i>Bukan rekomendasi investasi.</i>"
    )
