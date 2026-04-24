"""
Bybit Crypto Algo Bot — Strategy Engine (Kalimasada Pullback Style)
Pure Price Action: Higher Low Trendline + Demand Zone + Volume Rising + Stochastic
Entry at trendline/demand pullback, NEVER at breakout pucuk.
No ML. Pure math. Zero ambiguity.
"""
import logging
import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Tuple
from config import (
    PIVOT_LEFT, PIVOT_RIGHT, MIN_HL_TOUCHES, MAX_HL_TOUCHES, MIN_HL_CANDLE_GAP,
    ACCUM_MIN_CANDLES, ACCUM_MAX_RANGE_PCT,
    VOLUME_BREAKOUT_MULT, STOCH_K, STOCH_SMOOTH_K, STOCH_D,
    STOCH_ENTRY_MIN, STOCH_ENTRY_MAX, SL_BUFFER_PCT, DEFAULT_RR_RATIO,
    TRENDLINE_TOLERANCE_PCT, DEMAND_TOLERANCE_PCT,
    PUCUK_STOCH_THRESHOLD, PUCUK_SMA_DISTANCE_PCT,
    MIN_H4_CANDLES_FOR_STRUCTURE, MIN_D1_CANDLES_FOR_STRUCTURE,
    ATR_SL_MULT, ATR_SL_MULT_DEFAULT,
    PUMP_CANDLE_BODY_MULT, PUMP_RISE_PCT, PUMP_LOOKBACK,
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
        prev_idx = pivot_indices[i - 1]
        curr_idx = pivot_indices[i]

        # [FIX #3] Jarak minimum antar HL harus >= MIN_HL_CANDLE_GAP candle
        # Mencegah 3-4 candle berdekatan diakui sebagai HL palsu
        if (curr_idx - prev_idx) < MIN_HL_CANDLE_GAP:
            continue

        if lows[curr_idx] > lows[prev_idx]:
            current_seq.append(curr_idx)
        else:
            if len(current_seq) > len(best_seq):
                best_seq = current_seq[:]
            current_seq = [curr_idx]

    if len(current_seq) > len(best_seq):
        best_seq = current_seq[:]

    # We need the HL sequence to be recent (last HL within last 30 candles)
    # AND within the allowed touch range (2-5)
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
    Kalimasada v6 — PURE PRICE ACTION

    FOKUS HANYA PADA PRICE ACTION:
    1. Ascending trendline NAIK (Higher Lows, slope positif)
    2. Entry A: Di HL ke-2+ saat pullback menyentuh trendline
    3. Entry B: Di demand zone saat retest ke-3+
    4. TOLAK koin yang sudah pump tinggi
    5. Harga HARUS sedang pullback (turun ke support)

    TIDAK ADA: volume check, stochastic check, consolidation check
    Karena price action adalah RAJA.
    """
    if df is None or len(df) < 50:
        return None

    try:
        atr = calc_atr(df, 14)
        current_price = df['close'].iloc[-1]

        # -- Step 1: Pivots --
        p_lows = detect_pivot_lows(df)
        p_highs = detect_pivot_highs(df)

        if len(p_lows) < 2:
            return None

        # -- Step 2: Higher Lows (ascending trendline NAIK) --
        has_hl, hl_indices = detect_higher_lows(df, p_lows)
        if not has_hl or len(hl_indices) < 2:
            return None  # Butuh minimal 2 HL

        # -- Step 3: ASCENDING SLOPE --
        first_hl_idx = hl_indices[0]
        last_hl_idx = hl_indices[-1]
        first_hl_price = df['low'].iloc[first_hl_idx]
        last_hl_price = df['low'].iloc[last_hl_idx]

        if last_hl_price <= first_hl_price:
            return None  # Trendline TIDAK naik

        candle_span = last_hl_idx - first_hl_idx
        if candle_span <= 0:
            return None
        slope_per_candle = (last_hl_price - first_hl_price) / candle_span

        # -- Step 3b: FLAT RESISTANCE (Atap Datar) --
        # True Ascending Triangle HARUS punya Pivot High yang cluster di level yang sama
        # Ini membedakan Ascending Triangle sejati dengan random uptrend biasa
        FLAT_RESISTANCE_TOLERANCE = 3.0  # max 3% perbedaan antar Pivot High
        flat_resistance_valid = False
        flat_resistance_level = None

        if len(p_highs) >= 2:
            # Ambil pivot high yang relevan: hanya yang berada dalam rentang HL pertama hingga sekarang
            relevant_highs = [i for i in p_highs if i >= first_hl_idx]
            if len(relevant_highs) >= 2:
                # Ambil harga-harga pivot high terbaru
                ph_prices = [df['high'].iloc[i] for i in relevant_highs[-5:]]
                ph_max = max(ph_prices)
                ph_min = min(ph_prices)
                # Cek apakah semua Pivot High berkumpul dalam toleransi 3%
                spread_pct = ((ph_max - ph_min) / ph_max) * 100
                if spread_pct <= FLAT_RESISTANCE_TOLERANCE and len(ph_prices) >= 2:
                    flat_resistance_valid = True
                    flat_resistance_level = (ph_max + ph_min) / 2

        if not flat_resistance_valid:
            return None  # Bukan Ascending Triangle sejati

        # Cek: harga sekarang HARUS di bawah resistance (belum breakout)
        if current_price >= flat_resistance_level * 0.98:
            return None  # Harga sudah di resistance atau sudah breakout = pucuk

        # Cek: jarak HL ke Resistance semakin menyempit (kompresi aktif)
        gap_first_to_resistance = ((flat_resistance_level - first_hl_price) / flat_resistance_level) * 100
        gap_last_to_resistance = ((flat_resistance_level - last_hl_price) / flat_resistance_level) * 100
        if gap_last_to_resistance >= gap_first_to_resistance:
            return None  # Triangle tidak menyempit = bukan kompresi


        # -- Step 4: Demand Zone + Retest Count --
        demand_zones = detect_demand_zones(df, lookback=200)
        nearest_demand = None
        demand_retest_count = 0

        if demand_zones:
            valid_demands = [dz for dz in demand_zones
                            if dz['high'] <= current_price * 1.05]
            if valid_demands:
                nearest_demand = max(valid_demands, key=lambda x: x['high'])

                dz_idx = nearest_demand['index']
                dz_high = nearest_demand['high']

                for k in range(dz_idx + 3, len(df)):
                    candle_low = df['low'].iloc[k]
                    candle_close = df['close'].iloc[k]
                    if candle_low <= dz_high * 1.01 and candle_close > dz_high * 0.99:
                        demand_retest_count += 1

        # -- Step 5: Trendline value --
        trendline_price = _calc_trendline_value(df, hl_indices)

        # -- Step 6: ENTRY CONDITIONS --
        # Entry A: HL ke-2+ trendline touch
        near_trendline = False
        if trendline_price and trendline_price > 0 and len(hl_indices) >= 2:
            distance_pct = ((current_price - trendline_price) / trendline_price) * 100
            near_trendline = (-1.0 <= distance_pct <= 2.0)

        # Entry B: Demand 3x retest
        near_demand_3x = False
        if nearest_demand and demand_retest_count >= 2:
            dz_distance = ((current_price - nearest_demand['mid']) / nearest_demand['mid']) * 100
            near_demand_3x = (-1.0 <= dz_distance <= 2.0)

        if not near_trendline and not near_demand_3x:
            return None

        # -- Step 7: MAX RISE FILTER --
        recent_high = df['high'].iloc[-30:].max()
        total_rise = ((recent_high - first_hl_price) / first_hl_price) * 100
        if total_rise > 25.0:
            return None  # Sudah pump terlalu tinggi

        # -- Step 8: PULLBACK DIRECTION --
        if len(df) >= 4:
            c0 = current_price
            c1 = df['close'].iloc[-2]
            c2 = df['close'].iloc[-3]
            c3 = df['close'].iloc[-4]
            if c0 > c1 > c2 > c3:
                support_level = trendline_price if near_trendline else (nearest_demand['mid'] if nearest_demand else None)
                if support_level and ((c0 - support_level) / support_level * 100) > 1.5:
                    return None  # 4 candle naik berturut, bukan pullback

        # -- Step 9: No pump candles --
        if is_pump_candle(df, atr):
            return None

        # == SIGNAL ==
        entry_price = current_price
        current_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else entry_price * 0.02

        atr_mult = ATR_SL_MULT.get(timeframe, ATR_SL_MULT_DEFAULT)
        atr_sl_distance = current_atr * atr_mult

        if near_trendline and trendline_price:
            trendline_sl = trendline_price * (1 - SL_BUFFER_PCT / 100)
            sl_price = min(trendline_sl, entry_price - atr_sl_distance)
        elif nearest_demand:
            demand_sl = nearest_demand['low'] * (1 - SL_BUFFER_PCT / 100)
            sl_price = min(demand_sl, entry_price - atr_sl_distance)
        else:
            sl_price = entry_price - atr_sl_distance

        min_sl_pct = atr_mult / 100.0
        min_sl_floor = entry_price * min_sl_pct
        if (entry_price - sl_price) < min_sl_floor:
            sl_price = entry_price - min_sl_floor

        sl_distance = entry_price - sl_price
        tp_price = entry_price + (sl_distance * DEFAULT_RR_RATIO)

        sl_pct = ((entry_price - sl_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100

        accum = detect_accumulation_zone(df, p_highs, p_lows)
        resistance = accum['resistance'] if accum else tp_price
        support = trendline_price if trendline_price else sl_price

        hl_prices = [round(df['low'].iloc[i], 6) for i in hl_indices]

        if near_trendline:
            entry_type = 'HL_TRENDLINE_TOUCH'
        else:
            entry_type = 'DEMAND_3X_RETEST'

        vol_sma = calc_volume_sma(df, 20)

        signal = {
            'symbol': symbol,
            'timeframe': timeframe,
            'signal_type': entry_type,
            'entry_price': round(entry_price, 8),
            'sl_price': round(sl_price, 8),
            'tp_price': round(tp_price, 8),
            'sl_pct': round(sl_pct, 2),
            'tp_pct': round(tp_pct, 2),
            'rr_ratio': round(DEFAULT_RR_RATIO, 1),
            'resistance': round(resistance, 8) if resistance else 0,
            'support': round(support, 8),
            'higher_lows': hl_prices,
            'hl_touches': len(hl_indices),
            'demand_zone': nearest_demand,
            'demand_retest_count': demand_retest_count,
            'trendline_price': round(trendline_price, 8) if trendline_price else None,
            'trendline_slope': round(slope_per_candle, 8),
            'total_rise_pct': round(total_rise, 1),
            'volume_ratio': round(df['volume'].iloc[-1] / vol_sma.iloc[-1], 2) if vol_sma.iloc[-1] > 0 else 1.0,
            'atr': round(current_atr, 8),
            'atr_pct': round((current_atr / entry_price) * 100, 2),
            'confidence': min(100, 40 + len(hl_indices) * 15 + (10 if nearest_demand else 0) + min(demand_retest_count * 10, 30)),
        }

        log.info(f"🎯 [{entry_type}]: {symbol} {timeframe} | "
                 f"Entry={entry_price:.6f} SL={sl_price:.6f} ({sl_pct:.1f}%) "
                 f"TP={tp_price:.6f} ({tp_pct:.1f}%) | "
                 f"HL={len(hl_indices)} Slope={slope_per_candle:.6f} Rise={total_rise:.1f}% "
                 f"DemandRetest={demand_retest_count}x")

        return signal

    except Exception as e:
        log.error(f"Strategy error for {symbol} {timeframe}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# KALIMASADA HELPERS — Trendline, Volume Rising, Consolidation
# ══════════════════════════════════════════════════════════════

def _calc_trendline_value(df: pd.DataFrame, hl_indices: List[int]) -> Optional[float]:
    """
    Calculate the expected trendline price at the current candle
    by linearly extrapolating the last 2 higher lows.
    
    [FIX #6] Proyeksi dibatasi maks 10 candle dari HL terakhir.
    Proyeksi terlalu jauh menghasilkan nilai yang tidak akurat dan menyesatkan.
    """
    if len(hl_indices) < 2:
        return None

    idx1 = hl_indices[-2]
    idx2 = hl_indices[-1]
    price1 = df['low'].iloc[idx1]
    price2 = df['low'].iloc[idx2]

    if idx2 == idx1:
        return price2

    slope = (price2 - price1) / (idx2 - idx1)
    current_idx = len(df) - 1
    candles_since_last_hl = current_idx - idx2

    # Batasi proyeksi maks 30 candle dari HL terakhir
    # Harus cukup panjang untuk menangkap pullback yang valid
    if candles_since_last_hl > 30:
        return None

    trendline_at_now = price2 + slope * candles_since_last_hl

    # Trendline must be positive and slope must be upward
    if trendline_at_now <= 0 or slope < 0:
        return None

    return trendline_at_now


def _is_volume_rising(df: pd.DataFrame, lookback: int = 5) -> bool:
    """
    Check if volume is trending up (accumulation signal).
    Recent N candles volume avg must be > prior N candles.
    """
    if len(df) < lookback * 2 + 5:
        return False

    vol = df['volume']
    recent_avg = vol.iloc[-lookback:].mean()
    prior_avg = vol.iloc[-lookback * 2:-lookback].mean()

    if prior_avg <= 0:
        return False

    return recent_avg > prior_avg


def is_pump_candle(df: pd.DataFrame, atr: pd.Series, lookback: int = None) -> bool:
    """
    Pump Candle Detector — detects abnormally large candles on ENTRY timeframe.
    Called INSIDE analyze() to prevent chasing pump candles.
    
    Returns True if PUMP detected (should REJECT entry):
    - ANY of last N candles has body > 2.5x ATR = pump candle, NOT a pullback
    """
    if df is None or len(df) < 10:
        return False
    
    lb = lookback if lookback else PUMP_LOOKBACK
    
    for j in range(1, lb + 1):
        idx = len(df) - j
        if idx < 0:
            break
        body = abs(df['close'].iloc[idx] - df['open'].iloc[idx])
        atr_val = atr.iloc[idx] if idx < len(atr) else None
        if atr_val is not None and not pd.isna(atr_val) and atr_val > 0:
            if body > atr_val * PUMP_CANDLE_BODY_MULT:
                return True  # Pump candle found
    
    return False


def _is_consolidating(df: pd.DataFrame, atr: pd.Series, lookback: int = 5) -> bool:
    """
    Check if recent candles show consolidation (small bodies).
    Big pump candles = NOT consolidating = skip.
    """
    if len(df) < lookback + 1:
        return False

    current_atr = atr.iloc[-1]
    if pd.isna(current_atr) or current_atr <= 0:
        return True  # Can't determine, allow

    recent = df.tail(lookback)
    avg_body = abs(recent['close'] - recent['open']).mean()

    # Consolidation: average body size < 1.5x ATR
    return avg_body < current_atr * 1.5


# ══════════════════════════════════════════════════════════════
# PUCUK PROTECTOR — Anti Entry di Pucuk H4/D1
# ══════════════════════════════════════════════════════════════

def is_pucuk(df: pd.DataFrame) -> bool:
    """
    Pucuk Protector v3 — KETAT. Detect if price is at peak/pump.
    Used on H4 and D1 timeframes to block entries.

    Returns True if PUCUK (should REJECT entry) if ANY of:
    1. Stochastic %K > 75 (Overbought) — turunkan dari 80
    2. Price > 4% above SMA-20 (Overextended) — turunkan dari 8%
    3. ANY of last 5 candles has body > 2.5x ATR (Pump candle)
    4. Price rose > 5% in last 5 candles (Rapid rise)
    """
    if df is None or len(df) < 20:
        return False  # Not enough data, allow

    current_price = df['close'].iloc[-1]

    # Check 1: Stochastic overbought
    stoch_k, _ = calc_stochastic(df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
    k_now = stoch_k.iloc[-1]
    if not pd.isna(k_now) and k_now > 82:
        return True  # PUCUK: Stochastic overbought (82+)

    # Check 2: SMA distance (turunkan ke 4%)
    sma_20 = df['close'].rolling(window=20).mean().iloc[-1]
    if not pd.isna(sma_20) and sma_20 > 0:
        distance_pct = ((current_price - sma_20) / sma_20) * 100
        if distance_pct > 7.0:
            return True  # PUCUK: Price >7% above SMA

    # Check 3: Pump candle detection — ANY candle terakhir body > 2.5x ATR
    atr = calc_atr(df, 14)
    lookback = min(PUMP_LOOKBACK, len(df) - 1)
    for j in range(1, lookback + 1):
        idx = len(df) - j
        body = abs(df['close'].iloc[idx] - df['open'].iloc[idx])
        atr_val = atr.iloc[idx]
        if not pd.isna(atr_val) and atr_val > 0:
            if body > atr_val * PUMP_CANDLE_BODY_MULT:
                return True  # PUCUK: Pump candle detected

    # Check 4: Rapid rise — harga naik > 5% dalam 5 candle
    if len(df) > PUMP_LOOKBACK:
        old_price = df['close'].iloc[-PUMP_LOOKBACK - 1]
        if old_price > 0:
            rise_pct = ((current_price - old_price) / old_price) * 100
            if rise_pct > PUMP_RISE_PCT:
                return True  # PUCUK: Rapid rise, momentum exhaustion

    return False  # Not pucuk, safe to enter


# ══════════════════════════════════════════════════════════════
# CANDLE STRUCTURE VALIDATOR — Bukan 1-3 Candle Besar di H4/D1
# ══════════════════════════════════════════════════════════════

def is_real_structure(lower_df: pd.DataFrame, higher_df: pd.DataFrame,
                      hl_indices: List[int], min_higher_candles: int = 4) -> bool:
    """
    Validates that the HL/HH pattern on lower TF (M15/H1)
    spans enough candles on higher TF (H4/D1).

    If the pattern only covers 1-3 candles on H4/D1,
    it's just a big pump candle — NOT a real trend structure.

    Returns True if VALID (real structure), False if FAKE.
    """
    if (lower_df is None or higher_df is None or
            not hl_indices or len(hl_indices) < 2):
        return False

    if 'timestamp' not in lower_df.columns or 'timestamp' not in higher_df.columns:
        return False

    try:
        # Time range of the HL pattern on lower TF
        start_time = lower_df['timestamp'].iloc[hl_indices[0]]
        end_time = lower_df['timestamp'].iloc[-1]

        # Count how many higher TF candles fall in this range
        mask = ((higher_df['timestamp'] >= start_time) &
                (higher_df['timestamp'] <= end_time))
        higher_candles = mask.sum()

        return higher_candles >= min_higher_candles
    except Exception:
        return False


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
    
    return score

def is_bullish_structure(df: pd.DataFrame) -> bool:
    """
    Pure Price Action trend detection for Triple Screen (H1/H4).
    
    [FIX v2] KETAT — Tidak ada fallback.
    Trend diakui Bullish HANYA jika:
    1. Pivot Low terakhir > pivot Low sebelumnya (Higher Low terkonfirmasi), DAN
    2. Harga Close saat ini > SMA-20 (uptrend jangka menengah terkonfirmasi).
    
    Jika TIDAK ADA Higher Low yang valid, return False. Titik.
    """
    if len(df) < 25:
        return False

    c = df['close'].iloc[-1]

    # SMA-20 sebagai filter tren dasar
    sma20 = df['close'].rolling(window=20).mean().iloc[-1]
    if pd.isna(sma20) or c <= sma20:
        return False  # Harga di bawah SMA-20 = TIDAK bullish

    # EMA-50 sebagai filter tren menengah (mencegah bear rally)
    ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    if pd.isna(ema50) or c <= ema50:
        return False  # Harga di bawah EMA-50 = masih dalam downtrend

    # Higher Low check via Pivots — WAJIB ada pola HL yang valid
    p_lows = detect_pivot_lows(df)
    if len(p_lows) >= 2:
        last_low = df['low'].iloc[p_lows[-1]]
        prev_low = df['low'].iloc[p_lows[-2]]
        if last_low > prev_low:
            return True  # Tren terkonfirmasi: HL + SMA20 + EMA50

    # TIDAK ADA FALLBACK — tanpa HL yang valid, TOLAK
    return False


def is_macro_bullish(d1_df: pd.DataFrame) -> bool:
    """
    Macro trend filter menggunakan EMA-50 pada Daily timeframe.
    Jika harga D1 di bawah EMA-50, market sedang bearish — JANGAN entry long.
    """
    if d1_df is None or len(d1_df) < 55:
        return False
    
    c = d1_df['close'].iloc[-1]
    ema50 = d1_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    sma20 = d1_df['close'].rolling(window=20).mean().iloc[-1]
    
    if pd.isna(ema50) or pd.isna(sma20):
        return False
    
    # Harga HARUS di atas EMA-50 DAN SMA-20 pada Daily
    return c > ema50 and c > sma20


def is_volume_confirmed(df: pd.DataFrame, lookback: int = 20) -> bool:
    """
    Volume confirmation for Triple Screen Multi-Timeframe.
    Checks if the recent volume on H1/H4 is above its SMA (avg of last N candles).
    This confirms that institutional money flow supports the M15 breakout.
    
    Returns True if current volume > average volume (buying pressure present).
    """
    if df is None or len(df) < lookback:
        return False
    
    vol = df['volume']
    vol_sma = vol.tail(lookback).mean()
    vol_now = vol.iloc[-1]
    
    # Volume on the higher timeframe must be at least equal to its average
    return vol_now >= vol_sma


# ══════════════════════════════════════════════════════════════
# SHORT TRADING — Mirror of LONG logic for bearish markets
# ══════════════════════════════════════════════════════════════

def detect_lower_highs(df: pd.DataFrame, p_highs: List[int]) -> Tuple[bool, List[int]]:
    """
    Detect Lower Highs pattern — mirror of Higher Lows.
    Each pivot high must be LOWER than the previous one.
    """
    if len(p_highs) < MIN_HL_TOUCHES:
        return False, []

    lh_indices = [p_highs[0]]
    for i in range(1, len(p_highs)):
        curr_high = df['high'].iloc[p_highs[i]]
        prev_high = df['high'].iloc[lh_indices[-1]]
        gap = p_highs[i] - lh_indices[-1]

        if curr_high < prev_high and gap >= MIN_HL_CANDLE_GAP:
            lh_indices.append(p_highs[i])

    if len(lh_indices) < MIN_HL_TOUCHES:
        return False, []
    if len(lh_indices) > MAX_HL_TOUCHES:
        lh_indices = lh_indices[-MAX_HL_TOUCHES:]

    return True, lh_indices


def _calc_resistance_trendline(df: pd.DataFrame, lh_indices: List[int]) -> Optional[float]:
    """Calculate resistance trendline from Lower Highs (for short entries)."""
    if len(lh_indices) < 2:
        return None

    idx1 = lh_indices[-2]
    idx2 = lh_indices[-1]
    price1 = df['high'].iloc[idx1]
    price2 = df['high'].iloc[idx2]

    if idx2 == idx1:
        return price2

    slope = (price2 - price1) / (idx2 - idx1)
    current_idx = len(df) - 1
    candles_since = current_idx - idx2

    if candles_since > 10:
        return None

    trendline_at_now = price2 + slope * candles_since

    if trendline_at_now <= 0 or slope > 0:  # slope harus negatif untuk downtrend
        return None

    return trendline_at_now


def is_bearish_structure(df: pd.DataFrame) -> bool:
    """
    Bearish structure detection — mirror of is_bullish_structure.
    Returns True if H4/D1 shows confirmed downtrend:
    1. Pivot High terakhir < pivot High sebelumnya (Lower High), DAN
    2. Harga < SMA-20 DAN < EMA-50
    """
    if len(df) < 25:
        return False

    c = df['close'].iloc[-1]
    sma20 = df['close'].rolling(window=20).mean().iloc[-1]
    if pd.isna(sma20) or c >= sma20:
        return False

    ema50 = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    if pd.isna(ema50) or c >= ema50:
        return False

    p_highs = detect_pivot_highs(df)
    if len(p_highs) >= 2:
        last_high = df['high'].iloc[p_highs[-1]]
        prev_high = df['high'].iloc[p_highs[-2]]
        if last_high < prev_high:
            return True

    return False


def is_macro_bearish(d1_df: pd.DataFrame) -> bool:
    """
    Macro bearish filter — D1 harus di bawah EMA-50 untuk konfirmasi downtrend.
    """
    if d1_df is None or len(d1_df) < 55:
        return False

    c = d1_df['close'].iloc[-1]
    ema50 = d1_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    sma20 = d1_df['close'].rolling(window=20).mean().iloc[-1]

    if pd.isna(ema50) or pd.isna(sma20):
        return False

    return c < ema50 and c < sma20


def is_dasar(df: pd.DataFrame) -> bool:
    """
    Dasar (Bottom) Protector — mirror of is_pucuk.
    Blocks SHORT entries when price is already at oversold bottom.
    Returns True if DASAR (should REJECT short entry).
    """
    if df is None or len(df) < 20:
        return False

    stoch_k, _ = calc_stochastic(df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
    k_now = stoch_k.iloc[-1]
    if not pd.isna(k_now) and k_now < (100 - PUCUK_STOCH_THRESHOLD):  # < 20
        return True

    sma_20 = df['close'].rolling(window=20).mean().iloc[-1]
    current_price = df['close'].iloc[-1]
    if not pd.isna(sma_20) and sma_20 > 0:
        distance_pct = ((sma_20 - current_price) / sma_20) * 100
        if distance_pct > PUCUK_SMA_DISTANCE_PCT:
            return True

    return False


def check_stochastic_short(stoch_k: pd.Series, stoch_d: pd.Series) -> Tuple[bool, Dict]:
    """
    Stochastic confirmation for SHORT — bearish cross from overbought.
    """
    if len(stoch_k) < 3 or len(stoch_d) < 3:
        return False, {}

    k_now = stoch_k.iloc[-1]
    k_prev = stoch_k.iloc[-2]
    d_now = stoch_d.iloc[-1]
    d_prev = stoch_d.iloc[-2]

    if pd.isna(k_now) or pd.isna(d_now):
        return False, {}

    details = {'stoch_k': round(k_now, 1), 'stoch_d': round(d_now, 1), 'signal': ''}

    # Bearish cross: K was above D, now below D
    is_bearish_cross = (k_prev >= d_prev) and (k_now < d_now)
    # Sweet spot: 50-80 (overbought zone tapi belum extreme)
    is_in_sweet_spot = (k_now >= (100 - STOCH_ENTRY_MAX)) and (k_now <= (100 - STOCH_ENTRY_MIN))

    if is_bearish_cross and is_in_sweet_spot:
        details['signal'] = 'BEARISH_CROSS_SWEET_SPOT'
        return True, details

    return False, details


def analyze_short(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict]:
    """
    Kalimasada SHORT Strategy — Entry at Resistance/LH Trendline Pullback.
    Mirror of analyze() for bearish markets.

    Pipeline:
    1. Calculate indicators
    2. Detect pivot highs
    3. Detect Lower Highs (LH trendline)
    4. Check: is price NEAR resistance trendline?
    5. Check: is volume rising?
    6. Check: Stochastic bearish cross from high area
    7. Calculate SL/TP (inverted)
    """
    if df is None or len(df) < 50:
        return None

    try:
        stoch_k, stoch_d = calc_stochastic(df, STOCH_K, STOCH_SMOOTH_K, STOCH_D)
        vol_sma = calc_volume_sma(df, 20)
        atr = calc_atr(df, 14)

        p_highs = detect_pivot_highs(df)
        p_lows = detect_pivot_lows(df)

        if len(p_highs) < 2:
            return None

        has_lh, lh_indices = detect_lower_highs(df, p_highs)
        if not has_lh:
            return None

        # Resistance trendline
        resistance_price = _calc_resistance_trendline(df, lh_indices)
        current_price = df['close'].iloc[-1]

        near_resistance = False
        if resistance_price and resistance_price > 0:
            distance_pct = ((resistance_price - current_price) / resistance_price) * 100
            near_resistance = (-0.5 <= distance_pct <= TRENDLINE_TOLERANCE_PCT)

        if not near_resistance:
            return None

        # Volume rising
        if not _is_volume_rising(df):
            return None

        # Stochastic bearish
        stoch_ok, stoch_info = check_stochastic_short(stoch_k, stoch_d)
        if not stoch_ok:
            return None

        # Consolidation check
        if not _is_consolidating(df, atr):
            return None

        # === SIGNAL — SHORT ===
        entry_price = current_price
        current_atr = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else entry_price * 0.02

        atr_mult = ATR_SL_MULT.get(timeframe, ATR_SL_MULT_DEFAULT)
        atr_sl_distance = current_atr * atr_mult

        # SL ABOVE resistance, TP BELOW entry
        if resistance_price:
            resistance_sl = resistance_price * (1 + SL_BUFFER_PCT / 100)
            sl_price = max(resistance_sl, entry_price + atr_sl_distance)
        else:
            sl_price = entry_price + atr_sl_distance

        sl_distance = sl_price - entry_price
        tp_price = entry_price - (sl_distance * DEFAULT_RR_RATIO)

        sl_pct = ((sl_price - entry_price) / entry_price) * 100
        tp_pct = ((entry_price - tp_price) / entry_price) * 100

        signal = {
            'symbol': symbol,
            'timeframe': timeframe,
            'signal_type': 'SHORT_RESISTANCE_PULLBACK',
            'direction': 'SHORT',
            'entry_price': round(entry_price, 8),
            'sl_price': round(sl_price, 8),
            'tp_price': round(tp_price, 8),
            'sl_pct': round(sl_pct, 2),
            'tp_pct': round(tp_pct, 2),
            'rr_ratio': round(DEFAULT_RR_RATIO, 1),
            'lower_highs': [round(df['high'].iloc[i], 6) for i in lh_indices],
            'lh_touches': len(lh_indices),
            'resistance_price': round(resistance_price, 8) if resistance_price else None,
            'stoch_k': stoch_info.get('stoch_k', 0),
            'stoch_d': stoch_info.get('stoch_d', 0),
            'stoch_signal': stoch_info.get('signal', ''),
            'atr': round(current_atr, 8),
            'confidence': 50,
        }

        log.info(f"🎯 SHORT SIGNAL: {symbol} {timeframe} | "
                 f"Entry={entry_price:.6f} SL={sl_price:.6f} ({sl_pct:.1f}%) "
                 f"TP={tp_price:.6f} ({tp_pct:.1f}%)")

        return signal

    except Exception as e:
        log.error(f"Short strategy error for {symbol} {timeframe}: {e}")
        return None
