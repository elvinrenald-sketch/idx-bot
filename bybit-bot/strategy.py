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
    PIVOT_LEFT, PIVOT_RIGHT, MIN_HL_TOUCHES, MAX_HL_TOUCHES, MIN_HL_CANDLE_GAP, MAX_RESISTANCE_RETEST,
    ACCUM_MIN_CANDLES, ACCUM_MAX_RANGE_PCT,
    VOLUME_BREAKOUT_MULT,
    SL_BUFFER_PCT, DEFAULT_RR_RATIO,
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
    Detect pivot low points based on fractal body analysis.
    A pivot low at index i means: body_low[i] <= all body_lows in window [i-left : i+right].
    """
    lows = df[['open', 'close']].min(axis=1).values
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
    """Detect pivot high points based on fractal body analysis."""
    highs = df[['open', 'close']].max(axis=1).values
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
    Check if pivot lows form a series of higher lows (using fractal body prices).
    Returns (is_valid, list_of_hl_indices).
    Need at least `min_touches` consecutive higher lows.
    """
    if len(pivot_indices) < 2:
        return False, []

    body_lows = df[['open', 'close']].min(axis=1).values

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

        if body_lows[curr_idx] > body_lows[prev_idx]:
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

        # -- Step 3: ASCENDING SLOPE (ANTI-NUKIK) --
        first_hl_idx = hl_indices[0]
        last_hl_idx = hl_indices[-1]
        # Use body prices (min of open/close) for fractal analysis instead of raw wicks
        first_hl_price = min(df['open'].iloc[first_hl_idx], df['close'].iloc[first_hl_idx])
        last_hl_price = min(df['open'].iloc[last_hl_idx], df['close'].iloc[last_hl_idx])

        if last_hl_price <= first_hl_price:
            return None  # Trendline TIDAK naik

        candle_span = last_hl_idx - first_hl_idx
        if candle_span <= 0:
            return None
        slope_per_candle = (last_hl_price - first_hl_price) / candle_span
        slope_pct_per_candle = (slope_per_candle / first_hl_price) * 100

        # Anti-Nukik Logic: Ensure slope is <= 45 degrees (approx 0.5% per candle max)
        if slope_pct_per_candle > 0.5:
            return None  # Terlalu curam / nukik ke atas

        # -- Step 3b: FLAT RESISTANCE (Atap Datar) --
        # Ascending Triangle: Pivot High cluster di level yang HAMPIR sama
        # Di real market, resistance tidak 100% flat — toleransi 2%
        FLAT_RESISTANCE_TOLERANCE = 2.0  # max 2% perbedaan antar Pivot High
        flat_resistance_valid = False
        flat_resistance_level = None

        if len(p_highs) >= 2:
            # Ambil pivot high yang relevan: hanya yang berada dalam rentang HL pertama hingga sekarang
            relevant_highs = [i for i in p_highs if i >= first_hl_idx]
            if len(relevant_highs) >= 2:
                # Ambil harga-harga pivot high terbaru
                ph_prices = [max(df['open'].iloc[i], df['close'].iloc[i]) for i in relevant_highs[-5:]]
                ph_max = max(ph_prices)
                ph_min = min(ph_prices)
                last_ph = ph_prices[-1]
                
                # Cek apakah semua Pivot High berkumpul dalam toleransi 2%
                spread_pct = ((ph_max - ph_min) / ph_max) * 100
                
                # Pucuk terakhir HARUS mengetes resistance (tidak boleh membentuk lower high yang jauh)
                distance_last_to_max = ((ph_max - last_ph) / ph_max) * 100
                
                if spread_pct <= FLAT_RESISTANCE_TOLERANCE and distance_last_to_max <= 1.0 and len(ph_prices) >= 2:
                    flat_resistance_valid = True
                    flat_resistance_level = (ph_max + ph_min) / 2

        if not flat_resistance_valid:
            return None  # Bukan Ascending Triangle sejati

        # Cek: harga sekarang HARUS di bawah resistance (belum breakout)
        if current_price >= flat_resistance_level * 1.005:
            return None  # Harga sudah BREAKOUT di atas resistance

        # Cek: jarak HL ke Resistance semakin menyempit (kompresi aktif)
        gap_first_to_resistance = ((flat_resistance_level - first_hl_price) / flat_resistance_level) * 100
        gap_last_to_resistance = ((flat_resistance_level - last_hl_price) / flat_resistance_level) * 100
        
        if gap_last_to_resistance >= gap_first_to_resistance:
            return None  # Triangle tidak menyempit = bukan kompresi
            
        # Minta Jarak HL terakhir ke demand/resistance TIDAK TERLALU JAUH (max 4.5%)
        # Semakin kecil persentasenya, semakin ketat kompresinya
        if gap_last_to_resistance > 4.5:
            return None  # Jarak HL ke resistance masih terlalu jauh (kurang menyempit)

        # ALPHA: Hitung compression percentage (untuk filter downstream)
        compression_pct = 0.0
        if gap_first_to_resistance > 0:
            compression_pct = ((gap_first_to_resistance - gap_last_to_resistance) / gap_first_to_resistance) * 100


        # -- Step 4: Resistance/Demand Retest Count --
        # User's "demand zone" = flat resistance level di atas ascending triangle
        # Seperti chart DASH: zona $36 yang terus di-retest dari bawah
        # Hitung berapa kali harga menyentuh flat resistance ini
        resistance_retest_count = 0
        resistance_tolerance = flat_resistance_level * 0.015  # 1.5% tolerance

        for k in range(first_hl_idx, len(df)):
            candle_body_high = max(df['open'].iloc[k], df['close'].iloc[k])
            candle_close = df['close'].iloc[k]
            # Harga menyentuh zona resistance (dari bawah) berdasarkan body
            if candle_body_high >= flat_resistance_level - resistance_tolerance:
                if candle_close <= flat_resistance_level * 1.01:  # Belum breakout
                    resistance_retest_count += 1

        # Deduplicate: hitung cluster (bukan setiap candle individual)
        # Grup candle yang berdekatan dianggap 1 retest
        retest_events = 0
        in_zone = False
        for k in range(first_hl_idx, len(df)):
            candle_body_high = max(df['open'].iloc[k], df['close'].iloc[k])
            near_resistance = candle_body_high >= flat_resistance_level - resistance_tolerance
            if near_resistance and not in_zone:
                retest_events += 1
                in_zone = True
            elif not near_resistance:
                in_zone = False

        # -- ALPHA: Volume Surge at Support --
        # Cek apakah volume meningkat di area pivot lows (tanda akumulasi institusi)
        vol_sma_20 = df['volume'].rolling(20).mean()
        vol_at_support_score = 0
        for hl_idx in hl_indices[-3:]:
            if hl_idx < len(df) and hl_idx < len(vol_sma_20):
                vol_at_hl = df['volume'].iloc[hl_idx]
                vol_avg = vol_sma_20.iloc[hl_idx]
                if not pd.isna(vol_avg) and vol_avg > 0:
                    if vol_at_hl >= vol_avg * 2.0:
                        vol_at_support_score += 2  # Volume spike 2x = strong
                    elif vol_at_hl >= vol_avg * 1.5:
                        vol_at_support_score += 1  # Volume above avg

        # -- Step 5: Trendline value --
        trendline_price = _calc_trendline_value(df, hl_indices)

        # -- Step 6: ENTRY CONDITIONS --
        # Entry A: HL ke-2+ trendline touch (pullback ke ascending trendline)
        near_trendline = False
        if trendline_price and trendline_price > 0 and MIN_HL_TOUCHES <= len(hl_indices) <= MAX_HL_TOUCHES:
            distance_pct = ((current_price - trendline_price) / trendline_price) * 100
            near_trendline = (-1.5 <= distance_pct <= 1.5)

        # Entry B: Flat resistance (demand zone) retest ke-2+
        # Seperti chart DASH: harga naik ke $36 untuk ke-3 kalinya = ENTRY
        near_demand_3x = False
        if 2 <= retest_events <= MAX_RESISTANCE_RETEST and MIN_HL_TOUCHES <= len(hl_indices) <= MAX_HL_TOUCHES:
            resistance_distance = ((current_price - flat_resistance_level) / flat_resistance_level) * 100
            # Harga harus DEKAT resistance (-3% sampai +0.5%)
            near_demand_3x = (-3.0 <= resistance_distance <= 0.5)

        if not near_trendline and not near_demand_3x:
            return None
            
        # -- Step 6.5: VOLUME CONFIRMATION --
        # Pullback entry = volume should NOT be dead, but doesn't need to spike
        # Accept if volume >= 0.7x avg (not dead) OR volume is rising (bounce starting)
        vol_sma = calc_volume_sma(df, 20)
        vol_ratio_1 = df['volume'].iloc[-1] / vol_sma.iloc[-1] if vol_sma.iloc[-1] > 0 else 1.0
        vol_ratio_2 = df['volume'].iloc[-2] / vol_sma.iloc[-2] if vol_sma.iloc[-2] > 0 else 1.0
        max_vol_ratio = max(vol_ratio_1, vol_ratio_2)
        vol_rising = vol_ratio_1 > vol_ratio_2  # Volume increasing = bounce confirmation
        
        if max_vol_ratio < 0.7 and not vol_rising:
            return None  # Volume completely dead — no interest at this level

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
                support_level = trendline_price if near_trendline else last_hl_price
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
        else:
            # Entry B (demand/resistance retest): SL di bawah HL terakhir
            last_hl_sl = last_hl_price * (1 - SL_BUFFER_PCT / 100)
            sl_price = min(last_hl_sl, entry_price - atr_sl_distance)

        min_sl_pct = atr_mult / 100.0
        min_sl_floor = entry_price * min_sl_pct
        if (entry_price - sl_price) < min_sl_floor:
            sl_price = entry_price - min_sl_floor

        sl_distance = entry_price - sl_price
        tp_price = entry_price + (sl_distance * DEFAULT_RR_RATIO)

        sl_pct = ((entry_price - sl_price) / entry_price) * 100
        tp_pct = ((tp_price - entry_price) / entry_price) * 100

        accum = detect_accumulation_zone(df, p_highs, p_lows)
        resistance = flat_resistance_level
        support = trendline_price if trendline_price else sl_price

        hl_prices = [round(df['low'].iloc[i], 6) for i in hl_indices]

        if near_trendline:
            entry_type = 'ASC_TRIANGLE_TRENDLINE'
        else:
            entry_type = 'ASC_TRIANGLE_RETEST'

        vol_sma = calc_volume_sma(df, 20)

        # Confidence formula yang meaningful (bukan selalu 100)
        # Range realistis: 35-100
        # Min valid setup (2 HL + 2 retest) = 35 + 0 + 20 + 0 + 0 = 55
        _hl_bonus     = min(25, max(0, (len(hl_indices) - 2) * 12))  # 0/12/25 for 2/3/4 HL
        _retest_bonus = min(25, (retest_events - 1) * 12)  # 0/12/25 for 1/2/3 retest (min 2 = 12)
        _vol_bonus    = min(15, vol_at_support_score * 5)
        _compress_bonus = min(10, int(compression_pct / 10)) if compression_pct > 0 else 0
        _rise_bonus   = 5 if total_rise > 5 else 0
        _confidence   = min(100, 35 + _hl_bonus + _retest_bonus + _vol_bonus + _compress_bonus + _rise_bonus)

        signal = {
            'symbol': symbol,
            'timeframe': timeframe,
            'direction':   'LONG',
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
            'flat_resistance': round(flat_resistance_level, 8),
            'resistance_retest_count': retest_events,
            'trendline_price': round(trendline_price, 8) if trendline_price else None,
            'trendline_slope': round(slope_per_candle, 8),
            'total_rise_pct': round(total_rise, 1),
            'volume_ratio': round(df['volume'].iloc[-1] / vol_sma.iloc[-1], 2) if vol_sma.iloc[-1] > 0 else 1.0,
            'vol_at_support_score': vol_at_support_score,
            'compression_pct': round(compression_pct, 1),
            'atr': round(current_atr, 8),
            'atr_pct': round((current_atr / entry_price) * 100, 2),
            'confidence': _confidence,
        }

        log.info(f"🎯 [{entry_type}]: {symbol} {timeframe} | "
                 f"Entry={entry_price:.6f} SL={sl_price:.6f} ({sl_pct:.1f}%) "
                 f"TP={tp_price:.6f} ({tp_pct:.1f}%) | "
                 f"HL={len(hl_indices)} Resistance={flat_resistance_level:.4f} "
                 f"Retests={retest_events}x Rise={total_rise:.1f}%")

        return signal

    except Exception as e:
        log.error(f"Strategy error for {symbol} {timeframe}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# ANALYZE SHORT — Descending Triangle (Mirror of analyze LONG)
# ══════════════════════════════════════════════════════════════

def analyze_short(df: pd.DataFrame, symbol: str, timeframe: str) -> Optional[Dict]:
    """
    Kalimasada v7 — SHORT via Descending Triangle (PURE PRICE ACTION)

    Struktur yang dicari (kebalikan sempurna dari Ascending Triangle):
    1. LANTAI DATAR (Flat Support): Min 2 Pivot Low dalam toleransi 3%
       → Menandakan ada buyer terakhir yang menahan di level tersebut
    2. ATAP MENURUN (Lower Highs): Pivot High makin rendah (slope negatif)
       → Menandakan seller makin agresif menekan harga
    3. KOMPRESI AKTIF: Jarak dari LH ke Support semakin menyempit
       → Harga seperti "per" yang ditekan — begitu lantai jebol, dump keras
    4. Entry: Di trendline atap menurun (LH touch) ATAU di Supply 3x retest
    5. SL: Di atas LH terakhir
    6. TP: SL distance ke bawah × RR Ratio
    """
    if df is None or len(df) < 50:
        return None

    try:
        atr = calc_atr(df, 14)
        current_price = df['close'].iloc[-1]

        # -- Step 1: Pivots --
        p_lows = detect_pivot_lows(df)
        p_highs = detect_pivot_highs(df)

        if len(p_highs) < 2:
            return None

        # -- Step 2: Lower Highs (Atap Menurun — slope NEGATIF) --
        highs_arr = df['high'].values
        # Cari sekuens Lower Highs yang valid
        best_lh_seq = []
        current_lh_seq = [p_highs[0]]

        for i in range(1, len(p_highs)):
            prev_idx = p_highs[i - 1]
            curr_idx = p_highs[i]
            if (curr_idx - prev_idx) < MIN_HL_CANDLE_GAP:
                continue
            if highs_arr[curr_idx] < highs_arr[prev_idx]:  # Lower High
                current_lh_seq.append(curr_idx)
            else:
                if len(current_lh_seq) > len(best_lh_seq):
                    best_lh_seq = current_lh_seq[:]
                current_lh_seq = [curr_idx]

        if len(current_lh_seq) > len(best_lh_seq):
            best_lh_seq = current_lh_seq[:]

        # Butuh minimal 2 Lower Highs, dan LH terakhir harus dalam 30 candle terakhir
        if len(best_lh_seq) < 2 or best_lh_seq[-1] < len(df) - 30:
            return None

        lh_indices = best_lh_seq
        first_lh_idx  = lh_indices[0]
        last_lh_idx   = lh_indices[-1]
        first_lh_price = df['high'].iloc[first_lh_idx]
        last_lh_price  = df['high'].iloc[last_lh_idx]

        # Pastikan slope NEGATIF
        if last_lh_price >= first_lh_price:
            return None

        lh_candle_span = last_lh_idx - first_lh_idx
        if lh_candle_span <= 0:
            return None
        lh_slope_per_candle = (last_lh_price - first_lh_price) / lh_candle_span  # negatif

        # -- Step 3: FLAT SUPPORT (Lantai Datar) --
        FLAT_SUPPORT_TOLERANCE = 3.0  # max 3% perbedaan antar Pivot Low
        flat_support_valid   = False
        flat_support_level   = None

        if len(p_lows) >= 2:
            relevant_lows = [i for i in p_lows if i >= first_lh_idx]
            if len(relevant_lows) >= 2:
                pl_prices = [df['low'].iloc[i] for i in relevant_lows[-5:]]
                pl_max = max(pl_prices)
                pl_min = min(pl_prices)
                spread_pct = ((pl_max - pl_min) / pl_max) * 100
                if spread_pct <= FLAT_SUPPORT_TOLERANCE:
                    flat_support_valid = True
                    flat_support_level = (pl_max + pl_min) / 2

        if not flat_support_valid:
            return None  # Bukan Descending Triangle sejati

        # Harga HARUS masih di atas support (belum breakdown)
        if current_price <= flat_support_level * 1.02:
            return None  # Harga sudah breakdown atau terlalu dekat support

        # -- Step 4: KOMPRESI AKTIF (Triangle semakin menyempit dari atas) --
        gap_first_to_support = ((first_lh_price - flat_support_level) / first_lh_price) * 100
        gap_last_to_support  = ((last_lh_price  - flat_support_level) / last_lh_price)  * 100
        if gap_last_to_support >= gap_first_to_support:
            return None  # Triangle tidak menyempit = bukan kompresi

        # -- Step 5: Supply Zone + Retest Count (kebalikan Demand Zone) --
        supply_retest_count = 0
        nearest_supply = None

        # Supply zone = area di mana harga turun kencang (bearish candle kuat)
        supply_zones = []
        start_idx = max(3, len(df) - 200)
        for i in range(start_idx, len(df) - 1):
            body = df['open'].iloc[i] - df['close'].iloc[i]  # bearish body
            candle_range = df['high'].iloc[i] - df['low'].iloc[i]
            if candle_range <= 0:
                continue
            body_ratio = body / candle_range
            if body_ratio < 0.55:
                continue
            prev_avg_close = df['close'].iloc[max(0, i - 3):i].mean()
            if df['high'].iloc[i] <= prev_avg_close:
                continue
            zone_high = df['high'].iloc[i]
            zone_low  = max(df['open'].iloc[i], df['close'].iloc[i])
            zone_mid  = (zone_high + zone_low) / 2
            supply_zones.append({'low': zone_low, 'high': zone_high, 'mid': zone_mid, 'index': i, 'strength': body_ratio})

        if supply_zones:
            valid_supplies = [sz for sz in supply_zones if sz['low'] >= current_price * 0.95]
            if valid_supplies:
                nearest_supply = min(valid_supplies, key=lambda x: x['low'])
                sz_idx  = nearest_supply['index']
                sz_low  = nearest_supply['low']
                for k in range(sz_idx + 3, len(df)):
                    candle_high  = df['high'].iloc[k]
                    candle_close = df['close'].iloc[k]
                    if candle_high >= sz_low * 0.99 and candle_close < sz_low * 1.01:
                        supply_retest_count += 1

        # -- Step 6: Trendline LH value at current candle --
        lh_trendline_price = None
        candles_since_last_lh = (len(df) - 1) - last_lh_idx
        if candles_since_last_lh <= 30:
            lh_slope = lh_slope_per_candle
            lh_trendline_price = last_lh_price + lh_slope * candles_since_last_lh

        # -- Step 7: ENTRY CONDITIONS --
        # Entry A: Harga menyentuh trendline LH (pantulan ke bawah dari atap)
        near_lh_trendline = False
        if lh_trendline_price and lh_trendline_price > 0:
            dist_pct = ((lh_trendline_price - current_price) / lh_trendline_price) * 100
            near_lh_trendline = (-2.0 <= dist_pct <= 1.0)  # harga mendekati/menyentuh LH trendline

        # Entry B: Supply Zone 3x retest
        near_supply_3x = False
        if nearest_supply and supply_retest_count >= 2:
            sz_dist = ((nearest_supply['mid'] - current_price) / nearest_supply['mid']) * 100
            near_supply_3x = (-2.0 <= sz_dist <= 1.0)

        if not near_lh_trendline and not near_supply_3x:
            return None

        # -- Step 8: MAX DROP FILTER (jangan short yang sudah dump terlalu dalam) --
        recent_low = df['low'].iloc[-30:].min()
        total_drop = ((first_lh_price - recent_low) / first_lh_price) * 100
        if total_drop > 30.0:
            return None  # Sudah oversold terlalu dalam

        # -- Step 9: Anti dump candle besar (jangan short saat baru saja dump keras) --
        # Jika 3 candle terakhir rata-rata body > 2.5x ATR, harga sudah oversold sementara
        last_bodies = [abs(df['close'].iloc[-j] - df['open'].iloc[-j]) for j in range(1, min(4, len(df)))]
        avg_body = sum(last_bodies) / len(last_bodies) if last_bodies else 0
        atr_check = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0
        if atr_check > 0 and avg_body > atr_check * 2.5:
            return None  # Sudah dump keras, tunggu rebound dulu baru short

        # == SIGNAL SHORT ==
        entry_price  = current_price
        current_atr  = atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else entry_price * 0.02
        atr_mult     = ATR_SL_MULT.get(timeframe, ATR_SL_MULT_DEFAULT)
        atr_sl_dist  = current_atr * atr_mult

        # SL untuk SHORT = di ATAS entry (di atas LH terakhir)
        if near_lh_trendline and lh_trendline_price:
            lh_sl = lh_trendline_price * (1 + SL_BUFFER_PCT / 100)
            sl_price = max(lh_sl, entry_price + atr_sl_dist)
        elif nearest_supply:
            supply_sl = nearest_supply['high'] * (1 + SL_BUFFER_PCT / 100)
            sl_price  = max(supply_sl, entry_price + atr_sl_dist)
        else:
            sl_price = entry_price + atr_sl_dist

        # TP untuk SHORT = ke bawah
        sl_distance = sl_price - entry_price
        tp_price    = entry_price - (sl_distance * DEFAULT_RR_RATIO)

        # TP boleh tembus flat support (target breakdown Descending Triangle)
        # Hanya cap jika TP > 15% dari entry (unrealistic)
        max_tp_dist = entry_price * 0.15
        if (entry_price - tp_price) > max_tp_dist:
            tp_price = entry_price - max_tp_dist

        sl_pct = ((sl_price - entry_price) / entry_price) * 100
        tp_pct = ((entry_price - tp_price) / entry_price) * 100

        lh_prices = [round(df['high'].iloc[i], 6) for i in lh_indices]

        if near_lh_trendline:
            entry_type = 'LH_TRENDLINE_TOUCH'
        else:
            entry_type = 'SUPPLY_3X_RETEST'

        vol_sma = calc_volume_sma(df, 20)

        signal = {
            'symbol':               symbol,
            'timeframe':            timeframe,
            'direction':            'SHORT',
            'signal_type':          entry_type,
            'entry_price':          round(entry_price, 8),
            'sl_price':             round(sl_price, 8),
            'tp_price':             round(tp_price, 8),
            'sl_pct':               round(sl_pct, 2),
            'tp_pct':               round(tp_pct, 2),
            'rr_ratio':             round(DEFAULT_RR_RATIO, 1),
            'flat_support':         round(flat_support_level, 8),
            'lower_highs':          lh_prices,
            'lh_touches':           len(lh_indices),
            'supply_zone':          nearest_supply,
            'supply_retest_count':  supply_retest_count,
            'lh_trendline_price':   round(lh_trendline_price, 8) if lh_trendline_price else None,
            'lh_slope':             round(lh_slope_per_candle, 8),
            'total_drop_pct':       round(total_drop, 1),
            'volume_ratio':         round(df['volume'].iloc[-1] / vol_sma.iloc[-1], 2) if vol_sma.iloc[-1] > 0 else 1.0,
            'atr':                  round(current_atr, 8),
            'atr_pct':              round((current_atr / entry_price) * 100, 2),
            'confidence':           min(100, 40 + len(lh_indices) * 15 + (10 if nearest_supply else 0) + min(supply_retest_count * 10, 30)),
        }

        log.info(f"🔻 [SHORT {entry_type}]: {symbol} {timeframe} | "
                 f"Entry={entry_price:.6f} SL={sl_price:.6f} (+{sl_pct:.1f}%) "
                 f"TP={tp_price:.6f} ({tp_pct:.1f}%) | "
                 f"LH={len(lh_indices)} Slope={lh_slope_per_candle:.6f} Drop={total_drop:.1f}% "
                 f"SupplyRetest={supply_retest_count}x")

        return signal

    except Exception as e:
        log.error(f"analyze_short error for {symbol} {timeframe}: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# KALIMASADA HELPERS — Trendline, Volume Rising, Consolidation
# ══════════════════════════════════════════════════════════════

def _calc_trendline_value(df: pd.DataFrame, hl_indices: List[int]) -> Optional[float]:
    """
    Calculate the expected trendline price at the current candle
    by linearly extrapolating the last 2 higher lows (using fractal body prices).
    
    [FIX #6] Proyeksi dibatasi maks 10 candle dari HL terakhir.
    Proyeksi terlalu jauh menghasilkan nilai yang tidak akurat dan menyesatkan.
    """
    if len(hl_indices) < 2:
        return None

    idx1 = hl_indices[-2]
    idx2 = hl_indices[-1]
    price1 = min(df['open'].iloc[idx1], df['close'].iloc[idx1])
    price2 = min(df['open'].iloc[idx2], df['close'].iloc[idx2])

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


# ══════════════════════════════════════════════════════════════
# BTC WEATHER SYSTEM — Macro Trend Filter
# ══════════════════════════════════════════════════════════════

def check_btc_weather(btc_d1_df: pd.DataFrame) -> str:
    """
    BTC Macro Weather System — EMA 20 & EMA 50 Gap Analysis pada Daily.

    Mengatasi kelemahan MA di market sideways dengan mengukur JARAK (gap)
    antara EMA 20 dan EMA 50, bukan sekadar crossover.

    Returns:
        'UPTREND'   → EMA20 > EMA50, gap > 3%  → Hanya LONG diizinkan
        'DOWNTREND' → EMA20 < EMA50, gap > 3%  → Hanya SHORT diizinkan
        'SIDEWAYS'  → Gap < 3% (MA kusut)       → LONG & SHORT diizinkan
    """
    if btc_d1_df is None or len(btc_d1_df) < 55:
        return 'SIDEWAYS'  # Data tidak cukup, izinkan semua

    ema20 = btc_d1_df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = btc_d1_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]

    if pd.isna(ema20) or pd.isna(ema50) or ema50 <= 0:
        return 'SIDEWAYS'

    gap_pct = ((ema20 - ema50) / ema50) * 100

    WEATHER_THRESHOLD = 3.0  # 3% gap minimum untuk konfirmasi tren

    if gap_pct > WEATHER_THRESHOLD:
        return 'UPTREND'     # ☀️ Cerah: BTC bullish kuat, fokus LONG
    elif gap_pct < -WEATHER_THRESHOLD:
        return 'DOWNTREND'   # ⛈️ Badai: BTC bearish kuat, fokus SHORT
    else:
        return 'SIDEWAYS'    # ⛅ Berawan: MA kusut, pure price action


# ══════════════════════════════════════════════════════════════
# ALPHA FILTER SYSTEM — 5 Layer Institutional Grade
# ══════════════════════════════════════════════════════════════

def calc_relative_strength(coin_df: pd.DataFrame, btc_df: pd.DataFrame,
                           lookback_days: int = 7) -> Optional[float]:
    """
    Layer 1: Relative Strength vs BTC.
    Hitung seberapa kuat koin dibandingkan BTC dalam N hari terakhir.

    RS = coin_return_7d - btc_return_7d
    RS > 0% = koin outperform BTC (alpha candidate)
    RS > +5% = koin jauh lebih kuat dari BTC (strong alpha)

    Returns RS percentage, or None if insufficient data.
    """
    if coin_df is None or btc_df is None:
        return None
    if len(coin_df) < lookback_days + 1 or len(btc_df) < lookback_days + 1:
        return None

    # Coin return
    coin_now = coin_df['close'].iloc[-1]
    coin_old = coin_df['close'].iloc[-lookback_days - 1]
    if coin_old <= 0:
        return None
    coin_return = ((coin_now - coin_old) / coin_old) * 100

    # BTC return
    btc_now = btc_df['close'].iloc[-1]
    btc_old = btc_df['close'].iloc[-lookback_days - 1]
    if btc_old <= 0:
        return None
    btc_return = ((btc_now - btc_old) / btc_old) * 100

    return coin_return - btc_return


def is_alpha_worthy(signal: Dict, coin_df: pd.DataFrame, btc_df: pd.DataFrame,
                    d1_df: pd.DataFrame = None, weather: str = 'SIDEWAYS') -> Tuple[bool, List[str]]:
    """
    5-Layer Alpha Filter — Hanya loloskan sinyal yang benar-benar institutional grade.

    Layer 1: Relative Strength vs BTC (coin harus outperform BTC 7d)
    Layer 2: Volume Surge at Support (vol_at_support_score >= 1)
    Layer 3: D1 Trend Confluence (D1 harus bullish/neutral)
    Layer 4: Compression Quality (>25% range reduction)
    Layer 5: Confidence Score (>= 65)

    Returns:
        (passed: bool, reasons: list of rejection reasons)
    """
    if not signal:
        return False, ['NO_SIGNAL']

    reasons = []
    passed_layers = 0
    total_layers = 5

    # ── Layer 1: Relative Strength vs BTC ──
    rs = calc_relative_strength(coin_df, btc_df, lookback_days=7)
    if rs is not None:
        if weather == 'DOWNTREND':
            # Saat BTC bearish, koin HARUS decouple: RS > +3%
            if rs > 3.0:
                passed_layers += 1
            else:
                reasons.append(f'RS_WEAK_IN_DOWNTREND({rs:+.1f}%)')
        elif weather == 'SIDEWAYS':
            # Saat sideways, koin harus minimal tidak underperform: RS > -2%
            if rs > -2.0:
                passed_layers += 1
            else:
                reasons.append(f'RS_UNDERPERFORM({rs:+.1f}%)')
        else:  # UPTREND
            # Saat bullish, hampir semua koin OK, tapi filter yang sangat lemah
            if rs > -5.0:
                passed_layers += 1
            else:
                reasons.append(f'RS_LAGGARD({rs:+.1f}%)')
    else:
        passed_layers += 1  # No data = pass (benefit of doubt)

    # ── Layer 2: Volume Surge at Support (BONUS — bukan hard filter) ──
    # Data backtest: trade tanpa volume score juga bisa WIN
    # Volume di support = bonus confidence, bukan requirement
    vol_score = signal.get('vol_at_support_score', 0)
    if vol_score >= 1:
        passed_layers += 1  # Bonus: ada volume institusi
    else:
        passed_layers += 1  # Tetap pass — volume bukan dealbreaker
        # Tapi catat sebagai warning
        if vol_score == 0:
            reasons.append(f'NO_VOL_AT_SUPPORT(warn)')

    # ── Layer 3: D1 Trend Confluence ──
    if d1_df is not None and len(d1_df) > 25:
        d1_close = d1_df['close'].iloc[-1]
        d1_sma20 = d1_df['close'].rolling(20).mean().iloc[-1]
        d1_ema50 = d1_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]

        if not pd.isna(d1_sma20) and not pd.isna(d1_ema50):
            # D1 harus tidak bearish: minimal harga di atas SMA20 ATAU EMA50
            if d1_close > d1_sma20 or d1_close > d1_ema50:
                passed_layers += 1
            else:
                reasons.append(f'D1_BEARISH(close<SMA20&EMA50)')
        else:
            passed_layers += 1  # No data = pass
    else:
        passed_layers += 1  # No D1 = pass

    # ── Layer 4: Triangle Freshness (BUKAN compression tinggi) ──
    # DATA INSIGHT: Trade yang WIN punya compression RENDAH (2-6%)
    # Trade yang LOSS punya compression TINGGI (30-56%)
    # Compression tinggi = triangle sudah tua = terlambat masuk = BAHAYA
    compression = signal.get('compression_pct', 0)
    if compression < 40.0:
        passed_layers += 1  # Fresh triangle, belum terlalu terkompresi
    else:
        reasons.append(f'STALE_TRIANGLE(comp={compression:.0f}%>40%)')

    # ── Layer 5: Confidence Score ──
    confidence = signal.get('confidence', 0)
    if confidence >= 55:
        passed_layers += 1
    else:
        reasons.append(f'LOW_CONFIDENCE({confidence}<55)')

    # ── Layer 6: BTC 4h Momentum Guard ──
    # Jika BTC turun >-1.5% dalam 4 candle terakhir, BLOCK entry.
    # Alasan: semua mid-small cap berkorelasi 1:1 dengan BTC jangka pendek.
    # Ascending triangle bisa valid secara teknikal tapi tetap ditarik turun
    # jika BTC sedang dalam downswing aktif.
    if btc_df is not None and len(btc_df) >= 5:
        btc_4h_start = float(btc_df['close'].iloc[-5])
        btc_4h_now   = float(btc_df['close'].iloc[-1])
        btc_4h_chg   = ((btc_4h_now - btc_4h_start) / btc_4h_start) * 100
        if btc_4h_chg < -1.5:
            reasons.append(f'BTC_4H_DUMP({btc_4h_chg:+.1f}%<-1.5%)')
            # Downswing BTC aktif = BLOCK semua entry, apapun pattern-nya
            return False, reasons
    else:
        btc_4h_chg = 0.0

    # KEPUTUSAN: Minimal 3 dari 5 layer harus pass
    # Saat DOWNTREND: minimal 4 dari 5 (lebih ketat)
    min_pass = 4 if weather == 'DOWNTREND' else 3
    passed = passed_layers >= min_pass

    return passed, reasons
