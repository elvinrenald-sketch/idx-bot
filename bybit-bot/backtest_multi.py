"""
Kalimasada v9 — ALPHA HUNTER BACKTEST (LONG ONLY)
Periode: Jan 2026, Feb 2026, Mar 2026 → Hari ini
Modal  : $3.50, $10, $20
Strategi: Ascending Triangle + 5-Layer Alpha Filter
  Layer 1: Relative Strength vs BTC (outperform)
  Layer 2: Volume Surge at Support (institusi akumulasi)
  Layer 3: D1 Trend Confluence (multi-timeframe)
  Layer 4: Compression Quality (>25%)
  Layer 5: Confidence Score (>=65)
"""
import os, sys, time, ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy import (
    analyze, is_pucuk, calc_atr,
    check_btc_weather, calc_relative_strength, is_alpha_worthy
)

# ══════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════
RISK_PCT = 3.0
LEVERAGE = 10
FEE_PCT  = 0.075

SCENARIOS = [
    {"name": "Jan 2026 → Hari Ini | Modal $3.50",  "start": "2026-01-01", "capital": 3.50},
    {"name": "Jan 2026 → Hari Ini | Modal $10",     "start": "2026-01-01", "capital": 10.0},
    {"name": "Jan 2026 → Hari Ini | Modal $20",     "start": "2026-01-01", "capital": 20.0},
    {"name": "Feb 2026 → Hari Ini | Modal $3.50",  "start": "2026-02-01", "capital": 3.50},
    {"name": "Feb 2026 → Hari Ini | Modal $10",     "start": "2026-02-01", "capital": 10.0},
    {"name": "Feb 2026 → Hari Ini | Modal $20",     "start": "2026-02-01", "capital": 20.0},
    {"name": "Mar 2026 → Hari Ini | Modal $3.50",  "start": "2026-03-01", "capital": 3.50},
    {"name": "Mar 2026 → Hari Ini | Modal $10",     "start": "2026-03-01", "capital": 10.0},
    {"name": "Mar 2026 → Hari Ini | Modal $20",     "start": "2026-03-01", "capital": 20.0},
]

COINS = [
    'BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT',
    'ADA/USDT', 'AVAX/USDT', 'DOT/USDT', 'LINK/USDT',
    'NEAR/USDT', 'SUI/USDT', 'APT/USDT', 'ARB/USDT', 'OP/USDT',
    'FIL/USDT', 'LTC/USDT', 'BCH/USDT', 'UNI/USDT', 'AAVE/USDT',
    'ATOM/USDT', 'ALGO/USDT', 'SAND/USDT', 'MANA/USDT',
    'GALA/USDT', 'IMX/USDT', 'LDO/USDT', 'CRV/USDT',
    'PEPE/USDT', 'WIF/USDT', 'BONK/USDT', 'FLOKI/USDT', 'SHIB/USDT',
    'TIA/USDT', 'SEI/USDT', 'INJ/USDT', 'ONDO/USDT', 'PENDLE/USDT',
    'RENDER/USDT', 'FET/USDT', 'JASMY/USDT', 'CHZ/USDT',
    'COMP/USDT', 'SNX/USDT', 'BLUR/USDT',
    'RUNE/USDT', 'ICP/USDT', 'HBAR/USDT', 'VET/USDT',
    'TRX/USDT', 'ETC/USDT',
    'TAO/USDT', 'WLD/USDT', 'STRK/USDT',
    'ARKM/USDT', 'SUPER/USDT', 'CORE/USDT', 'KAS/USDT',
    'FARTCOIN/USDT', 'BNB/USDT', 'POL/USDT', 'IP/USDT',
    'DASH/USDT', 'ZEC/USDT',
]

# ══════════════════════════════════════════════════════════════
# EXCHANGE
# ══════════════════════════════════════════════════════════════
def try_exchanges():
    for name, cls in [('gate', ccxt.gateio), ('kucoin', ccxt.kucoin),
                      ('mexc', ccxt.mexc), ('bitget', ccxt.bitget),
                      ('bybit', ccxt.bybit), ('binance', ccxt.binance)]:
        try:
            ex = cls({'enableRateLimit': True})
            ex.fetch_ohlcv('BTC/USDT', '1h', limit=5)
            print(f"OK Terhubung ke {name.upper()}")
            return ex
        except Exception as e:
            print(f"X {name}: {str(e)[:50]}")
    return None

