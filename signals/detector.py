"""
signals/detector.py — Deteksi sinyal akuisisi & backdoor listing dari keterbukaan IDX
"""
import logging
import re
from typing import List, Dict, Tuple

from config import (
    WATCHLIST_KEYWORDS,
    SIGNAL_HIGH_THRESHOLD,
    SIGNAL_MEDIUM_THRESHOLD,
)

logger = logging.getLogger("idx_bot.detector")

# ── Keyword definitions ────────────────────────────────────────────────────────
SIGNAL_KEYWORDS: Dict[str, Dict] = {
    "akuisisi": {
        "label": "🏢 Akuisisi",
        "weight": 3,
        "keywords": [
            "akuisisi", "acquisition", "pengambilalihan", "takeover",
            "pembelian saham", "share purchase", "pembelian kepemilikan",
            "beli saham", "pengambilalihan saham", "pengambilalihan kepemilikan",
        ],
    },
    "backdoor_listing": {
        "label": "🚪 Backdoor Listing",
        "weight": 4,
        "keywords": [
            "backdoor listing", "reverse takeover", "reverse merger",
            "rto", "injeksi aset", "injection of assets",
            "penerbitan saham baru kepada pihak tertentu",
            "perubahan kegiatan usaha utama", "change of core business",
            "change of main business",
        ],
    },
    "perubahan_kendali": {
        "label": "🔄 Perubahan Kendali",
        "weight": 3,
        "keywords": [
            "perubahan pengendalian", "change of control",
            "pengendali baru", "new controlling shareholder",
            "pemegang saham pengendali baru", "pergantian pengendali",
            "perubahan pemegang saham utama", "pemegang saham mayoritas baru",
        ],
    },
    "transaksi_material": {
        "label": "💰 Transaksi Material",
        "weight": 2,
        "keywords": [
            "transaksi material", "material transaction",
            "transaksi benturan kepentingan", "conflict of interest",
            "transaksi afiliasi", "affiliated transaction",
            "benturan kepentingan transaksi tertentu",
        ],
    },
    "penambahan_modal": {
        "label": "📈 Penambahan Modal",
        "weight": 2,
        "keywords": [
            "hmetd", "rights issue", "private placement",
            "penambahan modal tanpa hak memesan", "pmthmetd",
            "penambahan modal dengan hak memesan", "pmhmetd",
            "penerbitan saham baru", "capital increase",
            "obligasi konversi", "convertible bond",
            "saham baru tanpa hak",
        ],
    },
    "merger": {
        "label": "🔀 Merger / Penggabungan",
        "weight": 3,
        "keywords": [
            "merger", "penggabungan usaha", "peleburan usaha",
            "konsolidasi", "consolidation", "amalgamation",
            "penggabungan perusahaan",
        ],
    },
    "divestasi": {
        "label": "📤 Divestasi",
        "weight": 2,
        "keywords": [
            "divestasi", "divestiture", "penjualan aset", "asset sale",
            "pelepasan saham", "disposal of shares",
            "pengalihan kepemilikan", "penjualan kepemilikan",
        ],
    },
}


def _normalize(text: str) -> str:
    """Lowercase + strip tanda baca untuk matching."""
    return re.sub(r"[^\w\s]", " ", text.lower())


def _is_watchlist(text: str) -> bool:
    """Cek apakah teks mengandung kata kunci sektor prioritas."""
    norm = _normalize(text)
    return any(kw in norm for kw in WATCHLIST_KEYWORDS)


def score_disclosure(disclosure: Dict) -> Tuple[int, List[str]]:
    """
    Hitung skor sinyal untuk satu disclosure.
    Returns (total_score, list_of_matched_signal_labels).
    """
    combined_text = _normalize(
        f"{disclosure.get('title', '')} {disclosure.get('category', '')} {disclosure.get('emiten', '')}"
    )

    total_score = 0
    matched_labels = []

    for sig_key, sig_def in SIGNAL_KEYWORDS.items():
        for kw in sig_def["keywords"]:
            if kw in combined_text:
                total_score += sig_def["weight"]
                if sig_def["label"] not in matched_labels:
                    matched_labels.append(sig_def["label"])
                break  # Hanya hitung sekali per kategori sinyal

    # Bonus score kalau emiten/sektor masuk watchlist
    if _is_watchlist(combined_text):
        total_score += 1

    return total_score, matched_labels


def classify_signal(score: int) -> str:
    """Klasifikasi level sinyal berdasarkan skor."""
    if score >= SIGNAL_HIGH_THRESHOLD:
        return "🔴 TINGGI"
    elif score >= SIGNAL_MEDIUM_THRESHOLD:
        return "🟡 MENENGAH"
    return ""


def detect_signals(disclosures: List[Dict]) -> List[Dict]:
    """
    Jalankan deteksi sinyal pada semua disclosure.
    Returns hanya disclosure yang punya sinyal (score >= MEDIUM threshold).
    """
    results = []

    for disc in disclosures:
        score, matched = score_disclosure(disc)
        if score < SIGNAL_MEDIUM_THRESHOLD:
            continue

        level = classify_signal(score)
        is_watchlist = _is_watchlist(
            f"{disc.get('title', '')} {disc.get('emiten', '')}"
        )

        results.append({
            **disc,
            "signal_score":   score,
            "signal_level":   level,
            "signal_types":   matched,
            "is_watchlist":   is_watchlist,
        })

    # Urutkan: skor tertinggi dulu, watchlist di atas
    results.sort(key=lambda x: (x["is_watchlist"], x["signal_score"]), reverse=True)

    logger.info(
        "Deteksi sinyal: %d dari %d disclosure memiliki sinyal.",
        len(results), len(disclosures),
    )
    return results
