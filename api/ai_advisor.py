import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# We configure Gemini using the Google AI Studio Key, which the user can provision using their school account
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def get_portfolio_advice(total_equity: float, current_holdings: list, target_ticker: str, target_price: float, risk_profile: str = "moderate"):
    """
    Calls the Gemini Pro model to act as a financial advisor based on user's portfolio context.
    """
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY not found in .env. Please configure your Google School API key."

    # Using Gemini 1.5 Pro or Flash as they are highly capable reasoning engines
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    holdings_text = ", ".join([f"{h['total_lots']} lot {h['ticker']} @ Rp{h['average_price']}" for h in current_holdings])
    if not holdings_text:
        holdings_text = "Empty (100% Cash)"
        
    prompt = f"""
    Kamu adalah Manajer Investasi Profesional (AI Fund Manager) yang ahli di pasar saham Indonesia (IDX).
    Karaktermu tajam, pragmatis, dan ahli dalam manajemen risiko portofolio.
    
    Data Portofolio Klien Saat Ini:
    - Total Modal (Equity): Rp {total_equity:,.0f}
    - Profil Risiko: {risk_profile}
    - Posisi Saat Ini (Holdings): {holdings_text}
    
    Klien bertanya: "Berapa alokasi dan saran untuk masuk ke saham {target_ticker} di harga Rp {target_price}?"
    
    Berikan saran yang jelas mencakup:
    1. Maksimal persentase modal yang disarankan untuk masuk (Allocation Size).
    2. Berapa Lot yang sebaiknya dibeli.
    3. Catatan tentang diversifikasi (contoh: jika sudah terlalu banyak saham sektor perbankan, ingatkan risikonya).
    4. Psikologi trading (jangan fomo).
    
    Berikan respons dalam bahasa Indonesia yang elegan dan profesional (maksimal 3-4 paragraf).
    """

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error contacting Gemini AI: {e}"

if __name__ == "__main__":
    # Test stub
    simulated_holdings = [
        {"ticker": "BBCA", "total_lots": 100, "average_price": 9800},
        {"ticker": "AMMN", "total_lots": 50, "average_price": 8500}
    ]
    advice = get_portfolio_advice(50000000, simulated_holdings, "BREN", 10000)
    print(advice)
