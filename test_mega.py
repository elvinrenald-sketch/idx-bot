import pandas as pd
import ccxt
import time
import os
import sys

# Append bybit-bot to path
sys.path.append('/Users/oliveaprilia/Documents/workspace antigravity ai/bybit-bot')

from strategy import analyze_breakdown_short, calc_atr, detect_pivot_lows, detect_pivot_highs, detect_higher_lows, _calc_trendline_value

# Mock config
from config import MIN_ASCENDING_RANGE_PCT

exchange = ccxt.bybit({'enableRateLimit': True})

def test_mega():
    sym = 'MEGA/USDT:USDT'
    print(f"Fetching data for {sym}...")
    
    # Fetch H1
    ohlcv_h1 = exchange.fetch_ohlcv(sym, '1h', limit=300)
    df_h1 = pd.DataFrame(ohlcv_h1, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_h1['timestamp'] = pd.to_datetime(df_h1['timestamp'], unit='ms')
    
    # Fetch M15
    ohlcv_m15 = exchange.fetch_ohlcv(sym, '15m', limit=300)
    df_m15 = pd.DataFrame(ohlcv_m15, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df_m15['timestamp'] = pd.to_datetime(df_m15['timestamp'], unit='ms')
    
    # Let's iterate through the last 50 M15 candles and simulate the bot at each step
    print("\nSimulating past 50 M15 candles for SHORT Breakdown...")
    for i in range(50, 0, -1):
        if i == 1:
            sub_m15 = df_m15
        else:
            sub_m15 = df_m15.iloc[:-i+1]
            
        current_time = sub_m15['timestamp'].iloc[-1]
        
        # We need the H1 dataframe up to the current_time
        sub_h1 = df_h1[df_h1['timestamp'] <= current_time].copy()
        if len(sub_h1) < 50:
            continue
            
        # Run the actual function
        # Wait, the analyze_breakdown_short is imported. We can just call it, but it returns None on fail, 
        # so we won't know WHY it failed.
        # Let's manually run the steps here to print exactly why it fails for MEGA.
        
        # HTF Checks
        p_lows = detect_pivot_lows(sub_h1)
        p_highs = detect_pivot_highs(sub_h1)
        if len(p_lows) < 2: continue
        
        has_hl, hl_indices = detect_higher_lows(sub_h1, p_lows)
        if not has_hl or len(hl_indices) < 2: continue
        
        first_hl_idx = hl_indices[0]
        last_hl_idx = hl_indices[-1]
        first_hl_price = min(sub_h1['open'].iloc[first_hl_idx], sub_h1['close'].iloc[first_hl_idx])
        last_hl_price = min(sub_h1['open'].iloc[last_hl_idx], sub_h1['close'].iloc[last_hl_idx])
        if last_hl_price <= first_hl_price: continue
        
        trendline_price = _calc_trendline_value(sub_h1, hl_indices)
        if not trendline_price or trendline_price <= 0: continue
        
        m15_candle = sub_m15.iloc[-1]
        m15_open = m15_candle['open']
        m15_close = m15_candle['close']
        
        # Check if it's a breakdown candle (Red, open above, close below)
        if m15_close >= m15_open: continue
        if m15_close >= trendline_price: continue
        if m15_open < trendline_price * 0.995: continue # Open roughly above or near
        
        body_below_trendline_pct = ((trendline_price - m15_close) / trendline_price) * 100
        
        print(f"\n--- Potential Breakdown at {current_time} ---")
        print(f"Trendline: {trendline_price:.6f}, Close: {m15_close:.6f}")
        print(f"Body Below Trendline Pct: {body_below_trendline_pct:.4f}%")
        
        if body_below_trendline_pct < 0.23:
            print("❌ REJECTED: body_below_trendline_pct < 0.23 (Terlalu tipis)")
        elif body_below_trendline_pct > 0.35:
            print("❌ REJECTED: body_below_trendline_pct > 0.35 (Terlalu panjang)")
        else:
            print("✅ Body below trendline PASSED (between 0.23% and 0.35%)")
            
        # Check wick
        m15_high = m15_candle['high']
        m15_low = m15_candle['low']
        m15_range = m15_high - m15_low
        lower_wick = min(m15_open, m15_close) - m15_low
        if m15_range > 0:
            lower_wick_ratio = lower_wick / m15_range
            print(f"Lower Wick Ratio: {lower_wick_ratio:.4f}")
            if lower_wick_ratio > 0.35:
                print("❌ REJECTED: lower_wick_ratio > 0.35")
            else:
                print("✅ Wick ratio PASSED")
                
        # Check flat resistance
        FLAT_RESISTANCE_TOLERANCE = 3.0
        flat_resistance_valid = False
        if len(p_highs) >= 1:
            relevant_highs = [idx for idx in p_highs if idx >= first_hl_idx]
            if len(relevant_highs) >= 1:
                ph_prices = [sub_h1['high'].iloc[idx] for idx in relevant_highs[-5:]]
                ph_max = max(ph_prices)
                ph_min = min(ph_prices)
                spread_pct = ((ph_max - ph_min) / ph_max) * 100
                if spread_pct <= FLAT_RESISTANCE_TOLERANCE:
                    flat_resistance_valid = True
                    print(f"✅ Flat Resistance Valid (Spread: {spread_pct:.2f}%)")
                else:
                    print(f"❌ Flat Resistance INVALID (Spread: {spread_pct:.2f}% > 3.0%)")
            else:
                print("❌ No relevant highs")
        else:
            print("❌ No pivot highs")
        
test_mega()
