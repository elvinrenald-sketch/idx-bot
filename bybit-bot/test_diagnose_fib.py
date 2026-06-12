import sys
import os
import time
from typing import List, Tuple, Dict, Optional
import pandas as pd
import numpy as np

# Set dummy env vars for config import
os.environ['HL_PRIVATE_KEY'] = '0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef'
os.environ['HL_WALLET_ADDRESS'] = '0x1234567890abcdef1234567890abcdef12345678'
os.environ['TELEGRAM_BOT_TOKEN'] = 'fake'
os.environ['TELEGRAM_CHAT_ID'] = 'fake'
os.environ['BYBIT_API_KEY'] = 'fake'
os.environ['BYBIT_API_SECRET'] = 'fake'

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import *
from scanner import MarketScanner
from strategy import (
    _calc_trendline_value, _calc_resistance_trendline, calc_atr, is_pump_candle
)

# New helper functions using wick lows to mirror wick highs
def detect_pivot_lows_wick(df: pd.DataFrame, left: int = PIVOT_LEFT, right: int = PIVOT_RIGHT):
    lows = df['low'].values
    n = len(lows)
    pivots = []
    for i in range(left, n - right):
        is_pivot = True
        for j in range(1, left + 1):
            if lows[i] > lows[i - j]:
                is_pivot = False
                break
        if not is_pivot:
            continue
        for j in range(1, right + 1):
            if lows[i] > lows[i + j]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append(i)
    return pivots

def detect_higher_lows_wick(df: pd.DataFrame, p_lows: List[int]) -> Tuple[bool, List[int]]:
    if len(p_lows) < MIN_HL_TOUCHES:
        return False, []

    best_seq = []

    # Try every starting point to find the longest sequence (identical to detect_lower_highs)
    for start in range(len(p_lows)):
        seq = [p_lows[start]]
        for i in range(start + 1, len(p_lows)):
            curr_low = float(df['low'].iloc[p_lows[i]])
            prev_low = float(df['low'].iloc[seq[-1]])
            gap = p_lows[i] - seq[-1]

            # Must be higher
            if curr_low <= prev_low:
                continue

            # Gap filter
            if gap < MIN_HL_CANDLE_GAP or gap > MAX_HL_CANDLE_GAP:
                continue

            # Price jump check
            rise_pct = ((curr_low - prev_low) / prev_low) * 100
            if rise_pct > MAX_HL_PRICE_JUMP_PCT:
                continue

            seq.append(p_lows[i])

        if len(seq) > len(best_seq):
            best_seq = seq

    if len(best_seq) < MIN_HL_TOUCHES:
        return False, []

    # Recency check
    if best_seq[-1] < len(df) - 80:
        return False, []

    if len(best_seq) > MAX_HL_TOUCHES:
        best_seq = best_seq[-MAX_HL_TOUCHES:]

    return True, best_seq

# Detect pivot highs (redefined here for reference)
def detect_pivot_highs_wick(df: pd.DataFrame, left: int = PIVOT_LEFT, right: int = PIVOT_RIGHT):
    highs = df['high'].values
    n = len(highs)
    pivots = []
    for i in range(left, n - right):
        is_pivot = True
        for j in range(1, left + 1):
            if highs[i] < highs[i - j]:
                is_pivot = False
                break
        if not is_pivot:
            continue
        for j in range(1, right + 1):
            if highs[i] < highs[i + j]:
                is_pivot = False
                break
        if is_pivot:
            pivots.append(i)
    return pivots

