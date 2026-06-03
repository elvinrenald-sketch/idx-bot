"""
DIAGNOSTIC SCRIPT: Trace exactly WHERE the entry filter rejects signals.
Runs against live Bybit data, same as the bot, but logs every rejection reason.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ccxt
import pandas as pd
import numpy as np
from config import *

# Minimal imports from strategy
from strategy import (
    detect_pivot_highs, detect_pivot_lows, detect_higher_lows, detect_accumulation_zone,
    _calc_trendline_value, calc_atr, calc_volume_sma, is_pump_candle
)

exchange = ccxt.bybit({
    'apiKey': BYBIT_API_KEY,
    'secret': BYBIT_API_SECRET,
    'options': {'defaultType': 'swap'},
})

def trace_analyze(df, symbol, timeframe):
    """Identical to analyze() but prints WHERE it fails instead of returning None."""
    
    if df is None or len(df) < 50:
        return f"FAIL: df too short ({len(df) if df is not None else 0} < 50)"

    current_price = df['close'].iloc[-1]
    atr = calc_atr(df)

    # Step 1: Pivot points
    p_highs = detect_pivot_highs(df)
    p_lows = detect_pivot_lows(df)
    if len(p_lows) < 2:
        return f"FAIL Step1: Only {len(p_lows)} pivot lows (need >=2)"

    # Step 2: Higher Lows
    has_hl, hl_indices = detect_higher_lows(df, p_lows)
    if not has_hl or len(hl_indices) < 2:
        return f"FAIL Step2: No higher lows found (has_hl={has_hl}, count={len(hl_indices) if hl_indices else 0})"

    # Step 3: Ascending slope
    first_hl_idx = hl_indices[0]
    last_hl_idx = hl_indices[-1]
    first_hl_price = min(df['open'].iloc[first_hl_idx], df['close'].iloc[first_hl_idx])
    last_hl_price = min(df['open'].iloc[last_hl_idx], df['close'].iloc[last_hl_idx])

    if last_hl_price <= first_hl_price:
        return f"FAIL Step3: Trendline NOT ascending ({last_hl_price:.6f} <= {first_hl_price:.6f})"

    candle_span = last_hl_idx - first_hl_idx
    if candle_span <= 0:
        return f"FAIL Step3: candle_span={candle_span}"
    
    slope_pct = ((last_hl_price - first_hl_price) / candle_span / first_hl_price) * 100
    if slope_pct > 0.5:
        return f"FAIL Step3: Slope too steep ({slope_pct:.3f}% per candle > 0.5%)"

    # Step 3a-2: Min ascending range
    total_hl_range_pct = ((last_hl_price - first_hl_price) / first_hl_price) * 100
    if total_hl_range_pct < MIN_ASCENDING_RANGE_PCT:
        return f"FAIL Step3a: HL range too small ({total_hl_range_pct:.2f}% < {MIN_ASCENDING_RANGE_PCT}%)"

    # Step 3b: Flat resistance
    FLAT_RESISTANCE_TOLERANCE = 2.0
    flat_resistance_valid = False
    flat_resistance_level = None

    if len(p_highs) >= 2:
        relevant_highs = [i for i in p_highs if i >= first_hl_idx]
        if len(relevant_highs) >= 2:
            ph_prices = [df['high'].iloc[i] for i in relevant_highs[-5:]]
            ph_max = max(ph_prices)
            ph_min = min(ph_prices)
            last_ph = ph_prices[-1]
            spread_pct = ((ph_max - ph_min) / ph_max) * 100
            distance_last_to_max = ((ph_max - last_ph) / ph_max) * 100

            if spread_pct <= FLAT_RESISTANCE_TOLERANCE and distance_last_to_max <= 2.0 and len(ph_prices) >= 2:
                flat_resistance_valid = True
                flat_resistance_level = (ph_max + ph_min) / 2
            else:
                return f"FAIL Step3b: Resistance NOT flat (spread={spread_pct:.2f}% tol={FLAT_RESISTANCE_TOLERANCE}%, last_dist={distance_last_to_max:.2f}%)"
        else:
            return f"FAIL Step3b: Only {len(relevant_highs)} relevant highs"
    else:
        return f"FAIL Step3b: Only {len(p_highs)} pivot highs total"

    if not flat_resistance_valid:
        return f"FAIL Step3b: Resistance invalid"

    # Breakout check
    if current_price >= flat_resistance_level * 1.005:
        return f"FAIL: Already broke out ({current_price:.6f} >= {flat_resistance_level*1.005:.6f})"

    # Compression check
    gap_first = ((flat_resistance_level - first_hl_price) / flat_resistance_level) * 100
    gap_last = ((flat_resistance_level - last_hl_price) / flat_resistance_level) * 100
    
    if gap_last >= gap_first:
        return f"FAIL: No compression (gap_last={gap_last:.2f}% >= gap_first={gap_first:.2f}%)"
    if gap_last > 4.5:
        return f"FAIL: Gap too wide ({gap_last:.2f}% > 4.5%)"

    compression_pct = ((gap_first - gap_last) / gap_first) * 100 if gap_first > 0 else 0

    # Resistance retest count
    resistance_tolerance = flat_resistance_level * 0.025
    retest_events = 0
    in_zone = False
    for k in range(first_hl_idx, len(df)):
        candle_wick_high = df['high'].iloc[k]
        near_resistance = candle_wick_high >= flat_resistance_level - resistance_tolerance
        if near_resistance and not in_zone:
            retest_events += 1
            in_zone = True
        elif not near_resistance:
            in_zone = False

    # Trendline
    trendline_price = _calc_trendline_value(df, hl_indices)
    if not trendline_price or trendline_price <= 0:
        return f"FAIL Step5: No trendline (projection returned None — HL too far from current candle?)"

    if len(hl_indices) < MIN_HL_TOUCHES or len(hl_indices) > MAX_HL_TOUCHES:
        return f"FAIL: HL count {len(hl_indices)} outside [{MIN_HL_TOUCHES},{MAX_HL_TOUCHES}]"

    # ═══ TAHAP A: PULLBACK CONFIRMED ═══
    if len(df) >= 7:
        lookback_candles = df.iloc[-7:-1]
        max_recent_high = lookback_candles['high'].max()
        pullback_origin_pct = ((max_recent_high - trendline_price) / trendline_price) * 100
        
        if pullback_origin_pct < 1.0:
            return f"FAIL StepA: Price never above trendline (origin={pullback_origin_pct:.2f}% < 1.0%) — recent_high={max_recent_high:.6f} trendline={trendline_price:.6f}"

        bearish_count = sum(1 for _, c in lookback_candles.iterrows() if c['close'] < c['open'])
        if bearish_count < 2:
            return f"FAIL StepA: Not enough bearish candles ({bearish_count}/6 < 2)"

    # ═══ TAHAP B: TOUCH ═══
    triangle_range = flat_resistance_level - trendline_price
    if triangle_range <= 0:
        return f"FAIL StepB: trendline above resistance"

    price_position_pct = ((current_price - trendline_price) / triangle_range) * 100
    if price_position_pct > 40.0:
        return f"FAIL StepB: Price too high in triangle ({price_position_pct:.1f}% > 40%) — price={current_price:.6f} trendline={trendline_price:.6f} resistance={flat_resistance_level:.6f}"
    if price_position_pct < -15.0:
        return f"FAIL StepB: Price below trendline ({price_position_pct:.1f}%)"

    trendline_distance_pct = ((current_price - trendline_price) / trendline_price) * 100
    if trendline_distance_pct < -1.5 or trendline_distance_pct > 1.5:
        return f"FAIL StepB: Too far from trendline ({trendline_distance_pct:.2f}% vs ±1.5%)"

    resistance_distance_pct = ((flat_resistance_level - current_price) / flat_resistance_level) * 100
    if resistance_distance_pct < 2.0:
        return f"FAIL StepB: Too close to resistance ({resistance_distance_pct:.2f}% < 2.0%)"

    # ═══ TAHAP C: BOUNCE ═══
    if len(df) >= 2:
        entry_candle = df.iloc[-1]
        candle_body = entry_candle['close'] - entry_candle['open']
        candle_range = entry_candle['high'] - entry_candle['low']
        lower_wick = min(entry_candle['open'], entry_candle['close']) - entry_candle['low']

        is_bullish = candle_body > 0
        has_wick_rejection = candle_range > 0 and (lower_wick / candle_range) > 0.4

        if not is_bullish and not has_wick_rejection:
            return f"FAIL StepC: No bounce signal (bullish={is_bullish}, wick_reject={has_wick_rejection})"

        candle_low = entry_candle['low']
        low_to_trendline_pct = ((candle_low - trendline_price) / trendline_price) * 100
        if low_to_trendline_pct > 2.0 or low_to_trendline_pct < -2.0:
            return f"FAIL StepC: Candle low not near trendline (low_dist={low_to_trendline_pct:.2f}%)"

    # Retest count
    if retest_events < 2:
        return f"FAIL: Only {retest_events} resistance retests (need >=2)"
    if retest_events > MAX_RESISTANCE_RETEST:
        return f"FAIL: Too many retests ({retest_events} > {MAX_RESISTANCE_RETEST})"

    # Pump candle
    if is_pump_candle(df, atr):
        return f"FAIL Step9: Pump candle detected"

    # Max rise
    recent_high = df['high'].iloc[-30:].max()
    total_rise = ((recent_high - first_hl_price) / first_hl_price) * 100
    if total_rise > 25.0:
        return f"FAIL: Total rise too high ({total_rise:.1f}% > 25%)"

    return f"✅ PASS! HL={len(hl_indices)} retests={retest_events} compression={compression_pct:.1f}% pos={price_position_pct:.1f}% trendline={trendline_price:.6f} resis={flat_resistance_level:.6f}"


# ══════════════════════════════════════════════════════════════
# MAIN: Scan coins like the bot does
# ══════════════════════════════════════════════════════════════
print("Loading markets...")
exchange.load_markets()

# Get same coins as bot
tickers = exchange.fetch_tickers()
swap_tickers = {k: v for k, v in tickers.items() if k.endswith('/USDT:USDT')}

# Sort by volume, top 30
sorted_coins = sorted(swap_tickers.items(), key=lambda x: x[1].get('quoteVolume', 0) or 0, reverse=True)

# Skip blacklisted
skip = set(BLACKLIST_SYMBOLS)
coins = []
for sym, tick in sorted_coins:
    if sym in skip:
        continue
    vol = tick.get('quoteVolume', 0) or 0
    if vol < MIN_VOLUME_24H or vol > MAX_VOLUME_24H:
        continue
    coins.append(sym)
    if len(coins) >= 20:  # Test top 20
        break

print(f"\nTesting {len(coins)} coins across {TIMEFRAMES}...")
print("=" * 80)

results = {}
for sym in coins:
    base = sym.split('/')[0]
    for tf in TIMEFRAMES:
        try:
            ohlcv = exchange.fetch_ohlcv(sym, tf, limit=CANDLE_LOOKBACK)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            result = trace_analyze(df, sym, tf)
            key = f"{base} {tf}"
            results[key] = result
            
            # Print immediately if it passes
            if result.startswith("✅"):
                print(f"  🟢 {key}: {result}")
            
        except Exception as e:
            results[f"{base} {tf}"] = f"ERROR: {e}"
        
        import time
        time.sleep(0.15)

# Print summary grouped by failure reason
print("\n" + "=" * 80)
print("FAILURE BREAKDOWN:")
print("=" * 80)

failure_counts = {}
for key, result in results.items():
    if result.startswith("FAIL"):
        # Extract the step name
        step = result.split(":")[0].replace("FAIL ", "")
        failure_counts[step] = failure_counts.get(step, 0) + 1

for step, count in sorted(failure_counts.items(), key=lambda x: -x[1]):
    print(f"  {count:3d}x  {step}")
    # Show 2 examples
    examples = [f"     → {k}: {v}" for k, v in results.items() if v.startswith(f"FAIL {step}") or v.split(":")[0].replace("FAIL ", "") == step][:2]
    for ex in examples:
        print(ex)

passes = sum(1 for v in results.values() if v.startswith("✅"))
print(f"\nTotal: {len(results)} checks, {passes} PASS, {len(results)-passes} FAIL")
