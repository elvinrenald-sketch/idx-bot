"""
Bybit Crypto Algo Bot — Risk Manager
Auto Leverage, Position Sizing, SL/TP calculation.
All based on ATR volatility and equity — zero guesswork.
"""
import math
import logging
from typing import Optional, Dict
from config import (
    RISK_PER_TRADE_PCT, MIN_LEVERAGE, MAX_LEVERAGE,
    DEFAULT_RR_RATIO, MAX_OPEN_POSITIONS, MIN_NOTIONAL_USDT,
)

log = logging.getLogger('risk')


def calculate_leverage(atr_pct: float) -> int:
    """
    Auto-calculate leverage based on coin volatility (ATR%).

    Logic:
    - High volatility (ATR > 4%) → low leverage (3x) — safety first
    - Medium volatility (2-4%)   → medium leverage (5x)
    - Low volatility (< 2%)     → higher leverage (7-10x)

    Formula: leverage = clamp(target_move / ATR%, MIN, MAX)
    Target: we want ~5% account move per 1 ATR move.
    """
    if atr_pct <= 0:
        return MIN_LEVERAGE

    # Target: SL should cost ~RISK_PER_TRADE_PCT of equity
    # leverage = risk_budget / sl_distance
    # Approximation based on ATR
    if atr_pct > 5.0:
        lev = 3
    elif atr_pct > 3.0:
        lev = 4
    elif atr_pct > 2.0:
        lev = 5
    elif atr_pct > 1.5:
        lev = 7
    elif atr_pct > 1.0:
        lev = 8
    else:
        lev = 10

    return max(MIN_LEVERAGE, min(MAX_LEVERAGE, lev))


def calculate_position_size(
    equity: float,
    entry_price: float,
    sl_price: float,
    leverage: int,
    min_qty: float,
    qty_step: float,
) -> Optional[Dict]:
    """
    Calculate position size based on fixed risk percentage.

    Formula:
    1. risk_amount = equity × RISK_PER_TRADE_PCT / 100
    2. sl_distance_pct = (entry - sl) / entry
    3. position_value = risk_amount / sl_distance_pct
    4. qty = position_value / entry_price
    5. margin_required = position_value / leverage

    Returns sizing dict or None if impossible.
    """
    if entry_price <= 0 or sl_price <= 0 or sl_price >= entry_price:
        log.warning(f"Invalid prices: entry={entry_price} sl={sl_price}")
        return None

    if equity <= 0:
        log.warning("Zero equity, cannot size position")
        return None

    # Step 1: How much we're willing to lose
    risk_amount = equity * (RISK_PER_TRADE_PCT / 100.0)

    # Step 2: SL distance as percentage
    sl_distance_pct = (entry_price - sl_price) / entry_price

    if sl_distance_pct <= 0:
        return None

    # Step 3: Position value (notional) to risk exactly risk_amount
    # If price drops by sl_distance_pct, we lose risk_amount
    # loss = position_value × sl_distance_pct = risk_amount
    position_value = risk_amount / sl_distance_pct

    # Step 4: Quantity of the coin
    qty = position_value / entry_price

    # Step 5: Round down to minimum lot step
    if qty_step > 0:
        qty = math.floor(qty / qty_step) * qty_step

    # Check minimum quantity
    if qty < min_qty:
        # Try with higher leverage to meet minimum
        min_position_value = min_qty * entry_price
        min_margin = min_position_value / leverage
        if min_margin > equity * 0.5:  # Don't use more than 50% of equity
            log.warning(f"Cannot meet min qty {min_qty}: need ${min_margin:.2f} "
                        f"margin but equity=${equity:.2f}")
            return None
        qty = min_qty

    # Step 6: Margin required
    position_value = qty * entry_price
    margin_required = position_value / leverage

    # Safety check: margin should not exceed 40% of equity per position
    max_margin = equity * 0.40
    if margin_required > max_margin:
        # Scale down
        scale = max_margin / margin_required
        qty = qty * scale
        if qty_step > 0:
            qty = math.floor(qty / qty_step) * qty_step
        if qty < min_qty:
            log.warning(f"Position too large for equity. Need ${margin_required:.2f} "
                        f"margin, max=${max_margin:.2f}")
            return None
        position_value = qty * entry_price
        margin_required = position_value / leverage

    # ── Bybit minimum notional guard ($5.5 USDT) ───────────────
    if position_value < MIN_NOTIONAL_USDT:
        # Scale UP to meet minimum if it doesn't blow the margin safety
        required_qty = math.ceil(MIN_NOTIONAL_USDT / entry_price / qty_step) * qty_step if qty_step > 0 else MIN_NOTIONAL_USDT / entry_price
        required_margin = (required_qty * entry_price) / leverage
        
        if required_margin <= equity * 0.8: # Allow up to 80% margin for micro accounts
            log.info(f"Boosting position to ${MIN_NOTIONAL_USDT} to satisfy Bybit minimum.")
            qty = required_qty
            position_value = qty * entry_price
        else:
            log.warning(f"Position value ${position_value:.4f} below Bybit minimum "
                        f"${MIN_NOTIONAL_USDT} and cannot safely scale up.")
            return None


    # Recalculate actual risk
    actual_risk = position_value * sl_distance_pct
    actual_risk_pct = (actual_risk / equity) * 100 if equity > 0 else 0

    result = {
        'qty': round(qty, 8),
        'leverage': leverage,
        'margin_required': round(margin_required, 4),
        'position_value': round(position_value, 4),
        'risk_amount': round(actual_risk, 4),
        'risk_pct': round(actual_risk_pct, 2),
        'sl_distance_pct': round(sl_distance_pct * 100, 2),
    }

    log.info(f"📐 SIZING: qty={qty:.6f} lev={leverage}x "
             f"margin=${margin_required:.2f} notional=${position_value:.2f} "
             f"risk=${actual_risk:.4f} ({actual_risk_pct:.1f}%)")

    return result


def calculate_trailing_sl(entry_price: float, current_price: float,
                          original_sl: float, current_sl: float) -> Optional[float]:
    """
    Trailing stop: move SL to breakeven after profit >= 1R.

    1R = entry - original_sl (the original risk distance)
    When price reaches entry + 1R, move SL to entry (breakeven).
    When price reaches entry + 2R, move SL to entry + 1R.
    """
    r_distance = entry_price - original_sl  # 1R distance
    if r_distance <= 0:
        return None

    profit_in_r = (current_price - entry_price) / r_distance

    if profit_in_r >= 2.0:
        # At 2R profit, trail SL to entry + 1R
        new_sl = entry_price + r_distance
    elif profit_in_r >= 1.0:
        # At 1R profit, move SL to breakeven
        new_sl = entry_price + (entry_price * 0.001)  # Tiny buffer above entry
    else:
        return None  # Not enough profit to trail

    # Only move SL up, never down
    if new_sl > current_sl:
        log.info(f"📈 TRAILING SL: {current_sl:.6f} → {new_sl:.6f} "
                 f"(profit={profit_in_r:.1f}R)")
        return round(new_sl, 8)

    return None
