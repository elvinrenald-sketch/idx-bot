"""
intelligence/analyzer.py — AI-powered analysis coordinator
Uses Gemini to analyze disclosures, news, anomalies, and generate daily digests.
Indonesian market context-aware prompts.
"""
import json
import logging
from typing import Dict, List, Optional

from intelligence.gemini import GeminiClient
from data.pdf_reader import extract_pdf_text

logger = logging.getLogger("idx_bot.analyzer")


class IntelligenceEngine:
    """
    Central intelligence coordinator.
    Orchestrates Gemini AI calls for:
    - Disclosure analysis (backdoor listing, acquisition detection)
    - News article relevance scoring
    - Anomaly correlation (price spike + disclosure = insider activity?)
    - Daily digest generation
    """

    def __init__(self, gemini: GeminiClient):
        self.gemini = gemini

    def analyze_disclosure(self, disclosure: dict, pdf_text: str = "") -> Optional[Dict]:
        """
        Full AI analysis of a disclosure document.
        Returns structured analysis dict or None if AI unavailable.
        """
        prompt = self._build_disclosure_prompt(disclosure, pdf_text)
        result = self.gemini.analyze(prompt, temperature=0.1)

        if not result:
            return None

        # Validate required fields with defaults
        analysis = {
            "risk_type": result.get("risk_type", "normal"),
            "summary": result.get("summary", "Analisis tidak tersedia."),
            "urgency": min(max(int(result.get("urgency", 1)), 1), 10),
            "red_flags": result.get("red_flags", []),
            "confidence": min(max(float(result.get("confidence", 0.5)), 0), 1),
            "recommendation": result.get("recommendation", ""),
            "related_signals": result.get("related_signals", []),
        }

        logger.info(
            "Disclosure analysis: %s [%s] → %s (urgency=%d, confidence=%.1f)",
            disclosure.get("emiten", "?"),
            disclosure.get("title", "?")[:50],
            analysis["risk_type"],
            analysis["urgency"],
            analysis["confidence"],
        )

        return analysis

    def analyze_disclosure_with_pdf(self, disclosure: dict) -> Optional[Dict]:
        """Analyze disclosure including PDF content extraction."""
        pdf_text = ""
        pdf_url = disclosure.get("url", "")

        if pdf_url:
            try:
                pdf_text = extract_pdf_text(pdf_url) or ""
            except Exception as e:
                logger.debug("PDF extraction failed: %s", e)

        return self.analyze_disclosure(disclosure, pdf_text)

    def analyze_news(self, article: dict) -> Optional[Dict]:
        """Analyze a news article for relevance and signals."""
        prompt = self._build_news_prompt(article)
        result = self.gemini.analyze(prompt, temperature=0.1)

        if not result:
            return None

        return {
            "relevance_score": min(max(float(result.get("relevance_score", 0)), 0), 10),
            "is_actionable": result.get("is_actionable", False),
            "summary": result.get("summary", ""),
            "mentioned_tickers": result.get("mentioned_tickers", []),
            "signal_type": result.get("signal_type", "none"),
            "urgency": min(max(int(result.get("urgency", 1)), 1), 10),
        }

    def analyze_anomaly(self, anomaly: dict, related_disclosures: list = None) -> Optional[Dict]:
        """Correlate price anomaly with disclosures — detect insider activity."""
        prompt = self._build_anomaly_prompt(anomaly, related_disclosures or [])
        result = self.gemini.analyze(prompt, temperature=0.1)

        if not result:
            return None

        return {
            "explanation": result.get("explanation", ""),
            "insider_risk": result.get("insider_risk", "low"),  # low/medium/high
            "likely_cause": result.get("likely_cause", "unknown"),
            "action_recommendation": result.get("action_recommendation", ""),
            "urgency": min(max(int(result.get("urgency", 1)), 1), 10),
        }

    def generate_daily_digest(self, day_data: dict) -> Optional[str]:
        """Generate smart daily summary combining all signals."""
        prompt = self._build_digest_prompt(day_data)
        return self.gemini.analyze_text(prompt, temperature=0.5)

    # ── Prompt Builders ───────────────────────────────────────────

    def _build_disclosure_prompt(self, disc: dict, pdf_text: str) -> str:
        """Build analysis prompt for IDX disclosure."""
        content_section = ""
        if pdf_text:
            content_section = f"""

=== ISI DOKUMEN (diambil dari PDF) ===
{pdf_text[:3500]}
=== END DOKUMEN ===
"""
        return f"""Kamu adalah analis pasar modal Indonesia yang sangat berpengalaman.
Analisis keterbukaan informasi berikut dari Bursa Efek Indonesia (IDX).

=== DATA DISCLOSURE ===
Emiten: {disc.get('emiten', 'N/A')}
Judul: {disc.get('title', 'N/A')}
Kategori: {disc.get('category', 'N/A')}
Tanggal: {disc.get('date', 'N/A')}
{content_section}

=== INSTRUKSI ===
Analisis disclosure ini dan tentukan:

1. `risk_type` — Klasifikasi risiko. Pilih SATU dari:
   - "backdoor_listing" — Ada indikasi kuat backdoor listing / reverse takeover
   - "acquisition" — Akuisisi / pembelian saham signifikan
   - "change_of_control" — Perubahan pengendali / pemegang saham mayoritas
   - "merger" — Merger atau penggabungan usaha
   - "rights_issue" — Penambahan modal (HMETD, private placement)
   - "material_transaction" — Transaksi material atau benturan kepentingan
   - "divestiture" — Divestasi atau penjualan aset
   - "normal" — Aksi korporasi rutin / tidak signifikan

2. `summary` — Jelaskan dalam 2-3 kalimat BAHASA INDONESIA yang mudah dipahami investor ritel. Sebutkan:
   - Apa yang terjadi
   - Siapa pihak yang terlibat (jika diketahui)
   - Dampak potensial untuk pemegang saham

3. `urgency` — Skor urgensi 1-10:
   - 1-3: Rutin, tidak perlu perhatian segera
   - 4-6: Cukup penting, perlu dipantau
   - 7-8: Penting, perlu perhatian segera
   - 9-10: Sangat kritis, kemungkinan dampak besar pada harga saham

4. `red_flags` — List string berisi tanda-tanda mencurigakan (kosong jika tidak ada):
   - Contoh: "Transaksi dengan pihak afiliasi", "Nilai transaksi tidak wajar", "Perubahan bisnis inti mendadak"

5. `confidence` — Tingkat keyakinan analisis 0.0-1.0 (0.8+ = yakin, 0.5 = tidak pasti)

6. `recommendation` — Saran singkat untuk investor ritel (1 kalimat)

7. `related_signals` — List string prediksi sinyal terkait yang mungkin muncul selanjutnya

Jawab dalam format JSON yang valid. Jangan tambahkan teks di luar JSON."""

    def _build_news_prompt(self, article: dict) -> str:
        """Build analysis prompt for news article."""
        return f"""Kamu adalah analis pasar modal Indonesia.
Evaluasi relevansi artikel berita ini terhadap sinyal akuisisi, backdoor listing, atau aksi korporasi penting.

=== ARTIKEL ===
Sumber: {article.get('source', 'N/A')}
Judul: {article.get('title', 'N/A')}
Cuplikan: {article.get('snippet', 'N/A')}
Tanggal: {article.get('date', 'N/A')}

=== INSTRUKSI ===
Analisis dan berikan:

1. `relevance_score` — Skor relevansi 0-10 terhadap deteksi akuisisi/backdoor listing:
   - 0-2: Tidak relevan
   - 3-5: Sedikit relevan, informasi umum
   - 6-8: Relevan, ada indikasi aksi korporasi
   - 9-10: Sangat relevan, sinyal kuat

2. `is_actionable` — boolean: apakah berita ini perlu alert segera?

3. `summary` — Ringkasan 1-2 kalimat dalam BAHASA INDONESIA

4. `mentioned_tickers` — List kode saham yang disebutkan (format: ["BBCA", "GOTO"])

5. `signal_type` — Jenis sinyal: "acquisition", "backdoor_listing", "rumor", "corporate_action", "none"

6. `urgency` — Skor urgensi 1-10

Jawab dalam format JSON yang valid."""

    def _build_anomaly_prompt(self, anomaly: dict, disclosures: list) -> str:
        """Build analysis prompt for price/volume anomaly."""
        disc_section = ""
        if disclosures:
            disc_items = []
            for d in disclosures[:5]:
                disc_items.append(f"- [{d.get('date','')}] {d.get('title','')}")
            disc_section = f"""
=== DISCLOSURE TERKAIT (48 jam terakhir) ===
{chr(10).join(disc_items)}
"""
        else:
            disc_section = """
=== DISCLOSURE TERKAIT ===
TIDAK ADA disclosure resmi terdeteksi dalam 48 jam terakhir.
Ini SANGAT MENCURIGAKAN — anomali tanpa pengumuman resmi bisa mengindikasikan kebocoran informasi.
"""

        return f"""Kamu adalah analis pasar modal Indonesia yang ahli dalam mendeteksi aktivitas perdagangan mencurigakan.

=== DATA ANOMALI ===
Saham: {anomaly.get('ticker', 'N/A')}
Jenis Anomali: {anomaly.get('type', 'N/A')}
Magnitude: {anomaly.get('magnitude', 0):.1f}x {'rata-rata volume' if 'VOLUME' in anomaly.get('type','') else 'pergerakan harga'}
Volume Saat Ini: {anomaly.get('current_volume', 'N/A')}
Volume Rata-rata 20 Hari: {anomaly.get('avg_volume', 'N/A')}
Perubahan Harga: {anomaly.get('change_pct', 0):.1f}%
{disc_section}

=== INSTRUKSI ===
Analisis anomali ini dengan mempertimbangkan dinamika pasar Indonesia (T+2 settlement, auto-reject ±25%):

1. `explanation` — Penjelasan singkat 2-3 kalimat tentang apa yang mungkin terjadi

2. `insider_risk` — Risiko aktivitas insider: "low", "medium", atau "high"

3. `likely_cause` — Kemungkinan penyebab: "insider_trading", "market_rumor", "institutional_flow", "sector_rotation", "technical_breakout", "unknown"

4. `action_recommendation` — Rekomendasi untuk investor ritel (1 kalimat)

5. `urgency` — Skor urgensi 1-10

Jawab dalam format JSON yang valid."""

    def _build_digest_prompt(self, data: dict) -> str:
        """Build prompt for daily digest generation."""
        disclosures = data.get("disclosures", [])
        anomalies = data.get("anomalies", [])
        news = data.get("news", [])
        ihsg = data.get("ihsg", {})

        disc_summary = "\n".join([
            f"- [{d.get('emiten','')}] {d.get('title','')[:60]} (skor: {d.get('signal_score',0)})"
            for d in disclosures[:10]
        ]) or "Tidak ada disclosure baru."

        anomaly_summary = "\n".join([
            f"- {a.get('ticker','')} — {a.get('anomaly_type','')} ({a.get('magnitude',0):.1f}x)"
            for a in anomalies[:10]
        ]) or "Tidak ada anomali terdeteksi."

        news_summary = "\n".join([
            f"- [{n.get('source','')}] {n.get('title','')[:60]}"
            for n in news[:5]
        ]) or "Tidak ada berita relevan."

        ihsg_str = ""
        if ihsg and not ihsg.get("error"):
            ihsg_str = f"IHSG: {ihsg.get('close',0):,.2f} ({ihsg.get('change_pct',0):+.2f}%)"

        return f"""Buat ringkasan harian pasar modal Indonesia yang informatif dan mudah dipahami.

=== DATA HARI INI ===
{ihsg_str}

Disclosure baru:
{disc_summary}

Anomali harga/volume:
{anomaly_summary}

Berita relevan:
{news_summary}

=== FORMAT ===
Tulis dalam BAHASA INDONESIA, ringkas tapi informatif.
Gunakan emoji secukupnya.
Maksimal 5 paragraf.
Akhiri dengan "Catatan: Ini bukan rekomendasi investasi."
"""
