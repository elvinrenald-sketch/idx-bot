"""
intelligence/technical.py — Professional Swing Trading Technical Analysis
Uses standard `ta` package to calculate Swing indicators (MA, MACD, RSI, Bollinger Bands).
"""
import logging
import yfinance as yf
import pandas as pd
import ta
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger("idx_bot.technical")

class TechnicalAnalyzer:
    """
    Analyzes historical daily prices to determine swing trading setups.
    Identifies trends, momentum, and calculates Entry, Target, and Stop Loss.
    """
    
    def __init__(self):
        # We download data locally on demand and cache if needed
        self.cached_data = {}
        
    def fetch_history(self, ticker: str, days: int = 150) -> Optional[pd.DataFrame]:
        """Fetch daily history for an IDX stock from Yahoo Finance."""
        yf_ticker = f"{ticker}.JK"
        
        try:
            stock = yf.Ticker(yf_ticker)
            # Get enough data for MA200 if needed, but for Swing MA50 is usually enough
            history = stock.history(period=f"{days}d")
            
            if history.empty:
                logger.warning(f"No price history found for {yf_ticker}")
                return None
                
            history = history.dropna()
            return history
            
        except Exception as e:
            logger.error(f"Error fetching tech history for {ticker}: {e}")
            return None

    def analyze(self, ticker: str, current_price: float = None) -> Dict:
        """
        Perform a full Swing Trading technical analysis.
        Returns a dict with signals, score contribution, and trade levels.
        """
        df = self.fetch_history(ticker)
        
        if df is None or len(df) < 50:
            return {"error": "Kurang data historis untuk analisa teknikal."}
            
        # Optional: Append current price as latest day if not included in yf
        # Normally yf daily has up to the minute if live, but we can trust it for swing.
        
        # Calculate Indicators
        # 1. Moving Averages (Trend)
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['MA50'] = ta.trend.sma_indicator(df['Close'], window=50)
        
        # 2. RSI (Momentum)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        
        # 3. MACD (Trend Momentum)
        macd = ta.trend.MACD(df['Close'])
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Diff'] = macd.macd_diff() # Histogram
        
        # 4. Bollinger Bands (Volatility / Squeeze)
        bollinger = ta.volatility.BollingerBands(df['Close'], window=20, window_dev=2)
        df['BB_High'] = bollinger.bollinger_hband()
        df['BB_Low'] = bollinger.bollinger_lband()
        
        # Latest data
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = current_price if current_price else latest['Close']
        
        # Compute Score
        score = 0
        signals = []
        
        # Trend check
        if close > latest['MA20']:
            score += 15
            signals.append("Harga di atas MA20 (Uptrend Jangka Pendek ✅)")
        elif close < latest['MA20']:
            score -= 10
            signals.append("Harga di bawah MA20 (Downtrend Pendek ❌)")
            
        if close > latest['MA50']:
            score += 15
            signals.append("Harga di atas MA50 (Uptrend Menengah ✅)")
            
        # RSI Check
        rsi = latest['RSI']
        if rsi < 30:
            score += 20
            signals.append(f"RSI Oversold ({rsi:.1f}) - Potensi Rebound 🚀")
        elif rsi > 70:
            score -= 15
            signals.append(f"RSI Overbought ({rsi:.1f}) - Rawan Profit Taking ⚠️")
        elif 40 <= rsi <= 60:
            score += 10
            signals.append(f"RSI Netral-Kuat ({rsi:.1f})")
            
        # MACD Check (Golden Cross / Momentum)
        if latest['MACD_Diff'] > 0 and prev['MACD_Diff'] <= 0:
            score += 25
            signals.append("MACD Golden Cross! Sinyal Swing Kuat 🟢")
        elif latest['MACD_Diff'] > 0:
            score += 10
            signals.append("MACD Momentum Positif")
        elif latest['MACD_Diff'] < 0 and prev['MACD_Diff'] >= 0:
            score -= 20
            signals.append("MACD Death Cross! Hindari V 🔴")
            
        # BB Squeeze Breakout Check
        bb_width = (latest['BB_High'] - latest['BB_Low']) / latest['MA20']
        if bb_width < 0.10: # Tight squeeze
            if close > latest['BB_High']:
                score += 20
                signals.append("Breakout Bollinger Band dari fase Squeeze! 💥")
            else:
                signals.append("Bollinger Band Squeeze - Bersiap untuk Volatilitas")
                
        # Generate Professional Trade Setup Parameters
        # Stop Loss: Below recent local support or slightly below MA20
        # Target Price: Next resistance (e.g. recent high in 15 days or using BB High + ATR)
        
        recent_low = df['Close'].tail(15).min()
        recent_high = df['Close'].tail(15).max()
        
        # Stop loss calculation (2-5% below support or current price)
        sl_price = min(recent_low * 0.98, latest['MA20'] * 0.98)
        # Avoid SL being too far if volatile
        if (close - sl_price) / close > 0.15:
             sl_price = close * 0.90 # Cap max loss at 10% for Swing

        # Target Price calculation (Reward/Risk minimum 1.5x)
        risk = close - sl_price
        tp1 = close + (risk * 1.5)
        tp2 = max(recent_high, close + (risk * 2.5))
        
        return {
            "score": max(0, min(100, score)), # Normalize 0-100
            "signals": signals,
            "rsi": rsi,
            "macd_diff": latest['MACD_Diff'],
            "trend": "UPTREND" if close > latest['MA50'] else "DOWNTREND",
            "setup": {
                "entry_zone": f"{close * 0.98:,.0f} - {close:,.0f}",
                "tp1": tp1,
                "tp2": tp2,
                "sl": sl_price,
                "risk_reward_ratio": round((tp1 - close) / risk, 1) if risk > 0 else 0
            }
        }
