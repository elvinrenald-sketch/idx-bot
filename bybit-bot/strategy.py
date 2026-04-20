"""
Bybit Crypto Algo Bot — Strategy Engine
Pure Price Action: Accumulation Zone + Higher Low + Breakout + Volume + Stochastic
No ML. Pure math. Zero ambiguity.
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
from config import (
    PIVOT_LEFT, PIVOT_RIGHT, MIN_HL_TOUCHES, MAX_HL_TOUCHES,
    ACCUM_MIN_CANDLES, ACCUM_MAX_RANGE_PCT,
    VOLUME_BREAKOUT_MULT, STOCH_K, STOCH_SMOOTH_K, STOCH_D,
    STOCH_ENTRY_MIN, STOCH_ENTRY_MAX, SL_BUFFER_PCT, DEFAULT_RR_RATIO,
)

log = logging.getLogger('strategy')


# ══════════════════════════════════════════════════════════════
# INDICATORS — Hand-coded, zero external TA dependencies
# ══════════════════════════════════════════════════════════════

def calc_stochastic(df: pd.DataFrame, k: int = 5, smooth_k: int = 3,
                    d: int = 3) -> Tuple[pd.Series, pd.Series]:
    """
    Stochastic Oscillator (%K, %D).
    Settings: (5, 3, 3) — fast, responsive to momentum shifts.
    """
    low_min = df['low'].rolling(window=k, min_periods=k).min()
    high_max = df['high'].rolling(window=k, min_periods=k).max()
    denominator = high_max - low_min
    # Avoid division by zero
    denominator = denominator.replace(0, np.nan)
    fast_k = 100.0 * (df['close'] - low_min) / denominator
    slow_k = fast_k.rolling(window=smooth_k, min_periods=1).mean()
    slow_d = slow_k.rolling(window=d, min_periods=1).mean()
    return slow_k, slow_d


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — used for volatility-based leverage."""
    high_low = df['high'] - df['low']
    high_prev_close = (df['high'] - df['close'].shift(1)).abs()
    low_prev_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


