"""
intelligence/fundamental.py — Fundamental Filtering (Garbage Protection)
Ensures the bot does not recommend intrinsically bankrupt or highly manipulated third-liner stocks.
"""
import logging
import yfinance as yf
from typing import Dict, Tuple

logger = logging.getLogger("idx_bot.fundamental")


class FundamentalFilter:
    """
    Evaluates basic financial health to discard 'garbage' stocks.
    """
    
    def __init__(self):
        pass
        
    def evaluate(self, ticker: str) -> Tuple[bool, str, Dict]:
        """
        Evaluate if a stock passes fundamental safety checks.
        Returns: (is_safe, reason, metrics)
        """
        # Exclude warrants and special instruments
        if ticker.endswith('-W') or ticker.endswith('-R'):
            return False, f"Saham derivatif ({ticker}) tidak masuk kriteria bot.", {}
            
        yf_ticker = f"{ticker}.JK"
        
        try:
            stock = yf.Ticker(yf_ticker)
            info = stock.info
            
            # Note: yfinance info can sometimes be empty or missing fields for obscure IDX stocks.
            if not info or len(info) < 5:
                # If yahoo finance has no data, it's likely a very illiquid or new stock.
                # To be safe but flexible, we allow it but score it low later.
                return True, "Data fundamental YF tidak lengkap, lolos otomatis (risiko tinggi).", {}
            
            metrics = {
                "market_cap": info.get("marketCap", 0),
                "pe_ratio": info.get("forwardPE", info.get("trailingPE", None)),
                "pb_ratio": info.get("priceToBook", None),
                "roe": info.get("returnOnEquity", None),
                "profit_margin": info.get("profitMargins", None),
                "debt_to_equity": info.get("debtToEquity", None),
                "sector": info.get("sector", "Unknown"),
            }
            
            # --- The "Garbage" Filters ---
            
            # 1. Market Cap Filter (Avoid ultra micro-cap < 50 Billion IDR)
            if metrics["market_cap"] and metrics["market_cap"] < 50_000_000_000:
                return False, f"Market Cap terlalu kecil (< Rp50 M). Rawan manipulasi bandar.", metrics
                
            # 2. Extreme PBV (Negative Equity)
            # Note: Yahoo Finance PBV data for IDX stocks is frequently WRONG
            # (e.g. BREN shows PBV 1,160,000x when real PBV is ~20x).
            # We ONLY reject on genuinely negative equity, not on high PBV.
            pb = metrics["pb_ratio"]
            if pb is not None:
                if pb < 0:
                    return False, f"Ekuitas Negatif (PBV {pb:.2f}). Fundamental hancur/FCA.", metrics
                # Don't reject high PBV — YF data too unreliable for IDX
                    
            # 3. ROE / Profitability (Consistently losing massive money? Filter if extreme)
            roe = metrics["roe"]
            if roe is not None and roe < -0.5: # Losing 50% of equity in a year
                # We allow it if the system caught an acquisition signal, but purely for swing, it's garbage.
                return False, f"ROE sangat negatif ({-roe*100:.1f}%). Membakar kas terlalu cepat.", metrics
                
            return True, "Lolos filter fundamental (Safe for Swing Trading).", metrics
            
        except Exception as e:
            logger.error(f"Error checking fundamentals for {ticker}: {e}")
            return True, "Error mengambil API YFinance, dilewatkan otomatis.", {}
            
    def get_fundamental_score(self, metrics: Dict) -> int:
        """Calculate a bonus score from 0-25 for strong fundamentals."""
        score = 0
        
        # PE Ratio Bonus (Undervalued but profitable)
        pe = metrics.get("pe_ratio")
        if pe:
            if 0 < pe < 15:
                score += 10
            elif 15 <= pe <= 25:
                score += 5
                
        # Profitability Bonus
        roe = metrics.get("roe")
        if roe and roe > 0.15: # ROE > 15%
            score += 10
            
        # Dividend Bonus (Safer for swing holding)
        # Not fetched directly here but placeholder
        
        return score