# Detect lower highs (redefined here for reference)
def detect_lower_highs_wick(df: pd.DataFrame, p_highs: List[int]) -> Tuple[bool, List[int]]:
    if len(p_highs) < MIN_HL_TOUCHES:
        return False, []

    best_seq = []

    for start in range(len(p_highs)):
        seq = [p_highs[start]]
        for i in range(start + 1, len(p_highs)):
            curr_high = float(df['high'].iloc[p_highs[i]])
            prev_high = float(df['high'].iloc[seq[-1]])
            gap = p_highs[i] - seq[-1]

            if curr_high >= prev_high:
                continue

            if gap < MIN_HL_CANDLE_GAP or gap > MAX_HL_CANDLE_GAP:
                continue

            drop_pct = ((prev_high - curr_high) / prev_high) * 100
            if drop_pct > MAX_HL_PRICE_JUMP_PCT:
                continue

            seq.append(p_highs[i])

        if len(seq) > len(best_seq):
            best_seq = seq

    if len(best_seq) < MIN_HL_TOUCHES:
        return False, []

    if best_seq[-1] < len(df) - 80:
        return False, []

    if len(best_seq) > MAX_HL_TOUCHES:
        best_seq = best_seq[-MAX_HL_TOUCHES:]

    return True, best_seq


def diagnose_hl_long(df: pd.DataFrame, symbol: str, timeframe: str):
    if df is None or len(df) < 60:
        return f"FAIL: df too short ({len(df) if df is not None else 0})"

    atr = calc_atr(df, 14)
    current_price = df['close'].iloc[-1]

    # Step 1: Detect pivot lows (using new wick version)
    p_lows = detect_pivot_lows_wick(df)
    if len(p_lows) < 2:
        return f"FAIL: < 2 pivot lows ({len(p_lows)})"

    # Step 2: Higher lows (using new wick version)
    has_hl, hl_indices = detect_higher_lows_wick(df, p_lows)
    if not has_hl or len(hl_indices) < 2:
        hl_details = []
        for pl in p_lows:
            hl_details.append(f"idx={pl}(val={df['low'].iloc[pl]:.4f})")
        return f"FAIL: no HL pattern (p_lows: {', '.join(hl_details[-4:])})"

    # Step 3: Valid ascending range
    first_hl_idx = hl_indices[0]
    last_hl_idx = hl_indices[-1]
    first_hl_price = float(df['low'].iloc[first_hl_idx])
    last_hl_price = float(df['low'].iloc[last_hl_idx])

    if last_hl_price <= first_hl_price:
        return f"FAIL: last_hl_price <= first_hl_price ({last_hl_price:.4f} <= {first_hl_price:.4f})"

    candle_span = last_hl_idx - first_hl_idx
    if candle_span <= 0:
        return f"FAIL: candle_span <= 0 ({candle_span})"

    total_hl_range_pct = ((last_hl_price - first_hl_price) / first_hl_price) * 100
    if total_hl_range_pct < MIN_ASCENDING_RANGE_PCT:
        return f"FAIL: range {total_hl_range_pct:.2f}% < MIN_ASCENDING_RANGE_PCT {MIN_ASCENDING_RANGE_PCT}%"

    slope_per_candle = (last_hl_price - first_hl_price) / candle_span
    slope_pct_per_candle = abs((slope_per_candle / first_hl_price) * 100)
    if slope_pct_per_candle > 1.0:
        return f"FAIL: slope too steep {slope_pct_per_candle:.3f}%/candle > 1.0%"

    # Step 3b: trendline
    trendline_price = _calc_trendline_value(df, hl_indices)
    if not trendline_price or trendline_price <= 0:
        return "FAIL: trendline calc failed"

    # Step 4: Swing High/Low search
    current_idx = len(df) - 1
    best_candidate = None
    candidates_checked = 0
    rejections = []

    for i in range(len(hl_indices) - 1, -1, -1):
        candidate_low_idx = hl_indices[i]
        candidate_low = float(df['low'].iloc[candidate_low_idx])

        search_start = candidate_low_idx + 1
        search_end = current_idx

        if search_end - search_start < 2:
            rejections.append(f"HL[{i}]: range too small ({search_end - search_start} < 2)")
            continue

        high_slice = df['high'].iloc[search_start:search_end].values
        high_offset = int(high_slice.argmax())
        candidate_high_idx = search_start + high_offset
        candidate_high = float(df['high'].iloc[candidate_high_idx])

        if candidate_high_idx >= current_idx - 1:
            rejections.append(f"HL[{i}]: swing high too close to current (idx {candidate_high_idx} >= {current_idx-1})")
            continue

        if current_price >= candidate_high:
            rejections.append(f"HL[{i}]: price >= swing high ({current_price:.4f} >= {candidate_high:.4f})")
            continue

        _fib_range = candidate_high - candidate_low
        if _fib_range <= 0:
            rejections.append(f"HL[{i}]: fib range <= 0")
            continue

        _fib_range_pct = (_fib_range / candidate_low) * 100
        if _fib_range_pct < 3.0:
            rejections.append(f"HL[{i}]: rally {_fib_range_pct:.2f}% < 3.0%")
            continue

        if _fib_range_pct > 20.0:
            rejections.append(f"HL[{i}]: rally {_fib_range_pct:.2f}% > 20.0%")
            continue

        # Fib levels
        _fib_618 = candidate_high - (_fib_range * 0.618)
        _fib_702 = candidate_high - (_fib_range * 0.702)
        _fib_786 = candidate_high - (_fib_range * 0.786)

        candidates_checked += 1
        if best_candidate is None or candidate_low < best_candidate['swing_low']:
            best_candidate = {
                'swing_low': candidate_low,
                'swing_low_iloc': candidate_low_idx,
                'swing_high': candidate_high,
                'swing_high_iloc': candidate_high_idx,
                'fib_618': _fib_618,
                'fib_702': _fib_702,
                'fib_786': _fib_786,
                'fib_range': _fib_range,
            }

    if not best_candidate:
        return f"FAIL: no valid HL candidate found. Rejections: {'; '.join(rejections[-3:])}"

    swing_low = best_candidate['swing_low']
    swing_high = best_candidate['swing_high']
    fib_618 = best_candidate['fib_618']
    fib_702 = best_candidate['fib_702']
    fib_786 = best_candidate['fib_786']

    # Now check if current price in zone (FULL 0.618 - 0.786 ZONE)
    if not (fib_786 <= current_price <= fib_618):
        return f"FAIL: price {current_price:.4f} not in lowest SwL zone [{fib_786:.4f} - {fib_618:.4f}]. SwL={swing_low:.4f}, SwH={swing_high:.4f}"

    # CHECK 1: Came from below block
    for j in range(2, min(5, len(df))):
        past_close = float(df['close'].iloc[-j])
        if past_close < fib_786:
            return f"FAIL: candle -{j} close {past_close:.4f} < fib_786 {fib_786:.4f} (came from below)"

    # CHECK 2: Entered from above
    entered_from_above = False
    for j in range(2, min(5, len(df))):
        past_close = float(df['close'].iloc[-j])
        if past_close > fib_618:
            entered_from_above = True
            break

    if not entered_from_above:
        past_details = [f"-{j}={float(df['close'].iloc[-j]):.4f}" for j in range(2, min(5, len(df)))]
        return f"FAIL: not entered from above (no past close > fib_618 {fib_618:.4f}. Closes: {', '.join(past_details)})"

    if is_pump_candle(df, atr):
        return "FAIL: pump candle detected"

    return f"✅ PASS! Entry={current_price:.4f} SL={swing_low*(1-SL_BUFFER_PCT/100):.4f} TP={current_price + (current_price - swing_low*(1-SL_BUFFER_PCT/100)) * DEFAULT_RR_RATIO:.4f}"