def calc_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Simple Moving Average of volume."""
    return df['volume'].rolling(window=period, min_periods=1).mean()


# ══════════════════════════════════════════════════════════════
# PIVOT DETECTION
# ══════════════════════════════════════════════════════════════

def detect_pivot_lows(df: pd.DataFrame, left: int = PIVOT_LEFT,
                      right: int = PIVOT_RIGHT) -> List[int]:
    """
    Detect pivot low points.
    A pivot low at index i means: low[i] <= all lows in window [i-left : i+right].
    """
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


def detect_pivot_highs(df: pd.DataFrame, left: int = PIVOT_LEFT,
                       right: int = PIVOT_RIGHT) -> List[int]:
    """Detect pivot high points."""
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


# ══════════════════════════════════════════════════════════════
# DEMAND ZONE DETECTION
# ══════════════════════════════════════════════════════════════

def detect_demand_zones(df: pd.DataFrame, lookback: int = 100) -> List[Dict]:
    """
    Detect demand zones — areas where price previously bounced strongly.
    A demand zone = a big bullish reaction after a decline.
    """
    zones = []
    start = max(3, len(df) - lookback)

    for i in range(start, len(df) - 1):
        body = df['close'].iloc[i] - df['open'].iloc[i]
        candle_range = df['high'].iloc[i] - df['low'].iloc[i]

        if candle_range <= 0:
            continue

        body_ratio = body / candle_range

        # Strong bullish candle (body > 55% of range, close > open)
        if body_ratio < 0.55:
            continue

        # Check that this came after a decline (previous 3 candles trended down)
        prev_avg_close = df['close'].iloc[max(0, i - 3):i].mean()
        if df['low'].iloc[i] >= prev_avg_close:
            continue  # No decline before this candle

        # This is a demand zone
        zone_low = df['low'].iloc[i]
        zone_high = min(df['open'].iloc[i], df['close'].iloc[i])  # body low
        # Extend zone slightly
        zone_mid = (zone_low + zone_high) / 2

        zones.append({
            'low': zone_low,
            'high': zone_high,
            'mid': zone_mid,
            'index': i,
            'strength': body_ratio,
        })

    return zones


# ══════════════════════════════════════════════════════════════
# HIGHER LOW DETECTION
# ══════════════════════════════════════════════════════════════

def detect_higher_lows(df: pd.DataFrame, pivot_indices: List[int],
                       min_touches: int = MIN_HL_TOUCHES,
                       max_touches: int = MAX_HL_TOUCHES) -> Tuple[bool, List[int]]:
    """
    Check if pivot lows form a series of higher lows.
    Returns (is_valid, list_of_hl_indices).
    Need at least `min_touches` consecutive higher lows.
    """
    if len(pivot_indices) < 2:
        return False, []

    lows = df['low'].values

    # Find longest consecutive higher-low sequence ending near the latest candles
    best_seq = []
    current_seq = [pivot_indices[0]]

    for i in range(1, len(pivot_indices)):
        if lows[pivot_indices[i]] > lows[pivot_indices[i - 1]]:
            current_seq.append(pivot_indices[i])
        else:
            if len(current_seq) > len(best_seq):
                best_seq = current_seq[:]
            current_seq = [pivot_indices[i]]

    if len(current_seq) > len(best_seq):
        best_seq = current_seq[:]

    # We need the HL sequence to be recent (last HL within last 30 candles)
    # AND within the allowed touch range (2-3)
    if best_seq and best_seq[-1] >= len(df) - 30 and min_touches <= len(best_seq) <= max_touches:
        return True, best_seq


    return False, []


# ══════════════════════════════════════════════════════════════
# ACCUMULATION ZONE DETECTION
# ══════════════════════════════════════════════════════════════

def detect_accumulation_zone(df: pd.DataFrame, pivot_highs: List[int],
                             pivot_lows: List[int]) -> Optional[Dict]:
    """
    Detect accumulation zone (price ranging sideways in a box).
    The purple box from the screenshot.

    Returns: {support, resistance, start_idx, end_idx, range_pct}
    """
    n = len(df)
    if n < ACCUM_MIN_CANDLES + 10:
        return None

    # Look at the recent portion (last 60 candles) for ranging behavior
    lookback = min(60, n - 10)
    recent = df.iloc[-lookback:]

    # Find the resistance and support of this zone
    # Use recent pivot highs for resistance
    recent_p_highs = [i for i in pivot_highs if i >= n - lookback]
    recent_p_lows = [i for i in pivot_lows if i >= n - lookback]

    if len(recent_p_highs) < 2 or len(recent_p_lows) < 1:
        # Fallback: use rolling high/low
        resistance = recent['high'].rolling(window=10).max().iloc[-5:].median()
        support = recent['low'].rolling(window=10).min().iloc[-5:].median()
    else:
        resistance = np.mean([df['high'].iloc[i] for i in recent_p_highs[-3:]])
        support = np.mean([df['low'].iloc[i] for i in recent_p_lows[-3:]])

    if resistance <= support or support <= 0:
        return None

    range_pct = ((resistance - support) / support) * 100

    if range_pct > ACCUM_MAX_RANGE_PCT:
        return None  # Range too wide, not accumulation

    # Check that price has been in this zone for enough candles
    candles_in_zone = 0
    zone_start = n - lookback
    for i in range(n - lookback, n):
        if df['low'].iloc[i] >= support * 0.98 and df['high'].iloc[i] <= resistance * 1.02:
            candles_in_zone += 1

    if candles_in_zone < ACCUM_MIN_CANDLES:
        return None

    return {
        'support': support,
        'resistance': resistance,
        'range_pct': range_pct,
        'start_idx': zone_start,
        'candles_in_zone': candles_in_zone,
    }


# ══════════════════════════════════════════════════════════════
# BREAKOUT DETECTION — The final trigger
# ══════════════════════════════════════════════════════════════

def check_breakout(df: pd.DataFrame, resistance: float,
                   vol_sma: pd.Series) -> Tuple[bool, Dict]:
    """
    Check if the latest candle(s) broke above resistance with volume confirmation.
    Returns (is_breakout, details).
    """
    if len(df) < 3:
        return False, {}

    # Check the LAST CLOSED candle (index -2) or current (-1)
    # Use -2 to avoid false breakouts on incomplete candles
    # But if -1 already closed above, use it
    for offset in [-1, -2]:
        idx = len(df) + offset
        if idx < 0:
            continue

        candle_close = df['close'].iloc[offset]
        candle_high = df['high'].iloc[offset]
        candle_vol = df['volume'].iloc[offset]
        avg_vol = vol_sma.iloc[offset] if not pd.isna(vol_sma.iloc[offset]) else 1.0

        # Condition 1: CLOSE above resistance
        if candle_close <= resistance:
            continue

        # Condition 2: Volume confirmation
        if avg_vol <= 0:
            continue
        vol_ratio = candle_vol / avg_vol
        if vol_ratio < VOLUME_BREAKOUT_MULT:
            continue

        # Condition 3: The breakout candle should be bullish
        if candle_close <= df['open'].iloc[offset]:
            continue  # Bearish candle, not a real breakout

        return True, {
            'breakout_price': candle_close,
            'breakout_high': candle_high,
            'volume_ratio': round(vol_ratio, 2),
            'candle_index': idx,
        }

    return False, {}


# ══════════════════════════════════════════════════════════════
# STOCHASTIC CONFIRMATION
# ══════════════════════════════════════════════════════════════

def check_stochastic(stoch_k: pd.Series, stoch_d: pd.Series) -> Tuple[bool, Dict]:
    """
    Stochastic confirmation for entry (Sweet Spot 20-38):
    1. MUST be a Bullish Cross (%K crosses above %D).
    2. Value MUST be between 20 and 38 (The 'Sweet Spot').
    3. Skip if already above 38 (Too late) or Crossing Down.

    Returns (is_confirmed, details).
    """
    if len(stoch_k) < 3:
        return False, {}

    k_now = stoch_k.iloc[-1]
    d_now = stoch_d.iloc[-1]
    k_prev = stoch_k.iloc[-2]
    d_prev = stoch_d.iloc[-2]

    if pd.isna(k_now) or pd.isna(d_now):
        return False, {}

    details = {
        'stoch_k': round(k_now, 1),
        'stoch_d': round(d_now, 1),
        'signal': '',
    }

    # 1. Condition: Bullish Cross (%K was below D, now above D)
    is_bullish_cross = (k_prev <= d_prev) and (k_now > d_now)
    
    # 2. Condition: Within Sweet Spot (20 to 38)
    # Using STOCH_ENTRY_MIN (20) and STOCH_ENTRY_MAX (38)
    is_in_sweet_spot = (k_now >= STOCH_ENTRY_MIN) and (k_now <= STOCH_ENTRY_MAX)

    if is_bullish_cross and is_in_sweet_spot:
        details['signal'] = 'BULLISH_CROSS_SWEET_SPOT'
        return True, details
    
    # Rationale for Rejection (for logs)
    if k_now > STOCH_ENTRY_MAX:
        details['signal'] = 'REJECT_OVEREXTENDED'
    elif k_now < d_now:
        details['signal'] = 'REJECT_BEARISH_STATE'
    elif not is_bullish_cross:
        details['signal'] = 'REJECT_NO_CROSS'
    else:
        details['signal'] = 'REJECT_OUT_OF_RANGE'

    return False, details


# ══════════════════════════════════════════════════════════════
# MAIN ANALYSIS — Combines everything
# ══════════════════════════════════════════════════════════════

def analyze(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict]:
    """
    Full analysis pipeline for one coin on one timeframe.

    Pipeline:
    1. Calculate indicators (Stochastic, Volume SMA, ATR)
    2. Detect pivot lows/highs
    3. Detect demand zones
    4. Detect higher lows (2-3 touches)
    5. Detect accumulation zone
    6. Check breakout (close > resistance + volume)
    7. Check Stochastic confirmation
    8. Calculate SL/TP

    Returns signal dict or None.
    """
    if df is None or len(df) < 50:
        return None

    try:
        # ── Step 1: Indicators ──────────────────────────────
        stoch_k, stoch_d = calc_stochastic(df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
        vol_sma = calc_volume_sma(df, 20)
        atr = calc_atr(df, 14)

        # ── Step 2: Pivots ──────────────────────────────────
        p_lows = detect_pivot_lows(df)
        p_highs = detect_pivot_highs(df)

        if len(p_lows) < 2:
            return None  # Not enough structure

        # ── Step 3: Demand Zones ────────────────────────────
        demand_zones = detect_demand_zones(df)

        # ── Step 4: Higher Lows ─────────────────────────────
        has_hl, hl_indices = detect_higher_lows(df, p_lows)
        if not has_hl:
            return None  # No higher low structure

        # ── Step 5: Accumulation Zone ───────────────────────
        accum = detect_accumulation_zone(df, p_highs, p_lows)
        if accum is None:
            return None  # No accumulation zone detected

        resistance = accum['resistance']
        support = accum['support']

        # ── Step 6: Breakout Check ──────────────────────────
        is_breakout, breakout_info = check_breakout(df, resistance, vol_sma)
        if not is_breakout:
            return None  # No breakout yet

        # ── Step 7: Stochastic Confirmation ─────────────────
        stoch_ok, stoch_info = check_stochastic(stoch_k, stoch_d)
        if not stoch_ok:
            return None  # Stochastic doesn't confirm

        # ══ ALL CONDITIONS MET — GENERATE SIGNAL ══
        entry_price = breakout_info['breakout_price']
        current_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else entry_price * 0.02

        # SL: Below the support zone with buffer
        sl_price = support * (1 - SL_BUFFER_PCT / 100)

        # Ensure SL is at least 1% below entry
        max_sl = entry_price * 0.99
        if sl_price > max_sl:
            sl_price = max_sl

        # TP: Risk:Reward ratio
        sl_distance = entry_price - sl_price
        tp_price = entry_price + (sl_distance * DEFAULT_RR_RATIO)

        # SL/TP percentages
        sl_pct = ((entry_price - sl_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100

        # Find nearest demand zone to current price
        nearest_demand = None
        if demand_zones:
            valid_demands = [dz for dz in demand_zones if dz['high'] <= entry_price]
            if valid_demands:
                nearest_demand = max(valid_demands, key=lambda x: x['high'])

        # Higher Low values
        hl_prices = [round(df['low'].iloc[i], 6) for i in hl_indices]

        signal = {
            'symbol': symbol,
            'timeframe': timeframe,
            'signal_type': 'BREAKOUT_LONG',
            'entry_price': round(entry_price, 8),
            'sl_price': round(sl_price, 8),
            'tp_price': round(tp_price, 8),
            'sl_pct': round(sl_pct, 2),
            'tp_pct': round(tp_pct, 2),
            'rr_ratio': round(DEFAULT_RR_RATIO, 1),

            # Structure
            'resistance': round(resistance, 8),
            'support': round(support, 8),
            'accum_range_pct': round(accum['range_pct'], 2),
            'accum_candles': accum['candles_in_zone'],
            'higher_lows': hl_prices,
            'hl_touches': len(hl_indices),
            'demand_zone': nearest_demand,

            # Confirmations
            'volume_ratio': breakout_info['volume_ratio'],
            'stoch_k': stoch_info['stoch_k'],
            'stoch_d': stoch_info['stoch_d'],
            'stoch_signal': stoch_info['signal'],
            'atr': round(current_atr, 8),
            'atr_pct': round((current_atr / entry_price) * 100, 2),

            # Confidence score (simple weighted)
            'confidence': _calc_confidence(
                hl_touches=len(hl_indices),
                vol_ratio=breakout_info['volume_ratio'],
                stoch_signal=stoch_info['signal'],
                has_demand=nearest_demand is not None,
                accum_candles=accum['candles_in_zone'],
            ),
        }

        log.info(f"🎯 SIGNAL: {symbol} {timeframe} | "
                 f"Entry={entry_price:.6f} SL={sl_price:.6f} ({sl_pct:.1f}%) "
                 f"TP={tp_price:.6f} ({tp_pct:.1f}%) | "
                 f"Vol={breakout_info['volume_ratio']}x "
                 f"Stoch={stoch_info['stoch_k']:.0f}/{stoch_info['stoch_d']:.0f} "
                 f"HL={len(hl_indices)} touches | "
                 f"Conf={signal['confidence']}")

        return signal

    except Exception as e:
        log.error(f"Strategy error for {symbol} {timeframe}: {e}")
        return None


def _calc_confidence(hl_touches: int, vol_ratio: float, stoch_signal: str,
                     has_demand: bool, accum_candles: int) -> int:
    """
    Simple confidence score 0-100 based on signal quality.
    Not ML — just weighted checklist.
    """
    score = 0

    # Higher Lows (max 30 pts)
    score += min(30, hl_touches * 12)

    # Volume (max 25 pts)
    if vol_ratio >= 3.0:
        score += 25
    elif vol_ratio >= 2.0:
        score += 20
    elif vol_ratio >= 1.5:
        score += 15

    # Stochastic quality (max 20 pts)
    stoch_scores = {
        'BULLISH_CROSS_SWEET_SPOT': 20,
    }
    score += stoch_scores.get(stoch_signal, 0)

    # Demand zone present (15 pts)
    if has_demand:
        score += 15

    # Accumulation duration (max 10 pts)
    score += min(10, accum_candles)


def is_bullish_structure(df: pd.DataFrame) -> bool:
    """
    Pure Price Action trend detection for Triple Screen (H1/H4).
    Trend is Bullish if:
    1. Most recent pivot is a Higher Low OR
    2. Last 5 candles show an upward slope (Price > SMA5) OR
    3. Current candle closed bullish and above previous high.
    
    This avoids EMA dependency while ensuring we don't buy into a crash.
    """
    if len(df) < 10:
        return False
        
    c = df['close'].iloc[-1]
    o = df['open'].iloc[-1]
    
    # 1. Higher Low check via Pivots
    p_lows = detect_pivot_lows(df)
    if len(p_lows) >= 2:
        last_low = df['low'].iloc[p_lows[-1]]
        prev_low = df['low'].iloc[p_lows[-2]]
        if last_low > prev_low and c > last_low:
            return True
            
    # 2. Short-term momentum check (Price Action)
    # Price is above the average of the last 5 candles
    sma5 = df['close'].tail(5).mean()
    if c > sma5:
        # Also need current candle to be not too bearish
        if c >= o or (o - c) < (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.3:
            return True
            
    return False