def fetch_ohlcv(ex, sym, tf, since, batches=8):
    all_d = []
    cur = since
    for _ in range(batches):
        try:
            d = ex.fetch_ohlcv(sym, tf, since=cur, limit=500)
            if not d: break
            all_d.extend(d)
            if len(d) < 500: break
            cur = d[-1][0] + 1
            time.sleep(0.08)
        except: break
    if not all_d: return None
    df = pd.DataFrame(all_d, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.drop_duplicates(subset='timestamp').reset_index(drop=True)


# ══════════════════════════════════════════════════════════════
# BTC WEATHER — Get weather at specific timestamp
# ══════════════════════════════════════════════════════════════
def get_btc_weather_at(btc_d1, timestamp):
    """Get BTC weather state at a specific point in time."""
    if btc_d1 is None or len(btc_d1) < 55:
        return 'SIDEWAYS'
    btc_slice = btc_d1[btc_d1['timestamp'] <= timestamp].tail(60)
    if len(btc_slice) < 55:
        return 'SIDEWAYS'
    return check_btc_weather(btc_slice)

def get_btc_h1_at(btc_h1, timestamp, lookback=168):
    """Get BTC H1 data sliced up to timestamp for RS calculation."""
    if btc_h1 is None:
        return None
    btc_slice = btc_h1[btc_h1['timestamp'] <= timestamp].tail(lookback)
    return btc_slice if len(btc_slice) > 10 else None

def get_coin_d1_at(d1_df, timestamp):
    """Get coin D1 data sliced up to timestamp for D1 confluence."""
    if d1_df is None:
        return None
    d1_slice = d1_df[d1_df['timestamp'] <= timestamp].tail(60)
    return d1_slice if len(d1_slice) > 25 else None


# ══════════════════════════════════════════════════════════════
# SIMULATE TRADE
# ══════════════════════════════════════════════════════════════
def simulate_outcome(future_df, entry_price, sl_price, tp_price):
    """Check future candles to see if SL or TP is hit first (LONG only)."""
    for _, fc in future_df.iterrows():
        if fc['low'] <= sl_price:
            return 'LOSS'
        if fc['high'] >= tp_price:
            return 'WIN'
    return None


def calc_pnl(equity, entry_price, sl_price, tp_price, outcome):
    """Calculate PnL for LONG."""
    position_size = (equity * RISK_PCT / 100) * LEVERAGE
    fee = position_size * FEE_PCT / 100 * 2
    sl_dist_pct = abs(entry_price - sl_price) / entry_price
    tp_dist_pct = abs(tp_price - entry_price) / entry_price
    if outcome == 'WIN':
        return (position_size * tp_dist_pct) - fee, fee
    else:
        return -(position_size * sl_dist_pct) - fee, fee


# ══════════════════════════════════════════════════════════════
# WALK-FORWARD ENGINE — LONG ONLY + ALPHA FILTER
# ══════════════════════════════════════════════════════════════
def run_backtest(historical, btc_d1, btc_h1, start_date_str, initial_capital):
    """Run LONG-only backtest with 5-layer Alpha Filter."""
    start_ts = pd.Timestamp(start_date_str)
    equity   = initial_capital
    peak     = initial_capital
    max_dd   = 0.0
    trades   = []

    # Stats
    weather_counts = {'UPTREND': 0, 'DOWNTREND': 0, 'SIDEWAYS': 0}
    alpha_rejected = 0
    alpha_reasons_all = {}

    for sym, data in historical.items():
        h1 = data['1h']
        h4 = data.get('4h')
        d1 = data.get('1d')

        already_traded = False

        # ── SCAN H1 ──────────────────────────────────────────
        step = 4
        for start in range(80, len(h1) - 10, step):
            if already_traded:
                break

            df_slice = h1.iloc[:start+1].copy().reset_index(drop=True)
            curr_ts  = h1['timestamp'].iloc[start]

            if curr_ts < start_ts:
                continue

            # D1 pucuk check
            if d1 is not None and len(d1) > 20:
                d1_s = d1[d1['timestamp'] <= curr_ts].tail(60)
                if len(d1_s) > 20 and is_pucuk(d1_s):
                    continue

            # Get signal (LONG only)
            signal = analyze(df_slice, sym, '1h')
            if not signal:
                continue

            # ☁️ BTC Weather
            weather = get_btc_weather_at(btc_d1, curr_ts)

            # 🎯 ALPHA FILTER — 5 Layer Check
            btc_h1_slice = get_btc_h1_at(btc_h1, curr_ts)
            coin_d1_slice = get_coin_d1_at(d1, curr_ts)
            alpha_pass, reject_reasons = is_alpha_worthy(
                signal, df_slice, btc_h1_slice, coin_d1_slice, weather
            )

            if not alpha_pass:
                alpha_rejected += 1
                for r in reject_reasons:
                    key = r.split('(')[0]
                    alpha_reasons_all[key] = alpha_reasons_all.get(key, 0) + 1
                continue

            entry_price = signal['entry_price']
            sl_price    = signal['sl_price']
            tp_price    = signal['tp_price']

            future  = h1.iloc[start+1 : start+120]
            outcome = simulate_outcome(future, entry_price, sl_price, tp_price)

            if not outcome:
                continue

            pnl, fee = calc_pnl(equity, entry_price, sl_price, tp_price, outcome)
            equity += pnl
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd: max_dd = dd
            if equity <= 0: equity = 0; break

            already_traded = True
            weather_counts[weather] = weather_counts.get(weather, 0) + 1
            trades.append({
                'date': curr_ts, 'symbol': sym, 'tf': 'H1',
                'direction': 'LONG', 'weather': weather,
                'type': outcome, 'signal_type': signal.get('signal_type', ''),
                'entry': entry_price, 'sl': sl_price, 'tp': tp_price,
                'pnl': pnl, 'fee': fee, 'equity_after': equity,
                'confidence': signal.get('confidence', 0),
                'compression': signal.get('compression_pct', 0),
                'vol_support': signal.get('vol_at_support_score', 0),
            })

        # ── SCAN H4 ──────────────────────────────────────────
        if h4 is not None and len(h4) > 60 and not already_traded:
            h4_filtered = h4[h4['timestamp'] >= start_ts].reset_index(drop=True)
            if len(h4_filtered) < 40:
                continue

            for start_idx in range(40, len(h4_filtered) - 5):
                if already_traded:
                    break

                h4_slice = h4_filtered.iloc[:start_idx+1].copy().reset_index(drop=True)
                curr_ts  = h4_filtered['timestamp'].iloc[start_idx]

                # D1 pucuk check
                if d1 is not None and len(d1) > 20:
                    d1_s = d1[d1['timestamp'] <= curr_ts].tail(60)
                    if len(d1_s) > 20 and is_pucuk(d1_s):
                        continue

                signal = analyze(h4_slice, sym, '4h')
                if not signal:
                    continue

                # ☁️ BTC Weather
                weather = get_btc_weather_at(btc_d1, curr_ts)

                # 🎯 ALPHA FILTER
                btc_h1_slice = get_btc_h1_at(btc_h1, curr_ts)
                coin_d1_slice = get_coin_d1_at(d1, curr_ts)
                alpha_pass, reject_reasons = is_alpha_worthy(
                    signal, h4_slice, btc_h1_slice, coin_d1_slice, weather
                )

                if not alpha_pass:
                    alpha_rejected += 1
                    for r in reject_reasons:
                        key = r.split('(')[0]
                        alpha_reasons_all[key] = alpha_reasons_all.get(key, 0) + 1
                    continue

                entry_price = signal['entry_price']
                sl_price    = signal['sl_price']
                tp_price    = signal['tp_price']

                future  = h4_filtered.iloc[start_idx+1 : start_idx+60]
                outcome = simulate_outcome(future, entry_price, sl_price, tp_price)

                if not outcome:
                    continue

                pnl, fee = calc_pnl(equity, entry_price, sl_price, tp_price, outcome)
                equity += pnl
                if equity > peak: peak = equity
                dd = (peak - equity) / peak * 100
                if dd > max_dd: max_dd = dd
                if equity <= 0: equity = 0; break

                already_traded = True
                weather_counts[weather] = weather_counts.get(weather, 0) + 1
                trades.append({
                    'date': curr_ts, 'symbol': sym, 'tf': 'H4',
                    'direction': 'LONG', 'weather': weather,
                    'type': outcome, 'signal_type': signal.get('signal_type', ''),
                    'entry': entry_price, 'sl': sl_price, 'tp': tp_price,
                    'pnl': pnl, 'fee': fee, 'equity_after': equity,
                    'confidence': signal.get('confidence', 0),
                    'compression': signal.get('compression_pct', 0),
                    'vol_support': signal.get('vol_at_support_score', 0),
                })

    # ── Stats ─────────────────────────────────────────────────
    wins   = [t for t in trades if t['type'] == 'WIN']
    losses = [t for t in trades if t['type'] == 'LOSS']
    wr     = len(wins) / len(trades) * 100 if trades else 0
    net_pct     = (equity - initial_capital) / initial_capital * 100
    total_fees  = sum(t['fee'] for t in trades)
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss   = abs(sum(t['pnl'] for t in losses)) if losses else 1
    pf = gross_profit / gross_loss if gross_loss > 0 else 0

    return {
        'equity': equity, 'initial': initial_capital,
        'net_pct': net_pct, 'max_dd': max_dd,
        'wr': wr, 'total_trades': len(trades),
        'wins': len(wins), 'losses': len(losses),
        'pf': pf, 'total_fees': total_fees,
        'avg_win':  sum(t['pnl'] for t in wins)    / len(wins)   if wins   else 0,
        'avg_loss': abs(sum(t['pnl'] for t in losses) / len(losses)) if losses else 0,
        'ev':  sum(t['pnl'] for t in trades) / len(trades) if trades else 0,
        'trades': trades,
        'weather_counts': weather_counts,
        'alpha_rejected': alpha_rejected,
        'alpha_reasons': alpha_reasons_all,
    }


# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════
print("=" * 70)
print("  KALIMASADA v9 — ALPHA HUNTER (LONG ONLY)")
print("  9 Skenario: 3 Periode x 3 Modal")
print("  Ascending Triangle + 5-Layer Alpha Filter")
print("  RS vs BTC | Vol at Support | D1 Confluence | Kompresi | Confidence")
print("=" * 70)

exchange = try_exchanges()
if not exchange:
    print("X Semua exchange diblokir"); sys.exit(1)

since_dt  = datetime(2025, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
since_ms  = int(since_dt.timestamp() * 1000)
d1_since  = int(datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
h4_since  = int(datetime(2025, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)

historical = {}
btc_d1_global = None
btc_h1_global = None

print(f"\n   Downloading {len(COINS)} koin...")
for i, sym in enumerate(COINS):
    try:
        h1 = fetch_ohlcv(exchange, sym, '1h', since_ms)
        h4 = fetch_ohlcv(exchange, sym, '4h', h4_since)
        d1 = fetch_ohlcv(exchange, sym, '1d', d1_since)
        if h1 is not None and len(h1) > 60:
            historical[sym] = {'1h': h1, '4h': h4, '1d': d1}
            if sym == 'BTC/USDT':
                btc_d1_global = d1
                btc_h1_global = h1
            print(f"   [{i+1:02d}/{len(COINS)}] {sym:18s} "
                  f"H1={len(h1)} H4={len(h4) if h4 is not None else 0} "
                  f"D1={len(d1) if d1 is not None else 0}")
        time.sleep(0.05)
    except:
        pass

print(f"\n   {len(historical)} koin siap.")
if btc_d1_global is not None:
    current_weather = check_btc_weather(btc_d1_global)
    ema20_now = btc_d1_global['close'].ewm(span=20, adjust=False).mean().iloc[-1]
    ema50_now = btc_d1_global['close'].ewm(span=50, adjust=False).mean().iloc[-1]
    gap_now = ((ema20_now - ema50_now) / ema50_now) * 100
    weather_icon = {'UPTREND': '☀️', 'DOWNTREND': '⛈️', 'SIDEWAYS': '⛅'}.get(current_weather, '?')
    print(f"   BTC Weather NOW: {weather_icon} {current_weather} (EMA20/50 gap: {gap_now:+.1f}%)")

# ── RUN ALL SCENARIOS ─────────────────────────────────────────
results = []

for sc in SCENARIOS:
    print(f"\n{'─'*70}")
    print(f"  ▶ Scenario: {sc['name']}")
    print(f"    Start: {sc['start']} | Modal: ${sc['capital']:.2f}")
    print(f"{'─'*70}")

    r = run_backtest(historical, btc_d1_global, btc_h1_global, sc['start'], sc['capital'])
    r['scenario_name'] = sc['name']
    r['start_date']    = sc['start']
    results.append(r)

    print(f"    Modal Awal  : ${r['initial']:.2f}")
    print(f"    Modal Akhir : ${r['equity']:.4f}")
    print(f"    Net Profit  : ${r['equity'] - r['initial']:.4f} ({r['net_pct']:+.1f}%)")
    print(f"    Max Drawdown: {r['max_dd']:.1f}%")
    print(f"    Total Trades: {r['total_trades']} ({r['wins']}W / {r['losses']}L)")
    print(f"    Win Rate    : {r['wr']:.1f}%")
    print(f"    Profit Fctr : {r['pf']:.2f}")
    print(f"    Total Fees  : ${r['total_fees']:.4f}")
    wc = r.get('weather_counts', {})
    print(f"    Weather     : ☀️UP={wc.get('UPTREND',0)} ⛈️DOWN={wc.get('DOWNTREND',0)} ⛅SIDE={wc.get('SIDEWAYS',0)}")
    print(f"    Alpha Filter: {r.get('alpha_rejected',0)} sinyal DITOLAK karena tidak alpha")
    if r.get('alpha_reasons'):
        top_reasons = sorted(r['alpha_reasons'].items(), key=lambda x: -x[1])[:5]
        for reason, count in top_reasons:
            print(f"      → {reason}: {count}x ditolak")
    if r['avg_win']  > 0: print(f"    Avg WIN     : +${r['avg_win']:.4f}")
    if r['avg_loss'] > 0: print(f"    Avg LOSS    : -${r['avg_loss']:.4f}")
    if r['ev']      != 0: print(f"    Exp Value   : ${r['ev']:.4f}/trade")

    if r['trades']:
        print(f"\n    Trade Log:")
        print(f"    {'#':>3} {'Date':8} {'TF':3} {'Wthr':4} {'Coin':10} {'Signal':22} {'W/L':3} {'Conf':4} {'Cmp%':4} {'Vol':3} {'Entry':>10} {'SL':>10} {'TP':>10} {'PnL':>10}")
        for i, t in enumerate(r['trades'], 1):
            dt    = t['date'].strftime('%m-%d')
            sym_s = t['symbol'].replace('/USDT', '')[:8]
            icon  = "W" if t['type'] == 'WIN' else "L"
            pnl_s = f"+${t['pnl']:.3f}" if t['pnl'] > 0 else f"-${abs(t['pnl']):.3f}"
            sig   = t.get('signal_type', '')[:20]
            tf    = t.get('tf', 'H4')
            wthr  = {'UPTREND': '☀️', 'DOWNTREND': '⛈️', 'SIDEWAYS': '⛅'}.get(t.get('weather', ''), '?')
            conf  = t.get('confidence', 0)
            comp  = t.get('compression', 0)
            vsup  = t.get('vol_support', 0)
            print(f"    {i:>3} {dt:8} {tf:3} {wthr:4} {sym_s:10} {sig:22} {icon:3} {conf:4} {comp:3.0f}% {vsup:3} ${t['entry']:9.4f} ${t['sl']:9.4f} ${t['tp']:9.4f} {pnl_s:>10}")

# ── FINAL SUMMARY TABLE ───────────────────────────────────────
print(f"\n\n{'='*100}")
print(f"  RINGKASAN — ALPHA HUNTER (LONG ONLY + 5 LAYER FILTER)")
print(f"{'='*100}")
print(f"  {'Skenario':<40} {'Modal':>7} {'Akhir':>10} {'Net%':>8} {'WR':>6} {'MaxDD':>7} {'Trades':>7} {'PF':>6} {'Reject':>7}")
print(f"  {'─'*40} {'─'*7} {'─'*10} {'─'*8} {'─'*6} {'─'*7} {'─'*7} {'─'*6} {'─'*7}")

for r in results:
    print(f"  {r['scenario_name']:<40} ${r['initial']:5.2f} ${r['equity']:8.4f} {r['net_pct']:+7.1f}% {r['wr']:5.1f}% {r['max_dd']:5.1f}% {r['total_trades']:>7} {r['pf']:5.2f} {r.get('alpha_rejected',0):>7}")

print(f"{'='*100}")
print(f"\n  Catatan:")
print(f"  • LONG ONLY — Ascending Triangle (Higher Lows + Flat Resistance)")
print(f"  • 5-Layer Alpha Filter:")
print(f"    L1: Relative Strength vs BTC (coin harus outperform)")
print(f"    L2: Volume Surge at Support (institusi akumulasi)")
print(f"    L3: D1 Trend Confluence (multi-timeframe)")
print(f"    L4: Compression Quality (>25% range reduction)")
print(f"    L5: Confidence Score (>=65)")
print(f"  • Minimal 3/5 layer pass (4/5 saat BTC downtrend)")
print(f"  • Risk/Trade: {RISK_PCT}% | Leverage: {LEVERAGE}x | Fee: {FEE_PCT}%")
print(f"{'='*100}")