def diagnose_lh_short(df: pd.DataFrame, symbol: str, timeframe: str):
    if df is None or len(df) < 60:
        return f"FAIL: df too short ({len(df) if df is not None else 0})"

    atr = calc_atr(df, 14)
    current_price = df['close'].iloc[-1]

    # Step 1: Detect pivot highs
    p_highs = detect_pivot_highs_wick(df)
    if len(p_highs) < 2:
        return f"FAIL: < 2 pivot highs ({len(p_highs)})"

    # Step 2: Lower highs
    has_lh, lh_indices = detect_lower_highs_wick(df, p_highs)
    if not has_lh or len(lh_indices) < 2:
        lh_details = []
        for ph in p_highs:
            lh_details.append(f"idx={ph}(val={df['high'].iloc[ph]:.4f})")
        return f"FAIL: no LH pattern (p_highs: {', '.join(lh_details[-4:])})"

    # Step 3: Valid descending range
    first_lh_idx = lh_indices[0]
    last_lh_idx = lh_indices[-1]
    first_lh_price = float(df['high'].iloc[first_lh_idx])
    last_lh_price = float(df['high'].iloc[last_lh_idx])

    if last_lh_price >= first_lh_price:
        return f"FAIL: last_lh_price >= first_lh_price ({last_lh_price:.4f} >= {first_lh_price:.4f})"

    candle_span = last_lh_idx - first_lh_idx
    if candle_span <= 0:
        return f"FAIL: candle_span <= 0 ({candle_span})"

    total_lh_range_pct = ((first_lh_price - last_lh_price) / first_lh_price) * 100
    if total_lh_range_pct < MIN_ASCENDING_RANGE_PCT:
        return f"FAIL: range {total_lh_range_pct:.2f}% < MIN_ASCENDING_RANGE_PCT {MIN_ASCENDING_RANGE_PCT}%"

    slope_per_candle = (last_lh_price - first_lh_price) / candle_span
    slope_pct_per_candle = abs((slope_per_candle / first_lh_price) * 100)
    if slope_pct_per_candle > 1.0:
        return f"FAIL: slope too steep {slope_pct_per_candle:.3f}%/candle > 1.0%"

    # Step 3b: trendline
    trendline_price = _calc_resistance_trendline(df, lh_indices)
    if not trendline_price or trendline_price <= 0:
        return "FAIL: trendline calc failed"

    # Step 4: Swing High/Low search
    current_idx = len(df) - 1
    best_candidate = None
    candidates_checked = 0
    rejections = []

    for i in range(len(lh_indices) - 1, -1, -1):
        candidate_high_idx = lh_indices[i]
        candidate_high = float(df['high'].iloc[candidate_high_idx])

        search_start = candidate_high_idx + 1
        search_end = current_idx

        if search_end - search_start < 2:
            rejections.append(f"LH[{i}]: range too small ({search_end - search_start} < 2)")
            continue

        low_slice = df['low'].iloc[search_start:search_end].values
        low_offset = int(low_slice.argmin())
        candidate_low_idx = search_start + low_offset
        candidate_low = float(df['low'].iloc[candidate_low_idx])

        if candidate_low_idx >= current_idx - 1:
            rejections.append(f"LH[{i}]: swing low too close to current (idx {candidate_low_idx} >= {current_idx-1})")
            continue

        if current_price <= candidate_low:
            rejections.append(f"LH[{i}]: price <= swing low ({current_price:.4f} <= {candidate_low:.4f})")
            continue

        _fib_range = candidate_high - candidate_low
        if _fib_range <= 0:
            rejections.append(f"LH[{i}]: fib range <= 0")
            continue

        _fib_range_pct = (_fib_range / candidate_high) * 100
        if _fib_range_pct < 3.0:
            rejections.append(f"LH[{i}]: drop {_fib_range_pct:.2f}% < 3.0%")
            continue

        if _fib_range_pct > 20.0:
            rejections.append(f"LH[{i}]: drop {_fib_range_pct:.2f}% > 20.0%")
            continue

        # Fib levels
        _fib_618 = candidate_low + (_fib_range * 0.618)
        _fib_702 = candidate_low + (_fib_range * 0.702)
        _fib_786 = candidate_low + (_fib_range * 0.786)

        candidates_checked += 1
        if best_candidate is None or candidate_high > best_candidate['swing_high']:
            best_candidate = {
                'swing_high': candidate_high,
                'swing_high_iloc': candidate_high_idx,
                'swing_low': candidate_low,
                'swing_low_iloc': candidate_low_idx,
                'fib_618': _fib_618,
                'fib_702': _fib_702,
                'fib_786': _fib_786,
                'fib_range': _fib_range,
            }

    if not best_candidate:
        return f"FAIL: no valid LH candidate found. Rejections: {'; '.join(rejections[-3:])}"

    swing_low = best_candidate['swing_low']
    swing_high = best_candidate['swing_high']
    fib_618 = best_candidate['fib_618']
    fib_702 = best_candidate['fib_702']
    fib_786 = best_candidate['fib_786']

    # Now check if current price in zone (FULL 0.618 - 0.786 ZONE)
    if not (fib_618 <= current_price <= fib_786):
        return f"FAIL: price {current_price:.4f} not in highest SwH zone [{fib_618:.4f} - {fib_786:.4f}]. SwH={swing_high:.4f}, SwL={swing_low:.4f}"

    # CHECK 1: Came from above block
    for j in range(2, min(5, len(df))):
        past_close = float(df['close'].iloc[-j])
        if past_close > fib_786:
            return f"FAIL: candle -{j} close {past_close:.4f} > fib_786 {fib_786:.4f} (came from above)"

    # CHECK 2: Entered from below
    entered_from_below = False
    for j in range(2, min(5, len(df))):
        past_close = float(df['close'].iloc[-j])
        if past_close < fib_618:
            entered_from_below = True
            break

    if not entered_from_below:
        past_details = [f"-{j}={float(df['close'].iloc[-j]):.4f}" for j in range(2, min(5, len(df)))]
        return f"FAIL: not entered from below (no past close < fib_618 {fib_618:.4f}. Closes: {', '.join(past_details)})"

    if is_pump_candle(df, atr):
        return "FAIL: pump candle detected"

    return f"✅ PASS! Entry={current_price:.4f} SL={swing_high*(1+SL_BUFFER_PCT/100):.4f} TP={current_price - (swing_high*(1+SL_BUFFER_PCT/100) - current_price) * DEFAULT_RR_RATIO:.4f}"

if __name__ == '__main__':
    print("Initializing MarketScanner...")
    scanner = MarketScanner()
    
    # Load markets info
    print("Loading markets...")
    scanner.load_markets()
    
    # Scan for candidate coins (similar to bot)
    print("Fetching asset contexts...")
    all_mids = scanner.info.all_mids()
    meta = scanner.info.meta()
    
    # Find active coins in meta
    active_symbols = []
    for asset_info in meta['universe']:
        name = asset_info['name']
        if name in all_mids and name not in BLACKLIST_SYMBOLS:
            active_symbols.append(name)
            
    # Sort or limit to first 30 active symbols
    top_coins = active_symbols[:30]
    
    print(f"Loaded top {len(top_coins)} coins.")
    print("=" * 100)
    print(f"{'Coin':12s} | {'Timeframe':5s} | {'HL_LONG Result':55s}")
    print("-" * 100)
    
    long_passes = 0
    for symbol in top_coins:
        for tf in ['1h']:
            try:
                df = scanner.fetch_ohlcv(symbol, tf, limit=150)
                if df is None:
                    print(f"{symbol:12s} | {tf:5s} | FAIL: df is None")
                    continue
                
                long_res = diagnose_hl_long(df, symbol, tf)
                
                if "✅" in long_res:
                    print(f"\033[92m{symbol:12s} | {tf:5s} | {long_res}\033[0m")
                    long_passes += 1
                else:
                    print(f"{symbol:12s} | {tf:5s} | {long_res}")
                    
            except Exception as e:
                print(f"{symbol:12s} | {tf:5s} | ERROR: {e}")
                
            time.sleep(0.05)
                
    print("=" * 100)
    print(f"{'Coin':12s} | {'Timeframe':5s} | {'LH_SHORT Result':55s}")
    print("-" * 100)
    
    short_passes = 0
    for symbol in top_coins:
        for tf in ['1h']:
            try:
                df = scanner.fetch_ohlcv(symbol, tf, limit=150)
                if df is None:
                    print(f"{symbol:12s} | {tf:5s} | FAIL: df is None")
                    continue
                
                short_res = diagnose_lh_short(df, symbol, tf)
                
                if "✅" in short_res:
                    print(f"\033[91m{symbol:12s} | {tf:5s} | {short_res}\033[0m")
                    short_passes += 1
                else:
                    print(f"{symbol:12s} | {tf:5s} | {short_res}")
                    
            except Exception as e:
                print(f"{symbol:12s} | {tf:5s} | ERROR: {e}")
                
            time.sleep(0.05)
            
    print("=" * 100)
    print(f"Summary: {long_passes} LONG passes, {short_passes} SHORT passes.")
